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


def test_bitpro_capabilities_label_live_flag_as_mcp_gate() -> None:
    client = BitProMcpClient(
        settings=Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(
                    AssertionError(f"capabilities should stay local: {request.url}")
                )
            )
        ),
    )

    capabilities = client.call_tool("bitpro_capabilities", {})

    assert capabilities["live_trading_enabled"] is False
    assert capabilities["live_trading_enabled_scope"] == "hypertrade_mcp_live_write_gate"
    assert "not the BitPro runtime mode" in capabilities["live_trading_enabled_note"]
    assert "write/order tools" in capabilities["live_trading_enabled_note"]


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


def test_bitpro_backtest_list_results_filters_total_return_with_offset_pagination() -> None:
    seen: list[dict[str, Any]] = []
    first_page = [
        {
            "id": 161,
            "strategy_id": 178,
            "status": "completed",
            "start_date": "2024-01-01",
            "end_date": "2026-05-15",
            "created_at": "2026-05-15 19:57:11",
            "timeframe": "1d",
            "total_return": 305.53878586955756,
            "annual_return": 80.6615,
            "max_drawdown": 30.4763,
            "sharpe_ratio": 1.1422,
            "win_rate": 87.5,
            "trade_count": 8,
        },
        *[
            {
                "id": 1000 + index,
                "strategy_id": 300 + index,
                "status": "completed",
                "total_return": 10 - index,
                "trade_count": index,
            }
            for index in range(19)
        ],
    ]
    second_page = [
        {
            "id": 193,
            "strategy_id": 162,
            "status": "completed",
            "start_date": "2025-06-08",
            "end_date": "2026-06-07",
            "created_at": "2026-06-08 11:13:48",
            "timeframe": "1h",
            "total_return": 141.83713784801657,
            "annual_return": 142.4246,
            "max_drawdown": 14.5667,
            "sharpe_ratio": 0.3969,
            "win_rate": 50.63,
            "trade_count": 239,
        }
    ]

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
        if request.url.path == "/api/v2/backtest/results":
            offset = int(request.url.params.get("offset", "0"))
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "items": first_page if offset == 0 else second_page,
                        "total": 21,
                    },
                },
            )
        if request.url.path == "/api/v2/strategies/162":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": 162,
                        "name": "[合约][1H][CTA] ETH · Heikin Ashi趋势跟踪低频版 · 100U",
                    },
                },
            )
        if request.url.path == "/api/v2/strategies/178":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": 178,
                        "name": "[合约][1D][CTA] ETH · Donchian89/EMA89趋势跟踪稳健版 · 100U",
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

    result = adapter.backtest_list_results(min_total_return_pct=100, limit=40)

    assert result["status"] == "ok"
    assert result["filter"]["metric"] == "total_return_pct"
    assert result["result_count"] == 2
    assert result["raw_result_count"] == 21
    assert [row["id"] for row in result["results"]] == [161, 193]
    assert result["results"][0]["strategy_name"] == (
        "[合约][1D][CTA] ETH · Donchian89/EMA89趋势跟踪稳健版 · 100U"
    )
    assert result["results"][0]["total_return_pct"] == "305.53878586955756"
    assert result["results"][1]["strategy_name"] == (
        "[合约][1H][CTA] ETH · Heikin Ashi趋势跟踪低频版 · 100U"
    )
    assert result["results"][1]["total_return_pct"] == "141.83713784801657"
    assert [call["tool"] for call in result["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "backtest_list_results",
        "backtest_list_results",
        "strategy_get",
        "strategy_get",
    ]
    assert seen[:3] == [
        {"method": "GET", "path": "/api/v2/system/health", "query": {}},
        {
            "method": "GET",
            "path": "/api/v2/backtest/results",
            "query": {
                "offset": "0",
                "limit": "20",
                "status": "completed",
                "sort_by": "return",
                "sort_order": "desc",
            },
        },
        {
            "method": "GET",
            "path": "/api/v2/backtest/results",
            "query": {
                "offset": "20",
                "limit": "20",
                "status": "completed",
                "sort_by": "return",
                "sort_order": "desc",
            },
        },
    ]


def test_bitpro_backtest_get_result_normalizes_artifacts() -> None:
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
        if request.url.path == "/api/v2/backtest/result/196":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": 196,
                        "strategy_id": 293,
                        "status": "completed",
                        "start_date": "2026-05-10",
                        "end_date": "2026-06-09",
                        "symbol": "ETH/USDT:USDT",
                        "timeframe": "1h",
                        "metrics": {
                            "total_return": 4.044128,
                            "max_drawdown": 1.4438,
                            "sharpe_ratio": 0.8029,
                            "win_rate": 63.64,
                            "trade_count": 11,
                        },
                        "equity_curve": [
                            {"timestamp": "2026-05-10T14:00:00Z", "equity": 10000},
                            {"timestamp": "2026-05-11T14:00:00Z", "equity": 10120},
                            {"timestamp": "2026-05-12T14:00:00Z", "equity": 10404.41},
                        ],
                        "trades": [
                            {"id": 1, "symbol": "ETH/USDT:USDT", "side": "long", "pnl": 120.5},
                            {"id": 2, "symbol": "ETH/USDT:USDT", "side": "short", "pnl": 84.2},
                            {"id": 3, "symbol": "ETH/USDT:USDT", "side": "long", "pnl": -12.0},
                        ],
                        "orders": [{"id": "ord_1", "status": "filled"}],
                        "fills": [{"id": "fill_1", "price": 2500.0, "qty": 0.1}],
                        "drawdown_series": [
                            {"timestamp": "2026-05-11T14:00:00Z", "drawdown_pct": 0.2},
                            {"timestamp": "2026-05-12T14:00:00Z", "drawdown_pct": 1.4438},
                        ],
                    },
                },
            )
        if request.url.path == "/api/v2/strategies/293":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "id": 293,
                        "name": "[合约][1H][CTA] ETH · Agent EMA ATR 回撤 · 100U",
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

    result = adapter.backtest_get_result(backtest_id=196, sample_limit=2)

    assert result["status"] == "ok"
    assert result["result"]["id"] == 196
    assert result["result"]["strategy_name"] == (
        "[合约][1H][CTA] ETH · Agent EMA ATR 回撤 · 100U"
    )
    assert result["result"]["metrics"]["total_return_pct"] == "4.044128"
    assert result["artifact_summary"] == {
        "equity_curve": {"available": True, "count": 3, "sample_count": 2},
        "trades": {"available": True, "count": 3, "sample_count": 2},
        "orders": {"available": True, "count": 1, "sample_count": 1},
        "fills": {"available": True, "count": 1, "sample_count": 1},
        "drawdown_series": {"available": True, "count": 2, "sample_count": 2},
    }
    assert result["artifacts"]["equity_curve"]["sample"] == [
        {"timestamp": "2026-05-10T14:00:00Z", "equity": 10000},
        {"timestamp": "2026-05-11T14:00:00Z", "equity": 10120},
    ]
    assert [call["tool"] for call in result["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "backtest_get_result",
        "strategy_get",
    ]
    assert seen == [
        {"method": "GET", "path": "/api/v2/system/health", "query": {}},
        {"method": "GET", "path": "/api/v2/backtest/result/196", "query": {}},
        {"method": "GET", "path": "/api/v2/strategies/293", "query": {}},
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
