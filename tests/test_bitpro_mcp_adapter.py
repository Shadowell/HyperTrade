from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
from hypertrade.backtest.service import BacktestService
from hypertrade.bitpro.mcp import BitProMcpClient, BitProMcpError, BitProToolAdapter
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.strategy.sdk import Candle


def test_bitpro_adapter_calls_capabilities_health_then_market_klines() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.url.params),
                "token": request.headers.get("x-bitpro-mcp-token", ""),
            }
        )
        if request.url.path == "/api/v2/system/health":
            return httpx.Response(
                200,
                json={"success": True, "data": {"status": "healthy", "version": "bitpro-test"}},
            )
        if request.url.path == "/api/v2/market/klines":
            return httpx.Response(200, json={"success": True, "data": _bitpro_klines(12)})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = BitProMcpClient(
        settings=Settings(
            BITPRO_MCP_API_BASE="http://bitpro.local/api/v2",
            BITPRO_MCP_API_TOKEN="test-token",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = BitProToolAdapter(client).market_klines(symbol="ETH", timeframe="1H", limit=12)

    assert result["status"] == "ok"
    assert result["contract_version"] == "bitpro-mcp-v1"
    assert result["health"]["status"] == "healthy"
    assert [call["tool"] for call in result["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "market_klines",
    ]
    assert result["market"]["symbol"] == "ETH/USDT:USDT"
    assert result["market"]["timeframe"] == "1h"
    assert len(result["candles"]) == 12
    assert seen == [
        {
            "method": "GET",
            "path": "/api/v2/system/health",
            "query": {},
            "token": "test-token",
        },
        {
            "method": "GET",
            "path": "/api/v2/market/klines",
            "query": {
                "exchange": "okx",
                "symbol": "ETH/USDT:USDT",
                "timeframe": "1h",
                "limit": "12",
            },
            "token": "test-token",
        },
    ]


def test_bitpro_mcp_client_rejects_live_write_tools_before_http() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"live write tool should not call HTTP: {request.url}")

    client = BitProMcpClient(
        settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(PermissionError, match="live write"):
        client.call_tool("trading_futures_order", {"symbol": "ETH/USDT:USDT"})


def test_bitpro_mcp_client_allows_research_backtest_and_paper_writes() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "json": json_loads(request.content),
            }
        )
        return httpx.Response(200, json={"success": True, "data": {"ok": True}})

    client = BitProMcpClient(
        settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.call_tool(
        "strategy_create",
        {
            "name": "ETH breakout",
            "script_content": "class Strategy: pass",
            "description": "research draft",
            "symbols": ["ETH/USDT:USDT"],
        },
    ) == {"ok": True}
    assert client.call_tool(
        "strategy_update",
        {
            "strategy_id": 42,
            "name": "[合约][1H][CTA] ETH · EMA ATR趋势回撤 · 10000U",
            "description": "rename to canonical BitPro display name",
            "config": {"strategy_source": "db_script"},
            "symbols": ["ETH/USDT:USDT"],
        },
    ) == {"ok": True}
    assert client.call_tool(
        "backtest_start_job",
        {
            "strategy_id": 42,
            "start_date": "2026-06-01",
            "end_date": "2026-06-08",
            "initial_capital": 10000,
        },
    ) == {"ok": True}
    assert client.call_tool("paper_start", {"strategy_id": 7}) == {"ok": True}

    assert seen == [
        {
            "method": "POST",
            "path": "/api/v2/strategies",
            "json": {
                "name": "ETH breakout",
                "script_content": "class Strategy: pass",
                "description": "research draft",
                "config": {},
                "exchange": "okx",
                "symbols": ["ETH/USDT:USDT"],
            },
        },
        {
            "method": "PUT",
            "path": "/api/v2/strategies/42",
            "json": {
                "name": "[合约][1H][CTA] ETH · EMA ATR趋势回撤 · 10000U",
                "description": "rename to canonical BitPro display name",
                "config": {"strategy_source": "db_script"},
                "symbols": ["ETH/USDT:USDT"],
            },
        },
        {
            "method": "POST",
            "path": "/api/v2/backtest/run_job",
            "json": {
                "strategy_id": 42,
                "exchange": "okx",
                "timeframe_mode": "strategy",
                "start_date": "2026-06-01",
                "end_date": "2026-06-08",
                "initial_capital": 10000,
            },
        },
        {
            "method": "POST",
            "path": "/api/v2/live/start",
            "json": {"instance_id": 7},
        },
    ]


def test_bitpro_adapter_can_orchestrate_strategy_backtest_and_paper_steps() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json_loads(request.content)
        seen.append({"method": request.method, "path": request.url.path, "json": body})
        if request.url.path == "/api/v2/system/health":
            return httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
        if request.url.path == "/api/v2/agent/generate_strategy":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"name": "ETH breakout", "script_content": "class S: pass"},
                },
            )
        if request.url.path == "/api/v2/strategies":
            return httpx.Response(200, json={"success": True, "data": {"id": 42}})
        if request.url.path == "/api/v2/strategies/42":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": 42,
                        "name": "[合约][1H][CTA] ETH · EMA ATR趋势回撤 · 10000U",
                    },
                },
            )
        if request.url.path == "/api/v2/backtest/run_job":
            return httpx.Response(200, json={"success": True, "data": {"job_id": "job_1"}})
        if request.url.path == "/api/v2/live/configure":
            return httpx.Response(200, json={"success": True, "data": {"instance_id": 7}})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    adapter = BitProToolAdapter(
        BitProMcpClient(
            settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )

    generated = adapter.strategy_generate(prompt="ETH trend breakout", symbol="ETH", timeframe="1H")
    created = adapter.strategy_create(
        name="ETH breakout",
        script_content="class S: pass",
        description="research draft",
        symbols=["ETH"],
    )
    updated = adapter.strategy_update(
        strategy_id=42,
        name="[合约][1H][CTA] ETH · EMA ATR趋势回撤 · 10000U",
        description="rename to canonical BitPro display name",
        config={"strategy_source": "db_script"},
        symbols=["ETH/USDT:USDT"],
    )
    backtest = adapter.backtest_start_job(
        strategy_id=42,
        start_date="2026-06-01",
        end_date="2026-06-08",
        symbol="ETH",
        timeframe="1H",
    )
    paper = adapter.paper_configure(strategy_id=42, initial_equity=10000)

    assert generated["strategy"]["script_content"] == "class S: pass"
    assert created["strategy"]["id"] == 42
    assert updated["strategy"]["name"] == "[合约][1H][CTA] ETH · EMA ATR趋势回撤 · 10000U"
    assert [call["tool"] for call in updated["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "strategy_update",
    ]
    assert backtest["job"]["job_id"] == "job_1"
    assert paper["paper"]["instance_id"] == 7
    assert [call["tool"] for call in paper["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "paper_configure",
    ]
    assert seen[-1]["json"] == {
        "strategy_type": "42",
        "initial_equity": 10000.0,
        "exchange": "okx",
        "dry_run": True,
        "loop_interval": 60,
    }


def test_bitpro_paper_dashboard_adds_running_strategy_inventory() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.url.params),
            }
        )
        if request.url.path == "/api/v2/system/health":
            return httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
        if request.url.path == "/api/v2/live/dashboard":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "system": {
                            "state": "running",
                            "mode": "paper",
                            "strategy_id": 105,
                            "strategy": "[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U",
                        },
                        "equity": {"current": 106.08},
                        "performance": {"total_pnl_pct": 6.08, "sharpe_ratio": 1.6},
                    },
                },
            )
        if request.url.path == "/api/v2/strategies":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "id": 105,
                                "name": "[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U",
                                "status": "running",
                                "exchange": "okx",
                                "symbols": ["SOL/USDT:USDT"],
                            },
                            {
                                "id": 293,
                                "name": "[合约][1H][CTA] ETH · Agent EMA ATR 回撤 · 100U",
                                "status": "running",
                                "exchange": "okx",
                                "symbols": ["ETH/USDT:USDT"],
                            },
                        ],
                        "total": 2,
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    adapter = BitProToolAdapter(
        BitProMcpClient(
            settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )

    result = adapter.paper_dashboard()

    assert result["paper_scope"]["dashboard_scope"] == "current_instance"
    assert result["paper_scope"]["current_strategy_id"] == 105
    assert result["paper_scope"]["running_strategy_count"] == 2
    assert result["running_strategies"]["items"][1]["id"] == 293
    assert [call["tool"] for call in result["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "paper_dashboard",
        "strategy_search",
    ]
    assert seen == [
        {"method": "GET", "path": "/api/v2/system/health", "query": {}},
        {"method": "GET", "path": "/api/v2/live/dashboard", "query": {}},
        {
            "method": "GET",
            "path": "/api/v2/strategies",
            "query": {"page": "1", "per_page": "18", "status": "running"},
        },
    ]


def test_bitpro_paper_dashboard_explicit_strategy_keeps_filtered_scope() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": dict(request.url.params),
            }
        )
        if request.url.path == "/api/v2/system/health":
            return httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
        if request.url.path == "/api/v2/live/dashboard":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "system": {
                            "state": "running",
                            "mode": "paper",
                            "strategy_id": 105,
                            "strategy": "SOL paper",
                        }
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    adapter = BitProToolAdapter(
        BitProMcpClient(
            settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )

    result = adapter.paper_dashboard(strategy_id=105)

    assert result["paper_scope"]["dashboard_scope"] == "filtered_strategy"
    assert result["paper_scope"]["strategy_id_filter"] == 105
    assert result["running_strategies"] == {}
    assert [call["tool"] for call in result["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "paper_dashboard",
    ]
    assert seen == [
        {"method": "GET", "path": "/api/v2/system/health", "query": {}},
        {"method": "GET", "path": "/api/v2/live/dashboard", "query": {"strategy_id": "105"}},
    ]


def test_bitpro_mcp_client_wraps_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = BitProMcpClient(
        settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(BitProMcpError) as exc_info:
        client.call_tool("bitpro_health", {})

    assert exc_info.value.status_code is None
    assert "bitpro_health request failed" in str(exc_info.value)


def test_backtest_service_can_use_bitpro_mcp_market_klines() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    adapter = FakeBitProAdapter(_strategy_candles(24))

    result = BacktestService(
        db,
        settings=Settings(),
        bitpro_adapter=adapter,
    ).run(
        strategy_key="momentum_breakout_v1",
        candle_source="bitpro_mcp",
        symbol="ETH",
        bar="1H",
        candle_limit=24,
    )

    assert result["status"] == "completed"
    assert result["report_json"]["data_source"] == "bitpro_mcp_market_klines"
    assert result["report_json"]["inst_id"] == "ETH-USDT-SWAP"
    assert result["report_json"]["bar"] == "1H"
    assert result["report_json"]["candle_count"] == 24
    assert result["report_json"]["bitpro_tool_calls"] == [
        "bitpro_capabilities",
        "bitpro_health",
        "market_klines",
    ]
    assert adapter.requests == [{"symbol": "ETH", "timeframe": "1H", "limit": 24}]


class FakeBitProAdapter:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.requests: list[dict[str, Any]] = []
        self.last_tool_calls = [
            {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
            {"tool": "bitpro_health", "status": "success", "parameters": {}},
            {"tool": "market_klines", "status": "success", "parameters": {}},
        ]

    def fetch_candles(self, *, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        self.requests.append({"symbol": symbol, "timeframe": timeframe, "limit": limit})
        return self.candles


def _bitpro_klines(count: int) -> list[dict[str, Any]]:
    base_ts = 1_780_272_000_000
    return [
        {
            "timestamp": base_ts + index * 3_600_000,
            "open": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
            "close": 100 + index,
            "volume": 1000 + index,
        }
        for index in range(count)
    ]


def _strategy_candles(count: int) -> list[Candle]:
    return [
        Candle(
            timestamp=f"2026-06-01T{index:02d}:00:00+00:00",
            open=Decimal(str(100 + index)),
            high=Decimal(str(101 + index)),
            low=Decimal(str(99 + index)),
            close=Decimal(str(100 + index)),
            volume=Decimal(str(1000 + index)),
        )
        for index in range(count)
    ]


def json_loads(content: bytes) -> dict[str, Any]:
    if not content:
        return {}
    import json

    value = json.loads(content.decode("utf-8"))
    return value if isinstance(value, dict) else {"value": value}
