"""
DAG Tool Dispatcher & MCP Batch Pipeline Aggregator Subsystem

Provides Tool Dependency Graph Dispatcher for stage-partitioned parallel/sequential execution,
and MCP Batch Pipeline Aggregator for homogenous JSON-RPC request compaction.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from hypertrade.agent.harness_v2 import READ_ONLY_TOOL_NAMES

logger = logging.getLogger(__name__)


class ToolDependencyGraphDispatcher:
    """
    Constructs a 2-stage execution DAG partitioning mixed tool batches into:
    - Stage 0 (Parallel Read-Only Execution)
    - Stage 1 (Sequential Write Execution)
    """

    def __init__(
        self,
        executor_fn: Callable[[str, dict[str, Any]], dict[str, Any]],
        max_workers: int = 4,
    ) -> None:
        self.executor_fn = executor_fn
        self.max_workers = max_workers

    def dispatch_dag(
        self, tool_requests: list[tuple[str, dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        if not tool_requests:
            return []

        # Partition into Stage 0 (Read) & Stage 1 (Write)
        stage0_read: list[tuple[int, str, dict[str, Any]]] = []
        stage1_write: list[tuple[int, str, dict[str, Any]]] = []

        for idx, (name, args) in enumerate(tool_requests):
            if name in READ_ONLY_TOOL_NAMES:
                stage0_read.append((idx, name, args))
            else:
                stage1_write.append((idx, name, args))

        results: list[tuple[int, dict[str, Any]]] = []

        # Stage 0: Execute all read-only tools concurrently
        if stage0_read:
            with ThreadPoolExecutor(
                max_workers=min(len(stage0_read), self.max_workers)
            ) as ex:
                future_to_idx = {
                    ex.submit(self.executor_fn, name, args): idx
                    for idx, name, args in stage0_read
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
                                    "error": {
                                        "type": "stage0_execution_error",
                                        "message": str(exc),
                                    },
                                },
                            )
                        )

        # Stage 1: Execute all write tools sequentially
        for idx, name, args in stage1_write:
            try:
                res = self.executor_fn(name, args)
                results.append((idx, res))
            except Exception as exc:
                results.append(
                    (
                        idx,
                        {
                            "status": "error",
                            "error": {
                                "type": "stage1_execution_error",
                                "message": str(exc),
                            },
                        },
                    )
                )

        results.sort(key=lambda item: item[0])
        return [res for _, res in results]


class MCPBatchPipelineAggregator:
    """
    Aggregates homogenous MCP tool calls targeting identical servers
    into single JSON-RPC batch payload requests.
    """

    def aggregate_requests(
        self,
        requests: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for req in requests:
            server = str(req.get("mcp_server", "default"))
            grouped.setdefault(server, []).append(req)

        batch_payloads: list[dict[str, Any]] = []
        for server, reqs in grouped.items():
            json_rpc_calls = [
                {
                    "jsonrpc": "2.0",
                    "id": idx + 1,
                    "method": "tools/call",
                    "params": {
                        "name": r.get("tool_name"),
                        "arguments": r.get("arguments", {}),
                    },
                }
                for idx, r in enumerate(reqs)
            ]
            batch_payloads.append(
                {
                    "mcp_server": server,
                    "batch_count": len(reqs),
                    "payload": json_rpc_calls,
                }
            )

        return batch_payloads
