"""BitPro compatibility connector.

This connector exposes the current BitPro MCP adapter through the generic
connector contract without moving BitPro execution out of the audited adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hypertrade.bitpro.mcp import (
    MCP_AGENT_AUTH_POLICY,
    MCP_IDEMPOTENCY_REQUIRED_TOOLS,
    BitProMcpClient,
    BitProToolAdapter,
    bitpro_capabilities,
)
from hypertrade.config import Settings, get_settings
from hypertrade.connectors.base import (
    ConnectorAuthMetadata,
    ConnectorCapability,
    ConnectorToolDescriptor,
)

_SAFE_READ_SCOPES = {"read", "live_diagnostic"}


class BitProConnector:
    connector_id = "bitpro"
    display_name = "BitPro MCP"

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        adapter: BitProToolAdapter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.adapter = adapter or BitProToolAdapter(BitProMcpClient(settings=self.settings))

    def capabilities(self) -> ConnectorCapability:
        tools = self.list_tools()
        return ConnectorCapability(
            connector_id=self.connector_id,
            display_name=self.display_name,
            health={
                "status": "not_checked",
                "checked": False,
                "configured": bool(self.settings.bitpro_mcp_api_base),
            },
            auth=self._auth_metadata(),
            supported_scopes=_supported_scopes(),
            tools=tools,
            source_of_truth="bitpro_mcp",
            notes=[
                "BitPro remains the trading-system platform.",
                "HyperTrade calls BitPro through MCP/API only and redacts token values.",
            ],
        )

    def health(self) -> dict[str, object]:
        return self.adapter.health()

    def list_tools(self) -> list[ConnectorToolDescriptor]:
        capabilities = bitpro_capabilities()
        groups = capabilities.get("tool_groups", {})
        tool_scopes: dict[str, str] = {}
        if isinstance(groups, dict):
            for scope, tools in groups.items():
                if not isinstance(tools, list):
                    continue
                for tool_name in tools:
                    tool_scopes[str(tool_name)] = str(scope)
        tool_endpoints = capabilities.get("tool_endpoints", {})
        descriptions = _tool_descriptions()
        descriptors: list[ConnectorToolDescriptor] = []
        for tool_name in sorted(tool_scopes):
            scope = tool_scopes[tool_name]
            endpoint = tool_endpoints.get(tool_name, {}) if isinstance(tool_endpoints, dict) else {}
            schema: dict[str, Any] = dict(endpoint) if isinstance(endpoint, dict) else {}
            descriptors.append(
                ConnectorToolDescriptor(
                    name=tool_name,
                    description=descriptions.get(tool_name, _humanize_tool_name(tool_name)),
                    scope=scope,
                    safe_read=scope in _SAFE_READ_SCOPES,
                    idempotency_required=tool_name in MCP_IDEMPOTENCY_REQUIRED_TOOLS,
                    source_of_truth="bitpro_mcp",
                    connector_id=self.connector_id,
                    requires_approval=scope == "live_mutation",
                    parameters_schema=schema,
                )
            )
        return descriptors

    def execute_read_tool(self, tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        descriptor = self._tool_descriptor(tool_name)
        if not descriptor.safe_read:
            raise PermissionError(f"Connector tool is not a safe read: {tool_name}")
        executor = self._read_executors().get(tool_name)
        if executor is None:
            raise KeyError(f"BitPro connector read execution is not wired for: {tool_name}")
        return {
            "status": "ok",
            "connector_id": self.connector_id,
            "tool": tool_name,
            "result": executor(parameters),
        }

    def _auth_metadata(self) -> ConnectorAuthMetadata:
        token_configured = bool(self.settings.bitpro_mcp_api_token.strip())
        return ConnectorAuthMetadata(
            type="token",
            configured=token_configured,
            header=self.settings.bitpro_mcp_auth_header,
            token_env=str(MCP_AGENT_AUTH_POLICY["static_token_env"]),
            token_source="server_env" if token_configured else "not_configured",
            secret_redacted=True,
        )

    def _tool_descriptor(self, tool_name: str) -> ConnectorToolDescriptor:
        for descriptor in self.list_tools():
            if descriptor.name == tool_name:
                return descriptor
        raise KeyError(f"Unknown BitPro connector tool: {tool_name}")

    def _read_executors(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        return {
            "bitpro_capabilities": lambda _params: self.adapter.capabilities(),
            "bitpro_health": lambda _params: self.adapter.health(),
            "market_klines": self._execute_market_klines,
            "strategy_search": self._execute_strategy_search,
            "backtest_get_job": self._execute_backtest_get_job,
            "backtest_list_results": self._execute_backtest_list_results,
            "backtest_get_result": self._execute_backtest_get_result,
            "paper_dashboard": self._execute_paper_dashboard,
            "paper_events": self._execute_paper_events,
            "paper_equity_curve": self._execute_paper_equity_curve,
            "strategy_return_series": lambda params: self.adapter.strategy_return_series(
                **params
            ),
            "strategy_return_matrix": lambda params: self.adapter.strategy_return_matrix(
                **params
            ),
            "strategy_execution_quality": (
                lambda params: self.adapter.strategy_execution_quality(**params)
            ),
            "trading_positions": self._execute_trading_positions,
        }

    def _execute_market_klines(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.adapter.market_klines(
            symbol=str(params.get("symbol", "BTC")),
            timeframe=str(params.get("timeframe", params.get("bar", "1h"))),
            limit=int(params.get("limit", 200)),
            exchange=str(params.get("exchange", "okx")),
        )

    def _execute_strategy_search(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.adapter.strategy_search(
            search=str(params.get("search", "")),
            page=int(params.get("page", 1)),
            per_page=int(params.get("per_page", 18)),
            status=str(params.get("status", "all")),
        )

    def _execute_backtest_get_job(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.adapter.backtest_get_job(job_id=str(params.get("job_id", "")))

    def _execute_backtest_list_results(self, params: dict[str, Any]) -> dict[str, Any]:
        min_return = params.get("min_total_return_pct")
        return self.adapter.backtest_list_results(
            min_total_return_pct=float(min_return) if min_return is not None else None,
            status=str(params.get("status", "completed")),
            sort_by=str(params.get("sort_by", "return")),
            sort_order=str(params.get("sort_order", "desc")),
            limit=int(params.get("limit", 100)),
        )

    def _execute_backtest_get_result(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.adapter.backtest_get_result(
            backtest_id=params.get("backtest_id", ""),
            sample_limit=int(params.get("sample_limit", 20)),
        )

    def _execute_paper_dashboard(self, params: dict[str, Any]) -> dict[str, Any]:
        strategy_id = params.get("strategy_id")
        return self.adapter.paper_dashboard(
            strategy_id=int(strategy_id) if strategy_id is not None else None,
        )

    def _execute_paper_events(self, params: dict[str, Any]) -> dict[str, Any]:
        strategy_id = params.get("strategy_id")
        return self.adapter.paper_events(
            strategy_id=int(strategy_id) if strategy_id is not None else None,
            limit=int(params.get("limit", 50)),
        )

    def _execute_paper_equity_curve(self, params: dict[str, Any]) -> dict[str, Any]:
        strategy_id = params.get("strategy_id")
        return self.adapter.paper_equity_curve(
            strategy_id=int(strategy_id) if strategy_id is not None else None,
            sample_limit=int(params.get("sample_limit", 50)),
        )

    def _execute_trading_positions(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.adapter.live_positions(
            exchange=str(params.get("exchange", "okx")),
            symbol=str(params["symbol"]) if params.get("symbol") else None,
        )


def _supported_scopes() -> list[str]:
    capabilities = bitpro_capabilities()
    groups = capabilities.get("tool_groups", {})
    if not isinstance(groups, dict):
        return []
    return sorted(str(scope) for scope in groups)


def _tool_descriptions() -> dict[str, str]:
    return {
        "bitpro_capabilities": "Read BitPro MCP contract and auth metadata.",
        "bitpro_health": "Check BitPro API health.",
        "market_klines": "Read real BitPro K-line data.",
        "strategy_search": "Search BitPro strategy records.",
        "backtest_get_job": "Read BitPro backtest job status.",
        "backtest_list_results": "List BitPro backtest result records.",
        "backtest_get_result": "Read one BitPro backtest result artifact set.",
        "paper_dashboard": "Read BitPro paper/simulation dashboard state.",
        "paper_events": "Read BitPro paper/simulation events.",
        "paper_equity_curve": "Read BitPro paper/simulation equity curve.",
        "strategy_return_series": "Read a versioned bounded strategy return series.",
        "strategy_return_matrix": "Read an aligned strategy return matrix.",
        "strategy_execution_quality": "Read bounded strategy execution-quality evidence.",
        "trading_positions": "Read BitPro live positions for diagnostics.",
    }


def _humanize_tool_name(tool_name: str) -> str:
    return "BitPro " + tool_name.replace("_", " ")
