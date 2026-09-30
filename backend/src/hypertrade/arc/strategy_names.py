"""Human-readable BitPro names; execution identities remain in separate request keys."""

import re
from decimal import Decimal, InvalidOperation
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
    # This validates the external naming protocol, not BitPro trading logic.
    asset_type = asset_type.strip()
    timeframe = timeframe.strip().upper()
    strategy_type = strategy_type.strip()
    method = logic_summary.strip()
    if asset_type not in {"合约", "现货", "期权"}:
        raise ValueError("bitpro_strategy_name_invalid:asset")
    if not re.fullmatch(r"(?:(?:1|3|5|15|30)M|(?:1|2|4|6|8|12)H|1D|AI)", timeframe):
        raise ValueError("bitpro_strategy_name_invalid:timeframe")
    if strategy_type not in {
        "CTA",
        "ML",
        "AI",
        "马丁",
        "网格",
        "套利",
        "均值回归",
        "做市",
        "信号",
        "轮动",
        "中性",
    }:
        raise ValueError("bitpro_strategy_name_invalid:type")
    if not method or any(char in logic_summary for char in "·[]\r\n"):
        raise ValueError("bitpro_strategy_name_invalid:method")
    if any(
        re.search(pattern, method)
        for pattern in (
            r"^ht_",
            r"^cand[_-]",
            r"(?i)^arc[_-](?:probe|canary|selftest|self-test)",
            r"[0-9a-fA-F]{16,}",
            r"^[A-Za-z][A-Za-z0-9]*Strategy$",
        )
    ):
        raise ValueError("bitpro_strategy_name_invalid:machine_identifier")
    base = (scope_label if scope_label is not None else symbol).strip().upper()
    if not base or any(char in base for char in "·[]\r\n"):
        raise ValueError("bitpro_strategy_name_invalid:scope")
    if "/USDT" in base:
        base = base.split("/")[0]
    else:
        base = base.removesuffix("-SWAP").removesuffix("-USDT")
    try:
        number = Decimal(str(capital_u))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("bitpro_strategy_name_invalid:capital") from exc
    if isinstance(capital_u, bool) or not number.is_finite() or number <= 0:
        raise ValueError("bitpro_strategy_name_invalid:capital")
    capital = format(number.normalize(), "f")
    prefix = f"[{asset_type}][{timeframe.upper()}][{strategy_type}] {base}"
    return f"{prefix} · {method} · {capital}U"
