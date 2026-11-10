"""Market ingestion and the synchronous worker loops must never hold the event loop.

Background: the worker used to write ~700 tickers one by one on its event-loop thread (three
database round trips each), which froze every loop for ~9 s at a 2.6 ms round trip and for over a
minute while the database was busy after a deploy. These tests pin the batch write, that it runs
on a worker thread, and that a slow write cannot starve the loop.
"""

import asyncio
import threading
import time
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from hypertrade import worker
from hypertrade.config import Settings
from hypertrade.db import Database, MarketTicker
from hypertrade.market import client as market_client
from hypertrade.market.client import MarketIngestor
from hypertrade.market.okx import OkxTicker
from hypertrade.market.repository import MarketRepository
from hypertrade.runtime.heartbeat import HeartbeatRegistry
from sqlalchemy import event, select


def _ticker(i: int, *, last: str = "1", raw: dict[str, Any] | None = None) -> OkxTicker:
    return OkxTicker(
        inst_id=f"COIN{i}-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal(last),
        volume_ccy_24h=Decimal("10"),
        change_utc0_pct=Decimal("0.5"),
        raw={"n": i} if raw is None else raw,
    )


@pytest.fixture
def db() -> Iterator[Database]:
    database = Database("sqlite:///:memory:")
    database.create_all()
    yield database


def _rows(db: Database) -> dict[str, tuple[Any, ...]]:
    with db.session() as session:
        return {
            row.inst_id: (row.inst_type, row.last, row.volume_ccy_24h, row.change_utc0_pct, row.raw)
            for row in session.scalars(select(MarketTicker))
        }


# --- the batch write ------------------------------------------------------------------------


def test_batch_inserts_new_and_updates_existing_in_one_call(db: Database) -> None:
    repo = MarketRepository(db)
    assert repo.upsert_ticker_snapshots([_ticker(1, last="1"), _ticker(2, last="2")]) == 2

    written = repo.upsert_ticker_snapshots([_ticker(2, last="22"), _ticker(3, last="3")])

    assert written == 2
    rows = _rows(db)
    assert set(rows) == {"COIN1-USDT-SWAP", "COIN2-USDT-SWAP", "COIN3-USDT-SWAP"}
    assert rows["COIN2-USDT-SWAP"][1] == Decimal("22")
    assert rows["COIN1-USDT-SWAP"][1] == Decimal("1")


def test_newest_ticker_per_instrument_wins_inside_a_batch(db: Database) -> None:
    repo = MarketRepository(db)

    written = repo.upsert_ticker_snapshots([_ticker(1, last="1"), _ticker(1, last="9")])

    assert written == 1
    assert _rows(db)["COIN1-USDT-SWAP"][1] == Decimal("9")


def test_an_empty_raw_payload_keeps_the_stored_raw_like_the_per_ticker_method(
    db: Database,
) -> None:
    repo = MarketRepository(db)
    repo.upsert_ticker_snapshots([_ticker(1, raw={"keep": "me"})])

    repo.upsert_ticker_snapshots([_ticker(1, last="5", raw={})])

    row = _rows(db)["COIN1-USDT-SWAP"]
    assert row[1] == Decimal("5") and row[4] == {"keep": "me"}


def test_batch_and_per_ticker_writes_leave_the_same_rows() -> None:
    sequence = [_ticker(i % 5, last=str(i)) for i in range(40)]
    per_row, batched = Database("sqlite:///:memory:"), Database("sqlite:///:memory:")
    per_row.create_all()
    batched.create_all()
    for ticker in sequence:
        MarketRepository(per_row).upsert_ticker_snapshot(
            inst_id=ticker.inst_id,
            inst_type=ticker.inst_type,
            last=ticker.last,
            volume_ccy_24h=ticker.volume_ccy_24h,
            change_utc0_pct=ticker.change_utc0_pct,
            raw=ticker.raw,
        )
    MarketRepository(batched).upsert_ticker_snapshots(sequence)

    assert _rows(batched) == _rows(per_row)


