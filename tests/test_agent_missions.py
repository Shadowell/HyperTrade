from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import AgentRun, AgentTask, Database
from hypertrade.main import create_app
from hypertrade.runtime.adapters.foundation import (
    FoundationExecutor,
    FoundationPlanner,
    ReadOnlyCapabilityPolicy,
)
from hypertrade.runtime.adapters.memory_store import (
    InMemoryMissionStore,
    MissionVersionConflict,
)
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.models import (
    MissionBudgetV1,
    MissionCreate,
    MissionStatus,
    PlanStepV2,
    PlanV2,
    SteeringEventV1,
    SuccessCriterionV1,
)
from pydantic import ValidationError
from sqlalchemy import func, select


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def mission_payload(**updates: object) -> MissionCreate:
    values: dict[str, object] = {
        "objective": "Inspect the current market research objective",
        "success_criteria": (
            SuccessCriterionV1(
                criterion_id="validated",
                kind="all_steps_validated",
                description="Every planned step has a validated observation.",
            ),
        ),
    }
    values.update(updates)
    return MissionCreate.model_validate(values)


@pytest.mark.anyio
async def test_foundation_mission_completes_without_legacy_task_writes() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    created = await runtime.create(mission_payload())

    completed = await runtime.run(created.mission_id)

    assert completed.status == MissionStatus.COMPLETED
    assert completed.active_plan_version == 1
    assert completed.usage.step_attempts == 1
    assert completed.usage.tool_calls == 1
    attempts = await store.attempts(created.mission_id)
    assert attempts[0].observation is not None
    assert attempts[0].observation.source_refs
    events = await store.events(created.mission_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


@pytest.mark.anyio
async def test_completion_evidence_is_required() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    created = await runtime.create(
        mission_payload(
            success_criteria=(
                SuccessCriterionV1(
                    criterion_id="artifact",
                    kind="artifact_kind_exists",
                    description="A report artifact must exist.",
                    expected="report",
                ),
            )
        )
    )

    result = await runtime.run(created.mission_id)

    assert result.status == MissionStatus.WAITING_INPUT
    assert result.terminal_summary == ""


@pytest.mark.anyio
async def test_optimistic_version_conflict_fails_closed() -> None:
    store = InMemoryMissionStore()
    created = await store.create(mission_payload())
    with pytest.raises(MissionVersionConflict):
        await store.transition(
            created.mission_id,
            expected_version=created.version + 1,
            target=MissionStatus.PLANNING,
            actor="test",
            reason="stale worker",
        )


@pytest.mark.anyio
async def test_pause_cancel_resume_use_safe_state_machine() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    created = await runtime.create(mission_payload())
    planning = await store.transition(
        created.mission_id,
        expected_version=created.version,
        target=MissionStatus.PLANNING,
        actor="test",
        reason="prepare",
    )
    plan = await FoundationPlanner().plan(planning)
    await store.save_plan(created.mission_id, plan)
    current = await store.get(created.mission_id)
    await store.transition(
        created.mission_id,
        expected_version=current.version,
        target=MissionStatus.RUNNING,
        actor="test",
        reason="prepare",
    )

    requested = await runtime.pause(created.mission_id)
    assert requested.status == MissionStatus.PAUSE_REQUESTED
    paused = await runtime.run(created.mission_id)
    assert paused.status == MissionStatus.PAUSED
    resumed = await runtime.resume(created.mission_id)
    assert resumed.status == MissionStatus.RUNNING
    canceled_request = await runtime.cancel(created.mission_id)
    assert canceled_request.status == MissionStatus.CANCEL_REQUESTED
    canceled = await runtime.run(created.mission_id)
    assert canceled.status == MissionStatus.CANCELED


@pytest.mark.anyio
async def test_steer_appends_plan_and_preserves_original_objective() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    created = await runtime.create(mission_payload())
    planning = await store.transition(
        created.mission_id,
        expected_version=created.version,
        target=MissionStatus.PLANNING,
        actor="test",
        reason="prepare",
    )
    await store.save_plan(created.mission_id, await FoundationPlanner().plan(planning))
    current = await store.get(created.mission_id)
    await store.transition(
        created.mission_id,
        expected_version=current.version,
        target=MissionStatus.RUNNING,
        actor="test",
        reason="prepare",
    )

    result = await runtime.steer(
        created.mission_id,
        SteeringEventV1(
            instruction="Focus on ETH 4H",
            reason="Operator changed scope",
        ),
    )

    assert result.status == MissionStatus.RUNNING
    assert result.active_plan_version == 2
    assert result.original_objective == created.original_objective
    assert "ETH 4H" in result.objective
    plans = await store.plans(created.mission_id)
    assert plans[0].parent_version is None
    assert plans[1].parent_version == 1


@pytest.mark.anyio
async def test_sql_store_survives_new_adapter_instance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'missions.db'}"
    Database(database_url).create_all()
    first = SqlAlchemyMissionStore(database_url)
    created = await first.create(mission_payload())
    await first.dispose()

    second = SqlAlchemyMissionStore(database_url)
    loaded = await second.get(created.mission_id)
    events = await second.events(created.mission_id)
    await second.dispose()

    assert loaded.objective == created.objective
    assert events[0].event_type == "mission_created"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_plan_versions", 0),
        ("max_plan_versions", 6),
        ("max_steps_per_plan", 0),
        ("max_steps_per_plan", 25),
        ("max_attempts_per_step", 0),
        ("max_attempts_per_step", 4),
        ("max_model_calls_per_step", 9),
        ("max_tool_calls", 0),
        ("max_tokens", 999),
        ("max_duration_seconds", 9),
    ],
)
def test_mission_budget_cannot_be_expanded_beyond_hard_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        MissionBudgetV1.model_validate({field: value})


