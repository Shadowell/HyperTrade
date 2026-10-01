from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from hypertrade.config import Settings, get_settings
from hypertrade.db import Database, PaperEvent, PaperFill, PaperPosition, PaperSession, utc_now
from hypertrade.paper.allocation import RiskParityAllocator
from hypertrade.paper.engine import PaperExecutionEngine, PaperSignalEngine
from hypertrade.paper.models import PaperRunResult, PaperSessionSnapshot
from hypertrade.paper.repository import PaperRepository
from hypertrade.paper.stage_gate import ProgressiveStageGate
from hypertrade.paper.strategies import StrategySignal


class PaperTradingService:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        stage_gate: ProgressiveStageGate | None = None,
        allocator: RiskParityAllocator | None = None,
        signal_engine: PaperSignalEngine | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.repository = PaperRepository(db)
        self.stage_gate = stage_gate or ProgressiveStageGate()
        self.allocator = allocator or RiskParityAllocator(
            max_leverage=Decimal(str(self.settings.paper_max_leverage)),
            max_symbol_notional_pct=Decimal(str(self.settings.paper_max_symbol_notional_pct)),
        )
        self.signal_engine = signal_engine or PaperSignalEngine()

    def ensure_default_session(self) -> PaperSessionSnapshot:
        with self.db.session() as session:
            paper_session = session.scalar(
                select(PaperSession)
                .where(PaperSession.status != "reset")
                .order_by(desc(PaperSession.created_at))
            )
            if paper_session is None:
                paper_session = self._new_session()
                session.add(paper_session)
                session.flush()
            return _session_snapshot(paper_session)

    def run_once(self) -> PaperRunResult:
        paper_session = self.ensure_default_session()
        if paper_session.status == "paused":
            return PaperRunResult(status="paused", fill_count=0, event_count=0)

        # 1. Mark-to-Market: Sync live valuations for open positions
        self.repository.sync_mark_prices(paper_session.id)

        # 2. Check and trigger automated Bracket Orders (Stop-Loss & Take-Profit)
        closed_brackets = self.repository.check_and_trigger_bracket_orders(
            paper_session.id,
            taker_fee_bps=Decimal(self.settings.paper_taker_fee_bps),
        )
        for report in closed_brackets:
            self.stage_gate.record_trade(
                "utc0_momentum_legacy",
                realized_pnl=Decimal(report["realized_pnl"]),
                notional=Decimal(report["exit_price"]),
                inst_id=report["inst_id"],
            )
            trigger_msg = report.get("trigger_reason", "")
            self.repository.record_event(
                session_id=paper_session.id,
                kind="bracket_exit",
                message=f"Bracket order triggered exit for {report['inst_id']}: {trigger_msg}",
                payload=report,
            )

        # Re-fetch session after bracket closures
        paper_session = self.ensure_default_session()

        open_positions = self.repository.open_positions(paper_session.id)
        open_symbols = {position.inst_id for position in open_positions}
        remaining_slots = max(0, self.settings.paper_max_positions - len(open_positions))
        if remaining_slots == 0:
            self.stage_gate.evaluate_promotions()
            return PaperRunResult(
                status="running",
                fill_count=0,
                event_count=len(closed_brackets),
            )

        ticker_rows = self.repository.latest_tickers(limit=250)
        tickers = [row[0] for row in ticker_rows]
        ticker_times = {row[0].inst_id: row[1] for row in ticker_rows}
        signals = self.signal_engine.generate(
            tickers,
            max_signals=self.settings.paper_max_positions,
        )

        execution = PaperExecutionEngine(
            taker_fee_bps=Decimal(self.settings.paper_taker_fee_bps),
            slippage_bps=Decimal(self.settings.paper_slippage_bps),
        )

        # 3. Dynamic Risk-Parity Allocation
        strat_signals = [
            StrategySignal(
                strategy_key=getattr(sig, "strategy_key", "utc0_momentum_legacy"),
                inst_id=sig.inst_id,
                side=sig.side,
                conviction=getattr(sig, "conviction", 0.5),
                stop_loss_pct=getattr(sig, "stop_loss_pct", Decimal("0.035")),
                take_profit_pct=getattr(sig, "take_profit_pct", Decimal("0.070")),
                reason=sig.reason,
            )
            for sig in signals
        ]
        stage_multipliers = self.stage_gate.get_stage_multipliers()
        plan = self.allocator.allocate(
            equity=Decimal(paper_session.equity),
            signals=strat_signals,
            tickers=tickers,
            stage_multipliers=stage_multipliers,
            open_symbols=open_symbols,
        )

        fill_count = 0
        ticker_map = {t.inst_id: t for t in tickers}

        if plan.targets:
            for target in plan.targets:
                if fill_count >= remaining_slots:
                    break
                if target.inst_id in open_symbols:
                    continue
                ticker = ticker_map.get(target.inst_id)
                if ticker is None or ticker.last <= 0:
                    continue

                fill = execution.simulate_fill(
                    inst_id=target.inst_id,
                    side=target.side,
                    target_notional=target.target_notional,
                    last_price=ticker.last,
                )
                reason_tag = (
                    f"[{target.strategy_key}] sl:{target.stop_loss_pct} "
                    f"tp:{target.take_profit_pct} {target.reason}"
                )
                self.repository.create_order_and_fill(
                    session_id=paper_session.id,
                    simulated_fill=fill,
                    target_notional=target.target_notional,
                    reason=reason_tag,
                    source_ticker_updated_at=ticker_times[target.inst_id],
                )
                fill_msg = f"Paper {target.side} fill: {target.inst_id} ({target.strategy_key})"
                self.repository.record_event(
                    session_id=paper_session.id,
                    kind="fill",
                    message=fill_msg,
                    payload={
                        "inst_id": target.inst_id,
                        "side": target.side,
                        "strategy_key": target.strategy_key,
                        "target_notional": str(target.target_notional),
                        "price": str(fill.price),
                        "risk_weight": str(round(target.risk_weight, 4)),
                    },
                )
                fill_count += 1
        else:
            # Fallback allocation if risk parity yielded no targets (e.g. legacy test environment)
            target_notional = self._target_notional(Decimal(paper_session.equity))
            for signal in signals:
                if fill_count >= remaining_slots:
                    break
                if signal.inst_id in open_symbols:
                    continue
                ticker = ticker_map.get(signal.inst_id)
                if ticker is None or ticker.last <= 0:
                    continue

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

        self.stage_gate.evaluate_promotions()
        return PaperRunResult(
            status="running",
            fill_count=fill_count,
            event_count=fill_count + len(closed_brackets),
        )

    def pause(self) -> dict[str, Any]:
        return self._set_status("paused")

    def resume(self) -> dict[str, Any]:
        return self._set_status("running")

    def close(self, *, symbol: str | None = None) -> dict[str, Any]:
        paper_session = self.ensure_default_session()
        target = _normalize_symbol(symbol) if symbol else None
        positions = [
            position
            for position in self.repository.open_positions(paper_session.id)
            if target is None or position.inst_id == target
        ]
        closed: list[dict[str, str]] = []
        for position in positions:
            latest = self.repository.latest_ticker_price(position.inst_id)
            source_ticker_updated_at: object
            if latest is None:
                exit_price = position.mark_price
                source_ticker_updated_at = utc_now()
                data_source = "position_mark"
            else:
                exit_price, source_ticker_updated_at = latest
                data_source = "latest_ticker"
            closed_row = self.repository.close_position(
                session_id=paper_session.id,
                position_id=position.id,
                exit_price=exit_price,
                source_ticker_updated_at=source_ticker_updated_at,
                taker_fee_bps=Decimal(self.settings.paper_taker_fee_bps),
                reason="operator_close",
            )
            closed_row["data_source"] = data_source
            closed.append(closed_row)
            self.stage_gate.record_trade(
                "utc0_momentum_legacy",
                realized_pnl=Decimal(closed_row["realized_pnl"]),
                notional=position.notional,
                inst_id=position.inst_id,
            )
        self.repository.record_event(
            session_id=paper_session.id,
            kind="close",
            message=_close_message(target=target, closed_count=len(closed)),
            payload={"target": target or "all", "closed_count": len(closed), "closed": closed},
        )
        return {
            "session": self.ensure_default_session().__dict__,
            "closed_count": len(closed),
            "closed": closed,
        }

    def reset(self) -> dict[str, Any]:
        current = self.ensure_default_session()
        with self.db.session() as session:
            old_session = session.get(PaperSession, current.id)
            if old_session is not None:
                old_session.status = "reset"
                session.add(
                    PaperEvent(
                        session_id=old_session.id,
                        kind="reset",
                        message="Paper session reset by operator",
                        payload={"previous_session_id": old_session.id},
                    )
                )
            new_session = self._new_session()
            session.add(new_session)
            session.flush()
            session.add(
                PaperEvent(
                    session_id=new_session.id,
                    kind="reset",
                    message="New paper session created by reset",
                    payload={"previous_session_id": current.id},
                )
            )
            return {"session": _session_snapshot(new_session).__dict__}

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
            paper_session = session.scalar(
                select(PaperSession)
                .where(PaperSession.status != "reset")
                .order_by(desc(PaperSession.created_at))
            )
            if paper_session is None:
                raise RuntimeError("paper session bootstrap failed")
            paper_session.status = status
            session.flush()
            return {"session": _session_snapshot(paper_session).__dict__}

    def _new_session(self) -> PaperSession:
        starting_equity = Decimal(self.settings.paper_starting_equity_usdt)
        return PaperSession(
            cash=starting_equity,
            equity=starting_equity,
            realized_pnl=Decimal("0"),
            config_json=self._config_json(),
        )

    def _config_json(self) -> dict[str, Any]:
        return {
            "max_positions": self.settings.paper_max_positions,
            "max_symbol_notional_pct": self.settings.paper_max_symbol_notional_pct,
            "max_leverage": self.settings.paper_max_leverage,
            "taker_fee_bps": self.settings.paper_taker_fee_bps,
            "slippage_bps": self.settings.paper_slippage_bps,
        }

    def _target_notional(self, equity: Decimal) -> Decimal:
        max_symbol = equity * Decimal(str(self.settings.paper_max_symbol_notional_pct))
        leveraged_slot = equity * Decimal(str(self.settings.paper_max_leverage)) / Decimal(
            str(self.settings.paper_max_positions)
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


def _normalize_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    text = symbol.strip().upper()
    if not text:
        return None
    if "-" in text:
        return text
    return f"{text}-USDT-SWAP"


def _close_message(*, target: str | None, closed_count: int) -> str:
    if target is None:
        return f"Closed {closed_count} paper positions"
    return f"Closed {closed_count} paper positions for {target}"
