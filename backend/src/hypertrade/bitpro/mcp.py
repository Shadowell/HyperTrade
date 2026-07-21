"""BitPro MCP tool-contract adapter.

HyperTrade treats BitPro as an external capability provider. This module keeps
the boundary explicit: discover capabilities, check health, then call the
smallest tool needed for data access or research/paper lifecycle work. Live
write tools are blocked here.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
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
    "paper_snapshot": {"method": "GET", "path": "/live/paper_snapshot"},
    "strategy_return_series": {
        "method": "GET",
        "path": "/strategy-evidence/return-series",
    },
    "strategy_return_matrix": {
        "method": "GET",
        "path": "/strategy-evidence/aligned-return-matrix",
    },
    "strategy_execution_quality": {
        "method": "GET",
        "path": "/strategy-evidence/execution-quality",
    },
    "live_strategies": {"method": "GET", "path": "/live/strategies"},
    "live_preflight": {"method": "POST", "path": "/live/promote/preflight"},
    "trading_balance": {"method": "GET", "path": "/trading/accounts/balance"},
    "trading_positions": {"method": "GET", "path": "/trading/accounts/positions"},
    "trading_open_orders": {"method": "GET", "path": "/trading/orders/open"},
    "trading_order_history": {"method": "GET", "path": "/trading/orders/history"},
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

LIVE_DIAGNOSTIC_TOOLS = {
    "live_preflight",
    "trading_balance",
    "trading_positions",
    "trading_open_orders",
    "trading_order_history",
    "live_strategies",
}

LIVE_MUTATION_TOOLS = {
    "live_promote",
    "trading_spot_order",
    "trading_futures_order",
    "trading_cancel_order",
    "trading_transfer",
}

MCP_SCOPE_CLASSES: dict[str, dict[str, str]] = {
    "R": {
        "label": "read",
        "tool_group": "read",
        "description": "Read-only market, strategy, backtest, paper, and health tools.",
    },
    "W": {
        "label": "research_backtest_paper_mutation",
        "tool_group": "research_backtest_paper_mutation",
        "description": "Research, sync, backtest, and paper/simulation mutation tools.",
    },
    "L": {
        "label": "live_diagnostic",
        "tool_group": "live_diagnostic",
        "description": (
            "Read-only live preflight, balance, position, open-order, and order-history "
            "diagnostics."
        ),
    },
    "T": {
        "label": "live_mutation",
        "tool_group": "live_mutation",
        "description": "Real trading mutation tools; blocked by HyperTrade's adapter today.",
    },
}

MCP_IDEMPOTENCY_REQUIRED_TOOLS = sorted(RESEARCH_MUTATION_TOOLS | LIVE_MUTATION_TOOLS)

MCP_AGENT_AUTH_POLICY: dict[str, Any] = {
    "auth_header_default": DEFAULT_AUTH_HEADER,
    "static_token_env": "BITPRO_MCP_API_TOKEN",
    "plaintext_returned_once": True,
    "token_management": {
        "settings_routes": {
            "list": "GET /api/v2/settings/mcp-agent-tokens",
            "create": "POST /api/v2/settings/mcp-agent-tokens",
            "revoke": "DELETE /api/v2/settings/mcp-agent-tokens/{token_id}",
        },
        "plaintext_returned_once": True,
        "storage": "bitpro_sqlite_sha256_hash_only",
        "default_tool_groups": [
            "read",
            "research_backtest_paper_mutation",
            "live_diagnostic",
        ],
    },
    "idempotency": {
        "field": "idempotency_key",
        "header": "Idempotency-Key",
        "required_tools": MCP_IDEMPOTENCY_REQUIRED_TOOLS,
    },
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
        remote_tool_caller: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.base_url = (self.settings.bitpro_mcp_api_base or DEFAULT_API_BASE).rstrip("/")
        self.auth_token = self.settings.bitpro_mcp_api_token.strip()
        self.auth_header = (self.settings.bitpro_mcp_auth_header or DEFAULT_AUTH_HEADER).strip()
        self.http_client = http_client or httpx.Client(
            timeout=self.settings.bitpro_mcp_timeout_seconds
        )
        self.remote_tool_caller = remote_tool_caller

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
            caller = self.remote_tool_caller or (
                lambda name, arguments: _run_async(
                    _call_remote_mcp_tool(self.settings, name, arguments)
                )
            )
            return caller(tool_name, params)
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


async def _call_remote_mcp_tool(
    settings: Settings, tool_name: str, parameters: dict[str, Any]
) -> Any:
    """Use the real Streamable HTTP transport for tools without a REST equivalent."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    remote_url = settings.bitpro_remote_mcp_url.strip() or (
        f"{settings.bitpro_mcp_api_base.rstrip('/')}/mcp/"
    )
    headers: dict[str, str] = {}
    if settings.bitpro_mcp_api_token:
        headers[settings.bitpro_mcp_auth_header] = settings.bitpro_mcp_api_token
    timeout = httpx.Timeout(settings.bitpro_mcp_timeout_seconds)
    async with (
        httpx.AsyncClient(headers=headers, timeout=timeout) as client,
        streamable_http_client(remote_url, http_client=client) as (
            read_stream,
            write_stream,
            _,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool_name, arguments=parameters)
    if result.isError:
        detail = " ".join(
            str(getattr(item, "text", ""))[:500]
            for item in result.content
            if getattr(item, "text", "")
        )
        raise BitProMcpError(f"BitPro remote MCP tool failed: {tool_name}: {detail}")
    if result.structuredContent is not None:
        payload = dict(result.structuredContent)
        return payload.get("result") if set(payload) == {"result"} else payload
    for item in result.content:
        text = str(getattr(item, "text", ""))
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    raise BitProMcpError(f"BitPro remote MCP tool returned no structured result: {tool_name}")


def _run_async(awaitable: Coroutine[Any, Any, Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    # Synchronous Agent surfaces may be called from an async host. Isolate the MCP
    # lifecycle rather than nesting event loops or leaking a session across requests.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="bitpro-mcp") as pool:
        return pool.submit(asyncio.run, awaitable).result()


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

    def strategy_return_series(self, **parameters: Any) -> dict[str, Any]:
        """Read one bounded BitPro-owned return-series page without recalculating PnL."""
        self.last_tool_calls = []
        self._preflight()
        return _ensure_dict(self._call("strategy_return_series", dict(parameters)))

    def strategy_return_matrix(self, **parameters: Any) -> dict[str, Any]:
        """Read a BitPro-owned aligned matrix; HyperTrade validates the frozen contract."""
        self.last_tool_calls = []
        self._preflight()
        return _ensure_dict(self._call("strategy_return_matrix", dict(parameters)))

    def strategy_execution_quality(self, **parameters: Any) -> dict[str, Any]:
        """Read bounded execution-quality evidence with no order or strategy mutation."""
        self.last_tool_calls = []
        self._preflight()
        return _ensure_dict(self._call("strategy_execution_quality", dict(parameters)))

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
        idempotency_key: str = "",
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
                "idempotency_key": idempotency_key,
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
        idempotency_key: str = "",
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
        if idempotency_key:
            params["idempotency_key"] = idempotency_key
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
        wait_for_result: bool = False,
        poll_interval_sec: float = 2.0,
        timeout_sec: float = 90.0,
        maker_fee_bps: float | None = None,
        taker_fee_bps: float | None = None,
        slippage_bps: float | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        raw_job = _ensure_dict(
            self._call(
                "backtest_start_job",
                {
                    "strategy_id": int(strategy_id),
                    "start_date": start_date,
                    "end_date": end_date,
                    "initial_capital": float(initial_capital),
                    "exchange": exchange,
                    "symbol": _normalize_bitpro_spot_symbol(symbol) if symbol else None,
                    "timeframe": _normalize_bitpro_timeframe(timeframe) if timeframe else None,
                    "maker_fee_bps": maker_fee_bps,
                    "taker_fee_bps": taker_fee_bps,
                    "slippage_bps": slippage_bps,
                    "idempotency_key": idempotency_key,
                },
            )
        )
        payload: dict[str, Any] = {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "job": _backtest_job_item(raw_job),
            "tool_calls": self.last_tool_calls,
        }
        self._attach_backtest_result_from_job(payload, raw_job)
        if wait_for_result and "backtest_result" not in payload:
            job_id = _first_present(raw_job.get("job_id"), raw_job.get("id"))
            if job_id:
                polled_job = self._poll_backtest_job(
                    job_id=str(job_id),
                    poll_interval_sec=poll_interval_sec,
                    timeout_sec=timeout_sec,
                )
                if polled_job is not None:
                    payload["job"] = _backtest_job_item(polled_job)
                    self._attach_backtest_result_from_job(payload, polled_job)
                    payload["tool_calls"] = self.last_tool_calls
        return payload

    def strategy_validate_code(
        self,
        *,
        script_content: str,
        idempotency_key: str,
        symbols: list[str] | None = None,
        market_type: str = "spot",
        timeframe: str = "1m",
        smoke: bool = True,
    ) -> dict[str, Any]:
        """Run BitPro's sandbox and deterministic runtime smoke validation."""
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        validation = self._call(
            "strategy_validate_code",
            _compact(
                {
                    "code": script_content,
                    "symbols": symbols,
                    "market_type": market_type,
                    "timeframe": _normalize_bitpro_timeframe(timeframe),
                    "smoke": smoke,
                }
            ),
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "validation": validation,
            "idempotency_key": idempotency_key,
            "tool_calls": self.last_tool_calls,
        }

    def backtest_get_job(self, *, job_id: str) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        raw_job = _ensure_dict(self._call("backtest_get_job", {"job_id": job_id}))
        job = _backtest_job_item(raw_job)
        payload: dict[str, Any] = {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "job": job,
            "tool_calls": self.last_tool_calls,
        }
        self._attach_backtest_result_from_job(payload, raw_job)
        return payload

    def _poll_backtest_job(
        self,
        *,
        job_id: str,
        poll_interval_sec: float,
        timeout_sec: float,
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        last_job: dict[str, Any] | None = None
        while True:
            raw_job = _ensure_dict(self._call("backtest_get_job", {"job_id": job_id}))
            last_job = raw_job
            if _backtest_job_is_terminal(raw_job):
                return raw_job
            if time.monotonic() >= deadline:
                return last_job
            sleep_for = max(0.0, float(poll_interval_sec))
            if sleep_for:
                time.sleep(min(sleep_for, max(0.0, deadline - time.monotonic())))

    def _attach_backtest_result_from_job(
        self,
        payload: dict[str, Any],
        raw_job: dict[str, Any],
    ) -> None:
        result_raw = _backtest_result_from_job(raw_job)
        if not result_raw:
            return
        result = _backtest_detail_item(result_raw, sample_limit=20)
        matched_row = self._find_completed_backtest_result(raw_job=raw_job, result=result)
        if matched_row is not None:
            _merge_backtest_result_row(result, matched_row)
        self._attach_strategy_names([result])
        payload["backtest_result"] = result
        payload["artifact_summary"] = _artifact_summary(result.get("artifacts", {}))
        payload["tool_calls"] = self.last_tool_calls

    def _find_completed_backtest_result(
        self,
        *,
        raw_job: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = str(raw_job.get("status") or result.get("status") or "").lower()
        if status not in {"completed", "success", "succeeded", "done"}:
            return None
        try:
            rows = self._fetch_backtest_result_rows(
                status="completed",
                sort_by="return",
                sort_order="desc",
                limit=200,
            )
        except Exception:
            return None
        for row in rows:
            if _backtest_row_matches_result(row, result):
                return row
        return None

    def backtest_get_result(
        self,
        *,
        backtest_id: str | int,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        safe_limit = max(0, min(int(sample_limit), 100))
        raw = self._call("backtest_get_result", {"backtest_id": backtest_id})
        result = _backtest_detail_item(raw, sample_limit=safe_limit)
        self._attach_strategy_names([result])
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "backtest_id": result.get("id") or backtest_id,
            "result": result,
            "artifacts": result["artifacts"],
            "artifact_summary": _artifact_summary(result["artifacts"]),
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
        idempotency_key: str = "",
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
                "idempotency_key": idempotency_key,
            },
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "paper": paper,
            "tool_calls": self.last_tool_calls,
        }

    def paper_start(self, *, strategy_id: int, idempotency_key: str = "") -> dict[str, Any]:
        return self._paper_lifecycle(
            "paper_start", strategy_id=strategy_id, idempotency_key=idempotency_key
        )

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
            "monitor_summary": _paper_monitor_summary(
                dashboard,
                running_strategies=running_strategies,
                strategy_id_filter=strategy_id,
            ),
            "tool_calls": self.last_tool_calls,
        }

    def paper_events(
        self,
        *,
        strategy_id: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        safe_limit = _bounded_int(limit, default=50, minimum=1, maximum=200)
        params: dict[str, Any] = {"limit": safe_limit}
        if strategy_id is not None:
            params["strategy_id"] = int(strategy_id)
        raw = self._call("paper_events", params)
        rows = [_paper_event_item(row) for row in _extract_paper_event_rows(raw)]
        events = rows[:safe_limit]
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "strategy_id": strategy_id,
            "limit": safe_limit,
            "events": events,
            "event_summary": _paper_event_summary(rows, events),
            "tool_calls": self.last_tool_calls,
        }

    def paper_equity_curve(
        self,
        *,
        strategy_id: int | None = None,
        sample_limit: int = 50,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        safe_limit = _bounded_int(sample_limit, default=50, minimum=0, maximum=500)
        params: dict[str, Any] = {}
        if strategy_id is not None:
            params["strategy_id"] = int(strategy_id)
        raw = self._call("paper_equity_curve", params)
        rows = [_paper_equity_point(row) for row in _extract_paper_equity_rows(raw)]
        points = rows[:safe_limit]
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "strategy_id": strategy_id,
            "sample_limit": safe_limit,
            "equity_curve": points,
            "equity_summary": _paper_equity_summary(rows, points),
            "tool_calls": self.last_tool_calls,
        }

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]:
        """Read one immutable BitPro paper-evidence snapshot."""
        if strategy_id is None and not instance_id:
            raise ValueError("paper_snapshot requires strategy_id or instance_id")
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        snapshot = self._call(
            "paper_snapshot",
            _compact({"strategy_id": strategy_id, "instance_id": instance_id}),
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "snapshot": snapshot,
            "tool_calls": self.last_tool_calls,
        }

    def paper_strategy_performance(self, *, limit: int = 20) -> dict[str, Any]:
        """Build a paper-performance matrix from identity-validated dashboard reads."""
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        safe_limit = _bounded_int(limit, default=20, minimum=1, maximum=50)
        raw, inventory = self._fetch_strategy_inventory(
            status="running",
            per_page=min(safe_limit, 50),
            max_pages=5,
        )
        reported_total = _strategy_total(raw, default=len(inventory))
        selected = inventory[:safe_limit]
        comparable: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        for strategy in selected:
            strategy_id = strategy.get("id")
            if strategy_id is None:
                unavailable.append(
                    _paper_performance_gap(strategy, reason="inventory_missing_strategy_id")
                )
                continue
            try:
                dashboard = self._call("paper_dashboard", {"strategy_id": int(strategy_id)})
            except Exception as exc:
                unavailable.append(
                    _paper_performance_gap(
                        strategy,
                        reason="dashboard_read_failed",
                        detail=str(exc)[:200],
                    )
                )
                continue
            row, reason = _paper_strategy_performance_row(strategy, dashboard)
            if reason:
                unavailable.append(
                    _paper_performance_gap(strategy, reason=reason, dashboard=dashboard)
                )
                continue
            comparable.append(row)

        comparable.sort(
            key=lambda row: _decimal_or_none(row.get("return_pct")) or Decimal("-Infinity"),
            reverse=True,
        )
        for rank, row in enumerate(comparable, start=1):
            row["rank"] = rank
        selected_count = len(selected)
        coverage_complete = (
            reported_total == selected_count
            and len(comparable) == selected_count
            and not unavailable
        )
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "mode": "read_only",
            "rank_basis": "return_pct",
            "strategies": comparable,
            "unavailable_strategies": unavailable,
            "performance_summary": _compact(
                {
                    "reported_total": reported_total,
                    "requested_count": selected_count,
                    "comparable_count": len(comparable),
                    "unavailable_count": len(unavailable),
                    "coverage_complete": coverage_complete,
                    "ranking_status": "complete" if coverage_complete else "partial",
                    "top_strategy_id": comparable[0].get("strategy_id") if comparable else None,
                    "top_strategy_name": comparable[0].get("strategy_name") if comparable else None,
                    "top_return_pct": comparable[0].get("return_pct") if comparable else None,
                }
            ),
            "risk_boundary": (
                "read-only BitPro paper evidence; dashboard rows are accepted only when "
                "the returned strategy id matches the requested strategy id"
            ),
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

    def live_order_history(
        self,
        *,
        exchange: str = "okx",
        symbol: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        safe_limit = max(1, min(int(limit), 200))
        params: dict[str, Any] = {"exchange": exchange, "limit": safe_limit}
        if symbol:
            params["symbol"] = _normalize_bitpro_symbol(symbol)
        raw = self._call("trading_order_history", params)
        orders = [_live_order_item(row) for row in _extract_live_order_rows(raw)]
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "exchange": exchange,
            "symbol": params.get("symbol"),
            "limit": safe_limit,
            "orders": orders,
            "order_summary": _live_order_summary(orders),
            "tool_calls": self.last_tool_calls,
        }

    def live_strategy_performance(
        self,
        *,
        exchange: str = "okx",
        limit: int = 20,
    ) -> dict[str, Any]:
        self.last_tool_calls = []
        capabilities, health = self._preflight()
        safe_limit = max(1, min(int(limit), 100))
        raw = self._call("live_strategies", {})
        rows = [_live_strategy_item(row) for row in _extract_live_strategy_rows(raw)]
        if exchange:
            rows = [
                row
                for row in rows
                if str(row.get("exchange") or "").casefold() == exchange.casefold()
            ]
        rows.sort(
            key=lambda row: _decimal_or_none(row.get("return_pct")) or Decimal("-Infinity"),
            reverse=True,
        )
        strategies = rows[:safe_limit]
        return {
            "status": "ok",
            "contract_version": str(capabilities.get("contract_version", "")),
            "health": health,
            "exchange": exchange,
            "limit": safe_limit,
            "rank_basis": "return_pct",
            "strategies": strategies,
            "performance_summary": _live_strategy_performance_summary(strategies),
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
            "token_status_path": "/settings/mcp-token",
            "token_generate_path": "/settings/mcp-token/generate",
        },
        "agent_auth": {
            **MCP_AGENT_AUTH_POLICY,
            "scope_classes": {name: dict(policy) for name, policy in MCP_SCOPE_CLASSES.items()},
            "idempotency": {
                "field": "idempotency_key",
                "header": "Idempotency-Key",
                "required_tools": list(MCP_IDEMPOTENCY_REQUIRED_TOOLS),
            },
        },
        "tool_groups": {
            "read": ["bitpro_capabilities", *READ_TOOL_ENDPOINTS.keys()],
            "research_backtest_paper_mutation": sorted(RESEARCH_MUTATION_TOOLS),
            "live_diagnostic": sorted(LIVE_DIAGNOSTIC_TOOLS),
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
        "live_trading_enabled_scope": "hypertrade_mcp_live_write_gate",
        "live_trading_enabled_note": (
            "This flag describes whether HyperTrade exposes BitPro MCP live "
            "write/order tools. It is not the BitPro runtime mode or proof that "
            "BitPro has no live trading configured."
        ),
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
                "idempotency_key": params.get("idempotency_key") or None,
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
                "idempotency_key": params.get("idempotency_key") or None,
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
                "idempotency_key": params.get("idempotency_key"),
            }
        )
    if tool_name == "paper_configure":
        return _compact(
            {
                "strategy_type": str(params["strategy_id"]),
                "exchange": str(params.get("exchange", "okx")),
                "initial_equity": float(params.get("initial_equity", 10000.0)),
                "dry_run": True,
                "loop_interval": int(params.get("loop_interval_sec", 60)),
                "idempotency_key": params.get("idempotency_key") or None,
            }
        )
    if tool_name in {"paper_start", "paper_pause", "paper_resume"}:
        return _compact(
            {
                "instance_id": int(params["strategy_id"]),
                "idempotency_key": params.get("idempotency_key") or None,
            }
        )
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


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError):
        integer = default
    return max(minimum, min(integer, maximum))


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
            "initial_equity": _first_present(row.get("initial_equity"), row.get("initial_capital")),
            "equity": _first_present(row.get("equity"), row.get("current_equity")),
            "total_pnl": _first_present(row.get("total_pnl"), row.get("pnl")),
            "return_pct": _first_present(
                row.get("return_pct"), row.get("total_pnl_pct"), row.get("pnl_pct")
            ),
            "max_drawdown_pct": _first_present(
                row.get("max_drawdown_pct"), row.get("max_drawdown")
            ),
            "sharpe_ratio": _first_present(row.get("sharpe_ratio"), row.get("sharpe")),
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
            "initial_capital": _decimal_text(row.get("initial_capital")),
            "final_capital": _decimal_text(
                _first_present(row.get("final_capital"), row.get("final_equity"))
            ),
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
            "profit_factor": _decimal_text(row.get("profit_factor")),
            "trade_count": _first_present(row.get("trade_count"), row.get("total_trades")),
        }
    )


