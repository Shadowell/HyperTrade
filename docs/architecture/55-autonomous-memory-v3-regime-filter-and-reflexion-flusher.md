# Autonomous Memory 3.0 Architecture Specification

## 1. Executive Summary

This document specifies **Autonomous Memory 3.0** for HyperTrade, upgrading the memory subsystem with:
1. **Automatic Reflexion Memory Flusher (`AutoReflexionMemoryFlusher`)**: Autonomous post-task self-reflection and automatic memory flushing on run completion.
2. **Market Regime Contextual Memory Filter (`MarketRegimeMemoryFilter`)**: Regime tagging (`bull_trend`, `bear_crash`, `sideways_range`, `high_volatility`) and regime-matched retrieval.
3. **Memory Contradiction Resolver (`MemoryContradictionResolver`)**: Automatic detection and deprecation of invalidated historical strategy hypotheses.

---

## 2. Architecture & Components

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                                                Autonomous Memory 3.0 System                                                   |
+------------------------------------+------------------------------------+-----------------------------------------------------+
| 1. AutoReflexion Memory Flusher    | 2. Market Regime Memory Filter     | 3. Memory Contradiction Resolver                    |
| - Automatic post-task reflection   | - Tags memories with market regime | - Detects semantic hypothesis contradictions        |
| - Extracts strategy insights and   | - Filters memories matching        | - Deprecates invalidated historical items           |
|   error lessons into 3-tier memory |   current WorldModel regime        | - Maintains knowledge base consistency              |
+------------------------------------+------------------------------------+-----------------------------------------------------+
```

### 2.1 AutoReflexion Memory Flusher (`flusher.py`)
Intercepts completed agent runs and extracts structured takeaways:
- **Success Run**: Generates strategy lessons & factor insights -> Flushes into `Semantic Memory`.
- **Failure Run**: Generates error root causes & constraint warnings -> Flushes into `Episodic Memory`.
- **Importance Assignment**: Auto-computes importance score ($0.1 \sim 1.0$) based on risk breaches or Sharpe ratio delta.

### 2.2 Market Regime Memory Filter (`regime_filter.py`)
Tags memories with current `market_regime` during write. During retrieval:
- Filters memories matching the current active `market_regime` from `WorldModelService`.
- Applies a $0.5\times$ penalty to cross-regime memories to prevent misleading past experiences in different market regimes.

### 2.3 Memory Contradiction Resolver (`resolver.py`)
Detects contradicting hypotheses between new memory entries and existing stored memories:
- Computes semantic similarity. If similarity $>0.75$ but sentiment/conclusion is opposite:
  - Marks older memory item as `deprecated: true`.
  - Injects `replaced_by` link to the new memory item.

---

## 3. Verification Plan

1. **Unit Tests**:
   - `tests/test_memory_v3.py`: Test AutoReflexionMemoryFlusher, MarketRegimeMemoryFilter, and MemoryContradictionResolver.
2. **Integration Verification**:
   - Run `./scripts/check.sh` ensuring all 855+ Python and Vitest tests pass cleanly.
