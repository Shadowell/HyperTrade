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


@pytest.mark.anyio
async def test_mission_create_replays_only_the_same_idempotent_request() -> None:
    store = InMemoryMissionStore()
    payload = mission_payload(idempotency_key="mission-create-replay-001")

    first = await store.create(payload)
    replay = await store.create(payload)

    assert replay.mission_id == first.mission_id
    assert await store.by_idempotency("mission-create-replay-001") == first
    with pytest.raises(ValueError, match="idempotency key"):
        await store.create(payload.model_copy(update={"objective": "Different objective"}))


@pytest.mark.anyio
async def test_sql_mission_create_replays_only_the_same_idempotent_request(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'mission-idempotency.db'}"
    Database(database_url).create_all()
    store = SqlAlchemyMissionStore(database_url)
    payload = mission_payload(idempotency_key="mission-sql-replay-001")
    try:
        first = await store.create(payload)
        replay = await store.create(payload)

        assert replay.mission_id == first.mission_id
        found = await store.by_idempotency("mission-sql-replay-001")
        assert found is not None
        assert found.mission_id == first.mission_id
        with pytest.raises(ValueError, match="idempotency key"):
            await store.create(payload.model_copy(update={"objective": "Changed objective"}))
    finally:
        await store.dispose()


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
        first_sequence = events.json()["events"][0]["sequence"]
        replay = client.get(
            f"/api/agent/missions/{mission_id}/events/stream",
            headers={"Last-Event-ID": str(first_sequence)},
        )
        invalid_cursor = client.get(
            f"/api/agent/missions/{mission_id}/events/stream",
            headers={"Last-Event-ID": "not-a-sequence"},
        )

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert events.status_code == 200
    assert events.json()["next_cursor"] >= 1
    assert replay.status_code == 200
    replay_ids = [
        int(line.removeprefix("id: "))
        for line in replay.text.splitlines()
        if line.startswith("id: ")
    ]
    assert replay_ids and min(replay_ids) > first_sequence
    assert invalid_cursor.status_code == 400
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0
        assert session.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_chat_canary_routes_to_mission_runtime_without_legacy_writes() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="mission-canary-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_CANARY_PERCENT=100,
    )
    key = "mission-chat-canary-001"
    with TestClient(create_app(settings=settings, db=database)) as client:
        first = client.post(
            "/api/agent/runs",
            headers={"Idempotency-Key": key},
            json={"prompt": "研究 BTC 市场状态和策略证据"},
        )
        replay = client.post(
            "/api/agent/runs",
            headers={"Idempotency-Key": key},
            json={"prompt": "研究 BTC 市场状态和策略证据"},
        )
        assert first.status_code == 200
        assert replay.status_code == 200
        assert first.json()["runtime"] == "mission_v2"
        assert first.json()["mission_id"] == replay.json()["mission_id"]
        assert first.json()["status"] == "completed"
        loaded = client.get(f"/api/agent/runs/{first.json()['id']}")
        assert loaded.status_code == 200
        assert loaded.json()["runtime"] == "mission_v2"
        streamed = client.post(
            "/api/agent/runs/stream",
            headers={"Idempotency-Key": "mission-chat-stream-001"},
            json={"prompt": "研究 BTC 市场状态"},
        )
        assert streamed.status_code == 200
        assert '"event": "answer_delta"' in streamed.text
        assert '"event": "evidence_ready"' in streamed.text
        assert '"event": "final"' in streamed.text
        assert '"runtime": "mission_v2"' in streamed.text

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0
        assert session.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_chat_ingress_blocks_or_holds_execution_requests_before_planning() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="mission-safety-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_CANARY_PERCENT=100,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        blocked = client.post(
            "/api/agent/runs",
            headers={"Idempotency-Key": "mission-mainnet-block-001"},
            json={"prompt": "主网满仓买入 ETH"},
        )
        review = client.post(
            "/api/agent/runs",
            headers={"Idempotency-Key": "mission-approval-hold-001"},
            json={"prompt": "执行尚未批准的 Testnet 意图"},
        )
        leverage = client.post(
            "/api/agent/runs",
            headers={"Idempotency-Key": "mission-leverage-hold-001"},
            json={"prompt": "用 100U 开 50 倍 BTC 合约"},
        )

    assert blocked.status_code == 200
    assert blocked.json()["status"] == "canceled"
    assert blocked.json()["report_json"]["operator_response"]["outcome"] == "blocked"
    assert review.status_code == 200
    assert review.json()["status"] == "waiting_approval"
    assert review.json()["report_json"]["operator_response"]["outcome"] == "needs_review"
    assert leverage.status_code == 200
    assert leverage.json()["status"] == "waiting_approval"


