"""Standard MCP (Model Context Protocol) client layer.

A reusable, transport-injectable client for arbitrary standard MCP servers:
multi-server registration, tools/list discovery with TTL caching, tools/call
for any discovered tool, exponential-backoff retry for transport-class
failures, and a per-server circuit breaker. Tool-level ``isError`` responses
are structured failures and are never retried.

The production transport uses the official ``mcp`` SDK Streamable HTTP
client; tests inject a fake transport, so resilience semantics are verified
without any network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)


class McpClientError(RuntimeError):
    """Structured MCP client failure surfaced to the agent tool surface."""


class McpCircuitOpen(McpClientError):
    """The server breaker is open; fail fast instead of hammering upstream."""


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    url: str
    timeout_seconds: float = 30.0
    auth_header: str = ""
    auth_token: str = ""
    max_retries: int = 2
    breaker_threshold: int = 3
    backoff_seconds: float = 0.05


@dataclass(frozen=True)
class McpToolDescriptor:
    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


def parse_mcp_server_configs(raw: str) -> tuple[McpServerConfig, ...]:
    """Parse the MCP_SERVERS_JSON allowlist; invalid payloads disable the layer."""
    if not raw.strip():
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("MCP_SERVERS_JSON is not valid JSON; MCP layer disabled")
        return ()
    if not isinstance(payload, list):
        logger.warning("MCP_SERVERS_JSON must be an array; MCP layer disabled")
        return ()
    configs: list[McpServerConfig] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip()
        if not name or not url:
            continue
        configs.append(
            McpServerConfig(
                name=name,
                url=url,
                timeout_seconds=float(item.get("timeout_seconds", 30.0)),
                auth_header=str(item.get("auth_header", "")),
                auth_token=str(item.get("auth_token", "")),
                max_retries=max(0, int(item.get("max_retries", 2))),
                breaker_threshold=max(1, int(item.get("breaker_threshold", 3))),
            )
        )
    return tuple(configs)


class McpTransport(Protocol):
    """Async transport boundary so resilience logic is testable without IO."""

    async def list_tools(self, server: McpServerConfig) -> list[McpToolDescriptor]: ...

    async def call_tool(
        self, server: McpServerConfig, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...


def _result_to_dict(tool_name: str, result: Any) -> dict[str, Any]:
    if getattr(result, "isError", False):
        detail = " ".join(
            str(getattr(item, "text", ""))[:300]
            for item in getattr(result, "content", []) or []
            if getattr(item, "text", "")
        )
        raise McpClientError(f"tool {tool_name} failed: {detail[:400]}")
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload = dict(structured)
        if set(payload) == {"result"}:
            return {"result": payload["result"]}
        return payload
    for item in getattr(result, "content", []) or []:
        text = str(getattr(item, "text", ""))
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    raise McpClientError(f"tool {tool_name} returned no structured result")


class SdkMcpTransport:
    """Production transport on the official mcp SDK (Streamable HTTP)."""

    async def list_tools(self, server: McpServerConfig) -> list[McpToolDescriptor]:
        async def _action(session: Any) -> list[McpToolDescriptor]:
            listing = await session.list_tools()
            return [
                McpToolDescriptor(
                    server=server.name,
                    name=str(tool.name),
                    description=str(getattr(tool, "description", "") or ""),
                    input_schema=dict(getattr(tool, "inputSchema", {}) or {}),
                )
                for tool in getattr(listing, "tools", []) or []
            ]

        descriptors: list[McpToolDescriptor] = await self._with_session(server, _action)
        return descriptors

    async def call_tool(
        self, server: McpServerConfig, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        async def _action(session: Any) -> dict[str, Any]:
            result = await session.call_tool(tool_name, arguments=dict(arguments))
            return _result_to_dict(tool_name, result)

        payload: dict[str, Any] = await self._with_session(server, _action)
        return payload

    async def _with_session(
        self,
        server: McpServerConfig,
        action: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        headers: dict[str, str] = {}
        if server.auth_header and server.auth_token:
            headers[server.auth_header] = server.auth_token
        async with (
            httpx.AsyncClient(
                headers=headers, timeout=httpx.Timeout(server.timeout_seconds)
            ) as client,
            streamable_http_client(server.url, http_client=client) as (
                read_stream,
                write_stream,
                _,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            return await action(session)


class _ServerBreaker:
    def __init__(self, threshold: int) -> None:
        self.threshold = threshold
        self.consecutive_failures = 0
        self.opened_at: float | None = None

    def allows_probe(self, *, cooldown_seconds: float) -> bool:
        """True when a call may proceed (closed, or half-open probe due)."""
        if self.opened_at is None:
            return True
        return time.monotonic() - self.opened_at >= cooldown_seconds

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.opened_at = time.monotonic()


class McpClientRegistry:
    """Multi-server standard MCP client with caching, retry and breakers."""

    def __init__(
        self,
        servers: tuple[McpServerConfig, ...] = (),
        *,
        transport: McpTransport | None = None,
        discovery_ttl_seconds: float = 300.0,
        breaker_cooldown_seconds: float = 30.0,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._servers = {server.name: server for server in servers}
        self._transport = transport or SdkMcpTransport()
        self._discovery_ttl = discovery_ttl_seconds
        self._breaker_cooldown = breaker_cooldown_seconds
        self._sleep = sleep or asyncio.sleep
        self._cache: dict[str, tuple[float, list[McpToolDescriptor]]] = {}
        self._breakers = {
            name: _ServerBreaker(server.breaker_threshold)
            for name, server in self._servers.items()
        }

    def server_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._servers))

    def _server(self, name: str) -> McpServerConfig:
        server = self._servers.get(str(name).strip())
        if server is None:
            raise McpClientError(
                f"MCP server {name!r} is not configured; "
                f"configured: {', '.join(self.server_names()) or 'none'}"
            )
        return server

    async def list_tools(
        self, server: str, *, force_refresh: bool = False
    ) -> list[McpToolDescriptor]:
        server_config = self._server(server)
        cached = self._cache.get(server_config.name)
        if (
            not force_refresh
            and cached is not None
            and time.monotonic() - cached[0] < self._discovery_ttl
        ):
            return cached[1]
        descriptors: list[McpToolDescriptor] = await self._call_with_resilience(
            server_config, lambda: self._transport.list_tools(server_config)
        )
        self._cache[server_config.name] = (time.monotonic(), descriptors)
        return descriptors

    async def call_tool(
        self, server: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        server_config = self._server(server)
        try:
            result: dict[str, Any] = await self._call_with_resilience(
                server_config,
                lambda: self._transport.call_tool(server_config, tool_name, dict(arguments)),
            )
            return result
        except McpClientError as exc:
            # An unknown tool usually means the discovery cache is stale; drop
            # it so the next discover sees freshly deployed tools.
            if "unknown tool" in str(exc).lower():
                self._cache.pop(server_config.name, None)
            raise

    async def _call_with_resilience(
        self, server: McpServerConfig, action: Callable[[], Awaitable[Any]]
    ) -> Any:
        breaker = self._breakers[server.name]
        if not breaker.allows_probe(cooldown_seconds=self._breaker_cooldown):
            raise McpCircuitOpen(
                f"MCP server {server.name!r} circuit is open after "
                f"{breaker.consecutive_failures} consecutive failures"
            )
        last_error: Exception | None = None
        for attempt in range(server.max_retries + 1):
            try:
                result = await action()
            except McpClientError:
                # Tool-level failures are structured answers, not transport
                # faults: surface without retry, but count toward the breaker
                # so a consistently broken tool eventually opens the circuit.
                breaker.record_failure()
                raise
            except Exception as exc:  # noqa: BLE001 - transport-class failure
                last_error = exc
                breaker.record_failure()
                if attempt < server.max_retries and breaker.opened_at is None:
                    await self._sleep(server.backoff_seconds * (2**attempt))
                continue
            breaker.record_success()
            return result
        if breaker.opened_at is not None:
            raise McpCircuitOpen(f"MCP server {server.name!r} circuit opened: {last_error}")
        raise McpClientError(
            f"MCP server {server.name!r} call failed after retries: {last_error}"
        )


def run_async(coro: Any) -> Any:
    """Run a coroutine from sync executor threads, whatever the caller context.

    Executor handlers normally run in worker threads without a loop; if a loop
    is already running in this thread, bridge through a dedicated thread so we
    never nest or starve the caller's event loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
