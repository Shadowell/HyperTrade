from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from hypertrade.config import Settings, get_settings
from hypertrade.db import Database, PaperEvent, PaperFill, PaperPosition, PaperSession
from hypertrade.paper.engine import PaperExecutionEngine, PaperSignalEngine
from hypertrade.paper.models import PaperRunResult, PaperSessionSnapshot
from hypertrade.paper.repository import PaperRepository


class PaperTradingService:
    def __init__(self, db: Database, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.repository = PaperRepository(db)

    def ensure_default_session(self) -> PaperSessionSnapshot:
        with self.db.session() as session:
            paper_session = session.scalar(select(PaperSession).order_by(PaperSession.created_at))
            if paper_session is None:
                starting_equity = Decimal(self.settings.paper_starting_equity_usdt)
                paper_session = PaperSession(
                    cash=starting_equity,
                    equity=starting_equity,
                    realized_pnl=Decimal("0"),
                    config_json=self._config_json(),
                )
                session.add(paper_session)
                session.flush()
            return _session_snapshot(paper_session)

    def run_once(self) -> PaperRunResult:
        paper_session = self.ensure_default_session()
        if paper_session.status == "paused":
            return PaperRunResult(status="paused", fill_count=0, event_count=0)

        open_positions = self.repository.open_positions(paper_session.id)
        open_symbols = {position.inst_id for position in open_positions}
        remaining_slots = max(0, self.settings.paper_max_positions - len(open_positions))
        if remaining_slots == 0:
            return PaperRunResult(status="running", fill_count=0, event_count=0)

        ticker_rows = self.repository.latest_tickers(limit=250)
        tickers = [row[0] for row in ticker_rows]
        ticker_times = {row[0].inst_id: row[1] for row in ticker_rows}
        signals = PaperSignalEngine().generate(
            tickers,
            max_signals=self.settings.paper_max_positions,
        )
        target_notional = self._target_notional(Decimal(paper_session.equity))
        execution = PaperExecutionEngine(
            taker_fee_bps=Decimal(self.settings.paper_taker_fee_bps),
            slippage_bps=Decimal(self.settings.paper_slippage_bps),
        )
        fill_count = 0
        for signal in signals:
            if fill_count >= remaining_slots:
                break
            if signal.inst_id in open_symbols:
                continue
            ticker = next(ticker for ticker in tickers if ticker.inst_id == signal.inst_id)
            fill = execution.simulate_fill(
                inst_id=signal.inst_id,
                side=signal.side,
                target_notional=target_notional,
                last_price=ticker.last,
            )
            self.repository.create_order_and_fill(
                session_id=paper_session.id,
                simulated_fill=fill,
                target_notional=target_notional,
                reason=signal.reason,
                source_ticker_updated_at=ticker_times[signal.inst_id],
            )
            self.repository.record_event(
                session_id=paper_session.id,
                kind="fill",
                message=f"Paper {signal.side} fill for {signal.inst_id}",
                payload={
                    "inst_id": signal.inst_id,
                    "side": signal.side,
                    "target_notional": str(target_notional),
                    "price": str(fill.price),
                },
            )
            fill_count += 1
        return PaperRunResult(status="running", fill_count=fill_count, event_count=fill_count)

    def pause(self) -> dict[str, Any]:
        return self._set_status("paused")

    def resume(self) -> dict[str, Any]:
        return self._set_status("running")

    def status(self) -> dict[str, Any]:
        paper_session = self.ensure_default_session()
        return {
            "session": paper_session.__dict__,
            "positions": self._positions_payload(paper_session.id),
            "recent_fills": self._fills_payload(paper_session.id),
            "recent_events": self._events_payload(paper_session.id),
        }

    def _set_status(self, status: str) -> dict[str, Any]:
        self.ensure_default_session()
        with self.db.session() as session:
            paper_session = session.scalar(select(PaperSession).order_by(PaperSession.created_at))
            if paper_session is None:
                raise RuntimeError("paper session bootstrap failed")
            paper_session.status = status
            session.flush()
            return {"session": _session_snapshot(paper_session).__dict__}

    def _config_json(self) -> dict[str, Any]:
        return {
            "max_positions": self.settings.paper_max_positions,
            "max_symbol_notional_pct": self.settings.paper_max_symbol_notional_pct,
            "max_leverage": self.settings.paper_max_leverage,
            "taker_fee_bps": self.settings.paper_taker_fee_bps,
            "slippage_bps": self.settings.paper_slippage_bps,
        }

    def _target_notional(self, equity: Decimal) -> Decimal:
        max_symbol = equity * Decimal(self.settings.paper_max_symbol_notional_pct)
        leveraged_slot = equity * Decimal(self.settings.paper_max_leverage) / Decimal(
            self.settings.paper_max_positions
        )
        return min(max_symbol, leveraged_slot)

    def _positions_payload(self, session_id: str) -> list[dict[str, str]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(PaperPosition)
                .where(PaperPosition.session_id == session_id)
                .where(PaperPosition.status == "open")
                .order_by(desc(PaperPosition.updated_at))
                .limit(25)
            ).all()
            return [
                {
                    "inst_id": row.inst_id,
                    "side": row.side,
                    "quantity": _decimal_to_string(row.quantity),
                    "entry_price": _decimal_to_string(row.entry_price),
                    "mark_price": _decimal_to_string(row.mark_price),
                    "notional": _decimal_to_string(row.notional),
                    "unrealized_pnl": _decimal_to_string(row.unrealized_pnl),
                }
                for row in rows
            ]

    def _fills_payload(self, session_id: str) -> list[dict[str, str]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(PaperFill)
                .where(PaperFill.session_id == session_id)
                .order_by(desc(PaperFill.created_at))
                .limit(25)
            ).all()
            return [
                {
                    "inst_id": row.inst_id,
                    "side": row.side,
                    "quantity": _decimal_to_string(row.quantity),
                    "price": _decimal_to_string(row.price),
                    "fee": _decimal_to_string(row.fee),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def _events_payload(self, session_id: str) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(PaperEvent)
                .where(PaperEvent.session_id == session_id)
                .order_by(desc(PaperEvent.created_at))
                .limit(25)
            ).all()
            return [
                {
                    "kind": row.kind,
                    "message": row.message,
                    "payload": row.payload,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]


def _session_snapshot(session: PaperSession) -> PaperSessionSnapshot:
    return PaperSessionSnapshot(
        id=session.id,
        status=session.status,
        cash=_decimal_to_string(session.cash),
        equity=_decimal_to_string(session.equity),
        realized_pnl=_decimal_to_string(session.realized_pnl),
    )


def _decimal_to_string(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