def _backtest_job_item(raw: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "job_id": _first_present(raw.get("job_id"), raw.get("id")),
            "strategy_id": raw.get("strategy_id"),
            "status": raw.get("status"),
            "current_bar": raw.get("current_bar"),
            "total_bars": raw.get("total_bars"),
            "percent": _decimal_text(raw.get("percent")),
            "progress": _first_present(raw.get("progress"), raw.get("percent")),
            "message": raw.get("message"),
            "error_message": raw.get("error_message") or raw.get("error"),
            "updated_at": raw.get("updated_at"),
            "resumable": raw.get("resumable"),
        }
    )


def _backtest_result_from_job(raw: dict[str, Any]) -> dict[str, Any] | None:
    result = raw.get("result") or raw.get("backtest_result")
    if isinstance(result, dict):
        return result
    return None


def _backtest_job_is_terminal(raw: dict[str, Any]) -> bool:
    if _backtest_result_from_job(raw):
        return True
    status = str(raw.get("status") or "").lower()
    return status in {
        "completed",
        "success",
        "succeeded",
        "done",
        "failed",
        "error",
        "cancelled",
        "canceled",
    }


def _merge_backtest_result_row(result: dict[str, Any], row: dict[str, Any]) -> None:
    row_item = _backtest_result_item(row)
    for key in (
        "id",
        "strategy_id",
        "strategy_name",
        "status",
        "start_date",
        "end_date",
        "created_at",
        "timeframe",
        "symbol",
        "symbols",
    ):
        if row_item.get(key) is not None:
            result[key] = row_item[key]
    metrics = result.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
        result["metrics"] = metrics
    metric_keys = {
        "initial_capital",
        "final_capital",
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "win_rate_pct",
        "profit_factor",
        "trade_count",
    }
    for key in metric_keys:
        if row_item.get(key) is not None:
            metrics[key] = row_item[key]