def test_database_statements_do_not_grow_with_the_number_of_tickers(db: Database) -> None:
    # The steady state: every instrument already exists and the snapshot updates ~700 rows.
    repo = MarketRepository(db)
    repo.upsert_ticker_snapshots([_ticker(i) for i in range(700)])
    statements = 0

    def count(*_: Any) -> None:
        nonlocal statements
        statements += 1

    event.listen(db.engine, "before_cursor_execute", count)
    commits: list[int] = []
    event.listen(db.engine, "commit", lambda *_: commits.append(1))

    repo.upsert_ticker_snapshots([_ticker(i, last="7") for i in range(700)])

    # The per-ticker method needs about three round trips per ticker (SELECT, UPDATE, COMMIT):
    # ~2100 for this snapshot. The batch needs a couple of SELECTs, one bulk write and one COMMIT.
    assert statements <= 8, statements
    assert len(commits) == 1


def test_a_first_time_population_is_still_one_transaction(db: Database) -> None:
    # SQLite inserts row by row (it has to fetch each autoincrement key); PostgreSQL batches the
    # INSERTs. Either way it is a single transaction, and it only happens once per database.
    commits: list[int] = []
    event.listen(db.engine, "commit", lambda *_: commits.append(1))

    MarketRepository(db).upsert_ticker_snapshots([_ticker(i) for i in range(700)])

    assert len(commits) == 1 and len(_rows(db)) == 700


def test_an_empty_batch_touches_nothing(db: Database) -> None:
    seen: list[str] = []
    event.listen(db.engine, "before_cursor_execute", lambda *a: seen.append(a[2]))

    assert MarketRepository(db).upsert_ticker_snapshots([]) == 0
    assert seen == []


def test_a_cross_process_insert_race_is_retried_once_then_surfaces(db: Database) -> None:
    from sqlalchemy.exc import IntegrityError

    repo = MarketRepository(db)
    calls = {"n": 0}
    real = repo._write_ticker_batch

    def flaky(latest: dict[str, Any]) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("insert", {}, Exception("duplicate inst_id"))
        real(latest)

    repo._write_ticker_batch = flaky  # type: ignore[method-assign]
    assert repo.upsert_ticker_snapshots([_ticker(1)]) == 1 and calls["n"] == 2

    def always(latest: dict[str, Any]) -> None:
        raise IntegrityError("insert", {}, Exception("duplicate inst_id"))

    repo._write_ticker_batch = always  # type: ignore[method-assign]
    with pytest.raises(IntegrityError):
        repo.upsert_ticker_snapshots([_ticker(2)])


