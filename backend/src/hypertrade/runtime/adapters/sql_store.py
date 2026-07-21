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
from hypertrade.runtime.domain.mission_events import (
    MISSION_SCHEMA_VERSION,
    MissionEventV2,
    MissionProtocolError,
    MissionSnapshotV2,
    apply_mission_event,
    make_mission_event,
    mission_projection_hash,
)
from hypertrade.runtime.domain.models import (
    TERMINAL_STATUSES,
    CompletionProofV1,
    MissionBudgetV1,
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
)


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
        now = datetime.now(UTC)
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
            event_protocol_version=MISSION_SCHEMA_VERSION,
            replay_status="canonical",
            created_at=now,
            updated_at=now,
        )
        event = make_mission_event(
            event_id=new_id("mevt"),
            event_type="mission_created",
            mission_id=mission_id,
            sequence=1,
            actor=payload.created_by,
            policy_snapshot_hash=sha256(payload.permission_profile_ref.encode()).hexdigest(),
            payload={"projection": projection.model_dump(mode="json")},
        )
        snapshot = apply_mission_event(MissionSnapshotV2(), event)
        async with self.sessions.begin() as session:
            replay = await session.scalar(
                select(AgentMission).where(AgentMission.idempotency_key == idempotency_key)
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("mission idempotency key is bound to different content")
                return _projection(replay)
            session.add(_event_row(event))
            await _persist_snapshot(session, snapshot, request_hash=request_hash)
        assert snapshot.mission is not None
        return snapshot.mission

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
                .where(AgentMission.replay_status == "canonical")
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
            snapshot = await _load_snapshot(session, row.id)
            row.lease_owner = worker_id
            row.lease_expires_at = now + timedelta(seconds=max(10, lease_seconds))
            row.lease_fencing_token += 1
            updated = await _append_canonical(
                session,
                snapshot,
                "mission.lease_claimed",
                actor=f"worker:{worker_id}",
                payload={"lease_seconds": max(10, lease_seconds)},
                fencing_token=row.lease_fencing_token,
            )
            await session.flush()
            assert updated.mission is not None
            return updated.mission

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
            snapshot = await _load_snapshot(session, mission_id)
            updated = await _append_canonical(
                session,
                snapshot,
                "mission.lease_heartbeat",
                actor=f"worker:{worker_id}",
                payload={"lease_seconds": max(10, lease_seconds)},
                fencing_token=row.lease_fencing_token,
            )
            await session.flush()
            assert updated.mission is not None
            return updated.mission

    async def release(self, mission_id: str, worker_id: str) -> None:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.lease_owner != worker_id:
                return
            token = row.lease_fencing_token
            row.lease_owner = None
            row.lease_expires_at = None
            await _append_canonical(
                session,
                await _load_snapshot(session, mission_id),
                "mission.lease_released",
                actor=f"worker:{worker_id}",
                payload={},
                fencing_token=token,
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
        fencing_token: int = 0,
    ) -> MissionProjection:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.version != expected_version:
                raise MissionVersionConflict(mission_id)
            current = MissionStatus(row.status)
            snapshot = await _load_snapshot(session, mission_id)
            if target in TERMINAL_STATUSES:
                # Lease fields are operational, not reducer state. Clear them
                # before projection persistence so the ORM performs one UPDATE
                # whose timestamp remains bound to the terminal event.
                row.lease_owner = None
                row.lease_expires_at = None
            updated = await _append_canonical(
                session,
                snapshot,
                "mission.transitioned",
                actor=actor,
                payload={
                    "from": current.value,
                    "to": target.value,
                    "reason": reason,
                    "current_step_id": (
                        row.current_step_id if current_step_id is None else current_step_id
                    ),
                    "terminal_summary": (
                        row.terminal_summary if terminal_summary is None else terminal_summary
                    ),
                    "control_requested": (
                        row.control_requested if control_requested is None else control_requested
                    ),
                },
                fencing_token=fencing_token,
            )
            assert updated.mission is not None
            await session.flush()
            return updated.mission

    async def update_usage(
        self,
        mission_id: str,
        *,
        expected_version: int,
        delta: dict[str, int],
        fencing_token: int = 0,
    ) -> MissionProjection:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.version != expected_version:
                raise MissionVersionConflict(mission_id)
            updated = await _append_canonical(
                session,
                await _load_snapshot(session, mission_id),
                "mission.usage_updated",
                actor="runtime",
                payload={"delta": delta},
                fencing_token=fencing_token,
            )
            assert updated.mission is not None
            return updated.mission

    async def set_current_step(
        self,
        mission_id: str,
        *,
        expected_version: int,
        step_id: str,
        fencing_token: int = 0,
    ) -> MissionProjection:
        async with self.sessions.begin() as session:
            row = await self._locked_mission(session, mission_id)
            if row.version != expected_version:
                raise MissionVersionConflict(mission_id)
            updated = await _append_canonical(
                session,
                await _load_snapshot(session, mission_id),
                "mission.current_step_set",
                actor="runtime",
                payload={"step_id": step_id},
                fencing_token=fencing_token,
            )
            assert updated.mission is not None
            return updated.mission

    async def save_plan(
        self, mission_id: str, plan: PlanV2, *, fencing_token: int = 0
    ) -> None:
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
            await _append_canonical(
                session,
                await _load_snapshot(session, mission_id),
                "plan.activated",
                actor="runtime",
                payload={"plan": plan.model_dump(mode="json")},
                fencing_token=fencing_token,
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
        self,
        mission_id: str,
        plan_version: int,
        step: PlanStepV2,
        attempt: int,
        *,
        fencing_token: int = 0,
    ) -> StepAttemptV2:
        attempt_projection = StepAttemptV2(
            attempt_id=new_id("sat"),
            plan_version=plan_version,
            step_id=step.step_id,
            attempt=attempt,
            capability_id=step.capability_id,
            status="running",
        )
        async with self.sessions.begin() as session:
            await self._locked_mission(session, mission_id)
            updated = await _append_canonical(
                session,
                await _load_snapshot(session, mission_id),
                "attempt.started",
                actor="runtime",
                payload={"attempt": attempt_projection.model_dump(mode="json")},
                fencing_token=fencing_token,
            )
        return next(
            row for row in updated.attempts if row.attempt_id == attempt_projection.attempt_id
        )

    async def complete_attempt(
        self,
        attempt_id: str,
        observation: StepObservationV2,
        *,
        fencing_token: int = 0,
    ) -> StepAttemptV2:
        async with self.sessions.begin() as session:
            row = await session.get(AgentStepAttempt, attempt_id, with_for_update=True)
            if row is None:
                raise KeyError(attempt_id)
            await self._locked_mission(session, row.mission_id)
            updated = await _append_canonical(
                session,
                await _load_snapshot(session, row.mission_id),
                "attempt.completed",
                actor="runtime",
                payload={
                    "attempt_id": attempt_id,
                    "observation": observation.model_dump(mode="json"),
                },
                fencing_token=fencing_token,
            )
            return next(item for item in updated.attempts if item.attempt_id == attempt_id)

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
        try:
            async with self.sessions.begin() as session:
                await self._locked_mission(session, mission_id)
                aliases = {"mission_worker_failed": "mission.worker_failed"}
                event, _ = await _append_canonical_with_event(
                    session,
                    await _load_snapshot(session, mission_id),
                    aliases.get(event_type, event_type),
                    actor=actor,
                    payload=payload,
                    causation_id=causation_id,
                    policy_snapshot_hash=policy_snapshot_hash,
                    fencing_token=fencing_token,
                )
                return event
        except (MissionProtocolError, PermissionError) as exc:
            await self._quarantine(mission_id, str(exc))
            raise

    async def record_completion_proof(
        self,
        mission_id: str,
        proof: CompletionProofV1,
        *,
        fencing_token: int = 0,
    ) -> MissionProjection:
        async with self.sessions.begin() as session:
            await self._locked_mission(session, mission_id)
            updated = await _append_canonical(
                session,
                await _load_snapshot(session, mission_id),
                "mission.completion_proof_recorded",
                actor="completion_verifier",
                payload={"proof": proof.model_dump(mode="json")},
                fencing_token=fencing_token,
            )
            assert updated.mission is not None
            return updated.mission

    async def events(
        self, mission_id: str, *, after: int = 0, limit: int = 500
    ) -> Sequence[MissionEventV1 | MissionEventV2]:
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

    async def append_steer(
        self, mission_id: str, steer: SteeringEventV1, *, fencing_token: int = 0
    ) -> None:
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
            await _append_canonical(
                session,
                await _load_snapshot(session, mission_id),
                "mission.steered",
                actor=steer.actor,
                payload={
                    "instruction": steer.instruction,
                    "reason": steer.reason,
                    "objective": f"{mission.objective}\nSteer: {steer.instruction}",
                },
                fencing_token=fencing_token,
            )

    async def _locked_mission(self, session: AsyncSession, mission_id: str) -> AgentMission:
        row = await session.scalar(
            select(AgentMission).where(AgentMission.id == mission_id).with_for_update()
        )
        if row is None:
            raise KeyError(mission_id)
        return row

    async def _quarantine(self, mission_id: str, reason: str) -> None:
        async with self.sessions.begin() as session:
            snapshot = await _load_snapshot(session, mission_id)
            await _persist_quarantine(session, snapshot, reason)

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
            "event_cursor": row.last_event_sequence,
            "event_protocol_version": row.event_protocol_version,
            "replay_status": row.replay_status,
            "quarantine_reason": row.quarantine_reason,
            "fencing_token": row.lease_fencing_token,
            "control_requested": row.control_requested,
            "terminal_summary": row.terminal_summary,
            "unknowns": row.unknowns_json,
            "artifact_refs": row.artifact_refs_json,
            "completion_proof": row.completion_proof_json or None,
            "created_by": row.created_by,
            "idempotency_key": row.idempotency_key,
            "deadline": row.deadline,
            "created_at": _as_utc(row.created_at),
            "updated_at": _as_utc(row.updated_at),
        }
    )


