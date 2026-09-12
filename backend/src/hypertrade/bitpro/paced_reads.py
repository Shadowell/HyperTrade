"""Conservative read budget for hourly diagnostics; never retry a mutation."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

from hypertrade.bitpro.mcp import READ_TOOL_ENDPOINTS, BitProMcpClient, BitProMcpError


class PacedReadClient(BitProMcpClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._read_lock = Lock()
        self._next_read_at = 0.0
        self._health_until = 0.0
        self._cached_health: dict[str, Any] | None = None

    def call_tool(self, tool_name: str, parameters: dict[str, Any] | None = None) -> Any:
        with self._read_lock:
            return self._read(tool_name, parameters)

    def _read(self, tool_name: str, parameters: dict[str, Any] | None) -> Any:
        if tool_name == "bitpro_capabilities":
            return super().call_tool(tool_name, parameters)
        if tool_name not in READ_TOOL_ENDPOINTS:
            raise PermissionError("诊断客户端只允许读取，不允许交易或研究写操作")
        if (
            tool_name == "bitpro_health"
            and self._cached_health is not None
            and time.monotonic() < self._health_until
        ):
            return {**self._cached_health, "cached": True}
        for attempt in range(4):
            delay = self._next_read_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next_read_at = time.monotonic() + 1.1
            try:
                result = super().call_tool(tool_name, parameters)
            except BitProMcpError as exc:
                if exc.status_code != 429 or attempt == 3:
                    raise
                time.sleep(5 * (attempt + 1))
                continue
            if tool_name == "bitpro_health" and isinstance(result, dict):
                self._cached_health = result
                self._health_until = time.monotonic() + 30
            return result
        raise RuntimeError("read retry exhausted")
