from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

import anyio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hypertrade.db import (
    AgentAssignment,
    AgentBudgetReservation,
    AgentConflict,
    AgentHandoff,
    AgentMission,
)
from hypertrade.runtime.adapters.sql_store import async_database_url
from hypertrade.runtime.domain.models import MissionProjection
from hypertrade.runtime.domain.supervision import (
    AssignmentCreateV1,
    AssignmentV1,
    BudgetReservationV1,
    ConflictV1,
    HandoffV1,
    MergeDecisionV1,
    RoleDefinitionV1,
    TeamRunRequestV1,
    supervision_hash,
)

AssignmentWorker = Callable[[AssignmentV1], Awaitable[HandoffV1]]


class RoleCatalog:
    def __init__(self, roles: Sequence[RoleDefinitionV1] | None = None) -> None:
        self._roles = {role.role_id: role for role in (roles or builtin_roles())}

    def list(self) -> Sequence[RoleDefinitionV1]:
        return sorted(self._roles.values(), key=lambda role: role.role_id)

    def validate(self, payload: AssignmentCreateV1, permission_profile: str) -> None:
        role = self._roles.get(payload.role_id)
        if role is None or not role.reviewed:
            raise ValueError(f"role is not reviewed: {payload.role_id}")
        if permission_profile not in role.permission_profiles:
            raise ValueError("role does not allow Mission permission profile")
        if payload.capability_id not in role.capability_allowlist:
            raise ValueError("capability is outside role allowlist")

    def get(self, role_id: str) -> RoleDefinitionV1:
        try:
            return self._roles[role_id]
        except KeyError as exc:
            raise ValueError(f"role is not reviewed: {role_id}") from exc


def builtin_roles() -> tuple[RoleDefinitionV1, ...]:
    return (
        RoleDefinitionV1(
            role_id="research_lead",
            title="Research lead",
            purpose="Frame and merge bounded research assignments.",
            capability_allowlist=("runtime.objective_inspection",),
        ),
        RoleDefinitionV1(
            role_id="market_analyst",
            title="Market analyst",
            purpose="Inspect bounded market summaries.",
            capability_allowlist=("market.summary",),
        ),
        RoleDefinitionV1(
            role_id="evidence_analyst",
            title="Evidence analyst",
            purpose="Inspect reviewed RAG and Memory evidence.",
            capability_allowlist=("rag.search", "memory.search"),
        ),
        RoleDefinitionV1(
            role_id="critic",
            title="Evidence critic",
            purpose="Challenge claims and preserve unresolved unknowns.",
            capability_allowlist=("runtime.objective_inspection",),
        ),
    )


class SupervisionStore(Protocol):
    async def create(self, assignment: AssignmentV1) -> AssignmentV1: ...

    async def reserve(self, mission: MissionProjection, assignment: AssignmentV1) -> None: ...

    async def finish(self, assignment_id: str, status: str, error: str = "") -> None: ...

    async def save_handoff(self, handoff: HandoffV1) -> None: ...

    async def save_conflicts(self, conflicts: Sequence[ConflictV1]) -> None: ...

    async def assignments(self, mission_id: str) -> Sequence[AssignmentV1]: ...

    async def handoffs(self, mission_id: str) -> Sequence[HandoffV1]: ...

    async def conflicts(self, mission_id: str) -> Sequence[ConflictV1]: ...


