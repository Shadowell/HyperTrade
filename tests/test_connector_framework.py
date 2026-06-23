from __future__ import annotations

import httpx
from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter
from hypertrade.config import Settings
from hypertrade.connectors.bitpro import BitProConnector
from hypertrade.connectors.fixtures import FixtureConnector
from hypertrade.connectors.registry import ConnectorRegistry
from hypertrade.tools.registry import ToolRegistry


def test_connector_registry_exposes_fixture_and_bitpro_without_plaintext_secrets() -> None:
    settings = Settings(
        BITPRO_MCP_API_BASE="http://bitpro.local/api/v2",
        BITPRO_MCP_API_TOKEN="secret-token-should-stay-server-side",
    )
    registry = ConnectorRegistry(
        [
            FixtureConnector(),
            BitProConnector(settings=settings),
        ]
    )

    payload = registry.capabilities_payload()

    assert set(payload["connectors"]) == {"fixture", "bitpro"}
    assert "secret-token-should-stay-server-side" not in repr(payload)
    bitpro = payload["connectors"]["bitpro"]
    assert bitpro["display_name"] == "BitPro MCP"
    assert bitpro["auth"] == {
        "type": "token",
        "configured": True,
        "header": "X-BitPro-MCP-Token",
        "token_env": "BITPRO_MCP_API_TOKEN",
        "token_source": "server_env",
        "secret_redacted": True,
    }
    assert bitpro["health"]["status"] == "not_checked"
    assert "read" in bitpro["supported_scopes"]
    assert "research_backtest_paper_mutation" in bitpro["supported_scopes"]
    market_klines = next(tool for tool in bitpro["tools"] if tool["name"] == "market_klines")
    assert market_klines["connector_id"] == "bitpro"
    assert market_klines["scope"] == "read"
    assert market_klines["safe_read"] is True
    assert market_klines["idempotency_required"] is False
    paper_start = next(tool for tool in bitpro["tools"] if tool["name"] == "paper_start")
    assert paper_start["scope"] == "research_backtest_paper_mutation"
    assert paper_start["safe_read"] is False
    assert paper_start["idempotency_required"] is True


def test_fixture_connector_executes_safe_read_tools_deterministically() -> None:
    registry = ConnectorRegistry([FixtureConnector()])

    result = registry.execute_read(
        "fixture",
        "fixture_echo",
        {"message": "hello connector"},
    )

    assert result == {
        "status": "ok",
        "connector_id": "fixture",
        "tool": "fixture_echo",
        "message": "hello connector",
        "source": "fixture_connector",
    }


def test_bitpro_connector_uses_existing_adapter_for_safe_reads() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/v2/system/health":
            return httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
        if request.url.path == "/api/v2/market/klines":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "timestamp": "2026-06-23T00:00:00Z",
                            "open": "100",
                            "high": "105",
                            "low": "99",
                            "close": "104",
                            "volume": "123",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    settings = Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2")
    client = BitProMcpClient(
        settings=settings,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    connector = BitProConnector(
        settings=settings,
        adapter=BitProToolAdapter(client),
    )

    result = connector.execute_read_tool(
        "market_klines",
        {"symbol": "ETH", "timeframe": "1H", "limit": 1},
    )

    assert result["connector_id"] == "bitpro"
    assert result["tool"] == "market_klines"
    assert result["result"]["status"] == "ok"
    assert result["result"]["market"]["symbol"] == "ETH/USDT:USDT"
    assert seen == ["/api/v2/system/health", "/api/v2/market/klines"]


def test_tool_registry_marks_bitpro_tools_with_connector_origin() -> None:
    registry = ToolRegistry.default()

    market_klines = registry.get("bitpro.market_klines")
    market_summary = registry.get("market.summary")

    assert market_klines.connector_origin == {
        "connector_id": "bitpro",
        "tool": "market_klines",
    }
    assert market_summary.connector_origin is None
