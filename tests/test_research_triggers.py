from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from hypertrade.agent.tasks import AgentTaskService
from hypertrade.config import Settings
from hypertrade.db import (
    BitProPaperMonitorSnapshot,
    Database,
    MonitorRun,
    ResearchTrigger,
    ResearchTriggerFire,
    utc_now,
)
from hypertrade.main import create_app
from hypertrade.research.schemas import ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.triggers import (
    CommittedTriggerEventAdapter,
    ResearchTriggerCreate,
    ResearchTriggerService,
    TriggerCondition,
    TriggerControlUpdate,
    TriggerEvent,
)
from sqlalchemy import func, select


def _service(
    *, enabled: bool = True, global_quota: int = 20
) -> tuple[Database, ResearchTriggerService, str]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    mandate = ResearchProgramService(db).create_mandate(
        ResearchMandateCreate(
            name="Trigger test mandate",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    settings = Settings(
        RESEARCH_TRIGGERS_ENABLED=enabled,
        RESEARCH_TRIGGER_GLOBAL_DAILY_QUOTA=global_quota,
    )
    return db, ResearchTriggerService(db, settings=settings), str(mandate["id"])


def _create_trigger(
    service: ResearchTriggerService,
    mandate_id: str,
    *,
    trigger_type: str = "data_quality",
    daily_quota: int = 2,
    condition: TriggerCondition | None = None,
) -> dict[str, object]:
    return service.create(
        ResearchTriggerCreate(
            name=f"{trigger_type} trigger {utc_now().timestamp()}",
            trigger_type=trigger_type,  # type: ignore[arg-type]
            mandate_id=mandate_id,
            objective_template="Investigate the committed signal with structured evidence.",
            enabled=True,
            daily_quota=daily_quota,
            cooldown_seconds=60,
            condition=condition or TriggerCondition(),
        ),
        actor="test",
    )


def test_trigger_is_fail_closed_bounded_and_deduplicated() -> None:
    db, disabled_service, mandate_id = _service(enabled=False)
    trigger = _create_trigger(disabled_service, mandate_id)
    event = TriggerEvent(source_type="data_quality", source_id="monitor-run-1")

    skipped = disabled_service.fire(str(trigger["id"]), event, actor="test")

    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "feature_disabled"
    assert AgentTaskService(db).list_tasks(limit=10) == []

    enabled_service = ResearchTriggerService(db, settings=Settings(RESEARCH_TRIGGERS_ENABLED=True))
    second_event = TriggerEvent(source_type="data_quality", source_id="monitor-run-2")
    created = enabled_service.fire(str(trigger["id"]), second_event, actor="test")
    duplicate = enabled_service.fire(str(trigger["id"]), second_event, actor="test")

    assert created["status"] == "created"
    assert duplicate["id"] == created["id"]
    assert duplicate["deduplicated"] is True
    tasks = AgentTaskService(db).list_tasks(limit=10)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.kind == "triggered_research"
    assert task.resource_type == "research_trigger_fire"
    assert task.budget_json["max_backtests"] == 0
    assert task.control_json["read_only"] is True
    assert "do not perform write actions" in task.objective


def test_condition_kill_switch_cooldown_and_quota_block_before_task_creation() -> None:
    db, service, mandate_id = _service(enabled=True, global_quota=1)
    trigger = _create_trigger(
        service,
        mandate_id,
        condition=TriggerCondition(metric="data_gap_count", operator="gte", value=2),
    )
    trigger_id = str(trigger["id"])

    mismatch = service.fire(
        trigger_id,
        TriggerEvent(
            source_type="data_quality",
            source_id="mismatch",
            metrics={"data_gap_count": 1},
        ),
        actor="test",
    )
    assert mismatch["reason"] == "condition_not_matched"

    service.set_control(TriggerControlUpdate(kill_switch=True, reason="incident"), actor="operator")
    killed = service.fire(
        trigger_id,
        TriggerEvent(
            source_type="data_quality",
            source_id="kill",
            metrics={"data_gap_count": 2},
        ),
        actor="test",
    )
    assert killed["reason"] == "global_kill_switch"
    service.set_control(
        TriggerControlUpdate(kill_switch=False, reason="incident cleared"),
        actor="operator",
    )

    first = service.fire(
        trigger_id,
        TriggerEvent(
            source_type="data_quality",
            source_id="first",
            metrics={"data_gap_count": 2},
        ),
        actor="test",
    )
    assert first["status"] == "created"
    cooldown = service.fire(
        trigger_id,
        TriggerEvent(
            source_type="data_quality",
            source_id="cooldown",
            metrics={"data_gap_count": 2},
        ),
        actor="test",
    )
    assert cooldown["reason"] == "cooldown_active"

    with db.session() as session:
        row = session.get(ResearchTriggerFire, str(first["id"]))
        assert row is not None
        row.created_at = utc_now() - timedelta(days=1)
    # The global quota is reached by a different trigger even after cooldown expires.
    other = _create_trigger(service, mandate_id, trigger_type="strategy_drift")
    quota = service.fire(
        str(other["id"]),
        TriggerEvent(source_type="strategy_drift", source_id="quota"),
        actor="test",
    )
    assert quota["status"] == "created"
    third = _create_trigger(service, mandate_id, trigger_type="evaluation_regression")
    blocked = service.fire(
        str(third["id"]),
        TriggerEvent(source_type="evaluation_regression", source_id="global-quota"),
        actor="test",
    )
    assert blocked["reason"] == "global_daily_quota"
    assert len(AgentTaskService(db).list_tasks(limit=20)) == 2


def test_committed_projection_adapters_are_source_bound() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        monitor = MonitorRun(
            monitor_id="mon-1",
            monitor_type="data_quality",
            status="completed",
            completed_at=utc_now(),
            metric_snapshot_json={"freshness_seconds": 120},
            alerts_json=[{"code": "stale"}],
            data_gaps_json=["candles"],
        )
        paper = BitProPaperMonitorSnapshot(
            strategy_id=42,
            status="completed",
            metrics_json={"drawdown_pct": 0.12},
            drift_json={"sharpe_delta": -0.4},
        )
        session.add_all([monitor, paper])
        session.flush()
        monitor_event = CommittedTriggerEventAdapter.monitor_run(
            monitor, source_type="data_quality"
        )
        paper_event = CommittedTriggerEventAdapter.paper_snapshot(paper)

    world_event = CommittedTriggerEventAdapter.world_state(
        {
            "source_id": "world:committed-1",
            "status": "completed",
            "generated_at": "2026-07-14T12:00:00Z",
            "global_market": {"risk_regime": "risk_off", "volatility_regime": "high"},
            "missing_data": ["rates"],
        }
    )
    eval_event = CommittedTriggerEventAdapter.eval_status(
        {"status": "failed", "case_count": 2, "cases": [{"status": "failed"}]},
        observed_at=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert monitor_event.refs["monitor_run_id"] == monitor.id
    assert monitor_event.metrics["metric.freshness_seconds"] == 120
    assert paper_event.refs["paper_snapshot_id"] == paper.id
    assert paper_event.metrics["drift.sharpe_delta"] == -0.4
    assert world_event.metrics["risk_regime"] == "risk_off"
    assert eval_event.metrics["failed_case_count"] == 1


def test_trigger_module_has_no_direct_write_adapter_reachability() -> None:
    source = Path("backend/src/hypertrade/research/triggers.py").read_text()

    for forbidden in (
        "hypertrade.bitpro.mcp",
        "hypertrade.paper.service",
        "hypertrade.live.service",
        "okx_testnet_execute",
        "paper_start",
    ):
        assert forbidden not in source


def test_trigger_fire_history_is_immutable_decision_log() -> None:
    db, service, mandate_id = _service(enabled=True)
    trigger = _create_trigger(service, mandate_id)
    event = TriggerEvent(source_type="data_quality", source_id="immutable-1")

    service.fire(str(trigger["id"]), event, actor="test")

    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(ResearchTriggerFire)) == 1
    assert len(service.list_fires(trigger_id=str(trigger["id"]))) == 1


def test_trigger_storm_and_concurrent_workers_create_one_task(tmp_path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'trigger-race.db'}")
    db.create_all()
    mandate = ResearchProgramService(db).create_mandate(
        ResearchMandateCreate(
            name="Concurrent trigger mandate",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    settings = Settings(RESEARCH_TRIGGERS_ENABLED=True)
    service = ResearchTriggerService(db, settings=settings)
    trigger = _create_trigger(service, str(mandate["id"]))
    trigger_id = str(trigger["id"])
    observed_at = utc_now()

    def fire(_: int) -> dict[str, object]:
        return service.fire(
            trigger_id,
            TriggerEvent(
                source_type="data_quality",
                source_id="same-committed-event",
                observed_at=observed_at,
            ),
            actor="race",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(fire, range(2)))
    storm = [fire(index) for index in range(100)]

    assert {str(item["id"]) for item in concurrent + storm} == {str(concurrent[0]["id"])}
    assert any(item.get("deduplicated") is True for item in concurrent)
    assert len(AgentTaskService(db).list_tasks(limit=200)) == 1
    assert len(service.list_fires(trigger_id=trigger_id)) == 1


def test_fire_revalidates_persisted_task_budget() -> None:
    db, service, mandate_id = _service(enabled=True)
    trigger = _create_trigger(service, mandate_id)
    with db.session() as session:
        row = session.get(ResearchTrigger, str(trigger["id"]))
        assert row is not None
        row.task_budget_json = {**row.task_budget_json, "max_backtests": 1}

    result = service.fire(
        str(trigger["id"]),
        TriggerEvent(source_type="data_quality", source_id="invalid-budget"),
        actor="test",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "task_budget_invalid"
    assert AgentTaskService(db).list_tasks(limit=10) == []


def test_trigger_api_requires_admin_and_exposes_control_history() -> None:
    db, service, mandate_id = _service(enabled=True)
    trigger = _create_trigger(service, mandate_id)
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            RESEARCH_TRIGGERS_ENABLED=True,
        ),
        db=db,
    )
    client = TestClient(app)

    assert client.get("/api/research/triggers").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code
        == 200
    )
    listed = client.get("/api/research/triggers").json()
    assert listed["feature_enabled"] is True
    assert listed["items"][0]["id"] == trigger["id"]

    fire = client.post(
        f"/api/research/triggers/{trigger['id']}/fire",
        json={"source_type": "data_quality", "source_id": "api-event-1"},
    )
    assert fire.status_code == 200
    assert fire.json()["status"] == "created"
    history = client.get(
        "/api/research/triggers/fires", params={"trigger_id": trigger["id"]}
    ).json()
    assert history["items"][0]["task_id"] == fire.json()["task_id"]
    control = client.put(
        "/api/research/triggers/control",
        json={"kill_switch": True, "reason": "incident response"},
    )
    assert control.json()["kill_switch"] is True