class InMemorySupervisionStore:
    def __init__(self) -> None:
        self._assignments: dict[str, AssignmentV1] = {}
        self._reservations: dict[str, tuple[str, BudgetReservationV1]] = {}
        self._handoffs: dict[str, HandoffV1] = {}
        self._conflicts: dict[str, ConflictV1] = {}
        self._lock = anyio.Lock()

    async def create(self, assignment: AssignmentV1) -> AssignmentV1:
        existing = self._assignments.get(assignment.assignment_id)
        if existing is not None and not _same_assignment_contract(existing, assignment):
            raise ValueError("assignment id is bound to a different contract")
        self._assignments[assignment.assignment_id] = existing or assignment
        return self._assignments[assignment.assignment_id]

    async def reserve(self, mission: MissionProjection, assignment: AssignmentV1) -> None:
        async with self._lock:
            if assignment.assignment_id in self._reservations:
                return
            active = [
                reservation
                for owner, reservation in self._reservations.values()
                if owner == mission.mission_id
            ]
            requested = assignment.reservation
            if (
                mission.usage.tokens + sum(item.tokens for item in active) + requested.tokens
                > mission.budget.max_tokens
            ):
                raise ValueError("parallel token reservation exceeds Mission budget")
            if (
                mission.usage.tool_calls
                + sum(item.tool_calls for item in active)
                + requested.tool_calls
                > mission.budget.max_tool_calls
            ):
                raise ValueError("parallel tool reservation exceeds Mission budget")
            if (
                mission.usage.model_calls
                + sum(item.model_calls for item in active)
                + requested.model_calls
                > mission.budget.max_steps_per_plan * mission.budget.max_model_calls_per_step
            ):
                raise ValueError("parallel model reservation exceeds Mission budget")
            if (
                mission.usage.duration_ms
                + sum(item.duration_ms for item in active)
                + requested.duration_ms
                > mission.budget.max_duration_seconds * 1_000
            ):
                raise ValueError("parallel duration reservation exceeds Mission budget")
            self._reservations[assignment.assignment_id] = (mission.mission_id, requested)

    async def finish(self, assignment_id: str, status: str, error: str = "") -> None:
        current = self._assignments[assignment_id]
        self._assignments[assignment_id] = current.model_copy(
            update={"status": status, "error": error[:500]}
        )
        if status in {"succeeded", "failed", "canceled"}:
            self._reservations.pop(assignment_id, None)

    async def save_handoff(self, handoff: HandoffV1) -> None:
        self._handoffs[handoff.assignment_id] = handoff

    async def save_conflicts(self, conflicts: Sequence[ConflictV1]) -> None:
        for conflict in conflicts:
            self._conflicts[conflict.conflict_id] = conflict

    async def assignments(self, mission_id: str) -> Sequence[AssignmentV1]:
        return [row for row in self._assignments.values() if row.mission_id == mission_id]

    async def handoffs(self, mission_id: str) -> Sequence[HandoffV1]:
        return [row for row in self._handoffs.values() if row.mission_id == mission_id]

    async def conflicts(self, mission_id: str) -> Sequence[ConflictV1]:
        return [row for row in self._conflicts.values() if row.mission_id == mission_id]


