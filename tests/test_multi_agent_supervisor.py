from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.runtime.adapters.supervisor import (
    BoundedSupervisor,
    InMemorySupervisionStore,
    SqlSupervisionStore,
    deterministic_worker,
)
from hypertrade.runtime.domain.models import (
    MissionBudgetV1,
    MissionProjection,
    MissionStatus,
    SuccessCriterionV1,
)
from hypertrade.runtime.domain.supervision import (
    AssignmentCreateV1,
    BudgetReservationV1,
    HandoffV1,
    TeamRunRequestV1,
)
from pydantic import ValidationError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def mission(*, max_tokens: int = 10_000) -> MissionProjection:
    return MissionProjection(
        mission_id="mis_supervisor",
        objective="Run a bounded research team",
        original_objective="Run a bounded research team",
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="validated",
                kind="all_steps_validated",
                description="Assignments return validated handoffs",
            ),
        ),
        constraints=(),
        status=MissionStatus.RUNNING,
        budget=MissionBudgetV1(max_tokens=max_tokens),
        permission_profile_ref="read_only.v1",
        context_policy_ref="mission_context.v1",
        created_by="test",
    )


def item(
    role: str,
    capability: str,
    *,
    assignment_id: str = "",
    depends_on: tuple[str, ...] = (),
    reservation: BudgetReservationV1 | None = None,
    timeout: float = 1.0,
) -> AssignmentCreateV1:
    return AssignmentCreateV1(
        assignment_id=assignment_id,
        role_id=role,
        objective=f"Complete the {role} assignment",
        capability_id=capability,
        depends_on=depends_on,
        context_pack_refs=("context:ctxp_team@" + "a" * 64,),
        reservation=reservation or BudgetReservationV1(),
        timeout_seconds=timeout,
    )


def request(*assignments: AssignmentCreateV1, key: str = "team-run-001") -> TeamRunRequestV1:
    return TeamRunRequestV1(assignments=assignments, idempotency_key=key)


@pytest.mark.anyio
async def test_independent_roles_run_in_parallel() -> None:
    store = InMemorySupervisionStore()
    supervisor = BoundedSupervisor(store)
    payload = request(
        item("market_analyst", "market.summary"),
        item("evidence_analyst", "rag.search"),
    )
    started = time.monotonic()

    result = await supervisor.run(mission(), payload, deterministic_worker(delay=0.1))

    assert time.monotonic() - started < 0.18
    assert len(result.handoff_refs) == 2
    assert not result.conflicts
    replay = await supervisor.run(mission(), payload, deterministic_worker())
    assert replay.handoff_refs == result.handoff_refs
    assert len(await store.assignments(mission().mission_id)) == 2


@pytest.mark.anyio
async def test_dependencies_run_after_prerequisite() -> None:
    supervisor = BoundedSupervisor(InMemorySupervisionStore())
    order: list[str] = []

    async def worker(assignment):
        order.append(assignment.assignment_id)
        return await deterministic_worker()(assignment)

    payload = request(
        item("market_analyst", "market.summary", assignment_id="asgn_market"),
        item(
            "critic",
            "runtime.objective_inspection",
            assignment_id="asgn_critic",
            depends_on=("asgn_market",),
        ),
    )

    await supervisor.run(mission(), payload, worker)

    assert order == ["asgn_market", "asgn_critic"]


@pytest.mark.anyio
async def test_parallel_budget_reservation_is_atomic_and_released_on_failure() -> None:
    store = InMemorySupervisionStore()
    supervisor = BoundedSupervisor(store)
    too_large = BudgetReservationV1(tokens=600, tool_calls=1, model_calls=1)
    payload = request(
        item("market_analyst", "market.summary", reservation=too_large),
        item("evidence_analyst", "rag.search", reservation=too_large),
    )

    with pytest.raises(ValueError, match="token reservation"):
        await supervisor.run(mission(max_tokens=1_000), payload, deterministic_worker(delay=0.05))

    retry = request(
        item(
            "critic",
            "runtime.objective_inspection",
            reservation=BudgetReservationV1(tokens=1_000, tool_calls=1, model_calls=1),
        ),
        key="team-run-retry-001",
    )
    result = await supervisor.run(mission(max_tokens=1_000), retry, deterministic_worker())
    assert len(result.handoff_refs) == 1


