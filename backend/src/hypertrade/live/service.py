from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select

from hypertrade.config import Settings, get_settings
from hypertrade.db import Database, LiveOrderIntent, utc_now
from hypertrade.live.okx import OkxSignedRestClient, redacted_order_request
from hypertrade.risk.service import RiskEngine


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
        inst_id = _normalize_symbol(symbol)
        risk = RiskEngine(self.db, settings=self.settings).check_order_intent(
            environment=environment,
            inst_id=inst_id,
            side=normalized_side,
            size=parsed_size,
            order_type=normalized_order_type,
            price=parsed_price,
        )
        intent = LiveOrderIntent(
            environment=environment,
            status="risk_blocked" if risk["status"] == "blocked" else "pending_approval",
            inst_id=inst_id,
            side=normalized_side,
            order_type=normalized_order_type,
            size=parsed_size,
            price=parsed_price,
            reason=reason.strip(),
            source=source,
            source_run_id=source_run_id,
            risk_status=str(risk["status"]),
            risk_json=risk,
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
        with self.db.session() as session:
            intent = session.get(LiveOrderIntent, intent_id)
            if intent is None:
                raise KeyError(intent_id)
            if intent.status != "pending_approval":
                raise ValueError(f"intent is already {intent.status}")
            risk = RiskEngine(self.db, settings=self.settings).check_order_intent(
                environment=intent.environment,
                inst_id=intent.inst_id,
                side=intent.side,
                size=intent.size,
                order_type=intent.order_type,
                price=intent.price,
                current_intent_id=intent.id,
            )
            intent.risk_status = str(risk["status"])
            intent.risk_json = risk
            intent.decision_reason = reason.strip()
            intent.status = "risk_blocked" if risk["status"] == "blocked" else "approved"
            session.flush()
            return _intent_to_dict(intent)

    def reject(self, intent_id: str, *, reason: str = "") -> dict[str, Any]:
        return self._decide(intent_id, status="rejected", reason=reason)

    def execute(self, intent_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            intent = session.get(LiveOrderIntent, intent_id)
            if intent is None:
                raise KeyError(intent_id)
            if intent.status != "approved":
                raise ValueError(
                    f"intent must be approved before execution; current={intent.status}"
                )
            risk = RiskEngine(self.db, settings=self.settings).check_order_intent(
                environment=intent.environment,
                inst_id=intent.inst_id,
                side=intent.side,
                size=intent.size,
                order_type=intent.order_type,
                price=intent.price,
                current_intent_id=intent.id,
            )
            intent.risk_status = str(risk["status"])
            intent.risk_json = risk
            request = redacted_order_request(
                settings=self.settings,
                inst_id=intent.inst_id,
                side=intent.side,
                order_type=intent.order_type,
                size=_decimal_to_string(intent.size),
                price=_decimal_to_string(intent.price) if intent.price is not None else None,
            )
            if risk["status"] == "blocked" or not self.settings.okx_testnet:
                intent.status = "risk_blocked"
                intent.execution_json = {
                    "request": request,
                    "response": {},
                    "error": "risk_blocked",
                }
                session.flush()
                return _intent_to_dict(intent)
            if not (
                self.settings.okx_api_key
                and self.settings.okx_api_secret
                and self.settings.okx_passphrase
            ):
                intent.status = "execution_failed"
                intent.execution_json = {
                    "request": request,
                    "response": {},
                    "error": "missing OKX testnet credentials",
                }
                session.flush()
                return _intent_to_dict(intent)
            try:
                response = OkxSignedRestClient(self.settings).place_order(
                    inst_id=intent.inst_id,
                    side=intent.side,
                    order_type=intent.order_type,
                    size=_decimal_to_string(intent.size),
                    price=_decimal_to_string(intent.price) if intent.price is not None else None,
                )
                exchange_order_id = _extract_order_id(response)
                intent.status = "executed_testnet"
                intent.exchange_order_id = exchange_order_id
                intent.executed_at = utc_now()
                intent.execution_json = {"request": request, "response": response, "error": ""}
            except Exception as exc:  # noqa: BLE001 - execution result must be auditable
                intent.status = "execution_failed"
                intent.execution_json = {
                    "request": request,
                    "response": {},
                    "error": str(exc)[:500],
                }
            session.flush()
            return _intent_to_dict(intent)

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
        "risk_status": intent.risk_status,
        "risk": intent.risk_json,
        "execution": intent.execution_json,
        "exchange_order_id": intent.exchange_order_id,
        "executed_at": intent.executed_at.isoformat() if intent.executed_at else None,
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


def _extract_order_id(response: dict[str, Any]) -> str:
    data = response.get("data", [])
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get("ordId", ""))
    return ""