class SqlSupervisionStore(InMemorySupervisionStore):
    def __init__(self, database_url: str) -> None:
        super().__init__()
        self.engine = create_async_engine(async_database_url(database_url), pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def create(self, assignment: AssignmentV1) -> AssignmentV1:
        async with self.sessions.begin() as session:
            row = await session.get(AgentAssignment, assignment.assignment_id)
            if row is None:
                session.add(
                    AgentAssignment(
                        id=assignment.assignment_id,
                        mission_id=assignment.mission_id,
                        role_id=assignment.role_id,
                        objective=assignment.objective,
                        capability_id=assignment.capability_id,
                        depends_on_json=list(assignment.depends_on),
                        context_pack_refs_json=list(assignment.context_pack_refs),
                        artifact_refs_json=list(assignment.artifact_refs),
                        reservation_json=assignment.reservation.model_dump(mode="json"),
                        status=assignment.status,
                        error=assignment.error,
                    )
                )
                return assignment
            existing = _assignment_from_row(row)
            if not _same_assignment_contract(existing, assignment):
                raise ValueError("assignment id is bound to a different contract")
            return existing

    async def reserve(self, mission: MissionProjection, assignment: AssignmentV1) -> None:
        async with self.sessions.begin() as session:
            projection = await session.get(AgentMission, mission.mission_id, with_for_update=True)
            if projection is None:
                raise KeyError(mission.mission_id)
            replay = await session.scalar(
                select(AgentBudgetReservation).where(
                    AgentBudgetReservation.assignment_id == assignment.assignment_id
                )
            )
            if replay is not None:
                return
            reserved_tokens = await session.scalar(
                select(func.coalesce(func.sum(AgentBudgetReservation.tokens), 0))
                .where(AgentBudgetReservation.mission_id == mission.mission_id)
                .where(AgentBudgetReservation.status == "reserved")
            )
            reserved_tools = await session.scalar(
                select(func.coalesce(func.sum(AgentBudgetReservation.tool_calls), 0))
                .where(AgentBudgetReservation.mission_id == mission.mission_id)
                .where(AgentBudgetReservation.status == "reserved")
            )
            reserved_models = await session.scalar(
                select(func.coalesce(func.sum(AgentBudgetReservation.model_calls), 0))
                .where(AgentBudgetReservation.mission_id == mission.mission_id)
                .where(AgentBudgetReservation.status == "reserved")
            )
            reserved_duration = await session.scalar(
                select(func.coalesce(func.sum(AgentBudgetReservation.duration_ms), 0))
                .where(AgentBudgetReservation.mission_id == mission.mission_id)
                .where(AgentBudgetReservation.status == "reserved")
            )
            if (
                mission.usage.tokens + int(reserved_tokens or 0) + assignment.reservation.tokens
                > mission.budget.max_tokens
            ):
                raise ValueError("parallel token reservation exceeds Mission budget")
            if (
                mission.usage.tool_calls
                + int(reserved_tools or 0)
                + assignment.reservation.tool_calls
                > mission.budget.max_tool_calls
            ):
                raise ValueError("parallel tool reservation exceeds Mission budget")
            if (
                mission.usage.model_calls
                + int(reserved_models or 0)
                + assignment.reservation.model_calls
                > mission.budget.max_steps_per_plan * mission.budget.max_model_calls_per_step
            ):
                raise ValueError("parallel model reservation exceeds Mission budget")
            if (
                mission.usage.duration_ms
                + int(reserved_duration or 0)
                + assignment.reservation.duration_ms
                > mission.budget.max_duration_seconds * 1_000
            ):
                raise ValueError("parallel duration reservation exceeds Mission budget")
            session.add(
                AgentBudgetReservation(
                    mission_id=mission.mission_id,
                    assignment_id=assignment.assignment_id,
                    **assignment.reservation.model_dump(),
                    status="reserved",
                )
            )

    async def finish(self, assignment_id: str, status: str, error: str = "") -> None:
        async with self.sessions.begin() as session:
            row = await session.get(AgentAssignment, assignment_id, with_for_update=True)
            if row is None:
                raise KeyError(assignment_id)
            row.status = status
            row.error = error[:500]
            reservation = await session.scalar(
                select(AgentBudgetReservation).where(
                    AgentBudgetReservation.assignment_id == assignment_id
                )
            )
            if reservation is not None and status in {"succeeded", "failed", "canceled"}:
                reservation.status = "committed" if status == "succeeded" else "released"

    async def save_handoff(self, handoff: HandoffV1) -> None:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(AgentHandoff).where(AgentHandoff.assignment_id == handoff.assignment_id)
            )
            if existing is None:
                session.add(
                    AgentHandoff(
                        id=handoff.handoff_id,
                        mission_id=handoff.mission_id,
                        assignment_id=handoff.assignment_id,
                        role_id=handoff.role_id,
                        summary=handoff.summary,
                        claims_json=handoff.claims,
                        source_refs_json=list(handoff.source_refs),
                        artifact_refs_json=list(handoff.artifact_refs),
                        unknowns_json=list(handoff.unknowns),
                        output_hash=handoff.output_hash,
                    )
                )

    async def save_conflicts(self, conflicts: Sequence[ConflictV1]) -> None:
        async with self.sessions.begin() as session:
            for conflict in conflicts:
                if await session.get(AgentConflict, conflict.conflict_id) is None:
                    session.add(
                        AgentConflict(
                            id=conflict.conflict_id,
                            mission_id=conflict.mission_id,
                            claim_key=conflict.claim_key,
                            values_json={
                                key: list(value) for key, value in conflict.values.items()
                            },
                            source_refs_json=list(conflict.source_refs),
                            status=conflict.status,
                            resolution=conflict.resolution,
                        )
                    )

    async def assignments(self, mission_id: str) -> Sequence[AssignmentV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentAssignment)
                    .where(AgentAssignment.mission_id == mission_id)
                    .order_by(AgentAssignment.created_at)
                )
            ).all()
            return [_assignment_from_row(row) for row in rows]

    async def handoffs(self, mission_id: str) -> Sequence[HandoffV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentHandoff)
                    .where(AgentHandoff.mission_id == mission_id)
                    .order_by(AgentHandoff.created_at)
                )
            ).all()
            return [_handoff_from_row(row) for row in rows]

    async def conflicts(self, mission_id: str) -> Sequence[ConflictV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentConflict)
                    .where(AgentConflict.mission_id == mission_id)
                    .order_by(AgentConflict.created_at)
                )
            ).all()
            return [_conflict_from_row(row) for row in rows]


