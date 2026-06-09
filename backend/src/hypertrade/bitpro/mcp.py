"""Read-only BitPro MCP tool-contract adapter.

HyperTrade treats BitPro as an external capability provider. This module keeps
the boundary explicit: discover capabilities, check health, then call the
smallest read tool needed for data access. Live write tools are blocked here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from hypertrade.config import Settings, get_settings
from hypertrade.strategy.sdk import Candle

MCP_CONTRACT_VERSION = "bitpro-mcp-v1"
DEFAULT_API_BASE = "http://127.0.0.1:8889/api/v2"
DEFAULT_AUTH_HEADER = "X-BitPro-MCP-Token"

READ_TOOL_ENDPOINTS: dict[str, dict[str, str]] = {
    "bitpro_health": {"method": "GET", "path": "/system/health"},
    "market_symbols": {"method": "GET", "path": "/market/symbols"},
    "market_klines": {"method": "GET", "path": "/market/klines"},
    "market_indicators": {"method": "GET", "path": "/market/indicators"},
    "sync_config": {"method": "GET", "path": "/sync/config"},
    "sync_status": {"method": "GET", "path": "/sync/status"},
    "sync_jobs": {"method": "GET", "path": "/sync/jobs"},
    "sync_table_stats": {"method": "GET", "path": "/sync/table-stats"},
    "strategy_search": {"method": "GET", "path": "/strategies"},
    "strategy_get": {"method": "GET", "path": "/strategies/{strategy_id}"},
    "backtest_get_job": {"method": "GET", "path": "/backtest/job/{job_id}"},
    "backtest_list_results": {"method": "GET", "path": "/backtest/results"},
    "backtest_get_result": {"method": "GET", "path": "/backtest/result/{backtest_id}"},
    "paper_dashboard": {"method": "GET", "path": "/live/dashboard"},
    "paper_events": {"method": "GET", "path": "/live/events"},
    "paper_equity_curve": {"method": "GET", "path": "/live/equity_curve"},
    "live_preflight": {"method": "POST", "path": "/live/promote/preflight"},
    "trading_balance": {"method": "GET", "path": "/trading/accounts/balance"},
    "trading_positions": {"method": "GET", "path": "/trading/accounts/positions"},
    "trading_open_orders": {"method": "GET", "path": "/trading/orders/open"},
}

RESEARCH_MUTATION_TOOLS = {
    "sync_start_history",
    "sync_one",
    "strategy_create",
    "strategy_generate",
    "strategy_validate_code",
    "agent_create_task",
    "agent_accept_iteration",
    "optimizer_run_now",
    "backtest_start_job",
    "backtest_cancel_job",
    "backtest_resume_job",
    "paper_configure",
    "paper_start",
    "paper_pause",
    "paper_resume",
    "paper_stop",
}

LIVE_MUTATION_TOOLS = {
    "live_promote",
    "trading_spot_order",
    "trading_futures_order",
    "trading_cancel_order",
    "trading_transfer",
}


class BitProMcpError(RuntimeError):
    """Raised when a BitPro tool-contract call fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class BitProMcpClient:
    """Call BitPro tools through the stable MCP tool contract.

    Remote Streamable HTTP is the BitPro-facing transport, but HyperTrade keeps
    its own dependency surface small by using the stable tool-to-API mapping
    published by `bitpro_capabilities`.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.base_url = (self.settings.bitpro_mcp_api_base or DEFAULT_API_BASE).rstrip("/")
        self.auth_token = self.settings.bitpro_mcp_api_token.strip()
        self.auth_header = (self.settings.bitpro_mcp_auth_header or DEFAULT_AUTH_HEADER).strip()
        self.http_client = http_client or httpx.Client(
            timeout=self.settings.bitpro_mcp_timeout_seconds
        )

    def call_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> Any:
        params = dict(parameters or {})
        if tool_name == "bitpro_capabilities":
            return bitpro_capabilities()
        if tool_name in LIVE_MUTATION_TOOLS:
            raise PermissionError(f"BitPro live write tool is blocked: {tool_name}")
        if tool_name in RESEARCH_MUTATION_TOOLS:
            raise PermissionError(
                f"BitPro mutation tool is not enabled in this adapter: {tool_name}"
            )
        if tool_name not in READ_TOOL_ENDPOINTS:
            raise KeyError(f"Unknown BitPro MCP tool: {tool_name}")
        spec = READ_TOOL_ENDPOINTS[tool_name]
        method = spec["method"].upper()
        path = _format_path(spec["path"], params)
        if method == "GET":
            return self._request(method, path, params=params, tool_name=tool_name)
        return self._request(method, path, json=params, tool_name=tool_name)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        tool_name: str,
    ) -> Any:
        response = self.http_client.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json,
            headers=self._auth_headers(),
        )
        payload = _response_payload(response)
        if response.status_code >= 400 or (
            isinstance(payload, dict) and payload.get("success") is False
        ):
            raise BitProMcpError(
                _error_message(payload, response.status_code, tool_name=tool_name),
                status_code=response.status_code,
                payload=payload,
            )
        if isinstance(payload, dict) and payload.get("success") is True and "data" in payload:
            return payload["data"]
        return payload

    def _auth_headers(self) -> dict[str, str] | None:
        if not self.auth_token:
            return None
        return {self.auth_header: self.auth_token}


class BitProToolAdapter:
    """Read-oriented adapter used by Agent tools, API endpoints, and backtests."""

    def __init__(self, client: BitProMcpClient | None = None) -> None:
        self.client = client or BitProMcpClient()
        self.last_tool_calls: list[dict[str, Any]] = []

    def capabilities(self) -> dict[str, Any]:
        self.last_tool_calls = []
        return _ensure_dict(self._call("bitpro_capabilities", {}))

    def health(self) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "tool_calls": self.last_tool_calls,
        }

    def market_klines(
        self,
        *,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        exchange: str = "okx",
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        normalized_symbol = _normalize_bitpro_symbol(symbol)
        normalized_timeframe = _normalize_bitpro_timeframe(timeframe)
        safe_limit = max(1, min(int(limit), 1000))
        raw = self._call(
            "market_klines",
            {
                "exchange": exchange,
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe,
                "limit": safe_limit,
            },
        )
        candles = _extract_kline_rows(raw)
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "market": {
                "exchange": exchange,
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe,
                "limit": safe_limit,
            },
            "candles": candles,
            "raw": raw,
            "tool_calls": self.last_tool_calls,
        }

    def fetch_candles(self, *, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        payload = self.market_klines(symbol=symbol, timeframe=timeframe, limit=limit)
        candles = [_row_to_candle(row) for row in payload["candles"]]
        if not candles:
            raise ValueError(f"No BitPro MCP candles found for {symbol} {timeframe}")
        return sorted(candles, key=lambda candle: candle.timestamp)

    def paper_dashboard(self, *, strategy_id: int | None = None) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        params = {"strategy_id": strategy_id} if strategy_id is not None else {}
        dashboard = self._call("paper_dashboard", params)
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "dashboard": dashboard,
            "tool_calls": self.last_tool_calls,
        }

    def live_positions(self, *, exchange: str = "okx", symbol: str | None = None) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        params = {"exchange": exchange}
        if symbol:
            params["symbol"] = _normalize_bitpro_symbol(symbol)
        positions = self._call("trading_positions", params)
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "positions": positions,
            "tool_calls": self.last_tool_calls,
        }

    def _preflight(self) -> tuple[dict[str, Any], dict[str, Any]]:
        capabilities = self._call("bitpro_capabilities", {})
        contract_version = str(capabilities.get("contract_version", ""))
        if contract_version != MCP_CONTRACT_VERSION:
            raise BitProMcpError(
                f"Unsupported BitPro MCP contract: {contract_version or 'unknown'}"
            )
        health = self._call("bitpro_health", {})
        return capabilities, _ensure_dict(health)

    def _call(self, tool_name: str, parameters: dict[str, Any]) -> Any:
        try:
            result = self.client.call_tool(tool_name, parameters)
        except Exception as exc:
            self.last_tool_calls.append(
                {
                    "tool": tool_name,
                    "parameters": dict(parameters),
                    "status": "failed",
                    "error": str(exc)[:500],
                }
            )
            raise
        self.last_tool_calls.append(
            {
                "tool": tool_name,
                "parameters": dict(parameters),
                "status": "success",
                "result_summary": _summarize_tool_result(result),
            }
        )
        return result


def bitpro_capabilities() -> dict[str, Any]:
    return {
        "contract_version": MCP_CONTRACT_VERSION,
        "transports": ["stdio", "streamable-http"],
        "api_base_default": DEFAULT_API_BASE,
        "remote_mcp": {
            "transport": "streamable-http",
            "path_default": "/api/v2/mcp/",
            "auth_header_default": DEFAULT_AUTH_HEADER,
            "token_env": "BITPRO_MCP_API_TOKEN",
        },
        "tool_groups": {
            "read": ["bitpro_capabilities", *READ_TOOL_ENDPOINTS.keys()],
            "research_backtest_paper_mutation": sorted(RESEARCH_MUTATION_TOOLS),
            "live_mutation": sorted(LIVE_MUTATION_TOOLS),
        },
        "tool_endpoints": {
            "bitpro_capabilities": {"method": "LOCAL", "path": "bitpro://capabilities"},
            **{name: dict(spec) for name, spec in READ_TOOL_ENDPOINTS.items()},
        },
        "data_policy": "real_market_data_only_no_mock_or_synthetic_ohlcv",
        "live_trading_enabled": False,
    }


def _format_path(path: str, params: dict[str, Any]) -> str:
    formatted = path
    for key in list(params):
        placeholder = "{" + key + "}"
        if placeholder in formatted:
            formatted = formatted.replace(placeholder, str(params.pop(key)))
    return formatted


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {"success": False, "error": {"message": response.text or "non-json response"}}


def _error_message(payload: Any, status_code: int, *, tool_name: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        error = payload.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("detail") or detail or tool_name)
        return str(detail or error or payload.get("message") or f"{tool_name} HTTP {status_code}")
    return f"{tool_name} HTTP {status_code}: {payload}"


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {"value": value}


def _extract_kline_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [_ensure_dict(row) for row in raw]
    if isinstance(raw, dict):
        for key in ("klines", "items", "rows", "data"):
            value = raw.get(key)
            if isinstance(value, list):
                return [_ensure_dict(row) for row in value]
    return []


def _row_to_candle(row: dict[str, Any]) -> Candle:
    timestamp = _timestamp_to_iso(row.get("timestamp") or row.get("ts") or row.get("time"))
    return Candle(
        timestamp=timestamp,
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row.get("volume") or row.get("vol") or row.get("volume_ccy") or 0)),
    )


def _timestamp_to_iso(value: Any) -> str:
    if isinstance(value, str) and "T" in value:
        return value
    numeric = int(value)
    seconds = numeric / 1000 if numeric > 10_000_000_000 else numeric
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat()


def _normalize_bitpro_symbol(symbol: str) -> str:
    value = symbol.strip().upper().replace("_", "-")
    if not value:
        value = "BTC"
    if "/" in value:
        return value if ":" in value else f"{value}:USDT"
    if value.endswith("-SWAP"):
        value = value.removesuffix("-SWAP")
    base = value.removesuffix("-USDT") if value.endswith("-USDT") else value.split("-", 1)[0]
    return f"{base}/USDT:USDT"


def _normalize_bitpro_timeframe(timeframe: str) -> str:
    value = timeframe.strip()
    if not value:
        return "1h"
    if value.lower().endswith("h"):
        return f"{value[:-1]}h"
    if value.lower().endswith("d"):
        return f"{value[:-1]}d"
    return value.lower()


def _summarize_tool_result(result: Any) -> dict[str, Any]:
    if isinstance(result, list):
        return {"type": "list", "count": len(result)}
    if isinstance(result, dict):
        keys = list(result.keys())
        summary: dict[str, Any] = {"type": "dict", "keys": keys[:8]}
        if "status" in result:
            summary["status"] = result["status"]
        if "contract_version" in result:
            summary["contract_version"] = result["contract_version"]
        return summary
    return {"type": type(result).__name__}