@pytest.mark.anyio
async def test_timeout_releases_reservation_and_records_failure() -> None:
    store = InMemorySupervisionStore()
    supervisor = BoundedSupervisor(store)
    payload = request(
        item("market_analyst", "market.summary", timeout=0.01),
    )

    with pytest.raises(ValueError, match="team assignment failed"):
        await supervisor.run(mission(), payload, deterministic_worker(delay=0.05))

    rows = await store.assignments(mission().mission_id)
    assert rows[0].status == "failed"


@pytest.mark.anyio
async def test_conflicting_claims_are_preserved_as_unknown() -> None:
    supervisor = BoundedSupervisor(InMemorySupervisionStore())

    async def worker(assignment):
        value = "risk_on" if assignment.role_id == "market_analyst" else "risk_off"
        return HandoffV1(
            handoff_id=f"hndf_{assignment.role_id}",
            mission_id=assignment.mission_id,
            assignment_id=assignment.assignment_id,
            role_id=assignment.role_id,
            summary="Bounded conclusion with explicit evidence.",
            claims={"market.regime": value},
            source_refs=assignment.context_pack_refs,
        )

    result = await supervisor.run(
        mission(),
        request(
            item("market_analyst", "market.summary"),
            item("critic", "runtime.objective_inspection"),
        ),
        worker,
    )

    assert result.agreed_claims == {}
    assert result.conflicts[0].claim_key == "market.regime"
    assert "conflict:market.regime" in result.unknowns


def test_handoff_refuses_hidden_transcript_and_wrong_hash() -> None:
    values = {
        "handoff_id": "hndf_bad",
        "mission_id": "mis_supervisor",
        "assignment_id": "asgn_bad",
        "role_id": "critic",
        "summary": "Contains private reasoning transcript",
        "source_refs": ("context:ctxp@hash",),
    }
    with pytest.raises(ValidationError, match="forbidden"):
        HandoffV1.model_validate(values)
    values["summary"] = "Safe bounded summary"
    values["output_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="hash mismatch"):
        HandoffV1.model_validate(values)


@pytest.mark.anyio
async def test_sql_supervision_store_persists_team_state(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'supervision.db'}"
    Database(database_url).create_all()
    store = SqlSupervisionStore(database_url)
    supervisor = BoundedSupervisor(store)
    try:
        # SQL reservation locks the canonical Mission row, so this persistence test
        # uses direct append projections while API coverage exercises full dispatch.
        assignment = supervisor._materialize(
            mission(), request(item("market_analyst", "market.summary"))
        )[0]
        await store.create(assignment)
        handoff = await deterministic_worker()(assignment)
        await store.save_handoff(handoff)
        await store.finish(assignment.assignment_id, "succeeded")
        assignments = await store.assignments(mission().mission_id)
        handoffs = await store.handoffs(mission().mission_id)
    finally:
        await store.dispose()

    assert assignments[0].status == "succeeded"
    assert handoffs[0].output_hash == handoff.output_hash


def test_supervision_api_uses_compiled_context_and_shared_projection() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="supervision-api-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        AGENT_DYNAMIC_TEAM_ENABLED=True,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
        created = client.post(
            "/api/agent/missions",
            json={
                "objective": "Compile context then run a bounded research team",
                "success_criteria": [
                    {
                        "criterion_id": "validated",
                        "kind": "all_steps_validated",
                        "description": "The foundation step validates",
                    }
                ],
            },
        ).json()
        mission_id = created["mission_id"]
        client.post(f"/api/agent/missions/{mission_id}/run")
        pack = client.get(f"/api/agent/missions/{mission_id}/context-packs").json()[
            "context_packs"
        ][0]
        context_ref = f"context:{pack['context_pack_id']}@{pack['manifest_hash']}"
        team = client.post(
            f"/api/agent/missions/{mission_id}/team/run",
            json=request(
                item("market_analyst", "market.summary").model_copy(
                    update={"context_pack_refs": (context_ref,)}
                )
            ).model_dump(mode="json"),
        )
        projection = client.get(f"/api/agent/missions/{mission_id}/supervision")
        roles = client.get("/api/agent/roles")

    assert team.status_code == 200
    assert len(projection.json()["assignments"]) == 1
    assert len(projection.json()["handoffs"]) == 1
    assert len(roles.json()["roles"]) == 4
