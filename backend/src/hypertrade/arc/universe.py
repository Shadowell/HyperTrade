"""Research scope is frozen from connector instruments, never a coin allowlist."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from hypertrade.bitpro.mcp import BitProToolAdapter


def normalize_symbols(values: list[str]) -> list[str]:
    result = []
    for value in values:
        symbol = value.strip().upper()
        if re.fullmatch(r"[A-Z0-9]+/USDT:USDT", symbol):
            symbol = symbol.split("/")[0] + "-USDT-SWAP"
        elif re.fullmatch(r"[A-Z0-9]+", symbol):
            symbol += "-USDT-SWAP"
        if not re.fullmatch(r"[A-Z0-9]+-USDT-SWAP", symbol):
            raise ValueError("当前研究执行接口支持 OKX USDT 永续；请使用币种或完整永续合约代码")
        if symbol not in result:
            result.append(symbol)
    return result


def discover_symbols() -> list[str]:
    payload = BitProToolAdapter().client.call_tool(
        "market_symbols", {"exchange": "okx", "quote": "USDT", "market_type": "swap"}
    )
    rows = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, str) for row in rows):
        raise ValueError("无法读取可用标的列表，请稍后重试；未替换为默认标的")
    return normalize_symbols(rows)


def resolve_universe(
    requested: list[str], *, discover: Callable[[], list[str]] = discover_symbols
) -> list[str]:
    available = normalize_symbols(discover())
    if not available:
        raise ValueError("当前接口没有可用标的；未创建研究任务")
    chosen = normalize_symbols(requested)
    missing = set(chosen) - set(available)
    if missing:
        raise ValueError("当前接口不支持这些标的：" + ", ".join(sorted(missing)))
    return chosen or available


def candidate_symbol(spec: dict[str, Any], scope: list[str]) -> str:
    # A historical single-symbol candidate can inherit its sole scope. A multi-symbol
    # research must explicitly choose; silently taking index zero corrupts Paper binding.
    symbol = str(spec.get("symbol") or (scope[0] if len(scope) == 1 else ""))
    if not symbol or symbol not in scope:
        raise ValueError("candidate_symbol_missing_or_outside_research_scope")
    return symbol
