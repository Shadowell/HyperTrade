"""Worker liveness: what the worker records, how /api/healthz reads it, and the migration."""

import asyncio
import importlib.util
import time
from collections.abc import Iterator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from hypertrade import worker
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.market import client as market_client
from hypertrade.market.client import MarketIngestor
from hypertrade.runtime.heartbeat import (
    FAILING_STREAK,
    HeartbeatRegistry,
    WorkerHeartbeat,
    default_worker_id,
    flush_heartbeat,
    heartbeat_loop,
    read_worker_status,
)
from sqlalchemy import func, inspect, select

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    reset_store()
    database = Database(f"sqlite:///{tmp_path}/heartbeat.db")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


def _flush(db: Database, registry: HeartbeatRegistry, at: datetime = T0, **kwargs: Any) -> bool:
    return flush_heartbeat(
        db, worker_id=kwargs.pop("worker_id", "worker"), started_at=T0, registry=registry, now=at
    )


# --- the in-memory record ------------------------------------------------------------------


def test_success_resets_the_failure_streak_and_failure_extends_it() -> None:
    registry = HeartbeatRegistry()
    registry.record_failure("worker.x", RuntimeError("boom"), now=T0)
    registry.record_failure("worker.x", RuntimeError("boom"), now=T0)
    assert registry.snapshot()[0]["worker.x"]["consecutive_failures"] == 2

    registry.record_success("worker.x", now=T0 + timedelta(seconds=5))
    entry = registry.snapshot()[0]["worker.x"]

    assert entry["consecutive_failures"] == 0
    assert entry["failures_total"] == 2, "the lifetime total must survive a recovery"
    assert entry["last_ok_at"] == (T0 + timedelta(seconds=5)).isoformat()


def test_only_the_exception_type_is_recorded_never_its_message() -> None:
    registry = HeartbeatRegistry()
    registry.record_failure("worker.x", ValueError("api_key=sk-live-SECRET customer@example.com"))

    components, _ = registry.snapshot()

    assert components["worker.x"]["last_error_type"] == "ValueError"
    assert "SECRET" not in str(components) and "customer@example.com" not in str(components)


def test_supervisor_restarts_are_counted_separately_from_handled_failures() -> None:
    registry = HeartbeatRegistry()
    registry.record_failure("worker.x", RuntimeError(), restarted=True)
    registry.record_failure("worker.x", RuntimeError())

    entry = registry.snapshot()[0]["worker.x"]

    assert entry["restarts_total"] == 1 and entry["failures_total"] == 2


def test_snapshot_is_a_copy_and_event_loop_lag_keeps_recent_windows() -> None:
    registry = HeartbeatRegistry()
    registry.record_success("worker.x")
    registry.snapshot()[0]["worker.x"]["failures_total"] = 99
    assert registry.snapshot()[0]["worker.x"]["failures_total"] == 0

    registry.note_loop_lag(40.0)
    assert registry.snapshot(close_window=True)[1] == 40.0
    # the window closed, but the spike must stay visible to a reader polling a minute later
    assert registry.snapshot(close_window=True)[1] == 40.0
    for _ in range(10):  # ...for about ten flush windows, then it ages out
        registry.snapshot(close_window=True)
    assert registry.snapshot(close_window=True)[1] == 0.0


# --- the row and how it is read ------------------------------------------------------------


def test_flush_then_read_reports_an_alive_worker(db: Database) -> None:
    registry = HeartbeatRegistry()
    registry.record_success("worker.paper_trading", now=T0 - timedelta(seconds=10))
    registry.note_loop_lag(0.4)

    assert _flush(db, registry) is True
    status = read_worker_status(db, now=T0 + timedelta(seconds=20))

    assert status["status"] == "alive" and status["failing_components"] == []
    (worker_view,) = status["instances"]
    assert worker_view["worker_id"] == "worker" and worker_view["stale"] is False
    assert worker_view["heartbeat_age_seconds"] == 20.0
    assert worker_view["uptime_seconds"] == 20.0
    assert worker_view["event_loop_lag_max_seconds"] == 0.4
    assert worker_view["components"]["worker.paper_trading"]["last_ok_age_seconds"] == 30.0


