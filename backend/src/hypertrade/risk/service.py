"""Pre-trade risk checks shared by paper/live execution surfaces.

RiskEngine is the safety gate in front of order intents and execution.
Supports both:
- SUPERVISED mode: requires explicit human approval; mainnet blocked by default.
- AUTONOMOUS mode: bounded execution with hardware circuit breakers, daily loss limits,
  and notional caps, without requiring per-order human clicks.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import func, select

from hypertrade.config import Settings
from hypertrade.db import Database, LiveOrderIntent
from hypertrade.market.repository import MarketRepository

RiskExecutionMode = Literal["supervised", "autonomous"]


class AutonomousCircuitBreaker:
    """Hardware circuit breaker protecting the autonomous trading agent."""

    def __init__(self, max_daily_loss_pct: Decimal = Decimal("3.0")) -> None:
        self.max_daily_loss_pct = max_daily_loss_pct
        self._tripped: bool = False
        self._trip_reason: str = ""

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def trip_reason(self) -> str:
        return self._trip_reason

    def check_daily_pnl(self, current_daily_loss_pct: Decimal) -> bool:
        if current_daily_loss_pct >= self.max_daily_loss_pct:
            self._tripped = True
            self._trip_reason = (
                f"daily loss {current_daily_loss_pct}% exceeded max {self.max_daily_loss_pct}%"
            )
            return False
        return True

    def trip(self, reason: str) -> None:
        self._tripped = True
        self._trip_reason = reason

    def reset(self) -> None:
        self._tripped = False
        self._trip_reason = ""


class RiskEngine:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings,
        circuit_breaker: AutonomousCircuitBreaker | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        default_pct = str(getattr(settings, "autonomous_max_daily_loss_pct", "3.0"))
        self.circuit_breaker = circuit_breaker or AutonomousCircuitBreaker(
            max_daily_loss_pct=Decimal(default_pct)
        )

    def check_order_intent(
        self,
        *,
        environment: str,
        inst_id: str,
        side: str,
        size: Decimal,
        order_type: str,
        price: Decimal | None = None,
        current_intent_id: str = "",
        execution_mode: RiskExecutionMode = "supervised",
        daily_loss_pct: Decimal | None = None,
        autonomous_override: bool = False,
    ) -> dict[str, Any]:
        violations: list[str] = []
        checks: dict[str, Any] = {
            "environment": environment,
            "inst_id": inst_id,
            "side": side,
            "order_type": order_type,
            "size": str(size),
            "max_order_notional_usdt": str(self._max_order_notional()),
            "max_open_intents": self.settings.risk_max_open_intents,
            "execution_mode": execution_mode,
        }

        # 1. Circuit breaker check in autonomous mode
        if execution_mode == "autonomous":
            if self.circuit_breaker.is_tripped:
                violations.append(f"circuit breaker tripped: {self.circuit_breaker.trip_reason}")
            elif (
                daily_loss_pct is not None
                and not self.circuit_breaker.check_daily_pnl(daily_loss_pct)
            ):
                violations.append(
                    f"daily loss limit breached: {self.circuit_breaker.trip_reason}"
                )

        # 2. Environment permissions
        is_autonomous_authorized = (
            execution_mode == "autonomous"
            and (getattr(self.settings, "autonomous_trading_enabled", False) or autonomous_override)
        )
        if environment != "testnet" and not is_autonomous_authorized:
            violations.append("mainnet execution is forbidden")

        if not inst_id.endswith("-SWAP"):
            violations.append("instrument type must be SWAP")

        open_intents = self._open_intent_count(current_intent_id=current_intent_id)
        checks["open_intents"] = open_intents
        if open_intents >= self.settings.risk_max_open_intents:
            violations.append("open intent count exceeds limit")

        mark_price = price or self._latest_price(inst_id)
        checks["estimated_price"] = str(mark_price) if mark_price is not None else ""
        if mark_price is not None:
            notional = size * mark_price
            checks["estimated_notional_usdt"] = str(notional)
            max_notional = self._max_order_notional()
            if notional > max_notional:
                violations.append("order notional exceeds limit")
        else:
            checks["estimated_notional_usdt"] = "unknown"

        return {
            "status": "blocked" if violations else "allowed",
            "violations": violations,
            "checks": checks,
        }

    def _open_intent_count(self, *, current_intent_id: str = "") -> int:
        with self.db.session() as session:
            statement = (
                select(func.count())
                .select_from(LiveOrderIntent)
                .where(LiveOrderIntent.status.in_(["pending_approval", "approved"]))
            )
            if current_intent_id:
                statement = statement.where(LiveOrderIntent.id != current_intent_id)
            return int(session.scalar(statement) or 0)

    def _latest_price(self, inst_id: str) -> Decimal | None:
        ticker = MarketRepository(self.db).get_ticker(inst_id)
        return ticker.last if ticker is not None else None

    def _max_order_notional(self) -> Decimal:
        try:
            return Decimal(str(self.settings.risk_max_order_notional_usdt))
        except (InvalidOperation, ValueError):
            return Decimal("0")
