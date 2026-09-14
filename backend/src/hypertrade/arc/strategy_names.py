"""Human-readable BitPro names; execution identities remain in separate request keys."""

import re
from decimal import Decimal
from typing import Any


def scope_label_from_symbols(symbols: list[str], *, max_items: int = 3) -> str:
    """BitPro scope segment: first bases joined with '/', '等N' beyond the cap.

    Mirrors BitPro's ``scope_label_from_symbols`` so portfolio names stay inside
    the naming contract's scope grammar.
    """
    bases: list[str] = []
    for symbol in symbols or ():
        base = re.split(r"[/:\-]", str(symbol or "").strip())[0].upper()
        if base and base not in bases:
            bases.append(base)
    if not bases:
        return "多标的"
    if len(bases) <= max_items:
        return "/".join(bases)
    return f"{'/'.join(bases[:max_items])}等{len(bases)}"


def logic_summary(spec: dict[str, Any]) -> str:
    family = str(spec.get("family") or "")
    direction = {"long_short": "双向", "long_only": "多头", "short_only": "空头"}.get(
        str(spec.get("direction") or ""), ""
    )
    parameters = spec.get("tunable_parameters") or {}

    def period(key: str) -> str:
        value = parameters.get(key)
        if value is None or isinstance(value, bool):
            return ""
        number = Decimal(str(value))
        return format(number.normalize(), "f") if number.is_finite() else ""

    pair = "/".join(filter(None, [period("fast_window"), period("slow_window")]))
    names = {
        "ma_crossover": f"SMA{pair}{direction}趋势",
        "ema_macd_kdj": f"EMA{pair}+MACD+KDJ{direction}组合",
        "donchian_breakout": f"唐奇安{period('channel_period')}{direction}突破",
        "atr_breakout": f"ATR{direction}突破",
        "mean_reversion_zscore": f"ZScore{direction}均值回归",
        "rsi_reversal": f"RSI{direction}反转",
        "momentum_roc": f"ROC{direction}动量",
    }
    return names.get(family, "原策略对照基线" if "baseline_config" in spec else "策略研究")


def format_bitpro_strategy_name(
    symbol: str,
    timeframe: str = "1H",
    strategy_type: str = "CTA",
    logic_summary: str = "策略研究",
    capital_u: Any = 100,
    *,
    asset_type: str = "合约",
    scope_label: str | None = None,
) -> str:
    base = (scope_label or symbol).strip().upper()
    if "/USDT" in base:
        base = base.split("/")[0]
    else:
        base = base.removesuffix("-SWAP").removesuffix("-USDT")
    capital = format(Decimal(str(capital_u)).normalize(), "f")
    prefix = f"[{asset_type}][{timeframe.upper()}][{strategy_type}] {base}"
    return f"{prefix} · {logic_summary} · {capital}U"
