"""BitPro MCP tool-contract adapter.

HyperTrade treats BitPro as an external capability provider. This module keeps
the boundary explicit: discover capabilities, check health, then call the
smallest tool needed for data access or research/paper lifecycle work. Live
write tools are blocked here.
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

RESEARCH_MUTATION_TOOL_ENDPOINTS: dict[str, dict[str, str]] = {
    "sync_start_history": {"method": "POST", "path": "/sync/start"},
    "sync_one": {"method": "POST", "path": "/sync/sync-one"},
    "strategy_create": {"method": "POST", "path": "/strategies"},
    "strategy_update": {"method": "PUT", "path": "/strategies/{strategy_id}"},
    "strategy_generate": {"method": "POST", "path": "/agent/generate_strategy"},
    "agent_create_task": {"method": "POST", "path": "/agent/tasks"},
    "agent_accept_iteration": {
        "method": "POST",
        "path": "/agent/tasks/{task_id}/iterations/{iteration}/accept",
    },
    "optimizer_run_now": {"method": "POST", "path": "/agent/strategy-optimizer/run-now"},
    "backtest_start_job": {"method": "POST", "path": "/backtest/run_job"},
    "backtest_cancel_job": {"method": "POST", "path": "/backtest/job/{job_id}/cancel"},
    "backtest_resume_job": {"method": "POST", "path": "/backtest/job/{job_id}/resume"},
    "paper_configure": {"method": "POST", "path": "/live/configure"},
    "paper_start": {"method": "POST", "path": "/live/start"},
    "paper_pause": {"method": "POST", "path": "/live/pause"},
    "paper_resume": {"method": "POST", "path": "/live/resume"},
    "paper_stop": {"method": "POST", "path": "/live/stop"},
}

RESEARCH_MUTATION_TOOLS = {
    "sync_start_history",
    "sync_one",
    "strategy_create",
    "strategy_update",
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

LOCAL_ONLY_TOOLS = {"strategy_validate_code"}

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
        if tool_name in LOCAL_ONLY_TOOLS:
            raise BitProMcpError(
                f"BitPro tool requires MCP local execution and is not available through "
                f"the API path adapter: {tool_name}"
            )
        endpoints = {**READ_TOOL_ENDPOINTS, **RESEARCH_MUTATION_TOOL_ENDPOINTS}
        if tool_name not in endpoints:
            raise KeyError(f"Unknown BitPro MCP tool: {tool_name}")
        spec = endpoints[tool_name]
        method = spec["method"].upper()
        path = _format_path(spec["path"], params)
        if method == "GET":
            return self._request(
                method,
                path,
                params=_compact(params),
                tool_name=tool_name,
            )
        return self._request(
            method,
            path,
            json=_post_payload(tool_name, params),
            tool_name=tool_name,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        tool_name: str,
    ) -> Any:
        try:
            response = self.http_client.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                json=json,
                headers=self._auth_headers(),
            )
        except httpx.HTTPError as exc:
            raise BitProMcpError(
                f"{tool_name} request failed: {exc}",
                status_code=None,
                payload={"error": {"message": str(exc), "type": type(exc).__name__}},
            ) from exc
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
    """Agent-facing adapter for BitPro read and non-live lifecycle tools."""

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

    def strategy_search(
        self,
        *,
        search: str = "",
        page: int = 1,
        per_page: int = 18,
        status: str = "all",
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if search:
            params["search"] = search
        if status and status != "all":
            params["status"] = status
        strategies = self._call("strategy_search", params)
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "strategies": strategies,
            "tool_calls": self.last_tool_calls,
        }

    def strategy_generate(self, *, prompt: str, symbol: str, timeframe: str) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        normalized_symbol = _normalize_bitpro_spot_symbol(symbol)
        normalized_timeframe = _normalize_bitpro_timeframe(timeframe)
        strategy = self._call(
            "strategy_generate",
            {
                "prompt": prompt,
                "symbol": normalized_symbol,
                "timeframe": normalized_timeframe,
            },
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "strategy": strategy,
            "tool_calls": self.last_tool_calls,
        }

    def strategy_create(
        self,
        *,
        name: str,
        script_content: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str = "okx",
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        strategy = self._call(
            "strategy_create",
            {
                "name": name,
                "script_content": script_content,
                "description": description,
                "config": config or {},
                "exchange": exchange,
                "symbols": [_normalize_bitpro_spot_symbol(symbol) for symbol in symbols or []],
            },
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "strategy": strategy,
            "tool_calls": self.last_tool_calls,
        }

    def strategy_update(
        self,
        *,
        strategy_id: int,
        name: str | None = None,
        script_content: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        params: dict[str, Any] = {"strategy_id": int(strategy_id)}
        if name is not None:
            params["name"] = name
        if script_content is not None:
            params["script_content"] = script_content
        if description is not None:
            params["description"] = description
        if config is not None:
            params["config"] = config
        if exchange is not None:
            params["exchange"] = exchange
        if symbols is not None:
            # Updates preserve caller-provided symbol semantics. Contract rows
            # commonly use BASE/USDT:USDT, while spot rows use BASE/USDT.
            params["symbols"] = [str(symbol) for symbol in symbols]
        strategy = self._call("strategy_update", params)
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "strategy": strategy,
            "tool_calls": self.last_tool_calls,
        }

    def backtest_start_job(
        self,
        *,
        strategy_id: int,
        start_date: str,
        end_date: str,
        initial_capital: float = 10000.0,
        exchange: str = "okx",
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        job = self._call(
            "backtest_start_job",
            {
                "strategy_id": int(strategy_id),
                "start_date": start_date,
                "end_date": end_date,
                "initial_capital": float(initial_capital),
                "exchange": exchange,
                "symbol": _normalize_bitpro_spot_symbol(symbol) if symbol else None,
                "timeframe": _normalize_bitpro_timeframe(timeframe) if timeframe else None,
            },
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "job": job,
            "tool_calls": self.last_tool_calls,
        }

    def backtest_get_job(self, *, job_id: str) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        job = self._call("backtest_get_job", {"job_id": job_id})
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "job": job,
            "tool_calls": self.last_tool_calls,
        }

    def backtest_list_results(
        self,
        *,
        min_total_return_pct: float | None = None,
        status: str = "completed",
        sort_by: str = "return",
        sort_order: str = "desc",
        limit: int = 100,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        safe_limit = max(1, min(int(limit), 200))
        rows = self._fetch_backtest_result_rows(
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=safe_limit,
        )
        results = [_backtest_result_item(row) for row in rows]
        if min_total_return_pct is not None:
            threshold = Decimal(str(min_total_return_pct))
            results = [
                row
                for row in results
                if (total_return := _decimal_or_none(row.get("total_return_pct"))) is not None
                and total_return > threshold
            ]
        results.sort(
            key=lambda row: _decimal_or_none(row.get("total_return_pct")) or Decimal("-999999"),
            reverse=str(sort_order).lower() != "asc",
        )
        self._attach_strategy_names(results)
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "filter": {
                "metric": "total_return_pct",
                "min_total_return_pct": min_total_return_pct,
                "status": status,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "limit": safe_limit,
            },
            "result_count": len(results),
            "raw_result_count": len(rows),
            "results": results,
            "tool_calls": self.last_tool_calls,
        }

    def _fetch_backtest_result_rows(
        self,
        *,
        status: str,
        sort_by: str,
        sort_order: str,
        limit: int,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        offset = 0
        while len(rows) < limit:
            raw = self._call(
                "backtest_list_results",
                _compact(
                    {
                        "offset": offset,
                        "limit": min(page_size, limit - len(rows)),
                        "status": status if status and status != "all" else None,
                        "sort_by": sort_by,
                        "sort_order": sort_order,
                    }
                ),
            )
            page_rows = _extract_backtest_rows(raw)
            new_rows: list[dict[str, Any]] = []
            for row in page_rows:
                row_id = str(row.get("id") or row.get("backtest_id") or "")
                if row_id and row_id in seen_ids:
                    continue
                if row_id:
                    seen_ids.add(row_id)
                new_rows.append(row)
            rows.extend(new_rows)
            if len(page_rows) < page_size or not new_rows:
                break
            offset += page_size
        return rows[:limit]

    def _attach_strategy_names(self, results: list[dict[str, Any]]) -> None:
        strategy_ids: list[int] = []
        for row in results:
            if row.get("strategy_id") is None or row.get("strategy_name"):
                continue
            try:
                strategy_ids.append(int(row["strategy_id"]))
            except (TypeError, ValueError):
                continue
        strategy_ids = sorted(set(strategy_ids))
        strategy_names: dict[int, str] = {}
        for strategy_id in strategy_ids:
            try:
                strategy = self._call("strategy_get", {"strategy_id": strategy_id})
            except Exception:
                continue
            if isinstance(strategy, dict):
                name = strategy.get("name") or strategy.get("strategy_name")
                if name:
                    strategy_names[strategy_id] = str(name)
        for row in results:
            try:
                strategy_id_value = row.get("strategy_id")
                if strategy_id_value is None:
                    continue
                strategy_id = int(strategy_id_value)
            except (TypeError, ValueError):
                continue
            if strategy_id in strategy_names:
                row["strategy_name"] = strategy_names[strategy_id]

    def paper_configure(
        self,
        *,
        strategy_id: int,
        initial_equity: float = 10000.0,
        exchange: str = "okx",
        loop_interval_sec: int = 60,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        paper = self._call(
            "paper_configure",
            {
                "strategy_id": int(strategy_id),
                "initial_equity": float(initial_equity),
                "exchange": exchange,
                "loop_interval_sec": int(loop_interval_sec),
            },
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "paper": paper,
            "tool_calls": self.last_tool_calls,
        }

    def paper_start(self, *, strategy_id: int) -> dict[str, Any]:
        return self._paper_lifecycle("paper_start", strategy_id=strategy_id)

    def paper_pause(self, *, strategy_id: int) -> dict[str, Any]:
        return self._paper_lifecycle("paper_pause", strategy_id=strategy_id)

    def paper_resume(self, *, strategy_id: int) -> dict[str, Any]:
        return self._paper_lifecycle("paper_resume", strategy_id=strategy_id)

    def paper_stop(self, *, strategy_id: int, clear_metrics: bool = False) -> dict[str, Any]:
        return self._paper_lifecycle(
            "paper_stop",
            strategy_id=strategy_id,
            clear_metrics=clear_metrics,
        )

    def _paper_lifecycle(self, tool_name: str, **parameters: Any) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        paper = self._call(tool_name, dict(parameters))
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "paper": paper,
            "tool_calls": self.last_tool_calls,
        }

    def paper_dashboard(self, *, strategy_id: int | None = None) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        params = {"strategy_id": strategy_id} if strategy_id is not None else {}
        dashboard = self._call("paper_dashboard", params)
        running_strategies: dict[str, Any] = {}
        if strategy_id is None:
            # BitPro's live dashboard is a current-instance view in production.
            # Add the running strategy inventory so Agent reports do not mistake
            # one visible dashboard for the full simulation universe.
            running_raw, running_items = self._fetch_strategy_inventory(status="running")
            running_strategies = {
                "items": running_items,
                "total": _strategy_total(running_raw, default=len(running_items)),
                "source_tool": "strategy_search",
                "status_filter": "running",
            }
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "dashboard": dashboard,
            "paper_scope": _paper_dashboard_scope(
                dashboard,
                strategy_id_filter=strategy_id,
                running_strategies=running_strategies,
            ),
            "running_strategies": running_strategies,
            "tool_calls": self.last_tool_calls,
        }

    def _fetch_strategy_inventory(
        self,
        *,
        status: str,
        per_page: int = 18,
        max_pages: int = 5,
    ) -> tuple[Any, list[dict[str, Any]]]:
        first_raw = self._call(
            "strategy_search",
            {"page": 1, "per_page": per_page, "status": status},
        )
        items = _extract_strategy_items(first_raw)
        pages = _strategy_pages(first_raw, default=1)
        for page in range(2, min(pages, max_pages) + 1):
            page_raw = self._call(
                "strategy_search",
                {"page": page, "per_page": per_page, "status": status},
            )
            items.extend(_extract_strategy_items(page_raw))
        return first_raw, items

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
            **{name: dict(spec) for name, spec in RESEARCH_MUTATION_TOOL_ENDPOINTS.items()},
            "strategy_validate_code": {"method": "LOCAL", "path": "BaseStrategy sandbox"},
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


def _post_payload(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "strategy_create":
        return _compact(
            {
                "name": params["name"],
                "description": params.get("description"),
                "script_content": params["script_content"],
                "config": params.get("config") or {},
                "exchange": params.get("exchange", "okx"),
                "symbols": list(params.get("symbols") or []),
            }
        )
    if tool_name == "strategy_update":
        return _compact(
            {
                "name": params.get("name"),
                "description": params.get("description"),
                "script_content": params.get("script_content"),
                "config": params.get("config"),
                "exchange": params.get("exchange"),
                "symbols": list(params["symbols"]) if params.get("symbols") is not None else None,
            }
        )
    if tool_name == "strategy_generate":
        return {
            "prompt": str(params["prompt"]),
            "symbol": str(params.get("symbol", "BTC/USDT")),
            "timeframe": str(params.get("timeframe", "1h")),
        }
    if tool_name == "backtest_start_job":
        return _compact(
            {
                "strategy_id": int(params["strategy_id"]),
                "exchange": params.get("exchange", "okx"),
                "symbol": params.get("symbol"),
                "timeframe": params.get("timeframe"),
                "timeframe_mode": params.get("timeframe_mode", "strategy"),
                "timeframes": list(params["timeframes"]) if params.get("timeframes") else None,
                "start_date": params["start_date"],
                "end_date": params["end_date"],
                "initial_capital": params.get("initial_capital", 10000.0),
                "maker_fee_bps": params.get("maker_fee_bps"),
                "taker_fee_bps": params.get("taker_fee_bps"),
                "slippage_bps": params.get("slippage_bps"),
            }
        )
    if tool_name == "paper_configure":
        return {
            "strategy_type": str(params["strategy_id"]),
            "exchange": str(params.get("exchange", "okx")),
            "initial_equity": float(params.get("initial_equity", 10000.0)),
            "dry_run": True,
            "loop_interval": int(params.get("loop_interval_sec", 60)),
        }
    if tool_name in {"paper_start", "paper_pause", "paper_resume"}:
        return {"instance_id": int(params["strategy_id"])}
    if tool_name == "paper_stop":
        return {
            "instance_id": int(params["strategy_id"]),
            "clear_metrics": bool(params.get("clear_metrics", False)),
        }
    if tool_name == "sync_start_history":
        return _compact(
            {
                "exchange": params.get("exchange", "okx"),
                "symbols": list(params["symbols"]),
                "timeframes": list(params["timeframes"]),
                "history_days": int(params.get("history_days", 365)),
                "start_date": params.get("start_date"),
                "end_date": params.get("end_date"),
            }
        )
    if tool_name == "sync_one":
        return _compact(
            {
                "exchange": params.get("exchange", "okx"),
                "symbol": params["symbol"],
                "timeframe": params["timeframe"],
                "history_days": int(params.get("history_days", 365)),
                "start_date": params.get("start_date"),
                "end_date": params.get("end_date"),
            }
        )
    return _compact(params)


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


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


def _extract_strategy_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [_strategy_item(row) for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict):
        for key in ("items", "strategies", "results", "data"):
            value = raw.get(key)
            if isinstance(value, list):
                return [_strategy_item(row) for row in value if isinstance(row, dict)]
    return []


def _strategy_item(row: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "id": row.get("id") or row.get("strategy_id"),
            "name": row.get("name") or row.get("strategy_name"),
            "status": row.get("status"),
            "exchange": row.get("exchange"),
            "symbols": row.get("symbols"),
            "timeframe": row.get("timeframe"),
            "strategy_source": row.get("strategy_source"),
        }
    )


def _strategy_total(raw: Any, *, default: int) -> int:
    if isinstance(raw, dict):
        total = raw.get("total")
        if isinstance(total, int):
            return total
        if isinstance(total, str) and total.isdigit():
            return int(total)
    return default


def _strategy_pages(raw: Any, *, default: int) -> int:
    if isinstance(raw, dict):
        pages = raw.get("pages")
        if isinstance(pages, int):
            return max(1, pages)
        if isinstance(pages, str) and pages.isdigit():
            return max(1, int(pages))
    return default


def _extract_backtest_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [_ensure_dict(row) for row in raw]
    if isinstance(raw, dict):
        for key in ("items", "results", "rows", "data"):
            value = raw.get(key)
            if isinstance(value, list):
                return [_ensure_dict(row) for row in value]
    return []


def _backtest_result_item(row: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "id": _first_present(row.get("id"), row.get("backtest_id")),
            "strategy_id": row.get("strategy_id"),
            "strategy_name": _first_present(
                row.get("strategy_name"),
                row.get("name"),
                row.get("title"),
            ),
            "status": row.get("status"),
            "start_date": row.get("start_date"),
            "end_date": row.get("end_date"),
            "created_at": row.get("created_at"),
            "timeframe": _first_present(row.get("timeframe"), row.get("period")),
            "symbol": row.get("symbol"),
            "symbols": row.get("symbols"),
            "total_return_pct": _decimal_text(
                _first_present(
                    row.get("total_return_pct"),
                    row.get("return_pct"),
                    row.get("profit_pct"),
                    row.get("total_return"),
                )
            ),
            "annual_return_pct": _decimal_text(
                _first_present(
                    row.get("annual_return_pct"),
                    row.get("annual_return"),
                    row.get("annualized_return"),
                )
            ),
            "max_drawdown_pct": _decimal_text(
                _first_present(row.get("max_drawdown_pct"), row.get("max_drawdown"))
            ),
            "sharpe_ratio": _decimal_text(
                _first_present(row.get("sharpe_ratio"), row.get("sharpe"))
            ),
            "win_rate_pct": _decimal_text(
                _first_present(row.get("win_rate_pct"), row.get("win_rate"))
            ),
            "trade_count": _first_present(row.get("trade_count"), row.get("total_trades")),
        }
    )


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace("%", ""))
    except Exception:
        return None


def _decimal_text(value: Any) -> str | None:
    decimal = _decimal_or_none(value)
    if decimal is None:
        return None
    text = format(decimal.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _paper_dashboard_scope(
    dashboard: Any,
    *,
    strategy_id_filter: int | None,
    running_strategies: dict[str, Any],
) -> dict[str, Any]:
    dashboard_dict = _ensure_dict(dashboard)
    system = dashboard_dict.get("system")
    system_dict = system if isinstance(system, dict) else {}
    strategy_id = system_dict.get("strategy_id")
    strategy_name = system_dict.get("strategy")
    running_count = 0
    running_items = running_strategies.get("items") if running_strategies else None
    if isinstance(running_items, list):
        running_count = len(running_items)
    running_total = running_strategies.get("total") if running_strategies else running_count
    dashboard_scope = "filtered_strategy" if strategy_id_filter is not None else "current_instance"
    coverage_note = (
        "paper_dashboard exposes the current BitPro paper dashboard only; "
        "running_strategies comes from strategy_search(status=running)."
    )
    return _compact(
        {
            "dashboard_scope": dashboard_scope,
            "strategy_id_filter": strategy_id_filter,
            "current_strategy_id": strategy_id,
            "current_strategy_name": strategy_name,
            "running_strategy_count": running_count,
            "running_strategy_total": running_total,
            "coverage_note": coverage_note,
        }
    )


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


def _normalize_bitpro_spot_symbol(symbol: str) -> str:
    value = symbol.strip().upper().replace("_", "-")
    if not value:
        value = "BTC"
    if "/" in value:
        return value.split(":", 1)[0]
    if value.endswith("-SWAP"):
        value = value.removesuffix("-SWAP")
    base = value.removesuffix("-USDT") if value.endswith("-USDT") else value.split("-", 1)[0]
    return f"{base}/USDT"


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
