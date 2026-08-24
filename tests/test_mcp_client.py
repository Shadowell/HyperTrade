"""Sprint-142: standard MCP client layer — caching, retry, breaker, governance.

All resilience semantics are verified against an injected fake transport with
zero network. The production transport (official SDK, Streamable HTTP) is
exercised only for importability.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypertrade.connectors.mcp_client import (
    McpCircuitOpen,
    McpClientError,
    McpClientRegistry,
    McpServerConfig,
    McpToolDescriptor,
    parse_mcp_server_configs,
)


class FakeTransport:
    """Scriptable transport: records calls, raises queued errors."""

    def __init__(
        self,
        *,
        tools: list[McpToolDescriptor] | None = None,
        list_errors: list[Exception] | None = None,
        call_results: dict[str, Any] | Exception | None = None,
    ) -> None:
        self.tools = tools or [
            McpToolDescriptor(
                server="fs",
                name="read_file",
                description="Read a file",
                input_schema={"type": "object", "required": ["path"]},
            ),
            McpToolDescriptor(server="fs", name="write_file", description="Write a file"),
        ]
        self.list_errors = list(list_errors or [])
        self.call_result = call_results
        self.list_calls = 0
        self.call_calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self, server: McpServerConfig) -> list[McpToolDescriptor]:
        self.list_calls += 1
        if self.list_errors:
            raise self.list_errors.pop(0)
        return self.tools

    async def call_tool(
        self, server: McpServerConfig, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.call_calls.append((tool_name, arguments))
        if isinstance(self.call_result, Exception):
            raise self.call_result
        if isinstance(self.call_result, McpClientError):
            raise self.call_result
        return dict(self.call_result or {"ok": True})


def _server(**overrides: Any) -> McpServerConfig:
    defaults: dict[str, Any] = {
        "name": "fs",
        "url": "http://127.0.0.1:9/mcp/",
        "max_retries": 2,
        "breaker_threshold": 3,
        "backoff_seconds": 0.0,
    }
    defaults.update(overrides)
    return McpServerConfig(**defaults)


def _registry(transport: FakeTransport, **kwargs: Any) -> McpClientRegistry:
    sleeps: list[float] = []

    async def _no_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    registry = McpClientRegistry(
        (_server(),),
        transport=transport,
        breaker_cooldown_seconds=60.0,
        sleep=_no_sleep,
        **kwargs,
    )
    registry._sleeps = sleeps  # type: ignore[attr-defined]
    return registry


@pytest.mark.anyio
async def test_discovery_is_cached_until_ttl_or_force_refresh() -> None:
    transport = FakeTransport()
    registry = _registry(transport, discovery_ttl_seconds=300.0)

    first = await registry.list_tools("fs")
    second = await registry.list_tools("fs")
    forced = await registry.list_tools("fs", force_refresh=True)

    assert [tool.name for tool in first] == ["read_file", "write_file"]
    assert second == first
    assert transport.list_calls == 2  # initial + forced refresh only
    assert [tool.name for tool in forced] == ["read_file", "write_file"]


@pytest.mark.anyio
async def test_transport_errors_retry_with_backoff_then_succeed() -> None:
    transport = FakeTransport(list_errors=[ConnectionError("reset"), ConnectionError("reset")])
    registry = _registry(transport)
    registry._servers["fs"] = _server(backoff_seconds=0.05)  # type: ignore[attr-defined]

    tools = await registry.list_tools("fs")

    assert transport.list_calls == 3  # two failures + success
    assert tools
    # Exponential backoff: 0.05 then 0.1.
    assert registry._sleeps == [0.05, 0.1]  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_circuit_opens_after_consecutive_failures_and_half_open_recovers() -> None:
    transport = FakeTransport(
        list_errors=[ConnectionError("down") for _ in range(5)]
    )
    registry = _registry(transport)

    for _ in range(3):
        with pytest.raises((McpClientError, ConnectionError)):
            await registry.list_tools("fs", force_refresh=True)

    with pytest.raises(McpCircuitOpen, match="circuit is open"):
        await registry.list_tools("fs", force_refresh=True)
    assert transport.list_calls == 3  # breaker blocks further transport calls

    # Half-open probe: cooldown elapsed (we use a tiny cooldown here).
    registry._breaker_cooldown = 0.0  # type: ignore[attr-defined]
    transport.list_errors.clear()
    tools = await registry.list_tools("fs", force_refresh=True)

    assert tools
    # Breaker closed again: subsequent calls go straight through.
    await registry.list_tools("fs", force_refresh=True)
    assert transport.list_calls == 5


@pytest.mark.anyio
async def test_tool_level_error_is_structured_and_never_retried() -> None:
    transport = FakeTransport(
        call_results=McpClientError("tool write_file failed: permission denied")
    )
    registry = _registry(transport)

    with pytest.raises(McpClientError, match="permission denied"):
        await registry.call_tool("fs", "write_file", {"path": "/x"})

    assert len(transport.call_calls) == 1  # no retry on tool-level failure


@pytest.mark.anyio
async def test_unknown_tool_invalidates_stale_discovery_cache() -> None:
    transport = FakeTransport(
        call_results=McpClientError("Unknown tool: new_tool")
    )
    registry = _registry(transport)
    await registry.list_tools("fs")
    assert transport.list_calls == 1

    with pytest.raises(McpClientError):
        await registry.call_tool("fs", "new_tool", {})

    await registry.list_tools("fs")
    assert transport.list_calls == 2  # cache was dropped and refreshed


@pytest.mark.anyio
async def test_unconfigured_server_fails_with_actionable_message() -> None:
    registry = _registry(FakeTransport())

    with pytest.raises(McpClientError, match="not configured"):
        await registry.call_tool("nope", "tool", {})


def test_settings_parsing_valid_and_invalid() -> None:
    valid = parse_mcp_server_configs(
        json.dumps(
            [
                {"name": "fs", "url": "http://localhost/mcp/"},
                {"name": "", "url": "http://skipped/"},
                "not-a-dict",
            ]
        )
    )
    assert len(valid) == 1
    assert valid[0].name == "fs"

    assert parse_mcp_server_configs("") == ()
    assert parse_mcp_server_configs("not json") == ()
    assert parse_mcp_server_configs('{"a": 1}') == ()


def test_registry_tool_surface_policies_and_idempotency():
    from hypertrade.tools.registry import ToolRegistry

    registry = ToolRegistry.default()

    discover = registry.get("mcp.discover")
    assert discover.policy.scope == "read"
    assert discover.policy.source_of_truth == "mcp_servers"

    invoke = registry.get("mcp.invoke_tool")
    assert invoke.policy.scope == "research_write"
    assert invoke.policy.idempotency == "required"

    from hypertrade.tools.registry import default_runtime_schemas

    schemas = {
        str(schema["function"]["name"]): schema for schema in default_runtime_schemas()
    }
    props = schemas["mcp_invoke_tool"]["function"]["parameters"]["properties"]
    assert "idempotency_key" in props
    assert {"server", "tool"} <= set(props)
