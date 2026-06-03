"""Pre-trade risk checks shared by paper/live execution surfaces.

RiskEngine is the safety gate in front of order intents and Testnet execution.
Mainnet execution is blocked here even if a caller accidentally reaches the
live service. Keeping these rules centralized makes API, CLI, frontend, and
Agent-created intents show the same risk result.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select

from hypertrade.config import Settings
from hypertrade.db import Database, LiveOrderIntent
from hypertrade.market.repository import MarketRepository


class RiskEngine:
    def __init__(self, db: Database, *, settings: Settings) -> None:
        self.db = db
        self.settings = settings

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
        }
        # V1 only allows OKX Testnet execution. Mainnet may still create an
        # auditable intent, but the execution path must remain blocked.
        if environment != "testnet":
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
            # Notional is estimated from the limit price when available; market
            # orders use the latest stored ticker price.
            notional = size * mark_price
            checks["estimated_notional_usdt"] = str(notional)
            if notional > self._max_order_notional():
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
