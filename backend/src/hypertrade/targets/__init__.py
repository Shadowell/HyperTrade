"""Pluggable market targets.

Public surface: register/get a target profile, resolve the active target from
settings, and validate generic MCP-contract servers before plugging them in.
"""

from __future__ import annotations

from hypertrade.targets.mcp_contract import (
    CANONICAL_ARGUMENTS,
    CANONICAL_TOOLS,
    MARKET_EVOLUTION_CONTRACT_V1,
    READ_EXTENSION_TOOLS,
    McpContractClient,
    McpContractPreflight,
    build_mcp_contract_profile,
)
from hypertrade.targets.mcp_read_ports import McpReadPorts
from hypertrade.targets.registry import (
    MarketTargetBinding,
    MarketTargetUnavailable,
    active_market_target_id,
    get_active_market_target,
    get_market_target,
    register_market_target,
    registered_market_targets,
    reset_market_targets,
)
from hypertrade.targets.schemas import (
    MarketTargetProfileV1,
    TargetCalendarV1,
    TargetCapabilitiesV1,
)

__all__ = [
    "CANONICAL_ARGUMENTS",
    "CANONICAL_TOOLS",
    "MARKET_EVOLUTION_CONTRACT_V1",
    "MarketTargetBinding",
    "MarketTargetProfileV1",
    "MarketTargetUnavailable",
    "McpContractClient",
    "McpContractPreflight",
    "McpReadPorts",
    "READ_EXTENSION_TOOLS",
    "TargetCalendarV1",
    "TargetCapabilitiesV1",
    "active_market_target_id",
    "build_mcp_contract_profile",
    "get_active_market_target",
    "get_market_target",
    "register_market_target",
    "registered_market_targets",
    "reset_market_targets",
]