def test_a_second_flush_updates_the_same_row(db: Database) -> None:
    registry = HeartbeatRegistry()
    _flush(db, registry, T0)
    _flush(db, registry, T0 + timedelta(seconds=30))

    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkerHeartbeat)) == 1

    status = read_worker_status(db, now=T0 + timedelta(seconds=40))
    assert status["instances"][0]["heartbeat_age_seconds"] == 10.0


def test_a_worker_that_stopped_reporting_is_stale_but_a_retired_one_is_forgotten(
    db: Database,
) -> None:
    _flush(db, HeartbeatRegistry())

    assert read_worker_status(db, now=T0 + timedelta(seconds=170))["status"] == "alive"
    stale = read_worker_status(db, now=T0 + timedelta(seconds=200))
    assert stale["status"] == "stale" and stale["instances"][0]["stale"] is True
    assert stale["failing_components"] == [], "a stale worker's streaks say nothing about now"

    forgotten = read_worker_status(db, now=T0 + timedelta(hours=25))
    assert forgotten == {"status": "unknown", "instances": []}


def test_no_worker_row_is_unknown_not_unhealthy(db: Database) -> None:
    assert read_worker_status(db) == {"status": "unknown", "instances": []}


def test_a_loop_failing_repeatedly_is_reported_until_it_recovers(db: Database) -> None:
    registry = HeartbeatRegistry()
    for _ in range(FAILING_STREAK):
        registry.record_failure("worker.arc_evolution", RuntimeError("down"), now=T0)
    registry.record_failure("worker.rag_scanner", RuntimeError("blip"), now=T0)
    _flush(db, registry)

    failing = read_worker_status(db, now=T0 + timedelta(seconds=5))["failing_components"]
    assert failing == ["worker.arc_evolution"], "one failure is a blip, a streak is a fault"

    registry.record_success("worker.arc_evolution", now=T0 + timedelta(seconds=10))
    _flush(db, registry, T0 + timedelta(seconds=30))
    assert read_worker_status(db, now=T0 + timedelta(seconds=35))["failing_components"] == []


def test_replicas_are_separate_rows_and_one_alive_is_enough(db: Database) -> None:
    _flush(db, HeartbeatRegistry(), T0, worker_id="worker-a")
    _flush(db, HeartbeatRegistry(), T0 + timedelta(seconds=200), worker_id="worker-b")

    status = read_worker_status(db, now=T0 + timedelta(seconds=210))

    assert status["status"] == "alive"
    assert {w["worker_id"]: w["stale"] for w in status["instances"]} == {
        "worker-a": True,
        "worker-b": False,
    }


def test_liveness_reporting_never_raises(tmp_path: Path) -> None:
    unmigrated = Database(f"sqlite:///{tmp_path}/no-tables.db")  # no create_all: table is missing

    assert flush_heartbeat(
        unmigrated, worker_id="w", started_at=T0, registry=HeartbeatRegistry()
    ) is False
    status = read_worker_status(unmigrated)
    assert status["status"] == "unknown" and status["reason"] == "unreadable"