class BoundedSupervisor:
    def __init__(self, store: SupervisionStore, catalog: RoleCatalog | None = None) -> None:
        self.store = store
        self.catalog = catalog or RoleCatalog()

    async def run(
        self,
        mission: MissionProjection,
        request: TeamRunRequestV1,
        worker: AssignmentWorker,
    ) -> MergeDecisionV1:
        assignments = self._materialize(mission, request)
        completed: set[str] = set()
        handoffs: list[HandoffV1] = []
        while len(completed) < len(assignments):
            ready = [
                row
                for row in assignments
                if row.assignment_id not in completed and set(row.depends_on) <= completed
            ]
            if not ready:
                raise ValueError("assignment dependency graph has a cycle")
            results: dict[str, HandoffV1] = {}

            async def execute(row: AssignmentV1, output: dict[str, HandoffV1]) -> None:
                await self.store.create(row)
                try:
                    await self.store.reserve(mission, row)
                    await self.store.finish(row.assignment_id, "running")
                    with anyio.fail_after(
                        next(
                            item.timeout_seconds
                            for item in request.assignments
                            if (item.assignment_id or _assignment_id(request, item))
                            == row.assignment_id
                        )
                    ):
                        handoff = await worker(row)
                    if handoff.assignment_id != row.assignment_id or handoff.role_id != row.role_id:
                        raise ValueError("handoff identity does not match assignment")
                    if not set(row.context_pack_refs) & set(handoff.source_refs):
                        raise ValueError("handoff must cite its assigned Context Pack")
                    await self.store.save_handoff(handoff)
                    await self.store.finish(row.assignment_id, "succeeded")
                    output[row.assignment_id] = handoff
                except BaseException as exc:
                    with anyio.CancelScope(shield=True):
                        await self.store.finish(row.assignment_id, "failed", str(exc))
                    raise

            try:
                async with anyio.create_task_group() as task_group:
                    for row in ready:
                        task_group.start_soon(execute, row, results)
            except BaseExceptionGroup as exc:
                failure = _first_failure(exc)
                raise ValueError(f"team assignment failed: {failure}") from failure
            for row in ready:
                handoffs.append(results[row.assignment_id])
                completed.add(row.assignment_id)
        conflicts, agreed = _merge_conflicts(mission.mission_id, handoffs)
        await self.store.save_conflicts(conflicts)
        return MergeDecisionV1(
            mission_id=mission.mission_id,
            handoff_refs=tuple(f"handoff:{row.handoff_id}@{row.output_hash}" for row in handoffs),
            agreed_claims=agreed,
            conflicts=tuple(conflicts),
            unknowns=tuple(
                sorted(
                    {unknown for row in handoffs for unknown in row.unknowns}
                    | {f"conflict:{row.claim_key}" for row in conflicts}
                )
            ),
        )

    def _materialize(
        self, mission: MissionProjection, request: TeamRunRequestV1
    ) -> tuple[AssignmentV1, ...]:
        if len(request.assignments) > 4:
            raise ValueError("team exceeds maximum of four assignments")
        ids = {item.assignment_id or _assignment_id(request, item) for item in request.assignments}
        if len(ids) != len(request.assignments):
            raise ValueError("assignment identities must be unique")
        role_counts: dict[str, int] = defaultdict(int)
        rows: list[AssignmentV1] = []
        for item in request.assignments:
            self.catalog.validate(item, mission.permission_profile_ref)
            role_counts[item.role_id] += 1
            if role_counts[item.role_id] > self.catalog.get(item.role_id).max_concurrency:
                raise ValueError("role concurrency exceeds reviewed catalog limit")
            if set(item.depends_on) - ids:
                raise ValueError("assignment has unknown dependencies")
            rows.append(
                AssignmentV1(
                    assignment_id=item.assignment_id or _assignment_id(request, item),
                    mission_id=mission.mission_id,
                    role_id=item.role_id,
                    objective=item.objective,
                    capability_id=item.capability_id,
                    depends_on=item.depends_on,
                    context_pack_refs=item.context_pack_refs,
                    artifact_refs=item.artifact_refs,
                    reservation=item.reservation,
                )
            )
        return tuple(rows)


