# Advanced Context & Memory Management 2.0 Architecture Specification

## 1. Executive Summary

This document specifies the enterprise-grade **Context & Memory Management 2.0** subsystem for HyperTrade. It upgrades context handling with model-aware token budgets, AST/Schema-aware pruning, and sliding-window multi-turn summarization. In parallel, it upgrades memory management to a 3-tier hierarchical pyramid (Working, Episodic, Semantic) with Ebbinghaus time-decay scoring and deduplication consolidation.

---

## 2. Advanced Context Management 2.0 (`context_v2.py`)

### 2.1 Dynamic Token Budget Guard (`DynamicTokenBudgetManager`)
Dynamically adjusts context allocations based on provider model capacity ($32\text{K} \sim 200\text{K}$ tokens):

$$\text{Total Budget} = \text{ModelMaxTokens} - \text{GenerationReserve}$$

Allocates fixed ratio pools:
- **System & Guardrail Prompts**: 20%
- **Tool Output History**: 40%
- **Episodic & RAG Memory**: 30%
- **Model Generation Budget**: 10%

### 2.2 Schema-Aware Semantic Pruner (`SemanticContextPruner`)
Prevents JSON syntax corruption by preserving dictionary schema structures. When payload limits are exceeded:
- Preserves all top-level dictionary keys and metadata.
- Truncates large lists (e.g. market candles) by keeping the first 2 and last 3 items, replacing the middle with `[Folded N items]`.
- Truncates raw text fields longer than 500 characters.

### 2.3 Multi-Turn Sliding Window Summarizer (`TurnSlidingWindowSummarizer`)
When conversational turns exceed 12 steps:
- Compresses turns 3 through 10 into a single `[Historical Executive Summary]` message node.
- Preserves original mission goal and latest 2 active turns, enabling infinite-horizon multi-turn sessions.

---

## 3. Advanced Memory Management 2.0 (`memory_v2.py`)

### 3.1 3-Tier Hierarchical Memory Pyramid (`HierarchicalMemoryPyramid`)
```
+---------------------------------------------------------------------------------------+
|                       3-Tier Hierarchical Memory Pyramid                              |
+---------------------------------------------------------------------------------------+
|  1. Working Memory (Scratchpad)  |  Current task temporary variables & hypotheses     |
|  2. Episodic Memory (Mid-term)   |  7-day research task logs, backtest experiments    |
|  3. Semantic Memory (Long-term)  |  Market regime rules, factor failure patterns      |
+---------------------------------------------------------------------------------------+
```

### 3.2 Ebbinghaus Time-Decay & Importance Scorer (`EbbinghausDecayScorer`)
Ranks memory retrieval using a composite scoring formula combining semantic similarity, exponential time decay, and importance rating:

$$\text{Score}(M) = \alpha \cdot \text{Similarity}(Q, M) + \beta \cdot e^{-\lambda \cdot \Delta t} + \gamma \cdot \text{Importance}(M)$$

Where:
- $\alpha = 0.50$, $\beta = 0.30$, $\gamma = 0.20$
- $\lambda = \text{Decay Rate} = 0.05 \text{ per day}$

### 3.3 Memory Consolidation & Deduplicator (`MemoryConsolidator`)
Prevents memory database bloat by clustering incoming memory entries:
- Computes cosine similarity between new memory and existing items.
- If similarity $> 0.85$, merges the new observation into the existing item's evidence trace rather than creating a duplicate row.

---

## 4. Verification Plan

1. **Unit Tests**:
   - `tests/test_agent_context_v2.py`: Test TokenBudgetManager, SemanticPruner, and TurnSlidingWindowSummarizer.
   - `tests/test_memory_v2.py`: Test HierarchicalMemoryPyramid, EbbinghausDecayScorer, and MemoryConsolidator.
2. **Integration Verification**:
   - Execute `./scripts/check.sh` ensuring all 849+ Python and Vitest tests pass cleanly.
