"""Built-in BitPro market target.

The profile freezes the vocabulary the evolution core used to hardcode:
OKX swap venue, USDT quote, 24/7 continuous calendar with UTC-aligned 14-day
windows and hourly evidence buckets, the BitPro evidence contracts, and the
BitPro cost resolver as the only accepted cost-policy source. The adapter
factory stays lazy so importing the registry never builds an HTTP client.
"""

from __future__ import annotations

from typing import Any

from hypertrade.targets.registry import register_market_target
from hypertrade.targets.schemas import (
    MarketTargetProfileV1,
    TargetCalendarV1,
    TargetCapabilitiesV1,
)

BITPRO_TARGET_ID = "bitpro"

BITPRO_TARGET_PROFILE = MarketTargetProfileV1(
    target_id=BITPRO_TARGET_ID,
    display_name="BitPro（OKX 模拟盘）",
    transport="bitpro_mcp_v1",
    tool_contract="bitpro-mcp-v1",
    venue="okx",
    market_type="swap",
    quote_currency="USDT",
    strategy_id_format="integer",
    calendar=TargetCalendarV1(
        mode="continuous",
        timezone="UTC",
        evidence_window_days=14,
        evidence_bucket_seconds=3600,
    ),
    evidence_contracts=(
        "strategy_return_series.v1",
        "paper_evidence.v1",
        "research_costs.v1",
    ),
    cost_policy_sources=("bitpro_backtest_cost_resolver",),
    capabilities=TargetCapabilitiesV1(
        running_inventory=True,
        session_snapshot=True,
        return_series=True,
        session_trades=True,
        execution_ledger=True,
        backtest=True,
        paper_launch=True,
        cost_identity=True,
        live_preflight=True,
    ),
)


def bitpro_adapter_factory() -> Any:
    from hypertrade.bitpro.mcp import BitProToolAdapter
    from hypertrade.bitpro.paced_reads import PacedReadClient

    return BitProToolAdapter(PacedReadClient())


def register_bitpro_target() -> None:
    from hypertrade.targets.registry import _REGISTRY

    if BITPRO_TARGET_ID in _REGISTRY:
        return
    register_market_target(BITPRO_TARGET_PROFILE, bitpro_adapter_factory)
