from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from hashlib import sha256

from hypertrade.runtime.domain.mission_events import (
    MissionEventV2,
    MissionProtocolError,
    MissionSnapshotV2,
    apply_mission_event,
    make_mission_event,
)
from hypertrade.runtime.domain.models import (
    CompletionProofV1,
    MissionCreate,
    MissionEventV1,
    MissionProjection,
    MissionReplayStatus,
    MissionStatus,
    PlanStepV2,
    PlanV2,
    SteeringEventV1,
    StepAttemptV2,
    StepObservationV2,
    utc_now,
)


class MissionVersionConflict(RuntimeError):
    pass


class InMemoryMissionStore:
    """Deterministic store used by runtime scenario tests and local simulations."""

    def __init__(self) -> None:
        self._missions: dict[str, MissionProjection] = {}
        self._snapshots: dict[str, MissionSnapshotV2] = {}
        self._plans: dict[str, list[PlanV2]] = {}
        self._attempts: dict[str, list[StepAttemptV2]] = {}
        self._events: dict[str, list[MissionEventV1 | MissionEventV2]] = {}
        self._steers: dict[str, list[SteeringEventV1]] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._leases: dict[str, tuple[str, datetime, int]] = {}
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
            event_protocol_version=2,
            replay_status="canonical",
            created_at=now,
            updated_at=now,
        )
        self._events[mission_id] = []
        self._steers[mission_id] = []
        self._idempotency[idempotency_key] = (mission_id, request_hash)
        event = make_mission_event(
            event_id=self._id("mevt"),
            event_type="mission_created",
            mission_id=mission_id,
            sequence=1,
            actor=payload.created_by,
            policy_snapshot_hash=sha256(payload.permission_profile_ref.encode()).hexdigest(),
            payload={"projection": projection.model_dump(mode="json")},
        )
        self._commit(mission_id, apply_mission_event(MissionSnapshotV2(), event), event)
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

    async def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
    ) -> MissionProjection | None:
        """Reserve one non-terminal Mission for a single deterministic worker."""

        now = utc_now()
        runnable = {
            MissionStatus.DRAFT,
            MissionStatus.RUNNING,
            MissionStatus.RETRY_WAIT,
            MissionStatus.REPLANNING,
        }
        for mission in sorted(self._missions.values(), key=lambda row: row.created_at):
            if mission.status not in runnable:
                continue
            lease = self._leases.get(mission.mission_id)
            if lease is not None and lease[1] >= now:
                continue
            token = mission.fencing_token + 1
            self._leases[mission.mission_id] = (
                worker_id,
                now + timedelta(seconds=max(10, lease_seconds)),
                token,
            )
            await self.append_event(
                mission.mission_id,
                "mission.lease_claimed",
                actor=f"worker:{worker_id}",
                payload={"lease_seconds": max(10, lease_seconds)},
                fencing_token=token,
            )
            return await self.get(mission.mission_id)
        return None

    async def heartbeat(
        self,
        mission_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 60,
    ) -> MissionProjection:
        await self.get(mission_id)
        lease = self._leases.get(mission_id)
        if lease is None or lease[0] != worker_id:
            raise PermissionError(f"worker {worker_id} does not own mission {mission_id}")
        self._leases[mission_id] = (
            worker_id,
            utc_now() + timedelta(seconds=max(10, lease_seconds)),
            lease[2],
        )
        await self.append_event(
            mission_id,
            "mission.lease_heartbeat",
            actor=f"worker:{worker_id}",
            payload={"lease_seconds": max(10, lease_seconds)},
            fencing_token=lease[2],
        )
        return await self.get(mission_id)

    async def release(self, mission_id: str, worker_id: str) -> None:
        lease = self._leases.get(mission_id)
        if lease is None or lease[0] != worker_id:
            return
        self._leases.pop(mission_id, None)
        await self.append_event(
            mission_id,
            "mission.lease_released",
            actor=f"worker:{worker_id}",
            payload={},
            fencing_token=lease[2],
        )

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
        fencing_token: int = 0,
    ) -> MissionProjection:
        current = await self.get(mission_id)
        if current.version != expected_version:
            raise MissionVersionConflict(mission_id)
        await self.append_event(
            mission_id,
            "mission.transitioned",
            actor=actor,
            payload={
                "from": current.status.value,
                "to": target.value,
                "reason": reason,
                "current_step_id": (
                    current.current_step_id if current_step_id is None else current_step_id
                ),
                "terminal_summary": (
                    current.terminal_summary if terminal_summary is None else terminal_summary
                ),
                "control_requested": (
                    current.control_requested if control_requested is None else control_requested
                ),
            },
            fencing_token=fencing_token,
        )
        return await self.get(mission_id)

    async def update_usage(
        self,
        mission_id: str,
        *,
        expected_version: int,
        delta: dict[str, int],
        fencing_token: int = 0,
    ) -> MissionProjection:
        current = await self.get(mission_id)
        if current.version != expected_version:
            raise MissionVersionConflict(mission_id)
        await self.append_event(
            mission_id,
            "mission.usage_updated",
            actor="runtime",
            payload={"delta": delta},
            fencing_token=fencing_token,
        )
        return await self.get(mission_id)

    async def set_current_step(
        self,
        mission_id: str,
        *,
        expected_version: int,
        step_id: str,
        fencing_token: int = 0,
    ) -> MissionProjection:
        current = await self.get(mission_id)
        if current.version != expected_version:
            raise MissionVersionConflict(mission_id)
        await self.append_event(
            mission_id,
            "mission.current_step_set",
            actor="runtime",
            payload={"step_id": step_id},
            fencing_token=fencing_token,
        )
        return await self.get(mission_id)

    async def save_plan(
        self, mission_id: str, plan: PlanV2, *, fencing_token: int = 0
    ) -> None:
        mission = await self.get(mission_id)
        plans = self._plans[mission_id]
        if plan.version != len(plans) + 1:
            raise ValueError("plan versions must be contiguous and append-only")
        if plan.version > mission.budget.max_plan_versions:
            raise ValueError("plan version budget exceeded")
        if len(plan.steps) > mission.budget.max_steps_per_plan:
            raise ValueError("plan step budget exceeded")
        await self.append_event(
            mission_id,
            "plan.activated",
            actor="runtime",
            payload={"plan": plan.model_dump(mode="json")},
            fencing_token=fencing_token,
        )

    async def plans(self, mission_id: str) -> Sequence[PlanV2]:
        await self.get(mission_id)
        return list(self._plans[mission_id])

    async def start_attempt(
        self,
        mission_id: str,
        plan_version: int,
        step: PlanStepV2,
        attempt: int,
        *,
        fencing_token: int = 0,
    ) -> StepAttemptV2:
        row = StepAttemptV2(
            attempt_id=self._id("sat"),
            plan_version=plan_version,
            step_id=step.step_id,
            attempt=attempt,
            status="running",
            capability_id=step.capability_id,
        )
        await self.append_event(
            mission_id,
            "attempt.started",
            actor="runtime",
            payload={"attempt": row.model_dump(mode="json")},
            fencing_token=fencing_token,
        )
        return row

    async def complete_attempt(
        self,
        attempt_id: str,
        observation: StepObservationV2,
        *,
        fencing_token: int = 0,
    ) -> StepAttemptV2:
        for mission_id, attempts in self._attempts.items():
            for attempt in attempts:
                if attempt.attempt_id != attempt_id:
                    continue
                await self.append_event(
                    mission_id,
                    "attempt.completed",
                    actor="runtime",
                    payload={
                        "attempt_id": attempt_id,
                        "observation": observation.model_dump(mode="json"),
                    },
                    fencing_token=fencing_token,
                )
                return next(
                    row for row in self._attempts[mission_id] if row.attempt_id == attempt_id
                )
        raise KeyError(attempt_id)

    async def attempts(self, mission_id: str) -> Sequence[StepAttemptV2]:
        await self.get(mission_id)
        return list(self._attempts[mission_id])

    async def append_event(
        self,
        mission_id: str,
        event_type: str,
        *,
        actor: str,
        payload: dict[str, object],
        causation_id: str = "",
        policy_snapshot_hash: str = "",
        fencing_token: int = 0,
    ) -> MissionEventV2:
        snapshot = self._snapshots[mission_id]
        mission = snapshot.mission
        if mission is None or mission.replay_status != "canonical":
            raise RuntimeError("legacy or quarantined Mission is read-only")
        aliases = {
            "mission_worker_failed": "mission.worker_failed",
            "mission_lease_claimed": "mission.lease_claimed",
            "mission_lease_heartbeat": "mission.lease_heartbeat",
            "mission_lease_released": "mission.lease_released",
        }
        event = make_mission_event(
            event_id=self._id("mevt"),
            event_type=aliases.get(event_type, event_type),
            mission_id=mission_id,
            sequence=mission.event_cursor + 1,
            actor=actor,
            payload=payload,
            causation_id=causation_id,
            policy_snapshot_hash=policy_snapshot_hash,
            fencing_token=fencing_token,
        )
        try:
            updated = apply_mission_event(snapshot, event)
        except MissionProtocolError as exc:
            assert mission is not None
            quarantined_mission = mission.model_copy(
                update={
                    "replay_status": MissionReplayStatus.QUARANTINED,
                    "quarantine_reason": str(exc)[:1_000],
                }
            )
            self._snapshots[mission_id] = snapshot.model_copy(
                update={
                    "mission": quarantined_mission,
                    "replay_status": MissionReplayStatus.QUARANTINED,
                    "quarantine_reason": str(exc)[:1_000],
                }
            )
            self._missions[mission_id] = quarantined_mission
            raise
        self._commit(mission_id, updated, event)
        return event

    async def record_completion_proof(
        self,
        mission_id: str,
        proof: CompletionProofV1,
        *,
        fencing_token: int = 0,
    ) -> MissionProjection:
        await self.append_event(
            mission_id,
            "mission.completion_proof_recorded",
            actor="completion_verifier",
            payload={"proof": proof.model_dump(mode="json")},
            fencing_token=fencing_token,
        )
        return await self.get(mission_id)

    async def events(
        self, mission_id: str, *, after: int = 0, limit: int = 500
    ) -> Sequence[MissionEventV1 | MissionEventV2]:
        await self.get(mission_id)
        return [event for event in self._events[mission_id] if event.sequence > after][
            : max(1, min(limit, 1_000))
        ]

    async def append_steer(
        self, mission_id: str, steer: SteeringEventV1, *, fencing_token: int = 0
    ) -> None:
        mission = await self.get(mission_id)
        self._steers[mission_id].append(steer)
        await self.append_event(
            mission_id,
            "mission.steered",
            actor=steer.actor,
            payload={
                "instruction": steer.instruction,
                "reason": steer.reason,
                "objective": f"{mission.objective}\nSteer: {steer.instruction}",
            },
            fencing_token=fencing_token,
        )

    def _commit(
        self,
        mission_id: str,
        snapshot: MissionSnapshotV2,
        event: MissionEventV2,
    ) -> None:
        if snapshot.mission is None:
            raise ValueError("cannot persist an empty Mission snapshot")
        self._snapshots[mission_id] = snapshot
        self._missions[mission_id] = snapshot.mission
        self._plans[mission_id] = list(snapshot.plans)
        self._attempts[mission_id] = list(snapshot.attempts)
        self._events[mission_id].append(event)


def _request_hash(payload: MissionCreate) -> str:
    return sha256(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
