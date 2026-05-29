from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from hypertrade.market.okx import OkxCandle


def summarize_candles(inst_id: str, bar: str, candles: list[OkxCandle]) -> dict[str, object]:
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    if not ordered:
        return {
            "inst_id": inst_id,
            "bar": bar,
            "found": False,
            "candle_count": 0,
        }

    first = ordered[0]
    last = ordered[-1]
    high = max(candle.high for candle in ordered)
    low = min(candle.low for candle in ordered)
    closes = [candle.close for candle in ordered]
    return_pct = _pct(last.close, first.open)
    range_pct = _range_pct(high, low, first.open)
    close_position_pct = (
        Decimal("0")
        if high == low
        else ((last.close - low) / (high - low) * Decimal("100")).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )
    )

    return {
        "inst_id": inst_id,
        "bar": bar,
        "found": True,
        "candle_count": len(ordered),
        "first_open_time": first.open_time.isoformat(),
        "last_open_time": last.open_time.isoformat(),
        "open": _money(first.open),
        "close": _money(last.close),
        "high": _money(high),
        "low": _money(low),
        "return_pct": _pct_text(return_pct),
        "range_pct": _pct_text(range_pct),
        "close_position_pct": _pct_text(close_position_pct),
        "volume_ccy_total": _money(sum((candle.volume_ccy for candle in ordered), Decimal("0"))),
        "volume_ccy_quote_total": _money(
            sum((candle.volume_ccy_quote for candle in ordered), Decimal("0"))
        ),
        "ma20": _money(_mean(closes[-20:])),
        "ma60": _money(_mean(closes[-60:])),
        "trend_bias": _trend_bias(return_pct, close_position_pct),
    }


def _pct(current: Decimal, baseline: Decimal) -> Decimal:
    if baseline == 0:
        return Decimal("0")
    return ((current - baseline) / baseline * Decimal("100")).quantize(
        Decimal("0.000001"), rounding=ROUND_DOWN
    )


def _range_pct(high: Decimal, low: Decimal, baseline: Decimal) -> Decimal:
    if baseline == 0:
        return Decimal("0")
    return ((high - low) / baseline * Decimal("100")).quantize(
        Decimal("0.000001"), rounding=ROUND_DOWN
    )


def _mean(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000000000001"), rounding=ROUND_DOWN))


def _pct_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_DOWN))


def _trend_bias(return_pct: Decimal, close_position_pct: Decimal) -> str:
    if return_pct >= Decimal("1") and close_position_pct >= Decimal("60"):
        return "up"
    if return_pct <= Decimal("-1") and close_position_pct <= Decimal("40"):
        return "down"
    return "range"
