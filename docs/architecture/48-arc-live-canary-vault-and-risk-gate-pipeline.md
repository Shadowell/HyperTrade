# 48. ARC Live Canary Vault & Risk Gate Pipeline Architecture

## 1. Executive Summary

This specification defines **Phase 7 (Final Milestone) of the ARC Production Evolution Upgrade**: the **Live Canary Vault & Risk Gate Pipeline**.

While Phases 1-6 established automated strategy AST mutation, higher-order factor operator libraries, Red Team Monte Carlo stress matrices, multi-agent parallel rollout, portfolio co-evolution, and macro event causal risk scaling, strategies remained bounded within paper observation. Phase 7 implements a deterministic, multi-tiered capital allocation pipeline that safely governs progression from paper incubation to live trading:

$$\text{Paper Incubation (14D)} \xrightarrow{\text{Passed Gates}} \text{Canary Micro (0.5\% Capital)} \xrightarrow{\text{Passed Gates}} \text{Canary Mini (2.0\% Capital)} \xrightarrow{\text{Passed Gates}} \text{Production Vault (Dynamic Capital)}$$

```
+---------------------------------------------------------------------------------------+
|                               Candidate Strategy                                      |
+---------------------------------------------------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                             Paper Incubation (Tier 0)                                 |
|   - 14 Days minimum dwell time; Zero real capital risk                                 |
+---------------------------------------------------------------------------------------+
                                           | (Passes Anomaly & Correlation Gates)
                                           v
+---------------------------------------------------------------------------------------+
|                           Canary Live Micro (Tier 1: 0.5% Capital)                    |
|   - Hard Daily Max Loss Gate (3.0% Max Drawdown Circuit Breaker)                       |
|   - Execution Drift Gate (Paper vs Live PnL Deviation < 10%)                          |
+---------------------------------------------------------------------------------------+
                                           | (Passes 30D Live Verification)
                                           v
+---------------------------------------------------------------------------------------+
|                           Canary Live Mini (Tier 2: 2.0% Capital)                     |
|   - Multi-Sig Non-Custodial Exchange Key Isolation                                    |
+---------------------------------------------------------------------------------------+
                                           | (Passes 60D Live Verification)
                                           v
+---------------------------------------------------------------------------------------+
|                         Production Live Vault (Tier 3: Dynamic Allocation)            |
|   - Real-time automatic demotion back to Tier 0 if any Risk Gate is breached           |
+---------------------------------------------------------------------------------------+
```

---

## 2. Component Design

### 2.1 `CanaryTier` Enum
* **`PAPER_INCUBATION`** (Tier 0): Zero real capital; 100% paper simulation.
* **`CANARY_LIVE_MICRO`** (Tier 1): 0.5% max capital allocation.
* **`CANARY_LIVE_MINI`** (Tier 2): 2.0% max capital allocation.
* **`PRODUCTION_LIVE_VAULT`** (Tier 3): Dynamic risk-weighted capital allocation.

### 2.2 `RiskGatePolicy`
Enforces strict deterministic protection boundaries:
* **`max_daily_drawdown_pct`**: 3.0% absolute daily loss circuit breaker (triggers immediate position exit & emergency shutdown).
* **`max_pnl_drift_pct`**: 10.0% max allowed deviation between simulated paper PnL and live Canary PnL.
* **`mandatory_stop_loss_pct`**: Hard stop-loss limit ($\le 7.0\%$).

### 2.3 `CanaryVaultPipeline`
Governs automatic tier promotion and demotion:
* **`evaluate_promotion(instance)`**: Evaluates performance and risk metrics against `RiskGatePolicy`. Promotes candidate to the next tier if all criteria are satisfied.
* **`evaluate_demotion(instance)`**: Immediately demotes live Canary instance back to `PAPER_INCUBATION` if any risk threshold is violated.

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_arc_canary_vault.py`)**:
   * Verify Tier 0 to Tier 1 promotion after paper incubation passes cleanly.
   * Verify immediate automatic demotion to Tier 0 when daily drawdown exceeds 3.0%.
   * Verify immediate automatic demotion when paper-to-live PnL drift exceeds 10.0%.
2. **Integration Verification**:
   * Run full `./scripts/check.sh` confirming 100% green test suite.
