"""
Unit Tests for DAG Tool Dispatcher & MCP Batch Pipeline Aggregator (tool_pipeline.py)
"""

from typing import Any

from hypertrade.agent.tool_pipeline import (
    MCPBatchPipelineAggregator,
    ToolDependencyGraphDispatcher,
)


def test_tool_dependency_graph_dispatcher():
    execution_order: list[str] = []

    def mock_executor(name: str, args: dict[str, Any]) -> dict[str, Any]:
        execution_order.append(name)
        return {"status": "ok", "tool": name}

    dispatcher = ToolDependencyGraphDispatcher(mock_executor)

    # Mixed batch: 2 read-only tools + 1 write tool
    mixed_batch = [
        ("market_ticker", {"val": 1}),
        ("update_paper_config", {"val": 2}),
        ("market_candles", {"val": 3}),
    ]

    results = dispatcher.dispatch_dag(mixed_batch)
    assert len(results) == 3
    # Read-only tools (market_ticker, market_candles) execute in Stage 0 first
    # Write tool (update_paper_config) executes in Stage 1 last
    assert execution_order[-1] == "update_paper_config"
    assert results[0]["tool"] == "market_ticker"
    assert results[1]["tool"] == "update_paper_config"
    assert results[2]["tool"] == "market_candles"


def test_mcp_batch_pipeline_aggregator():
    aggregator = MCPBatchPipelineAggregator()

    requests = [
        {"mcp_server": "bitpro", "tool_name": "get_ticker", "arguments": {"symbol": "BTC"}},
        {"mcp_server": "bitpro", "tool_name": "get_candles", "arguments": {"symbol": "ETH"}},
        {"mcp_server": "okx", "tool_name": "get_depth", "arguments": {"symbol": "SOL"}},
    ]

    payloads = aggregator.aggregate_requests(requests)
    assert len(payloads) == 2  # 1 bitpro batch + 1 okx batch
    assert payloads[0]["mcp_server"] == "bitpro"
    assert payloads[0]["batch_count"] == 2
    assert len(payloads[0]["payload"]) == 2