def _attempt(row: AgentStepAttempt) -> StepAttemptV2:
    return StepAttemptV2.model_validate(
        {
            "attempt_id": row.id,
            "plan_version": row.plan_version,
            "step_id": row.step_id,
            "attempt": row.attempt,
            "status": row.status,
            "capability_id": row.capability_id,
            "observation": row.observation_json or None,
            "started_at": _as_utc(row.started_at),
            "completed_at": _as_utc(row.completed_at) if row.completed_at else None,
        }
    )


def _event(row: AgentMissionEvent) -> MissionEventV1 | MissionEventV2:
    if row.schema_version == MISSION_SCHEMA_VERSION:
        return MissionEventV2(
            event_id=row.id,
            event_type=row.event_type,
            aggregate_type=row.aggregate_type,
            aggregate_id=row.mission_id,
            aggregate_version=row.aggregate_version,
            sequence=row.sequence,
            schema_version=row.schema_version,
            reducer_version=row.reducer_version,
            causation_id=row.causation_id,
            correlation_id=row.correlation_id,
            actor=row.actor,
            policy_snapshot_hash=row.policy_snapshot_hash,
            payload_hash=row.payload_hash,
            payload=row.payload_json,
            fencing_token=row.fencing_token,
            occurred_at=_as_utc(row.occurred_at),
            recorded_at=_as_utc(row.recorded_at),
        )
    return MissionEventV1(
        sequence=row.sequence,
        event_type=row.event_type,
        actor=row.actor,
        payload=row.payload_json,
        created_at=_as_utc(row.created_at),
    )


