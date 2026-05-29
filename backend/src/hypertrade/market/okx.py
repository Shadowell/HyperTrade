from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class OkxTicker:
    inst_id: str
    inst_type: str
    last: Decimal
    volume_ccy_24h: Decimal
    change_utc0_pct: Decimal
    raw: dict[str, Any]


@dataclass(frozen=True)
class OkxCandle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    volume_ccy: Decimal
    volume_ccy_quote: Decimal
    confirmed: bool
    raw: list[Any]


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _pct(last: Decimal, baseline: Decimal) -> Decimal:
    if baseline == 0:
        return Decimal("0")
    return ((last - baseline) / baseline * Decimal("100")).quantize(
        Decimal("0.001"), rounding=ROUND_DOWN
    )


def parse_okx_ticker(payload: dict[str, Any]) -> OkxTicker:
    last = _decimal(payload.get("last"))
    sod_utc0 = _decimal(payload.get("sodUtc0"))
    return OkxTicker(
        inst_id=str(payload.get("instId", "")),
        inst_type=str(payload.get("instType", "SWAP") or "SWAP"),
        last=last,
        volume_ccy_24h=_decimal(payload.get("volCcy24h", payload.get("vol24h", "0"))),
        change_utc0_pct=_pct(last, sod_utc0),
        raw=dict(payload),
    )


def parse_okx_candle(payload: list[Any]) -> OkxCandle:
    return OkxCandle(
        open_time=datetime.fromtimestamp(int(str(payload[0])) / 1000, tz=UTC),
        open=_decimal(payload[1]),
        high=_decimal(payload[2]),
        low=_decimal(payload[3]),
        close=_decimal(payload[4]),
        volume=_decimal(payload[5]),
        volume_ccy=_decimal(payload[6]),
        volume_ccy_quote=_decimal(payload[7]),
        confirmed=str(payload[8]) == "1",
        raw=list(payload),
    )
