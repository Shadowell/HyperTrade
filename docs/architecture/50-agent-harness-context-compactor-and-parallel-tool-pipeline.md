# 50. Agent Harness Context Compactor & Parallel Tool Pipeline Architecture

## 1. Executive Summary

This specification defines the **SOTA Harness Completion Upgrade**, matching the context management and tool execution speed of benchmark systems such as Claude Code, Codex, and OpenCode.

This architecture introduces two SOTA scaffolding components:

1. **`ContextCompactor`**: Automatic background context pruning and summarization. When conversation trace tokens approach 80% of model capacity or exceed 20 tool interaction turns, `ContextCompactor` condenses verbose historical tool outputs (e.g. 5,000-line logs or raw candles) into structured key observation nodes while preserving mission goals, validated strategy ASTs, and verification proof markers.
2. **`ParallelToolPipeline`**: Asynchronous concurrent multi-tool execution engine. Executes independent tool call arrays concurrently via `asyncio.gather` / thread pools, reducing agent execution latency by up to 70%.

```
+---------------------------------------------------------------------------------------+
|                        HyperTrade SOTA Agent Harness Completion                       |
+---------------------------------------------------------------------------------------+
|  1. Context Compactor                     |  2. Parallel Tool Pipeline                |
|  - Token budget monitoring (> 80%)        |  - Concurrent non-interdependent tool     |
|  - Prunes verbose historical tool outputs |    execution via asyncio.gather           |
|  - Preserves Goals, ASTs & QA proofs      |  - Up to 70% latency reduction            |
+---------------------------------------------------------------------------------------+
```

---

## 2. Component Design

### 2.1 `ContextCompactor`
Located in `backend/src/hypertrade/agent/compactor.py`:
* **`compact_trace_events(events: list[dict[str, Any]], max_token_budget: int = 8000) -> list[dict[str, Any]]`**: Scans trace event history. If token count exceeds budget, truncates old tool output payloads into concise `[Truncated Summary: {tool_name} output ({byte_len} bytes)]` blocks while leaving system instructions, user goals, and latest strategy validation events intact.

### 2.2 `ParallelToolPipeline`
Located in `backend/src/hypertrade/agent/planner.py`:
* **`execute_parallel_tools(tool_calls: list[dict[str, Any]], executor_fn)`**: Identifies independent read tools (e.g., `market_ticker`, `market_candles`, `rag_search`) and executes them concurrently using an asynchronous task pool.

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_agent_harness_sota.py`)**:
   * Test `ContextCompactor` event pruning under high token load while preserving essential state.
   * Test `ParallelToolPipeline` concurrent execution latency & result collation.
2. **Integration Verification**:
   * Run full `./scripts/check.sh` suite ensuring 100% green test passing status across all test suites.