def _backtest_row_matches_result(row: dict[str, Any], result: dict[str, Any]) -> bool:
    row_item = _backtest_result_item(row)
    if not _same_optional(row_item.get("strategy_id"), result.get("strategy_id")):
        return False
    if not _same_optional(row_item.get("start_date"), result.get("start_date")):
        return False
    if not _same_optional(row_item.get("end_date"), result.get("end_date")):
        return False
    if not _same_optional_lower(row_item.get("timeframe"), result.get("timeframe")):
        return False
    result_metrics = result.get("metrics")
    result_metrics = result_metrics if isinstance(result_metrics, dict) else {}
    if not _same_decimal_optional(
        row_item.get("total_return_pct"),
        result_metrics.get("total_return_pct"),
    ):
        return False
    return _same_decimal_optional(
        row_item.get("final_capital"),
        result_metrics.get("final_capital"),
    )


def _backtest_detail_item(raw: Any, *, sample_limit: int) -> dict[str, Any]:
    raw_dict = _ensure_dict(raw)
    metrics = _backtest_detail_metrics(raw_dict)
    result = _compact(
        {
            "id": _detail_value(raw_dict, "id", "backtest_id", "result_id"),
            "strategy_id": _detail_value(raw_dict, "strategy_id", "strategyId"),
            "strategy_name": _detail_value(
                raw_dict,
                "strategy_name",
                "strategyName",
                "name",
                "title",
            ),
            "status": _detail_value(raw_dict, "status", "state"),
            "start_date": _detail_value(raw_dict, "start_date", "startDate", "start"),
            "end_date": _detail_value(raw_dict, "end_date", "endDate", "end"),
            "created_at": _detail_value(raw_dict, "created_at", "createdAt"),
            "timeframe": _detail_value(raw_dict, "timeframe", "period", "bar"),
            "symbol": _detail_value(raw_dict, "symbol", "inst_id", "instrument"),
            "symbols": _detail_value(raw_dict, "symbols"),
            "metrics": metrics,
            "artifacts": _backtest_artifacts(raw_dict, sample_limit=sample_limit),
        }
    )
    return result


