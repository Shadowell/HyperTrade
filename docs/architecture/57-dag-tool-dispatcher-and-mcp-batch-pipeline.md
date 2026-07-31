# DAG Tool Dispatcher & MCP Batch Pipeline Architecture Specification

## 1. Executive Summary

This document specifies the **DAG Tool Dispatcher & MCP Batch Pipeline Aggregator** for HyperTrade. It achieves maximum parallelism in mixed tool batches by constructing a Direct Acyclic Graph (DAG) and bundles homogenous MCP calls into single batch JSON-RPC requests.

---

## 2. Architecture & Components

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                                      DAG Dispatcher & MCP Batch Pipeline Aggregator                                           |
+-------------------------------------------------------------------------------------------------------------------------------+
| 1. Tool Dependency Graph Dispatcher (DAG)                                                                                     |
|    - Stage 0: Independent Read-Only Tools (Executed Concurrently via ThreadPool)                                             |
|    - Stage 1: State-Modifying Write Tools (Executed Sequentially with Idempotency Guard)                                      |
+-------------------------------------------------------------------------------------------------------------------------------+
| 2. MCP Batch Pipeline Aggregator                                                                                              |
|    - Groups tool calls targeting the same MCP server                                                                          |
|    - Aggregates multiple tool invocations into a single batch JSON-RPC request                                                |
+-------------------------------------------------------------------------------------------------------------------------------+
```

### 2.1 Tool Dependency Graph Dispatcher (`ToolDependencyGraphDispatcher`)
Analyzes tool batches and partitions calls into DAG execution stages:
- **Stage 0 (Parallel Execution)**: Dispatches all independent read-only tools concurrently.
- **Stage 1 (Sequential Execution)**: Executes write/side-effecting tools strictly in sequence after Stage 0 completes.

### 2.2 MCP Batch Pipeline Aggregator (`MCPBatchPipelineAggregator`)
Groups tool requests directed at identical MCP endpoints and serializes them into a single batch JSON-RPC payload:
`[{"jsonrpc": "2.0", "id": 1, "method": "tools/call", ...}, ...]`

---

## 3. Verification Plan

1. **Unit Tests**: `tests/test_tool_pipeline.py`
2. **Integration Verification**: Run `./scripts/check.sh` ensuring all tests pass.