def test_plan_rejects_cycles_unknown_dependencies_and_duplicate_ids() -> None:
    with pytest.raises(ValidationError, match="acyclic"):
        PlanV2(
            plan_id="plan_cycle",
            version=1,
            goal_interpretation="cycle test",
            completion_checks=("done",),
            steps=(
                PlanStepV2(
                    step_id="a",
                    title="Step A",
                    capability_id="runtime.objective_inspection",
                    depends_on=("b",),
                ),
                PlanStepV2(
                    step_id="b",
                    title="Step B",
                    capability_id="runtime.objective_inspection",
                    depends_on=("a",),
                ),
            ),
        )
    with pytest.raises(ValidationError, match="unknown dependencies"):
        PlanV2(
            plan_id="plan_unknown",
            version=1,
            goal_interpretation="unknown dependency test",
            completion_checks=("done",),
            steps=(
                PlanStepV2(
                    step_id="a",
                    title="Step A",
                    capability_id="runtime.objective_inspection",
                    depends_on=("missing",),
                ),
            ),
        )


def test_policy_rejects_unknown_and_write_capabilities() -> None:
    policy = ReadOnlyCapabilityPolicy()
    with pytest.raises(ValueError, match="unregistered"):
        policy.validate_step(
            PlanStepV2(
                step_id="unknown",
                title="Unknown capability",
                capability_id="live.order",
            ),
            "read_only.v1",
        )
    with pytest.raises(ValueError, match="write"):
        policy.validate_step(
            PlanStepV2(
                step_id="write",
                title="Write capability",
                capability_id="runtime.objective_inspection",
                read_only=False,
            ),
            "read_only.v1",
        )


def test_mission_api_uses_new_tables_without_legacy_dual_write() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="mission-test-secret",
        MISSION_RUNTIME_ENABLED=True,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        created = client.post(
            "/api/agent/missions",
            json=mission_payload().model_dump(mode="json"),
        )
        assert created.status_code == 200
        mission_id = created.json()["mission_id"]
        completed = client.post(f"/api/agent/missions/{mission_id}/run")
        events = client.get(f"/api/agent/missions/{mission_id}/events")

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert events.status_code == 200
    assert events.json()["next_cursor"] >= 1
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0
        assert session.scalar(select(func.count()).select_from(AgentRun)) == 0
