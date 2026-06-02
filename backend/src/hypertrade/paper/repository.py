from decimal import Decimal

from sqlalchemy import desc, select

from hypertrade.db import (
    Database,
    MarketTicker,
    PaperEvent,
    PaperFill,
    PaperOrder,
    PaperPosition,
    PaperSession,
)
from hypertrade.paper.models import PaperTicker, SimulatedFill


class PaperRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def latest_tickers(self, *, limit: int = 250) -> list[tuple[PaperTicker, object]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(MarketTicker)
                .order_by(desc(MarketTicker.updated_at), desc(MarketTicker.volume_ccy_24h))
                .limit(limit)
            ).all()
            return [
                (
                    PaperTicker(
                        inst_id=row.inst_id,
                        last=row.last,
                        volume_ccy_24h=row.volume_ccy_24h,
                        change_utc0_pct=row.change_utc0_pct,
                    ),
                    row.updated_at,
                )
                for row in rows
            ]

    def open_positions(self, session_id: str) -> list[PaperPosition]:
        with self.db.session() as session:
            positions = session.scalars(
                select(PaperPosition)
                .where(PaperPosition.session_id == session_id)
                .where(PaperPosition.status == "open")
                .order_by(PaperPosition.created_at)
            ).all()
            for position in positions:
                session.expunge(position)
            return list(positions)

    def latest_ticker_price(self, inst_id: str) -> tuple[Decimal, object] | None:
        with self.db.session() as session:
            row = session.scalar(select(MarketTicker).where(MarketTicker.inst_id == inst_id))
            if row is None:
                return None
            return row.last, row.updated_at

    def create_order_and_fill(
        self,
        *,
        session_id: str,
        simulated_fill: SimulatedFill,
        target_notional: Decimal,
        reason: str,
        source_ticker_updated_at: object,
    ) -> None:
        with self.db.session() as session:
            order = PaperOrder(
                session_id=session_id,
                inst_id=simulated_fill.inst_id,
                side=simulated_fill.side,
                quantity=simulated_fill.quantity,
                target_notional=target_notional,
                status="filled",
                reason=reason,
            )
            session.add(order)
            session.flush()
            fill = PaperFill(
                order_id=order.id,
                session_id=session_id,
                inst_id=simulated_fill.inst_id,
                side=simulated_fill.side,
                quantity=simulated_fill.quantity,
                price=simulated_fill.price,
                fee=simulated_fill.fee,
                slippage_bps=simulated_fill.slippage_bps,
                source_ticker_updated_at=source_ticker_updated_at,
            )
            position = PaperPosition(
                session_id=session_id,
                inst_id=simulated_fill.inst_id,
                side=simulated_fill.side,
                quantity=simulated_fill.quantity,
                entry_price=simulated_fill.price,
                mark_price=simulated_fill.price,
                notional=target_notional,
                unrealized_pnl=Decimal("0"),
                status="open",
            )
            session.add_all([fill, position])

    def close_position(
        self,
        *,
        session_id: str,
        position_id: str,
        exit_price: Decimal,
        source_ticker_updated_at: object,
        taker_fee_bps: Decimal,
        reason: str,
    ) -> dict[str, str]:
        with self.db.session() as session:
            position = session.get(PaperPosition, position_id)
            if position is None or position.session_id != session_id or position.status != "open":
                raise KeyError(position_id)
            close_side = "close_long" if position.side == "long" else "close_short"
            notional = position.quantity * exit_price
            fee = notional * taker_fee_bps / Decimal("10000")
            if position.side == "long":
                pnl = (exit_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - exit_price) * position.quantity
            realized_pnl = pnl - fee
            order = PaperOrder(
                session_id=session_id,
                inst_id=position.inst_id,
                side=close_side,
                quantity=position.quantity,
                target_notional=notional,
                status="filled",
                reason=reason,
            )
            session.add(order)
            session.flush()
            session.add(
                PaperFill(
                    order_id=order.id,
                    session_id=session_id,
                    inst_id=position.inst_id,
                    side=close_side,
                    quantity=position.quantity,
                    price=exit_price,
                    fee=fee,
                    slippage_bps=Decimal("0"),
                    source_ticker_updated_at=source_ticker_updated_at,
                )
            )
            position.mark_price = exit_price
            position.unrealized_pnl = Decimal("0")
            position.status = "closed"
            paper_session = session.get(PaperSession, session_id)
            if paper_session is not None:
                paper_session.realized_pnl += realized_pnl
                paper_session.cash += realized_pnl
                paper_session.equity = paper_session.cash
            return {
                "position_id": position.id,
                "inst_id": position.inst_id,
                "side": position.side,
                "exit_price": str(exit_price),
                "realized_pnl": str(realized_pnl),
            }

    def record_event(
        self,
        *,
        session_id: str,
        kind: str,
        message: str,
        payload: dict[str, object],
    ) -> None:
        with self.db.session() as session:
            session.add(
                PaperEvent(
                    session_id=session_id,
                    kind=kind,
                    message=message,
                    payload=payload,
                )
            )
