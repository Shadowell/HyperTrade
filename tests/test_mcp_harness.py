"""
Unit Tests for MCP Harness & Tool Governance (mcp_harness.py)
"""

import time

from hypertrade.agent.mcp_harness import (
    MCPConnectionCircuitBreaker,
    MCPToolSchemaTranslator,
    ToolCallPermissionSandboxGuard,
)


def test_mcp_tool_schema_translator():
    complex_schema = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "params": {
                "allOf": [
                    {"type": "object", "properties": {"stop_loss": {"type": "number"}}},
                    {"properties": {"take_profit": {"type": "number"}}},
                ]
            },
        },
    }

    flattened = MCPToolSchemaTranslator.flatten_schema(complex_schema)
    assert "properties" in flattened
    assert flattened["properties"]["params"]["type"] == "object"
    assert "stop_loss" in flattened["properties"]["params"]["properties"]


def test_mcp_connection_circuit_breaker():
    breaker = MCPConnectionCircuitBreaker(failure_threshold=3, cooldown_sec=0.1)
    server = "bitpro_mcp"

    assert breaker.can_execute(server) is True

    # Trigger 3 failures
    breaker.record_failure(server)
    breaker.record_failure(server)
    breaker.record_failure(server)

    # Circuit should now be OPEN
    assert breaker.can_execute(server) is False

    # Wait for cooldown
    time.sleep(0.12)
    # State switches to HALF_OPEN, allows 1 trial
    assert breaker.can_execute(server) is True

    # Record success to close circuit
    breaker.record_success(server)
    assert breaker.can_execute(server) is True


def test_tool_call_permission_sandbox_guard():
    guard = ToolCallPermissionSandboxGuard()

    # L1 Read-Only
    ok, msg = guard.evaluate_permission("market_ticker", {"symbol": "ETH-USDT"})
    assert ok is True

    # L2 Simulated Write
    ok, msg = guard.evaluate_permission("bitpro_paper_dashboard", {})
    assert ok is True

    # L3 Critical Live Write without token
    ok, msg = guard.evaluate_permission("submit_live_order", {"symbol": "BTC-USDT"})
    assert ok is False

    # L3 Critical Live Write with token
    ok, msg = guard.evaluate_permission(
        "submit_live_order", {"symbol": "BTC-USDT", "approval_token": "token_123"}
    )
    assert ok is True
