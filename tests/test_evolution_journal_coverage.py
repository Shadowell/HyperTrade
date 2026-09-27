"""Every worker loop and failure reason is journalled in full (redacted), not only stdout."""

import asyncio

import pytest
from hypertrade import worker
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.db import Database
from sqlalchemy import select
from test_arc_evolution import VariantPaper, _variant_service, prepare

SECRET = "sk-live-abcdefghijklmnopqrstuvwxyz0123456789"
LONG = "上游返回了一段很长的错误说明 " * 40 + f"api_key={SECRET} tail-marker"


@pytest.fixture
def db(tmp_path):
    reset_store()
    database = Database(f"sqlite:///{tmp_path}/journal.db")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


@pytest.fixture
def service(db):
    from hypertrade.arc.evolution import EvolutionService

    return EvolutionService(db)


def _errors(db, component=None):
    from hypertrade.arc.evolution_models import ArcRuntimeError

    with db.session() as session:
        rows = session.scalars(select(ArcRuntimeError)).all()
    return [r for r in rows if component is None or r.component == component]


class _Stop(Exception):
    pass


def _one_iteration(monkeypatch):
    async def stop(_seconds):
        raise _Stop

    monkeypatch.setattr(worker.asyncio, "sleep", stop)


def _boom(*args, **kwargs):
    raise RuntimeError("loop body failed")


async def _async_boom(*args, **kwargs):
    raise RuntimeError("loop body failed")


@pytest.mark.parametrize(
    ("loop", "patch", "component"),
    [
        ("paper_trading_loop", "PaperTradingService", "worker.paper_trading"),
        ("monitor_scheduler_loop", "monitor_scheduler_once", "worker.monitor_scheduler"),
        ("agent_task_worker_loop", "agent_task_worker_once", "worker.agent_task"),
        ("research_trigger_loop", "research_trigger_worker_once", "worker.research_trigger"),
        ("market_rest_supplement_loop", "MarketIngestor", "worker.okx_rest_supplement"),
    ],
)
def test_non_arc_worker_loop_failure_is_journalled(db, monkeypatch, loop, patch, component):
    class Failing:
        def __init__(self, *args, **kwargs):
            pass

        run_once = staticmethod(_boom)
        ingest_rest_once = staticmethod(_async_boom)

    monkeypatch.setattr(worker, patch, Failing if patch[0].isupper() else _boom)
    _one_iteration(monkeypatch)
    with pytest.raises(_Stop):
        asyncio.run(getattr(worker, loop)(db))
    rows = _errors(db, component)
    assert len(rows) == 1 and rows[0].message == "loop body failed"


def test_self_test_failure_reason_is_kept_in_full_and_redacted(db):
    from hypertrade.arc.self_test import ARCSelfTestService
    from test_arc_real_bitpro_path import _candidate, _goal, _RealShapeBitPro

    double = _RealShapeBitPro()
    double.fail_backtest_with = RuntimeError(LONG)
    result = ARCSelfTestService(client=double).run(_candidate(), _goal())
    assert result.passed is False
    assert "tail-marker" in result.message
    assert SECRET not in result.message
    rows = _errors(db, "self_test.backtest")
    assert len(rows) == 1 and "tail-marker" in rows[0].message


def test_diagnostic_reason_is_kept_in_full(service, monkeypatch):
    now = prepare(service, monkeypatch)

    def failing_trades(**kwargs):
        raise ValueError(LONG)

    service.client.strategy_trades = failing_trades
    result = service.tick(now)
    diagnostic = result["payload"]["diagnostics"][0]
    assert diagnostic["status"] == "unavailable"
    assert "tail-marker" in diagnostic["reason"]
    assert SECRET not in diagnostic["reason"]


def test_variant_policy_recheck_failure_is_recorded(service, db, monkeypatch):
    now = _variant_service(service, monkeypatch, 100)

    class FlakyPolicy(VariantPaper):
        reads = 0

        def strategy_research_variant_policy(self, **kwargs):
            self.reads += 1
            if self.reads > 1:
                raise ConnectionError("policy endpoint reset")
            return super().strategy_research_variant_policy(**kwargs)

    client = FlakyPolicy()
    client.capital = 100
    service.client = client
    result = service.tick(now)
    assert result["status"] == "source_changed"
    payload = result["payload"]
    assert payload["skip_error"] == "policy endpoint reset"
    rows = _errors(db, "evolution.variant_policy_recheck")
    assert [r.id for r in rows] == [payload["skip_error_id"]]