async def _load_snapshot(session: AsyncSession, mission_id: str) -> MissionSnapshotV2:
    mission = await session.get(AgentMission, mission_id)
    if mission is None:
        raise KeyError(mission_id)
    plans = (
        await session.scalars(
            select(AgentPlanVersion)
            .where(AgentPlanVersion.mission_id == mission_id)
            .order_by(AgentPlanVersion.version)
        )
    ).all()
    attempts = (
        await session.scalars(
            select(AgentStepAttempt)
            .where(AgentStepAttempt.mission_id == mission_id)
            .order_by(AgentStepAttempt.started_at, AgentStepAttempt.id)
        )
    ).all()
    projection = _projection(mission)
    return MissionSnapshotV2(
        mission=projection,
        plans=tuple(PlanV2.model_validate(row.plan_json) for row in plans),
        attempts=tuple(_attempt(row) for row in attempts),
        replay_status=projection.replay_status,
        quarantine_reason=projection.quarantine_reason,
    )


async def _persist_snapshot(
    session: AsyncSession,
    snapshot: MissionSnapshotV2,
    *,
    request_hash: str = "",
) -> None:
    mission = snapshot.mission
    if mission is None:
        raise ValueError("cannot persist an empty Mission snapshot")
    row = await session.get(AgentMission, mission.mission_id)
    values = {
        "objective": mission.objective,
        "original_objective": mission.original_objective,
        "success_criteria_json": [
            item.model_dump(mode="json") for item in mission.success_criteria
        ],
        "constraints_json": list(mission.constraints),
        "status": mission.status.value,
        "budget_json": mission.budget.model_dump(mode="json"),
        "usage_json": mission.usage.model_dump(mode="json"),
        "permission_profile_ref": mission.permission_profile_ref,
        "context_policy_ref": mission.context_policy_ref,
        "active_plan_version": mission.active_plan_version,
        "current_step_id": mission.current_step_id,
        "version": mission.version,
        "last_event_sequence": mission.event_cursor,
        "event_protocol_version": mission.event_protocol_version,
        "replay_status": mission.replay_status.value,
        "projection_hash": mission_projection_hash(snapshot),
        "quarantine_reason": mission.quarantine_reason,
        "completion_proof_json": (
            mission.completion_proof.model_dump(mode="json")
            if mission.completion_proof is not None
            else {}
        ),
        "lease_fencing_token": mission.fencing_token,
        "control_requested": mission.control_requested,
        "terminal_summary": mission.terminal_summary,
        "unknowns_json": list(mission.unknowns),
        "artifact_refs_json": list(mission.artifact_refs),
        "created_by": mission.created_by,
        "idempotency_key": mission.idempotency_key,
        "deadline": mission.deadline,
        "created_at": mission.created_at,
        "updated_at": mission.updated_at,
    }
    if row is None:
        if not request_hash:
            raise ValueError("new Mission projection requires request hash")
        row = AgentMission(id=mission.mission_id, request_hash=request_hash, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    for plan in snapshot.plans:
        existing = await session.scalar(
            select(AgentPlanVersion)
            .where(AgentPlanVersion.mission_id == mission.mission_id)
            .where(AgentPlanVersion.version == plan.version)
        )
        if existing is None:
            canonical = plan.model_dump_json(exclude={"created_at"})
            session.add(
                AgentPlanVersion(
                    mission_id=mission.mission_id,
                    version=plan.version,
                    parent_version=plan.parent_version,
                    plan_json=plan.model_dump(mode="json"),
                    content_hash=sha256(canonical.encode()).hexdigest(),
                )
            )
    for attempt in snapshot.attempts:
        attempt_row = await session.get(AgentStepAttempt, attempt.attempt_id)
        attempt_values = {
            "mission_id": mission.mission_id,
            "plan_version": attempt.plan_version,
            "step_id": attempt.step_id,
            "attempt": attempt.attempt,
            "capability_id": attempt.capability_id,
            "status": attempt.status,
            "observation_json": (
                attempt.observation.model_dump(mode="json")
                if attempt.observation is not None
                else {}
            ),
            "started_at": attempt.started_at,
            "completed_at": attempt.completed_at,
        }
        if attempt_row is None:
            session.add(AgentStepAttempt(id=attempt.attempt_id, **attempt_values))
        else:
            for key, value in attempt_values.items():
                setattr(attempt_row, key, value)
    await session.flush()


async def _append_canonical(
    session: AsyncSession,
    snapshot: MissionSnapshotV2,
    event_type: str,
    *,
    actor: str,
    payload: dict[str, object],
    causation_id: str = "",
    policy_snapshot_hash: str = "",
    fencing_token: int = 0,
) -> MissionSnapshotV2:
    _, updated = await _append_canonical_with_event(
        session,
        snapshot,
        event_type,
        actor=actor,
        payload=payload,
        causation_id=causation_id,
        policy_snapshot_hash=policy_snapshot_hash,
        fencing_token=fencing_token,
    )
    return updated


async def _append_canonical_with_event(
    session: AsyncSession,
    snapshot: MissionSnapshotV2,
    event_type: str,
    *,
    actor: str,
    payload: dict[str, object],
    causation_id: str = "",
    policy_snapshot_hash: str = "",
    fencing_token: int = 0,
) -> tuple[MissionEventV2, MissionSnapshotV2]:
    mission = snapshot.mission
    if mission is None or mission.replay_status.value != "canonical":
        raise RuntimeError("legacy or quarantined Mission is read-only")
    if (
        fencing_token
        and event_type != "mission.lease_claimed"
        and fencing_token != mission.fencing_token
    ):
        await _persist_quarantine(session, snapshot, "stale Mission worker fencing token")
        raise PermissionError("stale Mission worker fencing token")
    event = make_mission_event(
        event_id=new_id("mevt"),
        event_type=event_type,
        mission_id=mission.mission_id,
        sequence=mission.event_cursor + 1,
        actor=actor,
        payload=dict(payload),
        causation_id=causation_id,
        policy_snapshot_hash=policy_snapshot_hash,
        fencing_token=fencing_token,
    )
    try:
        updated = apply_mission_event(snapshot, event)
    except MissionProtocolError as exc:
        await _persist_quarantine(session, snapshot, str(exc))
        raise
    session.add(_event_row(event))
    await _persist_snapshot(session, updated)
    return event, updated


async def _persist_quarantine(
    session: AsyncSession,
    snapshot: MissionSnapshotV2,
    reason: str,
) -> None:
    mission = snapshot.mission
    if mission is None:
        return
    quarantined = snapshot.model_copy(
        update={
            "mission": mission.model_copy(
                update={
                    "replay_status": MissionReplayStatus.QUARANTINED,
                    "quarantine_reason": reason[:1_000],
                }
            ),
            "replay_status": MissionReplayStatus.QUARANTINED,
            "quarantine_reason": reason[:1_000],
        }
    )
    await _persist_snapshot(session, quarantined)


def _event_row(event: MissionEventV2) -> AgentMissionEvent:
    return AgentMissionEvent(
        id=event.event_id,
        mission_id=event.aggregate_id,
        sequence=event.sequence,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_version=event.aggregate_version,
        schema_version=event.schema_version,
        reducer_version=event.reducer_version,
        causation_id=event.causation_id,
        correlation_id=event.correlation_id,
        actor=event.actor,
        policy_snapshot_hash=event.policy_snapshot_hash,
        payload_hash=event.payload_hash,
        payload_json=event.payload,
        fencing_token=event.fencing_token,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
        created_at=event.recorded_at,
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _request_hash(payload: MissionCreate) -> str:
    return sha256(
        json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