def test_worker_id_can_be_set_per_replica(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPERTRADE_WORKER_ID", raising=False)
    assert default_worker_id() == "worker"
    monkeypatch.setenv("HYPERTRADE_WORKER_ID", " worker-2 ")
    assert default_worker_id() == "worker-2"


def test_heartbeat_loop_flushes_and_catches_a_blocked_event_loop(db: Database) -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        task = asyncio.create_task(
            heartbeat_loop(db, registry=registry, interval_seconds=0.05, worker_id="w")
        )
        await asyncio.sleep(0.15)  # first flush done, timer armed
        time.sleep(0.4)  # a synchronous call holding the event loop: what lag must reveal
        await asyncio.sleep(0.2)  # the late timer fires; the next flush carries the lag
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    (view,) = read_worker_status(db)["instances"]
    assert view["worker_id"] == "w"
    assert view["event_loop_lag_max_seconds"] >= 0.25


# --- the migration -------------------------------------------------------------------------


def _migration() -> Any:
    path = Path(__file__).parents[1] / "backend/alembic/versions/0052_worker_heartbeats.py"
    spec = importlib.util.spec_from_file_location("worker_heartbeats_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _columns(database: Database) -> dict[str, tuple[str, bool]]:
    return {
        c["name"]: (type(c["type"]).__name__, c["nullable"])
        for c in inspect(database.engine).get_columns("worker_heartbeats")
    }


def test_migration_is_idempotent_reversible_and_chained_after_0051(tmp_path: Path) -> None:
    migration = _migration()
    assert migration.down_revision == "0051_arc_ablation_runs"
    assert len(migration.revision) <= 32, "alembic_version.version_num is VARCHAR(32)"

    database = Database(f"sqlite:///{tmp_path}/migration.db")
    with database.engine.begin() as connection, Operations.context(
        MigrationContext.configure(connection)
    ):
        migration.upgrade()
        migration.upgrade()
        assert "worker_heartbeats" in inspect(connection).get_table_names()
        assert "ix_worker_heartbeats_heartbeat_at" in {
            item["name"] for item in inspect(connection).get_indexes("worker_heartbeats")
        }
        migration.downgrade()
        migration.downgrade()
        assert "worker_heartbeats" not in inspect(connection).get_table_names()
    database.engine.dispose()


def test_migration_accepts_a_create_all_database_and_matches_the_orm(tmp_path: Path) -> None:
    orm = Database(f"sqlite:///{tmp_path}/orm.db")
    orm.create_all()
    expected = _columns(orm)

    migrated = Database(f"sqlite:///{tmp_path}/migrated.db")
    with migrated.engine.begin() as connection, Operations.context(
        MigrationContext.configure(connection)
    ):
        _migration().upgrade()
    assert _columns(migrated) == expected

    with orm.engine.begin() as connection, Operations.context(
        MigrationContext.configure(connection)
    ):
        _migration().upgrade()  # developer databases already have the table from create_all
    orm.engine.dispose()
    migrated.engine.dispose()


# --- /api/healthz --------------------------------------------------------------------------


class _HealthyBitPro:
    def health(self) -> dict[str, Any]:
        return {"status": "ready"}


def _client(db: Database) -> TestClient:
    settings = Settings(
        ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", SESSION_SECRET="test-secret-123"
    )
    app = create_app(settings=settings, db=db)
    # Without a BitPro the adapter reports "degraded", which would make every verdict below
    # "degraded" regardless of the worker and hide whether the worker rule does anything.
    app.state.bitpro_adapter = _HealthyBitPro()
    return TestClient(app)


def test_healthz_reports_the_worker_and_degrades_only_for_a_stale_or_failing_one() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    client = _client(database)

    baseline = client.get("/api/healthz").json()
    assert baseline["workers"] == {"status": "unknown", "instances": []}
    assert baseline["status"] == "healthy", "an unknown worker must not count against health"

    now = datetime.now(UTC)
    healthy = HeartbeatRegistry()
    healthy.record_success("worker.paper_trading")
    flush_heartbeat(database, worker_id="worker", started_at=now, registry=healthy, now=now)
    alive = client.get("/api/healthz").json()
    assert alive["workers"]["status"] == "alive"
    assert alive["status"] == "healthy"

    failing = HeartbeatRegistry()
    for _ in range(FAILING_STREAK):
        failing.record_failure("worker.arc_evolution", RuntimeError("down"))
    flush_heartbeat(database, worker_id="worker", started_at=now, registry=failing, now=now)
    broken = client.get("/api/healthz").json()
    assert broken["status"] == "degraded"
    assert broken["workers"]["failing_components"] == ["worker.arc_evolution"]
    assert "down" not in str(broken["workers"]), "exception text must not reach the endpoint"

    stale_at = now - timedelta(minutes=10)
    flush_heartbeat(
        database, worker_id="worker", started_at=stale_at, registry=healthy, now=stale_at
    )
    stale = client.get("/api/healthz").json()
    assert stale["workers"]["status"] == "stale" and stale["status"] == "degraded"


# --- the worker feeds the record -----------------------------------------------------------


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> HeartbeatRegistry:
    fresh = HeartbeatRegistry()
    monkeypatch.setattr(worker, "HEARTBEATS", fresh)
    return fresh


class _Stop(Exception):
    pass


def _stop_at_first_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stop(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(worker.asyncio, "sleep", stop)


def test_guarded_steps_record_success_and_journalled_failures_record_failure(
    db: Database, registry: HeartbeatRegistry
) -> None:
    def boom() -> None:
        raise RuntimeError("down")

    assert asyncio.run(worker._guarded(db, "worker.ok", lambda: 7)) == 7
    assert asyncio.run(worker._guarded(db, "worker.bad", boom)) is None

    components = registry.snapshot()[0]
    assert components["worker.ok"]["last_ok_at"] is not None
    assert components["worker.bad"]["consecutive_failures"] == 1
    assert components["worker.bad"]["last_error_type"] == "RuntimeError"


@pytest.mark.parametrize(
    ("loop", "patch", "component"),
    [
        ("paper_trading_loop", "PaperTradingService", "worker.paper_trading"),
        ("monitor_scheduler_loop", "monitor_scheduler_once", "worker.monitor_scheduler"),
        ("agent_task_worker_loop", "agent_task_worker_once", "worker.agent_task"),
        ("research_trigger_loop", "research_trigger_worker_once", "worker.research_trigger"),
        ("market_rest_supplement_loop", "MarketIngestor", "worker.okx_rest_supplement"),
        ("rag_scanner_loop", "RagService", "worker.rag_scanner"),
    ],
)
def test_each_loop_records_success_after_a_good_iteration(
    db: Database,
    registry: HeartbeatRegistry,
    monkeypatch: pytest.MonkeyPatch,
    loop: str,
    patch: str,
    component: str,
) -> None:
    class Result:
        status = "ok"
        fill_count = 0
        scanned_files = 0
        ingested_files = 0

        def get(self, key: str, default: Any = None) -> Any:
            return {"status": "idle"}.get(key, default)

    async def rest_once() -> int:
        return 0

    class Working:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        run_once = staticmethod(lambda: Result())
        scan_once = staticmethod(lambda: Result())
        ingest_rest_once = staticmethod(rest_once)

    monkeypatch.setattr(
        worker, patch, Working if patch[0].isupper() else (lambda *a, **k: {"status": "idle"})
    )
    _stop_at_first_sleep(monkeypatch)

    with pytest.raises(_Stop):
        asyncio.run(getattr(worker, loop)(db))

    assert registry.snapshot()[0][component]["consecutive_failures"] == 0
    assert registry.snapshot()[0][component]["last_ok_at"] is not None


def test_main_reports_a_supervisor_restart_to_the_record(
    registry: HeartbeatRegistry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"n": 0}

    async def flaky() -> None:
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("boom")

    async def noop_journal(*args: Any, **kwargs: Any) -> None:
        return None

    real_sleep = asyncio.sleep

    async def instant(_seconds: float) -> None:
        await real_sleep(0)

    settings = Settings(DEEPSEEK_API_KEY="", DATABASE_URL=f"sqlite:///{tmp_path}/main.db")
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "build_loops", lambda db, s: [("flaky", flaky)])
    monkeypatch.setattr(worker, "_journal", noop_journal)
    monkeypatch.setattr(asyncio, "sleep", instant)

    asyncio.run(worker.main())

    entry = registry.snapshot()[0]["worker.flaky"]
    assert entry["restarts_total"] == 2 and entry["last_error_type"] == "RuntimeError"


def test_ws_ingestion_reports_success_at_most_every_few_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Ticker:
        inst_id = "BTC-USDT-SWAP"
        inst_type = "SWAP"
        last = 1
        volume_ccy_24h = 1
        change_utc0_pct = 0
        raw: dict[str, Any] = {}

    class Stream:
        calls = 0

        async def _batch(self) -> Any:
            for _ in range(4):
                yield Ticker()

        def stream(self) -> Any:
            Stream.calls += 1
            if Stream.calls > 1:
                raise _Halt
            return self._batch()

    class _Halt(BaseException):
        pass

    class Repository:
        def upsert_ticker_snapshot(self, **kwargs: Any) -> None:
            pass

    clock = iter([0.0, 1.0, 2.0, 6.5])  # four tickers: reported at 0.0 and again at 6.5 only
    monkeypatch.setattr(market_client, "_now", lambda: next(clock))
    reported: list[str] = []
    ingestor = MarketIngestor(Settings(DEEPSEEK_API_KEY=""), Repository())  # type: ignore[arg-type]
    ingestor.ws = Stream()  # type: ignore[assignment]

    with pytest.raises(_Halt):
        asyncio.run(ingestor.ingest_ws_forever(on_ok=reported.append))

    assert reported == ["worker.okx_ws", "worker.okx_ws"]
