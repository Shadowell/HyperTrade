from __future__ import annotations

import httpx
from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter, bitpro_capabilities
from hypertrade.config import Settings
from hypertrade.connectors.bitpro import BitProConnector
from strategy_evidence_fixtures import return_series_payload


def test_strategy_evidence_tools_are_additive_safe_reads() -> None:
    capabilities = bitpro_capabilities()
    expected = {
        "strategy_return_series": "/strategy-evidence/return-series",
        "strategy_return_matrix": "/strategy-evidence/aligned-return-matrix",
        "strategy_execution_quality": "/strategy-evidence/execution-quality",
    }
    assert all(name in capabilities["tool_groups"]["read"] for name in expected)
    assert {
        name: capabilities["tool_endpoints"][name]["path"] for name in expected
    } == expected


def test_connector_dispatches_bounded_return_series_as_read_only() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/v2/system/health":
            return httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
        if request.url.path == "/api/v2/strategy-evidence/return-series":
            assert request.url.params["limit"] == "500"
            return httpx.Response(200, json={"success": True, "data": return_series_payload()})
        raise AssertionError(f"unexpected connector request: {request.url}")

    settings = Settings(BITPRO_MCP_API_BASE="http://bitpro.local/api/v2")
    client = BitProMcpClient(
        settings=settings,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    connector = BitProConnector(settings=settings, adapter=BitProToolAdapter(client))
    result = connector.execute_read_tool(
        "strategy_return_series",
        {"source_layer": "backtest", "source_id": "7", "limit": 500},
    )

    assert result["result"]["schema_version"] == "strategy_return_series.v1"
    assert seen == [
        ("GET", "/api/v2/system/health"),
        ("GET", "/api/v2/strategy-evidence/return-series"),
    ]
    descriptor = next(
        item for item in connector.list_tools() if item.name == "strategy_return_series"
    )
    assert descriptor.safe_read is True
    assert descriptor.requires_approval is False
