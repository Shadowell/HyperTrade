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
