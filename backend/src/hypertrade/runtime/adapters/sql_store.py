from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hypertrade.db import (
    AgentMission,
    AgentMissionEvent,
    AgentPlanVersion,
    AgentSteeringEvent,
    AgentStepAttempt,
    new_id,
)
from hypertrade.runtime.adapters.memory_store import MissionVersionConflict
from hypertrade.runtime.domain.models import (
    TERMINAL_STATUSES,
    MissionBudgetV1,
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
)
from hypertrade.runtime.domain.state_machine import require_transition


def async_database_url(url: str) -> str:
    if url.startswith("sqlite+"):
        return url
    if url.startswith("sqlite:"):
        return url.replace("sqlite:", "sqlite+aiosqlite:", 1)
    if url.startswith("postgresql:"):
        return url.replace("postgresql:", "postgresql+psycopg:", 1)
    return url


class SqlAlchemyMissionStore:
    """Async PostgreSQL/SQLite adapter for the canonical Mission event model."""

    def __init__(self, database_url: str, *, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_async_engine(
            async_database_url(database_url), pool_pre_ping=True
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def create(self, payload: MissionCreate) -> MissionProjection:
        mission_id = new_id("mis")
        idempotency_key = payload.idempotency_key or f"internal:{mission_id}"
        request_hash = _request_hash(payload)
        row = AgentMission(
            id=mission_id,
            objective=payload.objective,
            original_objective=payload.objective,
            success_criteria_json=[
                item.model_dump(mode="json") for item in payload.success_criteria
            ],
            constraints_json=list(payload.constraints),
            status=MissionStatus.DRAFT.value,
            budget_json=payload.budget.model_dump(mode="json"),
            usage_json=MissionUsageV1().model_dump(mode="json"),
            permission_profile_ref=payload.permission_profile_ref,
            context_policy_ref=payload.context_policy_ref,
            created_by=payload.created_by,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            deadline=payload.deadline,
        )
        async with self.sessions.begin() as session:
            replay = await session.scalar(
                select(AgentMission).where(AgentMission.idempotency_key == idempotency_key)
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("mission idempotency key is bound to different content")
                return _projection(replay)
            session.add(row)
            await session.flush()
            await self._append_event(
                session,
                row,
                "mission_created",
                payload.created_by,
                {"objective_hash": sha256(payload.objective.encode()).hexdigest()},
            )
        return _projection(row)

    async def by_idempotency(self, idempotency_key: str) -> MissionProjection | None:
        if not idempotency_key:
            return None
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentMission).where(AgentMission.idempotency_key == idempotency_key)
            )
            return _projection(row) if row is not None else None

    async def get(self, mission_id: str) -> MissionProjection:
        async with self.sessions() as session:
            row = await session.get(AgentMission, mission_id)
            if row is None:
                raise KeyError(mission_id)
            return _projection(row)

    async def list(self, *, limit: int = 50) -> list[MissionProjection]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentMission)
                    .order_by(desc(AgentMission.created_at))
                    .limit(max(1, min(limit, 200)))
                )
            ).all()
            return [_projection(row) for row in rows]

    async def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 60,
    ) -> MissionProjection | None:
        """Claim one Mission without introducing a second queue or truth source."""

        now = datetime.now(UTC)
        runnable = (
            MissionStatus.DRAFT.value,
            MissionStatus.RUNNING.value,
            MissionStatus.RETRY_WAIT.value,
            MissionStatus.REPLANNING.value,
        )
        async with self.sessions.begin() as session:
            query = (
                select(AgentMission)
                .where(AgentMission.status.in_(runnable))
                .where(
                    or_(
                        AgentMission.lease_expires_at.is_(None),
                        AgentMission.lease_expires_at < now,
                    )
                )
                .order_by(AgentMission.created_at)
                .limit(1)
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = await session.scalar(query)
            if row is None:
                return None
            row.lease_owner = worker_id
            row.lease_expires_at = now + timedelta(seconds=max(10, lease_seconds))
            await self._append_event(
                session,
                row,
                "mission_lease_claimed",
                f"worker:{worker_id}",
                {"lease_seconds": max(10, lease_seconds)},
            )
            await session.flush()
            return _projection(row)

    async def heartbeat(
        self,
        mission_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 60,
    ) -> MissionProjection:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.lease_owner != worker_id:
                raise PermissionError(f"worker {worker_id} does not own mission {mission_id}")
            row.lease_expires_at = datetime.now(UTC) + timedelta(
                seconds=max(10, lease_seconds)
            )
            await self._append_event(
                session,
                row,
                "mission_lease_heartbeat",
                f"worker:{worker_id}",
                {"lease_seconds": max(10, lease_seconds)},
            )
            await session.flush()
            return _projection(row)

    async def release(self, mission_id: str, worker_id: str) -> None:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.lease_owner != worker_id:
                return
            row.lease_owner = None
            row.lease_expires_at = None
            await self._append_event(
                session,
                row,
                "mission_lease_released",
                f"worker:{worker_id}",
                {},
            )
            await session.flush()

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
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.version != expected_version:
                raise MissionVersionConflict(mission_id)
            current = MissionStatus(row.status)
            require_transition(current, target)
            row.status = target.value
            row.version += 1
            row.updated_at = datetime.now(UTC)
            if target in TERMINAL_STATUSES:
                row.lease_owner = None
                row.lease_expires_at = None
            if current_step_id is not None:
                row.current_step_id = current_step_id
            if terminal_summary is not None:
                row.terminal_summary = terminal_summary
            if control_requested is not None:
                row.control_requested = control_requested
            await self._append_event(
                session,
                row,
                "mission_transitioned",
                actor,
                {"from": current.value, "to": target.value, "reason": reason},
            )
            await session.flush()
            return _projection(row)

    async def update_usage(
        self, mission_id: str, *, expected_version: int, delta: dict[str, int]
    ) -> MissionProjection:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.version != expected_version:
                raise MissionVersionConflict(mission_id)
            usage = MissionUsageV1.model_validate(row.usage_json or {})
            values = usage.model_dump()
            for key, amount in delta.items():
                if key not in values or amount < 0:
                    raise ValueError(f"invalid usage delta: {key}")
                values[key] += amount
            row.usage_json = MissionUsageV1.model_validate(values).model_dump(mode="json")
            row.version += 1
            row.updated_at = datetime.now(UTC)
            await session.flush()
            return _projection(row)

    async def set_current_step(
        self, mission_id: str, *, expected_version: int, step_id: str
    ) -> MissionProjection:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.version != expected_version:
                raise MissionVersionConflict(mission_id)
            row.current_step_id = step_id
            row.version += 1
            row.updated_at = datetime.now(UTC)
            await session.flush()
            return _projection(row)

    async def save_plan(self, mission_id: str, plan: PlanV2) -> None:
        canonical = plan.model_dump_json(exclude={"created_at"})
        async with self.sessions.begin() as session:
            mission = await self._locked_mission(session, mission_id)
            if plan.version != mission.active_plan_version + 1:
                raise ValueError("plan versions must be contiguous and append-only")
            budget = MissionBudgetV1.model_validate(mission.budget_json)
            if (
                plan.version > budget.max_plan_versions
                or len(plan.steps) > budget.max_steps_per_plan
            ):
                raise ValueError("plan exceeds approved mission budget")
            session.add(
                AgentPlanVersion(
                    mission_id=mission_id,
                    version=plan.version,
                    parent_version=plan.parent_version,
                    plan_json=plan.model_dump(mode="json"),
                    content_hash=sha256(canonical.encode()).hexdigest(),
                )
            )
            usage = MissionUsageV1.model_validate(mission.usage_json or {})
            mission.usage_json = usage.model_copy(
                update={"plan_versions": plan.version}
            ).model_dump(mode="json")
            mission.active_plan_version = plan.version
            mission.version += 1
            mission.updated_at = datetime.now(UTC)
            await self._append_event(
                session,
                mission,
                "plan_activated",
                "runtime",
                {"plan_id": plan.plan_id, "version": plan.version, "diff": plan.diff.model_dump()},
            )

    async def plans(self, mission_id: str) -> Sequence[PlanV2]:
        await self.get(mission_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentPlanVersion)
                    .where(AgentPlanVersion.mission_id == mission_id)
                    .order_by(AgentPlanVersion.version)
                )
            ).all()
            return [PlanV2.model_validate(row.plan_json) for row in rows]

    async def start_attempt(
        self, mission_id: str, plan_version: int, step: PlanStepV2, attempt: int
    ) -> StepAttemptV2:
        row = AgentStepAttempt(
            mission_id=mission_id,
            plan_version=plan_version,
            step_id=step.step_id,
            attempt=attempt,
            capability_id=step.capability_id,
            status="running",
        )
        async with self.sessions.begin() as session:
            mission = await self._locked_mission(session, mission_id)
            session.add(row)
            await session.flush()
            await self._append_event(
                session,
                mission,
                "step_started",
                "runtime",
                {"plan_version": plan_version, "step_id": step.step_id, "attempt": attempt},
            )
        return _attempt(row)

    async def complete_attempt(
        self, attempt_id: str, observation: StepObservationV2
    ) -> StepAttemptV2:
        async with self.sessions.begin() as session:
            row = await session.get(AgentStepAttempt, attempt_id, with_for_update=True)
            if row is None:
                raise KeyError(attempt_id)
            mission = await self._locked_mission(session, row.mission_id)
            row.status = observation.status
            row.observation_json = observation.model_dump(mode="json")
            row.completed_at = datetime.now(UTC)
            await self._append_event(
                session,
                mission,
                "step_observed",
                "runtime",
                {
                    "step_id": row.step_id,
                    "attempt": row.attempt,
                    "status": observation.status,
                    "source_refs": list(observation.source_refs),
                    "artifact_refs": list(observation.artifact_refs),
                    "error_category": observation.error_category,
                },
            )
            await session.flush()
            return _attempt(row)

    async def attempts(self, mission_id: str) -> Sequence[StepAttemptV2]:
        await self.get(mission_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentStepAttempt)
                    .where(AgentStepAttempt.mission_id == mission_id)
                    .order_by(AgentStepAttempt.started_at)
                )
            ).all()
            return [_attempt(row) for row in rows]

    async def append_event(
        self, mission_id: str, event_type: str, *, actor: str, payload: dict[str, object]
    ) -> MissionEventV1:
        async with self.sessions.begin() as session:
            mission = await self._locked_mission(session, mission_id)
            row = await self._append_event(session, mission, event_type, actor, payload)
            await session.flush()
            return _event(row)

    async def events(
        self, mission_id: str, *, after: int = 0, limit: int = 500
    ) -> Sequence[MissionEventV1]:
        await self.get(mission_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentMissionEvent)
                    .where(AgentMissionEvent.mission_id == mission_id)
                    .where(AgentMissionEvent.sequence > after)
                    .order_by(AgentMissionEvent.sequence)
                    .limit(max(1, min(limit, 1_000)))
                )
            ).all()
            return [_event(row) for row in rows]

    async def append_steer(self, mission_id: str, steer: SteeringEventV1) -> None:
        async with self.sessions.begin() as session:
            mission = await self._locked_mission(session, mission_id)
            session.add(
                AgentSteeringEvent(
                    mission_id=mission_id,
                    plan_version_before=mission.active_plan_version,
                    instruction=steer.instruction,
                    reason=steer.reason,
                    actor=steer.actor,
                )
            )
            mission.objective = f"{mission.objective}\nSteer: {steer.instruction}"
            mission.updated_at = datetime.now(UTC)
            await self._append_event(
                session,
                mission,
                "mission_steered",
                steer.actor,
                {"instruction": steer.instruction, "reason": steer.reason},
            )

    async def _locked_mission(self, session: AsyncSession, mission_id: str) -> AgentMission:
        row = await session.scalar(
            select(AgentMission).where(AgentMission.id == mission_id).with_for_update()
        )
        if row is None:
            raise KeyError(mission_id)
        return row

    async def _append_event(
        self,
        session: AsyncSession,
        mission: AgentMission,
        event_type: str,
        actor: str,
        payload: dict[str, object],
    ) -> AgentMissionEvent:
        mission.last_event_sequence += 1
        event = AgentMissionEvent(
            mission_id=mission.id,
            sequence=mission.last_event_sequence,
            event_type=event_type,
            actor=actor,
            payload_json=payload,
        )
        session.add(event)
        return event


