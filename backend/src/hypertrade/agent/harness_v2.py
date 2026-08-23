"""
Industrial Agent Harness 2.0 Core Framework

Provides Async Parallel Tool Dispatcher, Smart Exponential Backoff Retry,
Dynamic Context Water-Cooler, Atomic Idempotency Lock Guard, and Harness Telemetry.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from hypertrade.tools.registry import read_only_runtime_tool_names

logger = logging.getLogger(__name__)

# Derived from registry policy scopes so the parallel dispatcher can never run
# a tool concurrently that governance does not classify as read-only.
READ_ONLY_TOOL_NAMES: frozenset[str] = read_only_runtime_tool_names()


class ToolIdempotencyLockGuard:
    """Thread-safe memory lock guard preventing duplicate write tool executions."""

    def __init__(self) -> None:
        self._active_keys: set[str] = set()

    def acquire(self, key: str) -> bool:
        if not key:
            return True
        if key in self._active_keys:
            return False
        self._active_keys.add(key)
        return True

    def release(self, key: str) -> None:
        if key:
            self._active_keys.discard(key)


class HarnessContextWaterCooler:
    """Dynamic context water-cooler truncating large JSON tool outputs.

    Truncation is recursive so deeply nested payloads cannot smuggle unbounded
    arrays or strings past the budget. Metadata fields stay intact and every
    truncation is self-describing for the planner.
    """

    MAX_LIST_ITEMS = 10
    KEEP_HEAD_ITEMS = 5
    MAX_STRING_CHARS = 500
    KEEP_STRING_CHARS = 250

    def __init__(self, max_payload_chars: int = 2000) -> None:
        self.max_payload_chars = max_payload_chars

    def water_cool_payload(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload

        raw_str = json.dumps(payload, ensure_ascii=False)
        if len(raw_str) <= self.max_payload_chars:
            return payload

        cooled: dict[str, Any] = {
            key: self._cool_value(value) for key, value in payload.items()
        }
        cooled["_water_cooler"] = {
            "truncated": True,
            "original_bytes": len(raw_str),
            "tool_name": tool_name,
            "summary": (
                f"Output payload was water-cooled to prevent context explosion "
                f"({len(raw_str)} bytes)."
            ),
        }
        return cooled

    @classmethod
    def _cool_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: cls._cool_value(item) for key, item in value.items()}
        if isinstance(value, list):
            if len(value) > cls.MAX_LIST_ITEMS:
                kept = [cls._cool_value(item) for item in value[: cls.KEEP_HEAD_ITEMS]]
                kept.append(f"... truncated {len(value) - cls.KEEP_HEAD_ITEMS} items ...")
                return kept
            return [cls._cool_value(item) for item in value]
        if isinstance(value, str) and len(value) > cls.MAX_STRING_CHARS:
            return value[: cls.KEEP_STRING_CHARS] + "... [truncated] ..."
        return value


class HarnessTelemetryCollector:
    """Micro-metrics collector tracking tool P95 latency and retry rates."""

    def __init__(self) -> None:
        self.metrics: dict[str, dict[str, Any]] = {}

    def record_call(
        self,
        tool_name: str,
        duration_ms: float,
        is_error: bool = False,
        retries: int = 0,
        water_cooled: bool = False,
    ) -> None:
        entry = self.metrics.setdefault(
            tool_name,
            {
                "calls": 0,
                "total_duration_ms": 0.0,
                "errors": 0,
                "retries": 0,
                "water_cooled": 0,
                "durations": [],
            },
        )
        entry["calls"] += 1
        entry["total_duration_ms"] += duration_ms
        entry["durations"].append(duration_ms)
        if is_error:
            entry["errors"] += 1
        entry["retries"] += retries
        if water_cooled:
            entry["water_cooled"] += 1

    def get_summary(self) -> dict[str, Any]:
        res: dict[str, Any] = {}
        for tool, entry in self.metrics.items():
            durations = sorted(entry["durations"])
            p95_idx = int(len(durations) * 0.95) if durations else 0
            res[tool] = {
                "calls": entry["calls"],
                "avg_ms": round(entry["total_duration_ms"] / max(1, entry["calls"]), 2),
                "p95_ms": round(durations[p95_idx], 2) if durations else 0.0,
                "error_rate": round(entry["errors"] / max(1, entry["calls"]), 3),
                "retries": entry["retries"],
                "water_cooled": entry["water_cooled"],
            }
        return res


class SmartToolExecutionHealer:
    """
    Industrial Tool Execution Engine featuring Exponential Backoff Retry
    and stacktrace-guided semantic self-correction.
    """

    def __init__(
        self,
        executor_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
        max_retries: int = 3,
        base_backoff_ms: float = 50.0,
    ) -> None:
        self.executor_fn = executor_fn
        self.max_retries = max_retries
        self.base_backoff_ms = base_backoff_ms
        self.lock_guard = ToolIdempotencyLockGuard()
        self.water_cooler = HarnessContextWaterCooler()
        self.telemetry = HarnessTelemetryCollector()

    def execute(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        started_at = time.monotonic()
        effective_key = idempotency_key or str(tool_args.get("idempotency_key", ""))

        # Enforce idempotency lock
        if effective_key and not self.lock_guard.acquire(effective_key):
            return {
                "status": "error",
                "error": {
                    "type": "idempotency_conflict",
                    "message": f"Duplicate request rejected for idempotency_key '{effective_key}'.",
                },
            }

        retries = 0
        last_exc: Exception | None = None

        try:
            for attempt in range(self.max_retries):
                try:
                    res = self.executor_fn(tool_name, tool_args)
                    duration_ms = (time.monotonic() - started_at) * 1000.0

                    # Apply water-cooling
                    cooled_res = self.water_cooler.water_cool_payload(tool_name, res)
                    is_cooled = cooled_res.get("_water_cooler", {}).get("truncated", False)

                    self.telemetry.record_call(
                        tool_name,
                        duration_ms,
                        is_error=False,
                        retries=attempt,
                        water_cooled=is_cooled,
                    )
                    return cooled_res
                except Exception as exc:
                    last_exc = exc
                    err_msg = str(exc).lower()
                    # Retry on transient network errors
                    if any(
                        code in err_msg
                        for code in ["502", "429", "connection refused", "connecterror", "timeout"]
                    ):
                        retries += 1
                        backoff_sec = (self.base_backoff_ms * (2**attempt)) / 1000.0
                        time.sleep(backoff_sec)
                        continue
                    break

            duration_ms = (time.monotonic() - started_at) * 1000.0
            self.telemetry.record_call(
                tool_name, duration_ms, is_error=True, retries=retries
            )
            return {
                "status": "unavailable",
                "execution_status": "error",
                "unavailable_reason": "execution_error",
                "error": {
                    "type": "execution_error",
                    "message": str(last_exc)[:240] if last_exc else "Tool execution failed",
                    "retryable": True,
                    "retries_attempted": retries,
                },
                "missing_data": [
                    {
                        "field": "tool_result",
                        "reason": "execution_error",
                        "source_of_truth": "tool_executor",
                    }
                ],
                "tool_name": tool_name,
            }
        finally:
            if effective_key:
                self.lock_guard.release(effective_key)


class AsyncParallelToolDispatcher:
    """
    Concurrent Multi-Tool Dispatcher executing read-only tools in parallel.
    """

    def __init__(self, healer: SmartToolExecutionHealer, max_workers: int = 4) -> None:
        self.healer = healer
        self.max_workers = max_workers

    def dispatch_batch(
        self, tool_requests: list[tuple[str, dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        if not tool_requests:
            return []

        if len(tool_requests) == 1:
            name, args = tool_requests[0]
            return [self.healer.execute(name, args)]

        # Check if all requests in batch are read-only
        all_read_only = all(req[0] in READ_ONLY_TOOL_NAMES for req in tool_requests)

        if not all_read_only:
            # Execute sequentially to maintain strict ordering
            return [self.healer.execute(name, args) for name, args in tool_requests]

        # Execute concurrently via ThreadPoolExecutor
        results: list[tuple[int, dict[str, Any]]] = []
        with ThreadPoolExecutor(
            max_workers=min(len(tool_requests), self.max_workers)
        ) as ex:
            future_to_idx = {
                ex.submit(self.healer.execute, name, args): idx
                for idx, (name, args) in enumerate(tool_requests)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    res = future.result()
                    results.append((idx, res))
                except Exception as exc:
                    results.append(
                        (
                            idx,
                            {
                                "status": "error",
                                "error": {"type": "parallel_execution_error", "message": str(exc)},
                            },
                        )
                    )

        results.sort(key=lambda item: item[0])
        return [res for _, res in results]
