# 45. ARC Parallel MCTS Rollout Engine & Distributed MAP-Elites Architecture

## 1. Executive Summary

This specification defines **Phase 4 of the ARC Production Evolution Upgrade**: the **Multi-Agent Parallel MCTS Rollout & Distributed MAP-Elites Engine**.

While Phases 1-3 established a high-quality strategy AST mutation pipeline, higher-order factor operator libraries, and a 3-tier Red Team Monte Carlo attack matrix, execution remained sequential. Phase 4 introduces parallel worker execution. It shards the 2D MAP-Elites grid across multi-agent worker threads/processes (`ProcessPoolExecutor` / Subagents), enabling concurrent Blue Team strategy invention, Red Team Monte Carlo simulation, and multi-regime causal attribution. This scales exploration throughput by 5x-10x without compromising evaluation rigor.

```
                               +----------------------------------+
                               |     Master ARC MCTS Engine       |
                               +----------------------------------+
                                                |
            +-----------------------------------+-----------------------------------+
            | (Worker 1)                        | (Worker 2)                        | (Worker 3)
            v                                   v                                   v
+-----------------------+           +-----------------------+           +-----------------------+
|  High-Vol SubAgent    |           | Low-Vol SubAgent      |           | Microstructure Agent  |
| - MAP-Elites Cell 0,1 |           | - MAP-Elites Cell 1,2 |           | - MAP-Elites Cell 2,2 |
| - Concurrent Mutation |           | - Concurrent Mutation |           | - Concurrent Mutation |
+-----------------------+           +-----------------------+           +-----------------------+
            \                                   |                                   /
             \                                  |                                  /
              +---------------------------------+---------------------------------+
                                                |
                                                v
                               +----------------------------------+
                               | Concurrent UCB1 Backpropagation  |
                               | & Master Skill Registry Merge    |
                               +----------------------------------+
```

---

## 2. Component Design

### 2.1 `ARCParallelMCTSEngine`
Extends `ARCMCTSEngine` to support concurrent worker execution:
* **`parallel_workers`**: Configurable concurrency pool size (default: 4 workers).
* **`run_parallel_exploration(goal, max_iterations=10)`**: Distributes candidate mutation and Red Team evaluation tasks asynchronously across parallel worker threads.
* **Atomic UCB1 Backpropagation**: Thread-safe backpropagation updating parent MCTS node visit counts ($N_{parent}$) and cumulative rewards ($\bar{V}$).

### 2.2 `DistributedMAPElitesArchive`
Provides thread-safe atomic access to the MAP-Elites 2D feature grid (Horizon $\times$ Regime Fit):
* **`atomic_add(candidate, feature_coords, score)`**: Atomically checks cell occupancy; replaces cell occupant only if the incoming candidate's quality score strictly exceeds the incumbent.

---

## 3. Integration with ARC API & Router

The `/api/v1/arc/missions` endpoint accepts `parallel_workers: int = 4`. When set $> 1$, `run_autonomous_arc_loop` automatically delegates strategy generation and Red-Blue adversarial testing to `ARCParallelMCTSEngine`.

---

## 4. Verification Plan

1. **Unit Tests (`tests/test_arc_parallel_mcts.py`)**:
   * Verify atomic grid insertion under high concurrency.
   * Verify parallel worker MCTS tree expansion and UCB1 backpropagation correctness.
2. **Acceptance Test**:
   * Verify end-to-end mission completion with `parallel_workers=4` yielding a validated, distilled strategy candidate in $< 50\%$ wall-clock time compared to sequential execution.