def deterministic_worker(delay: float = 0.0) -> AssignmentWorker:
    async def run(assignment: AssignmentV1) -> HandoffV1:
        if delay:
            await anyio.sleep(delay)
        return HandoffV1(
            handoff_id=f"hndf_{supervision_hash(assignment.assignment_id)[:20]}",
            mission_id=assignment.mission_id,
            assignment_id=assignment.assignment_id,
            role_id=assignment.role_id,
            summary=f"{assignment.role_id} completed its bounded assignment.",
            claims={f"{assignment.role_id}.status": "completed"},
            source_refs=assignment.context_pack_refs + assignment.artifact_refs,
            artifact_refs=assignment.artifact_refs,
        )

    return run


def _assignment_id(request: TeamRunRequestV1, item: AssignmentCreateV1) -> str:
    digest = supervision_hash(
        {
            "idempotency_key": request.idempotency_key,
            "role_id": item.role_id,
            "objective": item.objective,
            "capability_id": item.capability_id,
            "context_pack_refs": item.context_pack_refs,
        }
    )
    return f"asgn_{digest[:20]}"


def _merge_conflicts(
    mission_id: str, handoffs: Sequence[HandoffV1]
) -> tuple[list[ConflictV1], dict[str, str]]:
    claims: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    sources: dict[str, set[str]] = defaultdict(set)
    for handoff in handoffs:
        for key, value in handoff.claims.items():
            claims[key][value].append(handoff.handoff_id)
            sources[key].update(handoff.source_refs)
    conflicts: list[ConflictV1] = []
    agreed: dict[str, str] = {}
    for key, values in sorted(claims.items()):
        if len(values) == 1:
            agreed[key] = next(iter(values))
            continue
        conflict_hash = supervision_hash({"mission_id": mission_id, "key": key, "values": values})
        conflicts.append(
            ConflictV1(
                conflict_id=f"cnfl_{conflict_hash[:20]}",
                mission_id=mission_id,
                claim_key=key,
                values={value: tuple(refs) for value, refs in values.items()},
                source_refs=tuple(sorted(sources[key])),
            )
        )
    return conflicts, agreed


def _assignment_from_row(row: AgentAssignment) -> AssignmentV1:
    return AssignmentV1(
        assignment_id=row.id,
        mission_id=row.mission_id,
        role_id=row.role_id,
        objective=row.objective,
        capability_id=row.capability_id,
        depends_on=tuple(row.depends_on_json),
        context_pack_refs=tuple(row.context_pack_refs_json),
        artifact_refs=tuple(row.artifact_refs_json),
        reservation=row.reservation_json,
        status=row.status,
        error=row.error,
    )


def _handoff_from_row(row: AgentHandoff) -> HandoffV1:
    return HandoffV1(
        handoff_id=row.id,
        mission_id=row.mission_id,
        assignment_id=row.assignment_id,
        role_id=row.role_id,
        summary=row.summary,
        claims=row.claims_json,
        source_refs=tuple(row.source_refs_json),
        artifact_refs=tuple(row.artifact_refs_json),
        unknowns=tuple(row.unknowns_json),
        output_hash=row.output_hash,
    )


def _conflict_from_row(row: AgentConflict) -> ConflictV1:
    return ConflictV1(
        conflict_id=row.id,
        mission_id=row.mission_id,
        claim_key=row.claim_key,
        values={key: tuple(value) for key, value in row.values_json.items()},
        source_refs=tuple(row.source_refs_json),
        status=row.status,
        resolution=row.resolution,
    )


def _first_failure(group: BaseExceptionGroup) -> BaseException:
    current: BaseException = group.exceptions[0]
    while isinstance(current, BaseExceptionGroup):
        current = current.exceptions[0]
    return current


def _same_assignment_contract(left: AssignmentV1, right: AssignmentV1) -> bool:
    excluded = {"status", "error"}
    return left.model_dump(exclude=excluded) == right.model_dump(exclude=excluded)
