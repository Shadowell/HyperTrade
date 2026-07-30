# 44. ARC Red Team Monte Carlo Overfitting Attack Matrix Architecture

## 1. Executive Summary

This specification defines **Phase 3 of the ARC Production Evolution Upgrade**: the **Advanced Red Team Monte Carlo Overfitting Attack Matrix**.

Strategy backtest overfitting (p-hacking / curve-fitting) is the primary cause of strategy failure in live trading. Phase 3 upgrades the Red Team Quant with a 3-tier adversarial attack battery:
1. **Monte Carlo Parameter Sensitivity Perturbation**: Randomly perturbing strategy hyperparameters ($\pm 15\% \sim 25\%$) over 100 iterations to measure Sharpe stability.
2. **Historical Black Swan Shock Replay**: Testing candidate logic against historical market stress periods (e.g. 2020.03 Liquidity Crisis, 2022 LUNA Collapse, 2024 Flash Crash).
3. **Execution Friction & Slippage Stressing**: Applying stochastic slippage (1-5 bps random walk) and commission surges to kill strategies relying on zero-friction assumptions.

```
+-----------------------------------------------------------------------------------+
|               ARC Red Team Advanced Overfitting Attack Matrix                      |
+--------------------------+--------------------------+-----------------------------+
| Monte Carlo Perturbation | Black Swan Replay        | Stochastic Friction Stress  |
| - 100 Random Jitter Runs | - 2020.03 Liquidity Crash| - 1~5 bps Slippage Walk     |
| - Sharpe Degradation <25%| - 2022 LUNA Collapse     | - Commission Surge Test     |
+--------------------------+--------------------------+-----------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
|                          Adversarial Gate Evaluation                              |
|   PASS: Strategy survives parameter jitter + black swans + execution stress       |
|   FAIL: Strategy rejected -> Negative constraints sent to Reflexion Ledger        |
+-----------------------------------------------------------------------------------+
```

---

## 2. Attack Battery Specifications

### 2.1 `MonteCarloParamPerturbationAttack`
Perturbs numeric hyperparameter attributes of candidate strategies (e.g., `lookback_period`, `stop_loss`, `entry_multiplier`) by drawing from a Gaussian distribution $\mathcal{N}(\mu, \sigma^2)$ where $\sigma = 0.15 \times \mu$.

* **Passing Criteria**:
  * Median Sharpe Ratio across 100 runs $\ge 1.20$.
  * Sharpe degradation ratio: $\frac{\text{Baseline Sharpe} - \text{Median Perturbed Sharpe}}{\text{Baseline Sharpe}} \le 0.25$.
  * Max Drawdown across all perturbed runs $< 15.0\%$.

### 2.2 `BlackSwanScenarioReplayAttack`
Replays candidate logic across synthetic or historical extreme volatility periods:
* **2020 March Liquidity Crash** (Intraday volatility spike $+300\%$, sudden $-30\%$ market drop).
* **2022 LUNA Depeg Wave** (Extreme directional trend with liquidity void).

* **Passing Criteria**: No liquidation events, max drawdown $< 12.0\%$ during black swan window.

### 2.3 `StochasticFrictionStressAttack`
Injects stochastic slippage (uniform random walk between $1\text{ bps}$ and $5\text{ bps}$) and $2\times$ taker commission rates.

* **Passing Criteria**: Net total return must remain positive ($> 0\%$) under $3\times$ fee + 5 bps slippage stress.

---

## 3. Integration with Adversarial Engine & Reflexion

Strategies failing any attack tier are rejected and tagged with explicit failure codes:
* `OVERFITTING_FAIL: High parameter sensitivity (Sharpe degraded > 25%)`
* `BLACK_SWAN_FAIL: Max drawdown exceeded 12% under liquidity crash replay`
* `FRICTION_STRESS_FAIL: Strategy negative return under 5bps slippage stress`

The `ARCReflexionLedger` incorporates these failure codes into its negative constraint ledger for subsequent MCTS mutations.

---

## 4. Verification Plan

1. **Unit Tests (`tests/test_arc_adversarial_monte_carlo.py`)**:
   * Test Monte Carlo perturbation generator logic.
   * Test Black Swan scenario replay harness.
   * Test stochastic friction stress testing.
2. **End-to-End Acceptance Test**:
   * Verify an overfitted strategy (e.g., extremely narrow parameter sweet spot) is rejected by Monte Carlo attack, while a robust strategy passes and reaches `paper_observing`.
