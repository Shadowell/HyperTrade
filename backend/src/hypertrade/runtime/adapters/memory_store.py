from __future__ import annotations

import json
from collections.abc import Sequence
from hashlib import sha256

from hypertrade.runtime.domain.models import (
    MissionCreate,
    MissionEventV1,
    MissionProjection,
    MissionStatus,
    MissionUsageV1,
    PlanStepV2,
    PlanV2,
    SteeringEventV1,
    StepAttemptV2,
    StepObservationV2,
    utc_now,
)
from hypertrade.runtime.domain.state_machine import require_transition


class MissionVersionConflict(RuntimeError):
    pass


class InMemoryMissionStore:
    """Deterministic store used by runtime scenario tests and local simulations."""

    def __init__(self) -> None:
        self._missions: dict[str, MissionProjection] = {}
        self._plans: dict[str, list[PlanV2]] = {}
        self._attempts: dict[str, list[StepAttemptV2]] = {}
        self._events: dict[str, list[MissionEventV1]] = {}
        self._steers: dict[str, list[SteeringEventV1]] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._sequence = 0

    def _id(self, prefix: str) -> str:
        self._sequence += 1
        return f"{prefix}_{self._sequence:020d}"

    async def create(self, payload: MissionCreate) -> MissionProjection:
        mission_id = self._id("mis")
        idempotency_key = payload.idempotency_key or f"internal:{mission_id}"
        request_hash = _request_hash(payload)
        replay = self._idempotency.get(idempotency_key)
        if replay is not None:
            existing_id, existing_hash = replay
            if existing_hash != request_hash:
                raise ValueError("mission idempotency key is bound to different content")
            return await self.get(existing_id)
        now = utc_now()
        projection = MissionProjection(
            mission_id=mission_id,
            objective=payload.objective,
            original_objective=payload.objective,
            success_criteria=payload.success_criteria,
            constraints=payload.constraints,
            status=MissionStatus.DRAFT,
            budget=payload.budget,
            permission_profile_ref=payload.permission_profile_ref,
            context_policy_ref=payload.context_policy_ref,
            created_by=payload.created_by,
            idempotency_key=idempotency_key,
            deadline=payload.deadline,
            created_at=now,
            updated_at=now,
        )
        self._missions[mission_id] = projection
        self._plans[mission_id] = []
        self._attempts[mission_id] = []
        self._events[mission_id] = []
        self._steers[mission_id] = []
        self._idempotency[idempotency_key] = (mission_id, request_hash)
        await self.append_event(
            mission_id,
            "mission_created",
            actor=payload.created_by,
            payload={"objective_hash": sha256(payload.objective.encode()).hexdigest()},
        )
        return self._missions[mission_id]

    async def by_idempotency(self, idempotency_key: str) -> MissionProjection | None:
        replay = self._idempotency.get(idempotency_key)
        return await self.get(replay[0]) if replay is not None else None

    async def get(self, mission_id: str) -> MissionProjection:
        try:
            return self._missions[mission_id]
        except KeyError as exc:
            raise KeyError(mission_id) from exc

    async def list(self, *, limit: int = 50) -> list[MissionProjection]:
        values = sorted(self._missions.values(), key=lambda row: row.created_at, reverse=True)
        return values[: max(1, min(limit, 200))]

    async def transition(
        self,
        mission_id: str,
        *,
        expected_version: int,
        target: MissionStatus,
        actor: str,
        reason: str,
        current_step_id: str | None = None,
        terminal_summary: str | None = None,
        control_requested: str | None = None,
    ) -> MissionProjection:
        current = await self.get(mission_id)
        if current.version != expected_version:
            raise MissionVersionConflict(mission_id)
        require_transition(current.status, target)
        updated = current.model_copy(
            update={
                "status": target,
                "version": current.version + 1,
                "current_step_id": (
                    current.current_step_id if current_step_id is None else current_step_id
                ),
                "terminal_summary": (
                    current.terminal_summary if terminal_summary is None else terminal_summary
                ),
                "control_requested": (
                    current.control_requested if control_requested is None else control_requested
                ),
                "updated_at": utc_now(),
            }
        )
        self._missions[mission_id] = updated
        await self.append_event(
            mission_id,
            "mission_transitioned",
            actor=actor,
            payload={"from": current.status.value, "to": target.value, "reason": reason},
        )
        return updated

    async def update_usage(
        self, mission_id: str, *, expected_version: int, delta: dict[str, int]
    ) -> MissionProjection:
        current = await self.get(mission_id)
        if current.version != expected_version:
            raise MissionVersionConflict(mission_id)
        values = current.usage.model_dump()
        for key, amount in delta.items():
            if key not in values or amount < 0:
                raise ValueError(f"invalid usage delta: {key}")
            values[key] += amount
        updated = current.model_copy(
            update={
                "usage": MissionUsageV1.model_validate(values),
                "version": current.version + 1,
                "updated_at": utc_now(),
            }
        )
        self._missions[mission_id] = updated
        return updated

    async def set_current_step(
        self, mission_id: str, *, expected_version: int, step_id: str
    ) -> MissionProjection:
        current = await self.get(mission_id)
        if current.version != expected_version:
            raise MissionVersionConflict(mission_id)
        updated = current.model_copy(
            update={
                "current_step_id": step_id,
                "version": current.version + 1,
                "updated_at": utc_now(),
            }
        )
        self._missions[mission_id] = updated
        return updated

    async def save_plan(self, mission_id: str, plan: PlanV2) -> None:
        mission = await self.get(mission_id)
        plans = self._plans[mission_id]
        if plan.version != len(plans) + 1:
            raise ValueError("plan versions must be contiguous and append-only")
        if plan.version > mission.budget.max_plan_versions:
            raise ValueError("plan version budget exceeded")
        if len(plan.steps) > mission.budget.max_steps_per_plan:
            raise ValueError("plan step budget exceeded")
        plans.append(plan)
        self._missions[mission_id] = mission.model_copy(
            update={
                "active_plan_version": plan.version,
                "usage": mission.usage.model_copy(update={"plan_versions": plan.version}),
                "version": mission.version + 1,
                "updated_at": utc_now(),
            }
        )
        await self.append_event(
            mission_id,
            "plan_activated",
            actor="runtime",
            payload={
                "plan_id": plan.plan_id,
                "version": plan.version,
                "diff": plan.diff.model_dump(),
            },
        )

    async def plans(self, mission_id: str) -> Sequence[PlanV2]:
        await self.get(mission_id)
        return list(self._plans[mission_id])

    async def start_attempt(
        self, mission_id: str, plan_version: int, step: PlanStepV2, attempt: int
    ) -> StepAttemptV2:
        row = StepAttemptV2(
            attempt_id=self._id("sat"),
            step_id=step.step_id,
            attempt=attempt,
            status="running",
            capability_id=step.capability_id,
        )
        self._attempts[mission_id].append(row)
        await self.append_event(
            mission_id,
            "step_started",
            actor="runtime",
            payload={"plan_version": plan_version, "step_id": step.step_id, "attempt": attempt},
        )
        return row

    async def complete_attempt(
        self, attempt_id: str, observation: StepObservationV2
    ) -> StepAttemptV2:
        for mission_id, attempts in self._attempts.items():
            for index, attempt in enumerate(attempts):
                if attempt.attempt_id != attempt_id:
                    continue
                completed = attempt.model_copy(
                    update={
                        "status": observation.status,
                        "observation": observation,
                        "completed_at": utc_now(),
                    }
                )
                attempts[index] = completed
                await self.append_event(
                    mission_id,
                    "step_observed",
                    actor="runtime",
                    payload={
                        "step_id": completed.step_id,
                        "attempt": completed.attempt,
                        "status": observation.status,
                        "source_refs": list(observation.source_refs),
                        "artifact_refs": list(observation.artifact_refs),
                        "error_category": observation.error_category,
                    },
                )
                return completed
        raise KeyError(attempt_id)

    async def attempts(self, mission_id: str) -> Sequence[StepAttemptV2]:
        await self.get(mission_id)
        return list(self._attempts[mission_id])

    async def append_event(
        self, mission_id: str, event_type: str, *, actor: str, payload: dict[str, object]
    ) -> MissionEventV1:
        events = self._events[mission_id]
        event = MissionEventV1(
            sequence=len(events) + 1,
            event_type=event_type,
            actor=actor,
            payload=payload,
        )
        events.append(event)
        return event

    async def events(
        self, mission_id: str, *, after: int = 0, limit: int = 500
    ) -> Sequence[MissionEventV1]:
        await self.get(mission_id)
        return [event for event in self._events[mission_id] if event.sequence > after][
            : max(1, min(limit, 1_000))
        ]

    async def append_steer(self, mission_id: str, steer: SteeringEventV1) -> None:
        mission = await self.get(mission_id)
        self._steers[mission_id].append(steer)
        self._missions[mission_id] = mission.model_copy(
            update={
                "objective": f"{mission.objective}\nSteer: {steer.instruction}",
                "updated_at": utc_now(),
            }
        )
        await self.append_event(
            mission_id,
            "mission_steered",
            actor=steer.actor,
            payload={"instruction": steer.instruction, "reason": steer.reason},
        )


def _request_hash(payload: MissionCreate) -> str:
    return sha256(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