def _backtest_detail_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "total_return_pct": _decimal_text(
                _detail_value(
                    raw,
                    "total_return_pct",
                    "return_pct",
                    "profit_pct",
                    "total_return",
                )
            ),
            "annual_return_pct": _decimal_text(
                _detail_value(
                    raw,
                    "annual_return_pct",
                    "annual_return",
                    "annualized_return",
                )
            ),
            "max_drawdown_pct": _decimal_text(
                _detail_value(raw, "max_drawdown_pct", "max_drawdown")
            ),
            "sharpe_ratio": _decimal_text(_detail_value(raw, "sharpe_ratio", "sharpe")),
            "win_rate_pct": _decimal_text(_detail_value(raw, "win_rate_pct", "win_rate")),
            "trade_count": _detail_value(
                raw,
                "trade_count",
                "total_trades",
                "trades_count",
                "number_of_trades",
            ),
            "initial_capital": _decimal_text(
                _detail_value(raw, "initial_capital", "starting_equity", "start_cash")
            ),
            "final_capital": _decimal_text(
                _detail_value(raw, "final_capital", "final_equity", "ending_equity")
            ),
            "profit_factor": _decimal_text(_detail_value(raw, "profit_factor")),
        }
    )


def _detail_value(raw: dict[str, Any], *keys: str) -> Any:
    for source in _detail_sources(raw):
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
    return None


