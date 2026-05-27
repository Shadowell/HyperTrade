from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import Database, MarketTicker


@dataclass(frozen=True)
class MarketSummaryRow:
    inst_id: str
    last: Decimal
    volume_ccy_24h: Decimal
    change_utc0_pct: Decimal


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
