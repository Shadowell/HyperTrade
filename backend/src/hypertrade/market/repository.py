import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import Database, MarketTicker

# Batch writes are serialised inside this process: the REST supplement and the websocket flush
# run on different threads, and two first-time inserts of one instrument would race on the unique
# key. Cross-process races are handled by a single retry in upsert_ticker_snapshots.
_TICKER_WRITE_LOCK = threading.Lock()
# Keeps the IN (...) list well below every driver's bind-parameter limit.
_IN_CHUNK = 500


class TickerRow(Protocol):
    """What a batch write needs from a ticker; `OkxTicker` satisfies it."""

    @property
    def inst_id(self) -> str: ...
    @property
    def inst_type(self) -> str: ...
    @property
    def last(self) -> Decimal: ...
    @property
    def volume_ccy_24h(self) -> Decimal: ...
    @property
    def change_utc0_pct(self) -> Decimal: ...
    @property
    def raw(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class MarketSummaryRow:
    inst_id: str
    last: Decimal
    volume_ccy_24h: Decimal
    change_utc0_pct: Decimal


@dataclass(frozen=True)
class MarketTickerSnapshot:
    inst_id: str
    inst_type: str
    last: Decimal
    volume_ccy_24h: Decimal
    change_utc0_pct: Decimal
    updated_at: datetime
    raw: dict[str, Any]


class MarketRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_ticker_snapshot(
        self,
        *,
        inst_id: str,
        inst_type: str,
        last: Decimal,
        volume_ccy_24h: Decimal,
        change_utc0_pct: Decimal,
        raw: dict[str, Any] | None = None,
    ) -> None:
        with self.db.session() as session:
            ticker = session.scalar(select(MarketTicker).where(MarketTicker.inst_id == inst_id))
            if ticker is None:
                ticker = MarketTicker(
                    inst_id=inst_id,
                    inst_type=inst_type,
                    last=last,
                    volume_ccy_24h=volume_ccy_24h,
                    change_utc0_pct=change_utc0_pct,
                    raw=raw or {},
                )
                session.add(ticker)
                return
            ticker.inst_type = inst_type
            ticker.last = last
            ticker.volume_ccy_24h = volume_ccy_24h
            ticker.change_utc0_pct = change_utc0_pct
            ticker.raw = raw or ticker.raw

    def upsert_ticker_snapshots(self, tickers: Iterable[TickerRow]) -> int:
        """Upsert many snapshots in ONE transaction: one SELECT per 500 instruments, one COMMIT.

        `upsert_ticker_snapshot` costs three database round trips per ticker (SELECT, UPDATE,
        COMMIT). A full OKX SWAP snapshot is about 700 tickers, and the worker used to write it
        one by one on its event-loop thread: about 9 s at a 2.6 ms round trip, over a minute
        while the database was busy right after a deploy, during which no other loop (heartbeat,
        paper trading, ARC) ran at all. The newest ticker per instrument wins within a batch.
        Returns the number of distinct instruments written.
        """
        latest: dict[str, TickerRow] = {}
        for ticker in tickers:
            latest[ticker.inst_id] = ticker
        if not latest:
            return 0
        with _TICKER_WRITE_LOCK:
            try:
                self._write_ticker_batch(latest)
            except IntegrityError:
                # Another process inserted one of these instruments between our SELECT and our
                # INSERT; the retry sees it and updates instead.
                self._write_ticker_batch(latest)
        return len(latest)

    def _write_ticker_batch(self, latest: dict[str, TickerRow]) -> None:
        ids = list(latest)
        with self.db.session() as session:
            existing: dict[str, MarketTicker] = {}
            for start in range(0, len(ids), _IN_CHUNK):
                chunk = ids[start : start + _IN_CHUNK]
                for found in session.scalars(
                    select(MarketTicker).where(MarketTicker.inst_id.in_(chunk))
                ):
                    existing[found.inst_id] = found
            for inst_id, ticker in latest.items():
                row = existing.get(inst_id)
                if row is None:
                    session.add(
                        MarketTicker(
                            inst_id=inst_id,
                            inst_type=ticker.inst_type,
                            last=ticker.last,
                            volume_ccy_24h=ticker.volume_ccy_24h,
                            change_utc0_pct=ticker.change_utc0_pct,
                            raw=ticker.raw or {},
                        )
                    )
                    continue
                row.inst_type = ticker.inst_type
                row.last = ticker.last
                row.volume_ccy_24h = ticker.volume_ccy_24h
                row.change_utc0_pct = ticker.change_utc0_pct
                row.raw = ticker.raw or row.raw

    def top_movers(self, *, limit: int = 10) -> list[MarketSummaryRow]:
        with self.db.session() as session:
            rows = session.scalars(
                select(MarketTicker)
                .order_by(desc(MarketTicker.change_utc0_pct), desc(MarketTicker.volume_ccy_24h))
                .limit(limit)
            ).all()
            return [
                MarketSummaryRow(
                    inst_id=row.inst_id,
                    last=row.last,
                    volume_ccy_24h=row.volume_ccy_24h,
                    change_utc0_pct=row.change_utc0_pct,
                )
                for row in rows
            ]

    def latest_tickers(self, *, limit: int = 50) -> list[MarketSummaryRow]:
        with self.db.session() as session:
            rows = session.scalars(
                select(MarketTicker)
                .order_by(desc(MarketTicker.updated_at), desc(MarketTicker.volume_ccy_24h))
                .limit(limit)
            ).all()
            return [
                MarketSummaryRow(
                    inst_id=row.inst_id,
                    last=row.last,
                    volume_ccy_24h=row.volume_ccy_24h,
                    change_utc0_pct=row.change_utc0_pct,
                )
                for row in rows
            ]

    def get_ticker(self, inst_id: str) -> MarketTickerSnapshot | None:
        with self.db.session() as session:
            row = session.scalar(select(MarketTicker).where(MarketTicker.inst_id == inst_id))
            if row is None:
                return None
            return MarketTickerSnapshot(
                inst_id=row.inst_id,
                inst_type=row.inst_type,
                last=row.last,
                volume_ccy_24h=row.volume_ccy_24h,
                change_utc0_pct=row.change_utc0_pct,
                updated_at=row.updated_at,
                raw=row.raw,
            )