def test_batch_writes_in_one_process_never_overlap(db: Database) -> None:
    repo = MarketRepository(db)
    active, peak = 0, 0
    guard = threading.Lock()

    def slow(latest: dict[str, Any]) -> None:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with guard:
            active -= 1

    repo._write_ticker_batch = slow  # type: ignore[method-assign]
    threads = [
        threading.Thread(target=repo.upsert_ticker_snapshots, args=([_ticker(i)],))
        for i in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 1, "two first-time inserts of one instrument would race on the unique key"


# --- the ingestor keeps the event loop free -------------------------------------------------


_REAL_SLEEP = asyncio.sleep  # tests below patch asyncio.sleep; the measurement must not


async def _max_loop_gap(work: Any) -> float:
    """Longest time the loop went without running a 10 ms ticker while ``work`` ran."""
    gaps: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        last = time.monotonic()
        while not stop.is_set():
            await _REAL_SLEEP(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    task = asyncio.create_task(ticker())
    await _REAL_SLEEP(0.05)
    await work()
    await _REAL_SLEEP(0.05)
    stop.set()
    await task
    return max(gaps)


class _SlowRest:
    def __init__(self, tickers: list[OkxTicker]) -> None:
        self.tickers = tickers

    async def fetch_swap_tickers(self) -> list[OkxTicker]:
        return self.tickers


class _SlowRepository:
    """A database that takes 0.6 s to write a snapshot, like a busy Postgres."""

    def __init__(self) -> None:
        self.threads: list[int] = []
        self.batches: list[int] = []

    def upsert_ticker_snapshots(self, tickers: Any) -> int:
        self.threads.append(threading.get_ident())
        time.sleep(0.6)
        self.batches.append(len(list(tickers)))
        return self.batches[-1]


def test_a_slow_rest_snapshot_write_runs_on_a_thread_and_never_blocks_the_loop() -> None:
    repo = _SlowRepository()
    ingestor = MarketIngestor(Settings(DEEPSEEK_API_KEY=""), repo)  # type: ignore[arg-type]
    ingestor.rest = _SlowRest([_ticker(i) for i in range(700)])  # type: ignore[assignment]

    async def scenario() -> tuple[float, int]:
        stored = 0

        async def work() -> None:
            nonlocal stored
            stored = await ingestor.ingest_rest_once()

        return await _max_loop_gap(work), stored

    gap, stored = asyncio.run(scenario())

    assert stored == 700 and repo.batches == [700]
    assert repo.threads[0] != threading.get_ident(), "the write must not run on the loop thread"
    assert gap < 0.25, f"the loop was held for {gap:.2f}s during a 0.6s write"


def test_the_measurement_would_catch_the_old_behaviour() -> None:
    # Control: the same 0.6 s write done inline on the loop thread, as the old code did, must
    # show up as a long gap; otherwise the test above proves nothing.
    repo = _SlowRepository()

    async def scenario() -> float:
        async def inline() -> None:
            repo.upsert_ticker_snapshots([_ticker(1)])

        return await _max_loop_gap(inline)

    assert asyncio.run(scenario()) >= 0.5


def test_websocket_batches_are_written_off_the_loop_and_a_slow_write_does_not_starve_it() -> None:
    repo = _SlowRepository()
    ingestor = MarketIngestor(Settings(DEEPSEEK_API_KEY=""), repo)  # type: ignore[arg-type]

    class _Halt(BaseException):
        pass

    class Stream:
        calls = 0

        async def _batch(self) -> Any:
            for i in range(3):
                await asyncio.sleep(0)
                yield _ticker(i)

        def stream(self) -> Any:
            Stream.calls += 1
            if Stream.calls > 1:
                raise _Halt
            return self._batch()

    ingestor.ws = Stream()  # type: ignore[assignment]

    async def scenario() -> float:
        async def work() -> None:
            with pytest.raises(_Halt):
                await ingestor.ingest_ws_forever()

        return await _max_loop_gap(work)

    gap = asyncio.run(scenario())

    assert repo.batches == [3], "buffered tickers are written as one batch when the stream ends"
    assert repo.threads[0] != threading.get_ident()
    assert gap < 0.25


def test_buffered_websocket_tickers_are_dropped_when_the_stream_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[list[tuple[str, str]]] = []
    ingestor = MarketIngestor(Settings(DEEPSEEK_API_KEY=""), None)  # type: ignore[arg-type]

    class Repository:
        def upsert_ticker_snapshots(self, tickers: Any) -> int:
            written.append([(t.inst_id, str(t.last)) for t in tickers])
            return len(written)

    ingestor.repository = Repository()  # type: ignore[assignment]

    class _Halt(BaseException):
        pass

    class Stream:
        calls = 0

        async def _fails(self) -> Any:
            yield _ticker(1, last="1")  # buffered, then the connection drops
            raise ConnectionError("websocket closed")

        async def _reconnected(self) -> Any:
            yield _ticker(2, last="201")  # a fresh message on the new connection

        def stream(self) -> Any:
            Stream.calls += 1
            if Stream.calls == 1:
                return self._fails()
            if Stream.calls == 2:
                return self._reconnected()
            raise _Halt

    class Rest:
        async def fetch_swap_tickers(self) -> list[OkxTicker]:
            return [_ticker(1, last="100"), _ticker(2, last="200")]

    async def no_pause(_seconds: float) -> None:
        return None

    monkeypatch.setattr(market_client.asyncio, "sleep", no_pause)
    ingestor.ws = Stream()  # type: ignore[assignment]
    ingestor.rest = Rest()  # type: ignore[assignment]

    with pytest.raises(_Halt):
        asyncio.run(ingestor.ingest_ws_forever())

    # The REST snapshot supersedes the one ticker buffered before the drop. If that stale ticker
    # survived, the next flush would write COIN1 at 1 over the fresher 100 from the snapshot.
    assert written == [
        [("COIN1-USDT-SWAP", "100"), ("COIN2-USDT-SWAP", "200")],
        [("COIN2-USDT-SWAP", "201")],
    ]


def test_a_database_error_while_flushing_is_reported_like_a_stream_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reported: list[tuple[str, str]] = []

    class Repository:
        def upsert_ticker_snapshots(self, tickers: Any) -> int:
            raise RuntimeError("database is down")

    ingestor = MarketIngestor(Settings(DEEPSEEK_API_KEY=""), Repository())  # type: ignore[arg-type]

    class _Halt(BaseException):
        pass

    class Stream:
        calls = 0

        async def _batch(self) -> Any:
            yield _ticker(1)

        def stream(self) -> Any:
            Stream.calls += 1
            if Stream.calls > 1:
                raise _Halt
            return self._batch()

    async def on_error(component: str, exc: Exception) -> None:
        reported.append((component, str(exc)))

    async def no_pause(_seconds: float) -> None:
        return None

    monkeypatch.setattr(market_client.asyncio, "sleep", no_pause)
    ingestor.ws = Stream()  # type: ignore[assignment]

    with pytest.raises(_Halt):
        asyncio.run(ingestor.ingest_ws_forever(on_error=on_error))

    assert ("worker.okx_ws", "database is down") in reported
    # the REST fallback hits the same database and fails the same way, and is reported as such
    assert any(component == "worker.okx_rest_fallback" for component, _ in reported)


# --- the synchronous worker loops run on threads --------------------------------------------


class _Stop(Exception):
    pass


def _stop_at_first_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stop(_seconds: float) -> None:
        raise _Stop

    monkeypatch.setattr(worker.asyncio, "sleep", stop)


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> HeartbeatRegistry:
    fresh = HeartbeatRegistry()
    monkeypatch.setattr(worker, "HEARTBEATS", fresh)
    return fresh


class _Result:
    status = "ok"
    fill_count = 0
    scanned_files = 0
    ingested_files = 0

    def get(self, key: str, default: Any = None) -> Any:
        return {"status": "idle"}.get(key, default)


@pytest.mark.parametrize(
    ("loop", "patch"),
    [
        ("rag_scanner_loop", "RagService"),
        ("paper_trading_loop", "PaperTradingService"),
        ("monitor_scheduler_loop", "monitor_scheduler_once"),
    ],
)
def test_synchronous_loop_work_runs_on_a_thread_not_on_the_event_loop(
    registry: HeartbeatRegistry, monkeypatch: pytest.MonkeyPatch, loop: str, patch: str
) -> None:
    seen: list[int] = []

    def work(*args: Any, **kwargs: Any) -> _Result:
        seen.append(threading.get_ident())
        time.sleep(0.4)
        return _Result()

    class Service:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        run_once = staticmethod(work)
        scan_once = staticmethod(work)

    monkeypatch.setattr(worker, patch, Service if patch[0].isupper() else work)
    _stop_at_first_sleep(monkeypatch)
    database = Database("sqlite:///:memory:")

    async def scenario() -> float:
        async def run() -> None:
            with pytest.raises(_Stop):
                await getattr(worker, loop)(database)

        return await _max_loop_gap(run)

    gap = asyncio.run(scenario())

    assert seen and seen[0] != threading.get_ident()
    assert gap < 0.25, f"{loop} held the event loop for {gap:.2f}s during a 0.4s step"
