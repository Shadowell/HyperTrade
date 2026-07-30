# 46. ARC Portfolio MCTS Co-Evolution Engine & Low-Correlation Allocator

## 1. Executive Summary

This specification defines **Phase 5 of the ARC Production Evolution Upgrade**: the **Portfolio MCTS Co-Evolution Engine & Low-Correlation Portfolio Allocator**.

While Phase 4 introduced multi-agent parallel MCTS search for single-strategy discovery, single strategies inevitably suffer from strategy decay and regime vulnerability. Phase 5 elevates ARC from single-strategy optimization to **multi-strategy joint portfolio co-evolution**. It ensures new candidate strategies are selected not only for standalone performance, but for pairwise low correlation ($\rho < 0.35$) with existing portfolio constituents and net portfolio Sharpe ratio enhancement.

```
                              +------------------------------------+
                              |  ARC Portfolio Co-Evolution Engine |
                              +------------------------------------+
                                                |
                 +------------------------------+------------------------------+
                 |                              |                              |
                 v                              v                              v
    +------------------------+     +------------------------+     +------------------------+
    | Strategy A (1H CTA)    |     | Strategy B (Orderbook) |     | Candidate Strategy C   |
    | Sharpe: 1.85           |     | Sharpe: 1.62           |     | Standalone Sharpe: 1.50|
    +------------------------+     +------------------------+     +------------------------+
                 \                              /                              |
                  \                            /                               |
                   v                          v                                v
    +-------------------------------------------------------+     +------------------------+
    |           Existing Portfolio Return Series            |     |  Pairwise Correlation  |
    |                    (Composite R_p)                    | <---|   Matrix Verification  |
    +-------------------------------------------------------+     |      (\rho < 0.35)     |
                                |                                 +------------------------+
                                v
    +--------------------------------------------------------------------------------------+
    |             Net Portfolio Sharpe Ratio Evaluation (\Delta Sharpe > 15%)              |
    +--------------------------------------------------------------------------------------+
```

---

## 2. Component Design

### 2.1 `ARCPortfolioCoEvolutionEngine`
Manages multi-strategy ensemble discovery and allocation:
* **`compute_pairwise_correlation(returns_a: list[float], returns_b: list[float]) -> float`**: Computes Pearson correlation coefficient $\rho_{a,b}$. Rejects candidates where $\max_{k} \rho_{cand, k} \ge 0.35$.
* **`evaluate_portfolio_addition(existing_portfolio, candidate) -> tuple[bool, float, dict]`**: Calculates composite portfolio return series $R_{port} = \sum w_i R_i$, composite Sharpe ratio $S_{port}$, and marginal Sharpe gain $\Delta S = \frac{S_{port, new} - S_{port, old}}{S_{port, old}}$.

### 2.2 `ARCPortfolioMCTSNode`
Extends MCTS evaluation to represent multi-strategy portfolio states, using joint portfolio Sharpe as the primary UCB1 reward signal.

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_arc_portfolio_mcts.py`)**:
   * Verify pairwise correlation matrix calculation accuracy.
   * Verify candidate rejection when correlation exceeds $0.35$.
   * Verify candidate acceptance when correlation is low ($\rho < 0.20$) and net portfolio Sharpe increases by $> 15\%$.
2. **Integration Verification**:
   * Run full `./scripts/check.sh` suite confirming 100% green tests.
