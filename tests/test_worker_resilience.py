"""One failing worker loop must never take the whole worker process down.

`worker.main` runs every loop under one `asyncio.gather`, so an exception that escapes a single
loop ends the process (and with it every other loop) until Docker restarts the container. These
cover the two loops that used to let an exception escape; the sibling loops are covered by
tests/test_evolution_journal_coverage.py.
"""

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from hypertrade import worker
from hypertrade.arc.evolution_models import ArcRuntimeError
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.market import client as market_client
from hypertrade.market.client import MarketIngestor
from sqlalchemy import select


class _Stop(Exception):
    """Raised by the patched sleep: reaching it means one full iteration survived its failure."""


@pytest.fixture
def db(tmp_path: Any) -> Iterator[Database]:
    reset_store()
    database = Database(f"sqlite:///{tmp_path}/resilience.db")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


def _errors(db: Database, component: str) -> list[ArcRuntimeError]:
    with db.session() as session:
        rows = session.scalars(select(ArcRuntimeError)).all()
    return [row for row in rows if row.component == component]


def _stop_at_first_sleep(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[float]:
    slept: list[float] = []

    async def stop(seconds: float) -> None:
        slept.append(seconds)
        raise _Stop

    monkeypatch.setattr(module.asyncio, "sleep", stop)
    return slept


def test_rag_scanner_loop_survives_and_journals_a_failed_scan(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingRag:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def scan_once(self) -> None:
            raise RuntimeError("knowledge file unreadable")

    monkeypatch.setattr(worker, "RagService", FailingRag)
    _stop_at_first_sleep(monkeypatch, worker)

    with pytest.raises(_Stop):
        asyncio.run(worker.rag_scanner_loop(db))

    rows = _errors(db, "worker.rag_scanner")
    assert len(rows) == 1 and rows[0].message == "knowledge file unreadable"


class _BrokenStream:
    def stream(self) -> Any:
        raise ConnectionError("websocket closed")


class _BrokenRest:
    async def fetch_swap_tickers(self) -> list[Any]:
        raise ConnectionError("rest unreachable")


class _Repository:
    def upsert_ticker_snapshot(self, **kwargs: Any) -> None:  # pragma: no cover - never reached
        raise AssertionError("no ticker should be stored")


def _ingestor() -> MarketIngestor:
    ingestor = MarketIngestor(Settings(DEEPSEEK_API_KEY=""), _Repository())  # type: ignore[arg-type]
    ingestor.ws = _BrokenStream()  # type: ignore[assignment]
    ingestor.rest = _BrokenRest()  # type: ignore[assignment]
    return ingestor


def test_ws_ingestion_survives_the_rest_fallback_failing_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An upstream outage takes the websocket AND the REST endpoint down together. The REST
    # fallback runs inside the `except` block, so its failure used to escape the loop.
    slept = _stop_at_first_sleep(monkeypatch, market_client)

    with pytest.raises(_Stop):
        asyncio.run(_ingestor().ingest_ws_forever())

    assert slept == [15], "the loop must back off and retry, not exit"


def test_ws_ingestion_reports_both_failures_to_the_error_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stop_at_first_sleep(monkeypatch, market_client)
    reported: list[tuple[str, str]] = []

    async def on_error(component: str, exc: Exception) -> None:
        reported.append((component, str(exc)))

    with pytest.raises(_Stop):
        asyncio.run(_ingestor().ingest_ws_forever(on_error=on_error))

    assert reported == [
        ("worker.okx_ws", "websocket closed"),
        ("worker.okx_rest_fallback", "rest unreachable"),
    ]


def test_a_failing_error_hook_never_masks_the_ingestion_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept = _stop_at_first_sleep(monkeypatch, market_client)

    async def broken_hook(component: str, exc: Exception) -> None:
        raise RuntimeError("journal database is down")

    with pytest.raises(_Stop):
        asyncio.run(_ingestor().ingest_ws_forever(on_error=broken_hook))

    assert slept == [15]


class _Halt(BaseException):
    """Escapes `except Exception`, like a shutdown signal, so it can stop the forever-loop."""


def test_ws_ingestion_still_stores_tickers_when_the_stream_works() -> None:
    class Ticker:
        inst_id = "BTC-USDT-SWAP"
        inst_type = "SWAP"
        last = Decimal("1")
        volume_ccy_24h = Decimal("2")
        change_utc0_pct = Decimal("0")
        raw: dict[str, Any] = {}

    class Stream:
        calls = 0

        async def _batch(self) -> Any:
            yield Ticker()

        def stream(self) -> Any:
            Stream.calls += 1
            if Stream.calls > 1:  # the first stream drained normally; stop on the reconnect
                raise _Halt
            return self._batch()

    stored: list[str] = []

    class Repository:
        def upsert_ticker_snapshot(self, **kwargs: Any) -> None:
            stored.append(kwargs["inst_id"])

    ingestor = MarketIngestor(Settings(DEEPSEEK_API_KEY=""), Repository())  # type: ignore[arg-type]
    ingestor.ws = Stream()  # type: ignore[assignment]

    with pytest.raises(_Halt):
        asyncio.run(ingestor.ingest_ws_forever())

    assert stored == ["BTC-USDT-SWAP"]