def _projection(row: AgentMission) -> MissionProjection:
    return MissionProjection.model_validate(
        {
            "mission_id": row.id,
            "objective": row.objective,
            "original_objective": row.original_objective,
            "success_criteria": row.success_criteria_json,
            "constraints": row.constraints_json,
            "status": row.status,
            "budget": row.budget_json,
            "usage": row.usage_json or {},
            "permission_profile_ref": row.permission_profile_ref,
            "context_policy_ref": row.context_policy_ref,
            "active_plan_version": row.active_plan_version,
            "current_step_id": row.current_step_id,
            "version": row.version,
            "control_requested": row.control_requested,
            "terminal_summary": row.terminal_summary,
            "unknowns": row.unknowns_json,
            "artifact_refs": row.artifact_refs_json,
            "created_by": row.created_by,
            "idempotency_key": row.idempotency_key,
            "deadline": row.deadline,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
    )


def _attempt(row: AgentStepAttempt) -> StepAttemptV2:
    return StepAttemptV2.model_validate(
        {
            "attempt_id": row.id,
            "step_id": row.step_id,
            "attempt": row.attempt,
            "status": row.status,
            "capability_id": row.capability_id,
            "observation": row.observation_json or None,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
    )


def _event(row: AgentMissionEvent) -> MissionEventV1:
    return MissionEventV1(
        sequence=row.sequence,
        event_type=row.event_type,
        actor=row.actor,
        payload=row.payload_json,
        created_at=row.created_at,
    )


def _request_hash(payload: MissionCreate) -> str:
    return sha256(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