def test_operator_eval_fixtures_are_isolated_and_terminal() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    disabled = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="operator-eval-disabled-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_CANARY_PERCENT=100,
    )
    with TestClient(create_app(settings=disabled, db=database)) as client:
        rejected = client.post(
            "/api/agent/runs",
            json={
                "prompt": "读取 BTC 1H 行情",
                "evaluation_mode": True,
                "evaluation_case_id": "source_timeout",
            },
        )
    assert rejected.status_code == 409

    enabled_database = Database("sqlite:///:memory:")
    enabled_database.create_all()
    enabled = disabled.model_copy(
        update={"database_url": "sqlite:///:memory:", "operator_eval_fixtures_enabled": True}
    )
    with TestClient(create_app(settings=enabled, db=enabled_database)) as client:
        response = client.post(
            "/api/agent/runs",
            headers={"Idempotency-Key": "operator-eval-timeout-001"},
            json={
                "prompt": "读取 BTC 1H 行情",
                "evaluation_mode": True,
                "evaluation_case_id": "source_timeout",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    operator_response = response.json()["report_json"]["operator_response"]
    assert operator_response["outcome"] == "failed"
    assert operator_response["next_actions"]


def test_mission_stream_terminalizes_dispatch_failures_without_internal_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="mission-stream-failure-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_CANARY_PERCENT=100,
    )
    app = create_app(settings=settings, db=database)

    async def fail_dispatch(mission_id: str):
        created = await app.state.mission_store.get(mission_id)
        planning = await app.state.mission_store.transition(
            mission_id,
            expected_version=created.version,
            target=MissionStatus.PLANNING,
            actor="test",
            reason="prepare_failure_boundary",
        )
        await app.state.mission_store.transition(
            mission_id,
            expected_version=planning.version,
            target=MissionStatus.RUNNING,
            actor="test",
            reason="prepare_failure_boundary",
        )
        raise RuntimeError("private provider failure detail")

    monkeypatch.setattr(app.state.mission_runtime, "run", fail_dispatch)
    with TestClient(app) as client:
        streamed = client.post(
            "/api/agent/runs/stream",
            headers={"Idempotency-Key": "mission-stream-failure-001"},
            json={"prompt": "读取 BTC 行情"},
        )

    assert streamed.status_code == 200
    assert '"event": "warning"' in streamed.text
    assert '"event": "final"' in streamed.text
    assert '"outcome": "failed"' in streamed.text
    assert "private provider failure detail" not in streamed.text


def test_full_mission_cutover_makes_legacy_task_writes_read_only() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="mission-archive-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_CANARY_PERCENT=100,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret"},
        ).status_code == 200
        legacy = client.post(
            "/api/agent/sessions",
            json={"title": "legacy task should be archived"},
        )
        mission = client.post(
            "/api/agent/missions",
            json=mission_payload(idempotency_key="mission-archive-001").model_dump(mode="json"),
        )

    assert legacy.status_code == 410
    assert mission.status_code == 200


def test_mission_run_endpoint_leaves_dispatch_to_enabled_worker() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="mission-worker-dispatch-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_WORKER_ENABLED=True,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret"},
        ).status_code == 200
        created = client.post(
            "/api/agent/missions",
            json=mission_payload(idempotency_key="worker-dispatch-001").model_dump(mode="json"),
        )
        assert created.status_code == 200
        started = client.post(f"/api/agent/missions/{created.json()['mission_id']}/run")
        detail = client.get(f"/api/agent/missions/{created.json()['mission_id']}")

    assert started.status_code == 200
    assert started.json()["status"] == "draft"
    assert detail.status_code == 200
    assert detail.json()["attempts"] == []
