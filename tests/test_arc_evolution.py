import pytest
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.db import Database


@pytest.fixture
def service():
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    yield EvolutionService(db)
    reset_store()


def test_defaults_are_hourly_and_disabled(service):
    state = service.status()
    assert state["config"]["enabled"] is False
    assert state["config"]["interval_minutes"] == 60
    assert state["config"]["threshold_pp"] == "10"
    assert service.tick()["status"] == "disabled"


def test_config_uses_revision_and_rejects_stale_updates(service):
    state = service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    assert state["revision"] == 1
    with pytest.raises(ValueError):
        service.configure(EvolutionConfig(enabled=False), revision=0, actor="test")


def test_preview_queues_without_enabling_background_research(service):
    cycle = service.queue_preview()
    assert cycle["status"] == "queued"
    assert cycle["payload"]["preview"] is True
    assert service.status()["config"]["enabled"] is False


class Paper:
    def paper_strategy_performance(self, **kwargs):
        return {
            "strategies": [
                {"strategy_id": 44, "strategy_name": "source", "mode": "paper", "timeframe": "1H"}
            ]
        }

    def paper_snapshot(self, **kwargs):
        return {
            "strategy_id": 44,
            "instance_id": "paper-source",
            "strategy_version": "v1",
            "config_version": "c1",
            "status": "running",
            "trade_count": 60,
            "strategy": {"symbols": ["SOL/USDT:USDT"]},
            "session": {"started_at": "2026-01-01T00:00:00Z"},
        }

    def strategy_get(self, **kwargs):
        return {"strategy": {"script_content": "class Source: pass", "config": {"timeframe": "1H"}}}

    def strategy_trades(self, **kwargs):
        return [
            {
                "id": 1,
                "strategy_id": 44,
                "timestamp": 1789171200000,
                "symbol": "SOL/USDT:USDT",
                "fee": 1,
                "pnl": -2,
            }
        ]


def prepare(service, monkeypatch):
    from datetime import UTC, datetime

    service.client = Paper()
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows",
        lambda *a, **k: {
            "triggered": True,
            "reasons": ["return_drop"],
            "end_at": "2026-09-12T00:00:00Z",
        },
    )
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")
    return datetime(2026, 9, 12, 12, tzinfo=UTC)


def test_schedule_creates_source_bound_research_once_per_hour(service, monkeypatch):
    from hypertrade.arc.store import get_controller, list_mission_ids

    now = prepare(service, monkeypatch)
    first = service.tick(now)
    assert first["status"] == "research_created"
    child = get_controller(first["payload"]["mission_id"])
    assert child.projection.goal.symbols == ["SOL-USDT-SWAP"]
    context = child.projection.goal.evolution_context
    assert context["source_instance_id"] == "paper-source"
    assert context["orders"]["sample_count"] == 1
    assert child.projection.goal.paper_authorization is None
    assert child.projection.goal.paper_review_required
    assert service.tick(now)["status"] == "idle"
    assert len(list_mission_ids()) == 1


def test_preview_never_creates_research(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    service.configure(EvolutionConfig(enabled=False), revision=1, actor="test")
    service.queue_preview()
    assert service.tick(now)["status"] == "preview_complete"
    assert list_mission_ids() == []


def test_switch_off_during_diagnostics_prevents_creation(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    original = service.client.strategy_get

    def toggle(**kwargs):
        service.configure(EvolutionConfig(enabled=False), revision=1, actor="test")
        return original(**kwargs)

    service.client.strategy_get = toggle
    assert service.tick(now)["status"] == "cancelled_by_config"
    assert list_mission_ids() == []


def test_missing_paper_identity_does_not_launch_research(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    service.client.paper_snapshot = lambda **kwargs: {"status": "error"}
    result = service.tick(now)
    assert result["status"] == "no_action"
    assert result["payload"]["diagnostics"][0]["status"] == "unavailable"
    assert list_mission_ids() == []


def test_crash_after_creation_recovers_same_task(service, monkeypatch):
    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    original = service._save_cycle

    def crash(key, status, payload):
        if status == "research_created":
            raise SystemExit("simulated crash")
        return original(key, status, payload)

    monkeypatch.setattr(service, "_save_cycle", crash)
    with pytest.raises(SystemExit):
        service.tick(now)
    ids = list_mission_ids()
    monkeypatch.setattr(service, "_save_cycle", original)
    assert service.tick(now)["payload"]["mission_id"] == ids[0]
    assert list_mission_ids() == ids


def test_baseline_preserves_parameters_without_reusing_runtime():
    from decimal import Decimal

    from hypertrade.arc.evolution import baseline_config

    config = baseline_config(
        {
            "config": {
                "fast_window": 20,
                "leverage": 2,
                "paper_instance_id": "old",
                "_runtime": {"positions": [1]},
                "initial_capital": 1000,
            }
        },
        Decimal(100),
    )
    assert config["fast_window"] == 20
    assert config["leverage"] == 2
    assert config["strategy_source"] == "db_script"
    assert config["script_content_source"] == "db"
    assert config["initial_capital"] == 100
    assert "paper_instance_id" not in config
    assert "_runtime" not in config
    with pytest.raises(ValueError):
        baseline_config({"config": {"api_key": "sensitive"}}, Decimal(100))


def test_long_term_memory_uses_development_receipts_not_final_holdout(service, monkeypatch):
    from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.store import save_mission

    now = prepare(service, monkeypatch)
    old = ARCController(goal=ARCGoalV1(objective="prior", symbols=["SOL-USDT-SWAP"]))
    old.projection.state = "failed"
    old.projection.attempts = [
        ARCCandidateAttemptV1(
            attempt_id="prior",
            candidate_id="prior",
            hypothesis="reduce churn",
            strategy_code="pass",
            observed_metrics={"secret_final_score": 999},
        )
    ]
    old.projection.avo["development"] = {
        "prior": {"backtest_id": "dev-proof", "metrics": {"net_return": -0.1}}
    }
    save_mission(old)
    result = service.tick(now)
    from hypertrade.arc.store import get_controller

    memory = get_controller(result["payload"]["mission_id"]).projection.goal.evolution_context[
        "memory"
    ]
    assert memory[0]["development"]["backtest_id"] == "dev-proof"
    assert "secret_final_score" not in str(memory)


def test_active_evolution_blocks_duplicate_source_next_hour(service, monkeypatch):
    from datetime import timedelta

    from hypertrade.arc.store import list_mission_ids

    now = prepare(service, monkeypatch)
    assert service.tick(now)["status"] == "research_created"
    assert service.tick(now + timedelta(hours=1))["status"] == "deferred"
    assert len(list_mission_ids()) == 1


def test_evolution_migration_creates_and_removes_only_its_tables():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = Path(__file__).parents[1] / "backend/alembic/versions/0042_arc_evolution.py"
    spec = importlib.util.spec_from_file_location("evolution_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
        assert set(inspect(connection).get_table_names()) == {
            "arc_evolution_control",
            "arc_evolution_cycles",
        }
        module.downgrade()
        assert inspect(connection).get_table_names() == []
