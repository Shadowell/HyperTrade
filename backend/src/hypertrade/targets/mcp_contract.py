"""Generic MCP market evolution contract (``market-evolution.v1``).

Any standard MCP server that exposes the canonical tool names below can be
plugged in as a market target — the QuantLab-style on-ramp. The contract is
intentionally small: it is the minimum a platform must implement for the
evolution loop to observe running strategies and provision governed paper
sessions. Discovery is live (``tools/list``): a target that is missing any
required tool fails preflight with the missing list instead of failing mid
cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hypertrade.targets.registry import MarketTargetUnavailable
from hypertrade.targets.schemas import (
    MarketTargetProfileV1,
    TargetCalendarV1,
    TargetCapabilitiesV1,
)

MARKET_EVOLUTION_CONTRACT_V1 = "market-evolution.v1"

# Canonical capability -> required MCP tool name on the target server.
CANONICAL_TOOLS: dict[str, str] = {
    "list_running_strategies": "evolution_list_running_strategies",
    "get_session_snapshot": "evolution_get_session_snapshot",
    "read_equity_series": "evolution_get_equity_series",
    "list_session_trades": "evolution_list_session_trades",
    "read_execution_ledger": "evolution_read_execution_ledger",
    "configure_paper": "evolution_configure_paper",
    "start_paper": "evolution_start_paper",
}

# Phase 2 read extension. These are required to consume the typed read ports;
# the original seven-tool contract remains unchanged for older preflight callers.
READ_EXTENSION_TOOLS: dict[str, str] = {
    "get_strategy_source": "evolution_get_strategy_source",
    "list_trading_sessions": "evolution_list_trading_sessions",
}
READ_REQUIRED_CAPABILITIES = (
    "list_running_strategies",
    "get_strategy_source",
    "get_session_snapshot",
    "read_equity_series",
    "list_session_trades",
)

# Argument names the canonical tools are expected to accept. The remote tool's
# advertised input schema stays authoritative; these are the names HyperTrade
# will send, so a conforming server should accept exactly them.
CANONICAL_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "list_running_strategies": ("limit",),
    "get_session_snapshot": ("strategy_id", "instance_id"),
    "read_equity_series": ("instance_id", "start", "end", "bucket_seconds", "limit"),
    "list_session_trades": ("strategy_id", "limit", "since"),
    "read_execution_ledger": ("session_id", "kind", "start_ms", "end_ms", "limit"),
    "configure_paper": (
        "strategy_id",
        "capital",
        "symbols",
        "timeframe",
        "code_sha256",
        "review_hash",
        "idempotency_key",
    ),
    "start_paper": (
        "strategy_id",
        "instance_id",
        "code_sha256",
        "review_hash",
        "strategy_version",
        "config_version",
        "idempotency_key",
    ),
}
READ_EXTENSION_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "get_strategy_source": ("strategy_id",),
    "list_trading_sessions": ("start_date", "end_date"),
}


def build_mcp_contract_profile(
    target_id: str,
    display_name: str,
    *,
    venue: str | None = None,
    market_type: str | None = None,
    quote_currency: str | None = None,
    calendar: TargetCalendarV1 | None = None,
    capabilities: TargetCapabilitiesV1 | None = None,
    cost_policy_sources: tuple[str, ...] = (),
    evidence_contracts: tuple[str, ...] = (),
) -> MarketTargetProfileV1:
    """Build a profile for any server implementing the canonical MCP contract."""

    return MarketTargetProfileV1(
        target_id=target_id,
        display_name=display_name,
        transport="mcp_contract_v1",
        tool_contract=MARKET_EVOLUTION_CONTRACT_V1,
        venue=venue,
        market_type=market_type,
        quote_currency=quote_currency,
        strategy_id_format="string",
        calendar=calendar or TargetCalendarV1(),
        evidence_contracts=evidence_contracts,
        cost_policy_sources=cost_policy_sources,
        capabilities=capabilities or TargetCapabilitiesV1(live_preflight=False),
    )


@dataclass(frozen=True)
class McpContractPreflight:
    ok: bool
    server: str
    contract: str
    present: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    errors: tuple[str, ...] = field(default=())


class McpContractClient:
    """Routes canonical capabilities to a standard MCP server.

    Wraps ``McpClientRegistry`` (multi-server transport with discovery cache,
    backoff retry and per-server breaker); this class adds contract semantics:
    capability -> tool-name resolution and preflight validation against
    ``tools/list``. It performs no retries of its own.
    """

    def __init__(self, registry: Any, server: str, profile: MarketTargetProfileV1) -> None:
        if profile.transport != "mcp_contract_v1":
            raise ValueError(f"target {profile.target_id!r} is not an mcp_contract_v1 target")
        self._registry = registry
        self._server = server
        self._profile = profile

    @property
    def profile(self) -> MarketTargetProfileV1:
        return self._profile

    def canonical_tool(self, capability: str) -> str:
        tool = CANONICAL_TOOLS.get(capability) or READ_EXTENSION_TOOLS.get(capability)
        if tool is None:
            raise MarketTargetUnavailable(f"unknown canonical capability {capability!r}")
        return tool

    async def preflight(self, *, force_refresh: bool = False) -> McpContractPreflight:
        return await self._preflight(set(CANONICAL_TOOLS.values()), force_refresh=force_refresh)

    async def preflight_read(self, *, force_refresh: bool = False) -> McpContractPreflight:
        required = {
            CANONICAL_TOOLS[key] if key in CANONICAL_TOOLS else READ_EXTENSION_TOOLS[key]
            for key in READ_REQUIRED_CAPABILITIES
        }
        if self._profile.calendar.mode == "sessions":
            required.add(READ_EXTENSION_TOOLS["list_trading_sessions"])
        return await self._preflight(required, force_refresh=force_refresh)

    async def _preflight(self, required: set[str], *, force_refresh: bool) -> McpContractPreflight:
        errors: list[str] = []
        names: set[str] = set()
        try:
            descriptors = await self._registry.list_tools(self._server, force_refresh=force_refresh)
            names = {str(item.name) for item in descriptors}
        except Exception as exc:  # noqa: BLE001 - preflight reports, never raises
            errors.append(f"{type(exc).__name__}: {exc}")
        missing = sorted(required - names)
        present = sorted(required & names)
        return McpContractPreflight(
            ok=not missing and not errors,
            server=self._server,
            contract=MARKET_EVOLUTION_CONTRACT_V1,
            present=tuple(present),
            missing=tuple(missing),
            errors=tuple(errors),
        )

    async def call_canonical(self, capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self.canonical_tool(capability)
        result = await self._registry.call_tool(self._server, tool, dict(arguments))
        if not isinstance(result, dict):
            raise MarketTargetUnavailable(
                f"canonical tool {tool!r} returned {type(result).__name__}, expected object"
            )
        return result
