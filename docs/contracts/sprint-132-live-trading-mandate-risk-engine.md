# Sprint 132 — Live Trading Mandate & Deterministic Risk Engine (Canary Vault)

## 1. Context and Purpose

This contract defines **Sprint 132** of HyperTrade, implementing the **Live Trading Mandate & Deterministic Risk Engine (Canary Vault)** under the ARC Autonomous Research Core framework (governed by `docs/architecture/48-arc-live-canary-vault-and-risk-gate-pipeline.md`).

While Sprints 121–131 established canonical interaction protocols, evidence ledgers, strategy evolution, strategy discovery, unified validation funnels, autonomous paper incubation, and regime shadow allocators, strategies remained strictly within paper simulation. Sprint 132 introduces the deterministic multi-tiered capital allocation and risk governance pipeline for live Canary trading:

$$\text{Paper Incubation (Tier 0)} \xrightarrow{\text{Passed Gates}} \text{Canary Micro (Tier 1: 0.5\% Capital)} \xrightarrow{\text{Passed Gates}} \text{Canary Mini (Tier 2: 2.0\% Capital)} \xrightarrow{\text{Passed Gates}} \text{Production Vault (Tier 3)}$$

Mainnet live execution remains physically protected by default (`live_allowed=false`). Transitioning to any live Canary tier requires an explicit, operator-authenticated `LiveTradingMandateV1` and strict deterministic risk gate enforcement.

---

## 2. In Scope

1. **`CanaryTier` Enum**:
   - `PAPER_INCUBATION` (Tier 0): 0% real capital; 100% paper simulation.
   - `CANARY_LIVE_MICRO` (Tier 1): 0.5% max capital allocation.
   - `CANARY_LIVE_MINI` (Tier 2): 2.0% max capital allocation.
   - `PRODUCTION_LIVE_VAULT` (Tier 3): Dynamic risk-weighted capital allocation.

2. **`RiskGatePolicy`**:
   - `max_daily_drawdown_pct`: 3.0% hard daily loss circuit breaker (immediate demotion to Tier 0 & emergency exit).
   - `max_pnl_drift_pct`: 10.0% max allowed deviation between simulated paper PnL and live Canary PnL.
   - `mandatory_stop_loss_pct`: Hard stop-loss limit ($\le 7.0\%$).

3. **`LiveTradingMandateV1`**:
   - Immutable operator-approved mandate binding exact symbol, candidate identity, max capital cap ($50–$100 Micro Vault), approval token, expiring validity, and kill switch.

4. **`CanaryVaultPipeline`**:
   - `evaluate_promotion(instance, metrics)`: Evaluates candidate metrics and promotes instance to the next Canary tier if all gate criteria pass.
   - `evaluate_demotion(instance, metrics)`: Demotes live Canary instance back to Tier 0 immediately if any risk threshold is violated.

---

## 3. Out of Scope

- Direct mainnet order execution without operator approval.
- Bypassing BitPro MCP risk boundaries.
- Unbounded capital allocation or leverage expansion.

---

## 4. Verification

- Unit & integration tests in `tests/test_arc_canary_vault.py`.
- Full check suite `./scripts/check.sh` passing 100%.
