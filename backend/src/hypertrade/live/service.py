from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select

from hypertrade.config import Settings, get_settings
from hypertrade.db import Database, LiveOrderIntent


class LiveOrderIntentService:
    def __init__(self, db: Database, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def create(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
        source: str = "operator",
        source_run_id: str = "",
    ) -> dict[str, Any]:
        normalized_side = side.strip().lower()
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        normalized_order_type = order_type.strip().lower()
        if normalized_order_type not in {"market", "limit"}:
            raise ValueError("order_type must be market or limit")
        parsed_size = _positive_decimal(size, "size")
        parsed_price = _optional_positive_decimal(price, "price")
        if normalized_order_type == "limit" and parsed_price is None:
            raise ValueError("limit order requires price")
        environment = "testnet" if self.settings.okx_testnet else "mainnet"
        intent = LiveOrderIntent(
            environment=environment,
            status="pending_approval",
            inst_id=_normalize_symbol(symbol),
            side=normalized_side,
            order_type=normalized_order_type,
            size=parsed_size,
            price=parsed_price,
            reason=reason.strip(),
            source=source,
            source_run_id=source_run_id,
        )
        with self.db.session() as session:
            session.add(intent)
            session.flush()
            return _intent_to_dict(intent)

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(LiveOrderIntent).order_by(desc(LiveOrderIntent.created_at)).limit(limit)
            ).all()
            return [_intent_to_dict(row) for row in rows]

    def approve(self, intent_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._decide(intent_id, status="approved", reason=reason)

    def reject(self, intent_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._decide(intent_id, status="rejected", reason=reason)

    def _decide(self, intent_id: str, *, status: str, reason: str) -> dict[str, Any]:
        with self.db.session() as session:
            intent = session.get(LiveOrderIntent, intent_id)
            if intent is None:
                raise KeyError(intent_id)
            if intent.status != "pending_approval":
                raise ValueError(f"intent is already {intent.status}")
            intent.status = status
            intent.decision_reason = reason.strip()
            session.flush()
            return _intent_to_dict(intent)


def _intent_to_dict(intent: LiveOrderIntent) -> dict[str, Any]:
    return {
        "id": intent.id,
        "environment": intent.environment,
        "status": intent.status,
        "inst_id": intent.inst_id,
        "side": intent.side,
        "order_type": intent.order_type,
        "size": _decimal_to_string(intent.size),
        "price": _decimal_to_string(intent.price) if intent.price is not None else None,
        "reason": intent.reason,
        "source": intent.source,
        "source_run_id": intent.source_run_id,
        "decision_reason": intent.decision_reason,
        "created_at": intent.created_at.isoformat(),
        "updated_at": intent.updated_at.isoformat(),
    }


def _normalize_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    if not text:
        raise ValueError("symbol is required")
    if "-" in text:
        return text
    return f"{text}-USDT-SWAP"


def _positive_decimal(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    return parsed


def _optional_positive_decimal(value: str | None, field_name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    return _positive_decimal(value, field_name)


def _decimal_to_string(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
