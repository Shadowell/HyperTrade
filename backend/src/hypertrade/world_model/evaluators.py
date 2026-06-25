"""Pure evaluators for WorldState labels."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def risk_regime_from_crypto(crypto_market: dict[str, Any]) -> str:
    if crypto_market.get("status") != "available":
        return "unknown"
    avg = _decimal(crypto_market.get("average_change_utc0_pct"))
    advancers = int(crypto_market.get("advancers_count", 0) or 0)
    decliners = int(crypto_market.get("decliners_count", 0) or 0)
    if decliners >= max(3, advancers * 2) and avg <= Decimal("-2"):
        return "risk_off"
    if advancers >= max(3, decliners * 2) and avg >= Decimal("2"):
        return "risk_on"
    if abs(avg) <= Decimal("0.5"):
        return "mixed"
    return "mixed"


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
