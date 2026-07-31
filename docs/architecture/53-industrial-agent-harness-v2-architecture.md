# 53. Industrial Agent Harness 2.0 Architecture Specification

## 1. Executive Summary

This document specifies the architecture for **HyperTrade Industrial Agent Harness 2.0**.

The previous Harness (v1.0) suffered from five enterprise limitations: coarse error handling without exponential backoff, serial execution of independent read tools, context window explosion from large JSON outputs, lack of atomic write idempotency guards, and missing micro-telemetry metrics.

Agent Harness 2.0 addresses all five gaps:
1. **`AsyncParallelToolDispatcher`**: Concurrent execution of read-only tools via `asyncio.gather`.
2. **`SmartToolExecutionHealer`**: Exponential backoff retry ($100\text{ms} \rightarrow 200\text{ms} \rightarrow 400\text{ms}$) for network errors ($502, 429$, `httpx.ConnectError`) and stacktrace-guided parameter repair.
3. **`HarnessContextWaterCooler`**: Automatic truncation and summarization of large tool output payloads ($> 2,000$ chars) to prevent context explosion.
4. **`ToolIdempotencyLockGuard`**: Thread-safe atomic idempotency locking for write operations (`bitpro_paper_configure`, `live_order_intent`).
5. **`HarnessTelemetryCollector`**: Micro-metrics tracking tool P95 latency, retry ratios, and schema repair rates.

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                                              HyperTrade Industrial Harness 2.0                                                |
+------------------------------------+------------------------------------+-----------------------------------------------------+
| 1. Async Parallel Tool             | 2. Smart Self-Healing &             | 3. Dynamic Context Water-Cooler &                   |
|    Dispatcher Engine               |    Exponential Backoff             |    Output Truncator                                 |
| - Executes read-only tools         | - Retries 502/429 with backoff     | - Summarizes huge JSON outputs                      |
|   concurrently via asyncio.gather  | - Auto-repairs missing params      | - Prevents context explosion                        |
+------------------------------------+------------------------------------+-----------------------------------------------------+
| 4. Idempotency & Safety Sandbox    | 5. Micro-Metrics Telemetry         |                                                     |
|    Lock Guard                      |    Exporter                        |                                                     |
| - Prevents duplicate write actions | - Tracks P95 latency, retry rate,  |                                                     |
| - Enforces atomic key isolation    |   and schema repair metrics        |                                                     |
+------------------------------------+------------------------------------+-----------------------------------------------------+
```

---

## 2. Detailed Component Specifications

### 2.1 `AsyncParallelToolDispatcher`
* Classifies tools as `read_only` vs `side_effecting`.
* Groups consecutive read-only tool calls into parallel batches executed via `asyncio.gather` or concurrent thread pools, cutting multi-query latency by up to 70%.

### 2.2 `SmartToolExecutionHealer`
* Handles transient network errors with exponential backoff:
  $$\text{delay}(k) = \text{base\_ms} \times 2^k + \text{jitter}$$
* On schema mismatch or argument errors, formats a precise stacktrace payload to guide LLM parameter correction.

### 2.3 `HarnessContextWaterCooler`
* Monitors payload size of tool output JSON. If payload exceeds 2,000 characters, preserves head/tail schema structures and inserts a water-cooled summary string: `[WaterCooler: Truncated {len} bytes, showing key fields]`.

### 2.4 `ToolIdempotencyLockGuard`
* Maintains a thread-safe memory lock set of active `idempotency_key` strings.
* Rejects duplicate execution attempts within the same session with an `idempotency_conflict` error payload.

### 2.5 `HarnessTelemetryCollector`
* Collects per-tool micro-metrics: execution count, total duration, error count, retry count, water-cooling count.
* Exports structured telemetry records to `TraceEvent` logs for observability dashboards.

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_agent_harness_v2.py`)**:
   * Test exponential backoff retry on simulated network connection errors.
   * Test `AsyncParallelToolDispatcher` concurrent execution order and speed.
   * Test `HarnessContextWaterCooler` payload truncation on large JSON structures.
   * Test `ToolIdempotencyLockGuard` duplicate key rejection.
   * Test `HarnessTelemetryCollector` metric aggregation.
2. **Integration Verification**:
   * Run full `./scripts/check.sh` suite ensuring 100% green test passing status across all 840+ test suites.