def _detail_sources(raw: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [raw]
    queue = [raw]
    for _ in range(2):
        next_queue: list[dict[str, Any]] = []
        for source in queue:
            for key in (
                "result",
                "backtest",
                "summary",
                "metrics",
                "performance",
                "stats",
                "metadata",
                "data",
            ):
                value = source.get(key)
                if isinstance(value, dict) and value not in sources:
                    sources.append(value)
                    next_queue.append(value)
        queue = next_queue
    return sources


def _backtest_artifacts(raw: dict[str, Any], *, sample_limit: int) -> dict[str, Any]:
    aliases = {
        "equity_curve": ("equity_curve", "equityCurve", "equity", "balance_curve"),
        "trades": ("trades", "trade_history", "tradeHistory"),
        "orders": ("orders", "order_history", "orderHistory"),
        "fills": ("fills", "executions", "fill_history", "fillHistory"),
        "drawdown_series": (
            "drawdown_series",
            "drawdownSeries",
            "drawdowns",
            "drawdown_curve",
            "drawdownCurve",
        ),
    }
    return {
        name: _artifact_payload(_extract_artifact_rows(raw, keys), sample_limit=sample_limit)
        for name, keys in aliases.items()
    }


def _extract_artifact_rows(raw: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for source in _artifact_sources(raw):
        for key in keys:
            if key not in source:
                continue
            rows = _coerce_artifact_rows(source[key])
            if rows:
                return rows
    return []


def _artifact_sources(raw: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [raw]
    queue = [raw]
    for _ in range(2):
        next_queue: list[dict[str, Any]] = []
        for source in queue:
            for key in ("artifacts", "result", "report", "details", "backtest", "data"):
                value = source.get(key)
                if isinstance(value, dict) and value not in sources:
                    sources.append(value)
                    next_queue.append(value)
        queue = next_queue
    return sources


def _coerce_artifact_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [_ensure_dict(row) for row in value]
    if isinstance(value, dict):
        for key in ("items", "rows", "data", "points", "values"):
            rows = value.get(key)
            if isinstance(rows, list):
                return [_ensure_dict(row) for row in rows]
    return []


def _artifact_payload(rows: list[dict[str, Any]], *, sample_limit: int) -> dict[str, Any]:
    sample = rows[:sample_limit]
    return {
        "available": bool(rows),
        "count": len(rows),
        "sample_count": len(sample),
        "sample": sample,
    }


def _artifact_summary(artifacts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for name, payload in artifacts.items():
        payload = payload if isinstance(payload, dict) else {}
        summary[name] = {
            "available": bool(payload.get("available")),
            "count": int(payload.get("count") or 0),
            "sample_count": int(payload.get("sample_count") or 0),
        }
    return summary


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _same_optional(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return True
    return str(left) == str(right)


def _same_optional_lower(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return True
    return str(left).lower() == str(right).lower()


def _same_decimal_optional(left: Any, right: Any) -> bool:
    left_decimal = _decimal_or_none(left)
    right_decimal = _decimal_or_none(right)
    if left_decimal is None or right_decimal is None:
        return True
    return abs(left_decimal - right_decimal) <= Decimal("0.00000001")


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


def _paper_strategy_performance_row(
    strategy: dict[str, Any],
    dashboard: Any,
) -> tuple[dict[str, Any], str | None]:
    dashboard_dict = _ensure_dict(dashboard)
    system = dashboard_dict.get("system")
    system = system if isinstance(system, dict) else {}
    requested_id = strategy.get("id")
    returned_id = _first_present(system.get("strategy_id"), system.get("strategyId"))
    if returned_id is None:
        return {}, "dashboard_missing_strategy_identity"
    if str(returned_id) != str(requested_id):
        return {}, "dashboard_strategy_id_mismatch"
    equity = dashboard_dict.get("equity")
    equity = equity if isinstance(equity, dict) else {}
    performance = dashboard_dict.get("performance")
    performance = performance if isinstance(performance, dict) else {}
    return_pct = _first_present(
        performance.get("total_pnl_pct"),
        performance.get("total_return_pct"),
        performance.get("return_pct"),
        performance.get("pnl_pct"),
        strategy.get("return_pct"),
    )
    if _decimal_or_none(return_pct) is None:
        return {}, "paper_return_metric_unavailable"
    symbols = strategy.get("symbols")
    if isinstance(symbols, str):
        symbols = [symbols]
    return (
        _compact(
            {
                "strategy_id": requested_id,
                "strategy_name": _first_present(system.get("strategy"), strategy.get("name")),
                "status": _first_present(system.get("state"), strategy.get("status")),
                "mode": system.get("mode"),
                "exchange": strategy.get("exchange"),
                "symbols": symbols,
                "timeframe": strategy.get("timeframe"),
                "initial_equity": _decimal_text(
                    _first_present(
                        equity.get("initial"),
                        equity.get("initial_equity"),
                        strategy.get("initial_equity"),
                    )
                ),
                "equity": _decimal_text(
                    _first_present(
                        equity.get("current"),
                        equity.get("current_equity"),
                        strategy.get("equity"),
                    )
                ),
                "total_pnl": _decimal_text(
                    _first_present(
                        performance.get("total_pnl"),
                        performance.get("pnl"),
                        strategy.get("total_pnl"),
                    )
                ),
                "return_pct": _decimal_text(return_pct),
                "max_drawdown_pct": _decimal_text(
                    _first_present(
                        performance.get("max_drawdown_pct"),
                        performance.get("max_drawdown"),
                        strategy.get("max_drawdown_pct"),
                    )
                ),
                "sharpe_ratio": _decimal_text(
                    _first_present(
                        performance.get("sharpe_ratio"),
                        performance.get("sharpe"),
                        strategy.get("sharpe_ratio"),
                    )
                ),
                "uptime": system.get("uptime"),
                "evidence_source": "paper_dashboard",
                "evidence_strategy_id": returned_id,
            }
        ),
        None,
    )


def _paper_performance_gap(
    strategy: dict[str, Any],
    *,
    reason: str,
    detail: str | None = None,
    dashboard: Any = None,
) -> dict[str, Any]:
    dashboard_dict = dashboard if isinstance(dashboard, dict) else {}
    system = dashboard_dict.get("system")
    system = system if isinstance(system, dict) else {}
    return _compact(
        {
            "strategy_id": strategy.get("id"),
            "strategy_name": strategy.get("name"),
            "reason": reason,
            "returned_strategy_id": _first_present(
                system.get("strategy_id"), system.get("strategyId")
            ),
            "detail": detail,
        }
    )


def _paper_monitor_summary(
    dashboard: Any,
    *,
    running_strategies: dict[str, Any],
    strategy_id_filter: int | None,
) -> dict[str, Any]:
    dashboard_dict = _ensure_dict(dashboard)
    system = dashboard_dict.get("system")
    system_dict = system if isinstance(system, dict) else {}
    equity = dashboard_dict.get("equity")
    equity_dict = equity if isinstance(equity, dict) else {}
    performance = dashboard_dict.get("performance")
    performance_dict = performance if isinstance(performance, dict) else {}
    running_items_raw = running_strategies.get("items") if running_strategies else []
    running_items = running_items_raw if isinstance(running_items_raw, list) else []
    listed_count = len(running_items)
    reported_total = running_strategies.get("total") if running_strategies else listed_count
    if not isinstance(reported_total, int):
        try:
            reported_total = int(str(reported_total))
        except (TypeError, ValueError):
            reported_total = listed_count
    is_truncated = reported_total > listed_count
    total_pnl = _decimal_or_none(
        _first_present(
            performance_dict.get("total_pnl_pct"),
            performance_dict.get("total_return_pct"),
            performance_dict.get("pnl_pct"),
        )
    )
    max_drawdown = _decimal_or_none(
        _first_present(
            performance_dict.get("max_drawdown"),
            performance_dict.get("max_drawdown_pct"),
        )
    )
    alerts: list[dict[str, str]] = []
    if total_pnl is not None and total_pnl < 0:
        alerts.append(
            {
                "level": "warning",
                "code": "negative_pnl",
                "message": f"当前 dashboard 策略总收益为负: {_decimal_text(total_pnl)}%",
            }
        )
    if max_drawdown is not None and max_drawdown >= Decimal("10"):
        alerts.append(
            {
                "level": "warning",
                "code": "high_drawdown",
                "message": f"当前 dashboard 策略最大回撤偏高: {_decimal_text(max_drawdown)}%",
            }
        )
    if strategy_id_filter is None and reported_total == 0:
        alerts.append(
            {
                "level": "warning",
                "code": "no_running_strategies",
                "message": "BitPro strategy_search(status=running) 未返回运行中策略。",
            }
        )
    if is_truncated:
        alerts.append(
            {
                "level": "info",
                "code": "truncated_inventory",
                "message": (
                    f"运行策略清单未完全展开: listed_count={listed_count}, "
                    f"reported_total={reported_total}"
                ),
            }
        )
    has_strategy_metrics = all(
        isinstance(item, dict)
        and (
            item.get("total_pnl_pct") is not None
            or item.get("max_drawdown") is not None
            or item.get("max_drawdown_pct") is not None
        )
        for item in running_items
    )
    missing_strategy_metrics = bool(
        strategy_id_filter is None and running_items and not has_strategy_metrics
    )
    if missing_strategy_metrics:
        alerts.append(
            {
                "level": "info",
                "code": "missing_strategy_metrics",
                "message": "运行策略清单缺少逐策略收益/回撤指标。",
            }
        )
    data_gaps: list[str] = []
    if missing_strategy_metrics:
        data_gaps.append(
            "running strategy inventory does not include per-strategy PnL/drawdown metrics"
        )
    if is_truncated:
        data_gaps.append(
            f"running strategy inventory is truncated; listed_count={listed_count} "
            f"reported_total={reported_total}"
        )
    recommended_actions: list[dict[str, str]] = []
    if any(alert["code"] in {"negative_pnl", "high_drawdown"} for alert in alerts):
        recommended_actions.append(
            {
                "action": "inspect_current_dashboard_strategy",
                "message": (
                    "优先检查当前 dashboard 策略 "
                    f"{system_dict.get('strategy_id', 'n/a')} 的成交、事件和权益曲线"
                ),
            }
        )
    if is_truncated:
        recommended_actions.append(
            {
                "action": "fetch_full_running_strategy_inventory",
                "message": "增加分页或缩小过滤条件，补齐全部运行中策略清单。",
            }
        )
    recommended_actions.append(
        {
            "action": "continue_read_only_monitoring",
            "message": "继续只读监控；不要自动暂停、停止或实盘操作",
        }
    )
    return {
        "mode": "read_only",
        "current_dashboard": _compact(
            {
                "strategy_id": system_dict.get("strategy_id"),
                "strategy_name": system_dict.get("strategy"),
                "state": system_dict.get("state"),
                "mode": system_dict.get("mode"),
                "uptime": system_dict.get("uptime"),
                "equity": _decimal_text(equity_dict.get("current")),
                "total_pnl_pct": _decimal_text(total_pnl),
                "max_drawdown_pct": _decimal_text(max_drawdown),
                "sharpe_ratio": _decimal_text(performance_dict.get("sharpe_ratio")),
            }
        ),
        "running_inventory": {
            "listed_count": listed_count,
            "reported_total": reported_total,
            "is_truncated": is_truncated,
            "source_tool": running_strategies.get("source_tool") if running_strategies else None,
        },
        "alerts": alerts,
        "data_gaps": data_gaps,
        "recommended_actions": recommended_actions,
    }


def _extract_paper_event_rows(raw: Any) -> list[dict[str, Any]]:
    return _extract_nested_rows(raw, ("items", "events", "rows", "data", "logs"))


def _extract_paper_equity_rows(raw: Any) -> list[dict[str, Any]]:
    return _extract_nested_rows(
        raw,
        (
            "curve",
            "equity_curve",
            "equityCurve",
            "points",
            "items",
            "rows",
            "data",
            "values",
        ),
    )


def _extract_live_order_rows(raw: Any) -> list[dict[str, Any]]:
    return _extract_nested_rows(
        raw,
        (
            "orders",
            "order_history",
            "orderHistory",
            "items",
            "rows",
            "results",
            "data",
        ),
    )


def _extract_live_strategy_rows(raw: Any) -> list[dict[str, Any]]:
    return _extract_nested_rows(
        raw,
        (
            "strategies",
            "live_strategies",
            "liveStrategies",
            "items",
            "rows",
            "results",
            "data",
        ),
    )


def _extract_nested_rows(raw: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [_ensure_dict(row) for row in raw]
    if not isinstance(raw, dict):
        return []
    sources: list[dict[str, Any]] = []
    queue = [raw]
    seen: set[int] = set()
    for _ in range(3):
        next_queue: list[dict[str, Any]] = []
        for source in queue:
            marker = id(source)
            if marker in seen:
                continue
            seen.add(marker)
            sources.append(source)
            for wrapper in ("data", "result", "payload", "paper", "live"):
                value = source.get(wrapper)
                if isinstance(value, dict):
                    next_queue.append(value)
        queue = next_queue

    for source in sources:
        for key in keys:
            if key not in source:
                continue
            value = source[key]
            rows = _coerce_artifact_rows(value)
            if rows:
                return rows
            if isinstance(value, list):
                return [_ensure_dict(row) for row in value]
    return []


def _live_strategy_item(row: dict[str, Any]) -> dict[str, Any]:
    strategy_id = _first_present(row.get("strategy_id"), row.get("strategyId"), row.get("id"))
    symbols = _first_present(row.get("symbols"), row.get("trade_symbols"), row.get("tradeSymbols"))
    if isinstance(symbols, str):
        symbol_values = [symbols]
    elif isinstance(symbols, list):
        symbol_values = [str(symbol) for symbol in symbols if symbol is not None]
    else:
        symbol_values = []
    return _compact(
        {
            "strategy_id": strategy_id,
            "strategy_name": _first_present(
                row.get("strategy_name"),
                row.get("strategyName"),
                row.get("name"),
            ),
            "status": row.get("status"),
            "workspace_status": _first_present(
                row.get("workspace_status"),
                row.get("workspaceStatus"),
            ),
            "exchange": row.get("exchange"),
            "account_id": _first_present(row.get("account_id"), row.get("accountId")),
            "account_ids": _first_present(row.get("account_ids"), row.get("accountIds")),
            "symbols": symbol_values,
            "market_type": _first_present(row.get("market_type"), row.get("marketType")),
            "total_pnl": _decimal_text(
                _first_present(row.get("total_pnl"), row.get("totalPnl"), row.get("pnl"))
            ),
            "return_pct": _decimal_text(
                _first_present(row.get("return_pct"), row.get("returnPct"), row.get("pnl_pct"))
            ),
            "deployed": row.get("deployed"),
            "deployment_status": _first_present(
                row.get("deployment_status"),
                row.get("deploymentStatus"),
            ),
            "live_subscription_id": _first_present(
                row.get("live_subscription_id"),
                row.get("liveSubscriptionId"),
                row.get("subscription_id"),
            ),
            "updated_at": _first_present(row.get("updated_at"), row.get("updatedAt")),
            "created_at": _first_present(row.get("created_at"), row.get("createdAt")),
        }
    )


def _live_strategy_performance_summary(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    top = strategies[0] if strategies else None
    return _compact(
        {
            "count": len(strategies),
            "top_strategy_id": top.get("strategy_id") if top else None,
            "top_strategy_name": top.get("strategy_name") if top else None,
            "top_return_pct": top.get("return_pct") if top else None,
            "top_total_pnl": top.get("total_pnl") if top else None,
        }
    )


def _live_order_item(row: dict[str, Any]) -> dict[str, Any]:
    order_id = _first_present(
        row.get("order_id"),
        row.get("ordId"),
        row.get("ord_id"),
        row.get("id"),
    )
    timestamp = _timestamp_text(
        _first_present(
            row.get("timestamp"),
            row.get("created_at"),
            row.get("createdAt"),
            row.get("cTime"),
            row.get("uTime"),
            row.get("time"),
            row.get("ts"),
        )
    )
    return _compact(
        {
            "id": order_id,
            "order_id": order_id,
            "client_order_id": _first_present(
                row.get("client_order_id"),
                row.get("clOrdId"),
                row.get("clientOrderId"),
            ),
            "symbol": _first_present(row.get("symbol"), row.get("instId"), row.get("inst_id")),
            "side": row.get("side"),
            "pos_side": _first_present(row.get("posSide"), row.get("pos_side")),
            "status": _first_present(row.get("status"), row.get("state")),
            "type": _first_present(row.get("type"), row.get("order_type"), row.get("ordType")),
            "average": _decimal_text(
                _first_present(row.get("average"), row.get("avgPx"), row.get("avg_price"))
            ),
            "price": _decimal_text(_first_present(row.get("price"), row.get("px"))),
            "amount": _decimal_text(
                _first_present(row.get("amount"), row.get("qty"), row.get("sz"))
            ),
            "filled": _decimal_text(
                _first_present(row.get("filled"), row.get("filled_qty"), row.get("accFillSz"))
            ),
            "fee": _decimal_text(_first_present(row.get("fee"), row.get("fee_amount"))),
            "pnl": _decimal_text(_first_present(row.get("pnl"), row.get("realizedPnl"))),
            "margin_mode": _first_present(row.get("margin_mode"), row.get("tdMode")),
            "timestamp": timestamp,
            "bitpro_source": row.get("bitpro_source"),
            "bitpro_source_label": row.get("bitpro_source_label"),
            "source_strategy_id": row.get("source_strategy_id"),
            "source_strategy_name": row.get("source_strategy_name"),
            "subscription_id": row.get("subscription_id"),
            "signal_event_id": row.get("signal_event_id"),
        }
    )


def _live_order_summary(orders: list[dict[str, Any]]) -> dict[str, Any]:
    latest = orders[0] if orders else None
    return {
        "count": len(orders),
        "latest_order_id": latest.get("order_id") if latest else None,
        "latest_timestamp": latest.get("timestamp") if latest else None,
    }


def _paper_event_item(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = _timestamp_text(
        _first_present(
            row.get("timestamp"),
            row.get("created_at"),
            row.get("event_time"),
            row.get("time"),
            row.get("ts"),
        )
    )
    return _compact(
        {
            "id": _first_present(row.get("id"), row.get("event_id")),
            "strategy_id": row.get("strategy_id"),
            "level": _first_present(row.get("level"), row.get("severity"), row.get("status")),
            "type": _first_present(
                row.get("type"),
                row.get("event_type"),
                row.get("event"),
                row.get("kind"),
                row.get("name"),
            ),
            "message": _first_present(
                row.get("message"),
                row.get("msg"),
                row.get("detail"),
                row.get("error"),
                row.get("reason"),
            ),
            "timestamp": timestamp,
        }
    )


def _paper_event_summary(
    rows: list[dict[str, Any]],
    sample: list[dict[str, Any]],
) -> dict[str, Any]:
    error_count = 0
    for row in rows:
        level = str(row.get("level", "")).casefold()
        event_type = str(row.get("type", "")).casefold()
        message = str(row.get("message", "")).casefold()
        if (
            level in {"error", "critical", "fatal"}
            or "error" in event_type
            or "reject" in event_type
            or "fail" in event_type
            or "error" in message
        ):
            error_count += 1
    latest_at = rows[0].get("timestamp") if rows else None
    return _compact(
        {
            "count": len(rows),
            "sample_count": len(sample),
            "error_count": error_count,
            "latest_event_at": latest_at,
        }
    )


def _paper_equity_point(row: dict[str, Any]) -> dict[str, Any]:
    timestamp = _timestamp_text(
        _first_present(
            row.get("timestamp"),
            row.get("created_at"),
            row.get("time"),
            row.get("ts"),
        )
    )
    return _compact(
        {
            "timestamp": timestamp,
            "equity": _decimal_text(
                _first_present(row.get("equity"), row.get("current_equity"), row.get("value"))
            ),
            "balance": _decimal_text(row.get("balance")),
            "pnl": _decimal_text(_first_present(row.get("pnl"), row.get("profit"))),
            "pnl_pct": _decimal_text(
                _first_present(row.get("pnl_pct"), row.get("return_pct"), row.get("profit_pct"))
            ),
            "drawdown_pct": _decimal_text(
                _first_present(
                    row.get("drawdown_pct"),
                    row.get("drawdown"),
                    row.get("max_drawdown"),
                )
            ),
        }
    )


def _paper_equity_summary(
    rows: list[dict[str, Any]],
    sample: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = rows[-1] if rows else {}
    drawdowns = [
        value for row in rows if (value := _decimal_or_none(row.get("drawdown_pct"))) is not None
    ]
    max_drawdown = max(drawdowns) if drawdowns else None
    return _compact(
        {
            "count": len(rows),
            "sample_count": len(sample),
            "latest_at": latest.get("timestamp"),
            "latest_equity": latest.get("equity"),
            "latest_drawdown_pct": latest.get("drawdown_pct"),
            "max_drawdown_pct": _decimal_text(max_drawdown),
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


def _timestamp_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and any(marker in value for marker in ("T", "-", ":")):
        return value
    try:
        return _timestamp_to_iso(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)


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
