# 42. ARC Dynamic Paper Observation Feedback & Auto Re-training Architecture

## 1. Executive Summary

This specification defines **Phase 1 of the ARC Production Evolution Upgrade**: the **Dynamic Paper Observation Feedback & Auto Re-training Loop**. 

Previously, when a strategy candidate passed Red-Blue adversarial testing, it was provisioned to paper trading (`paper_observing`), and the research mission terminated. Under Phase 1, paper trading is no longer an isolated endpoint. Instead, a real-time observation daemon monitors live simulated PnL, drawdowns, slippage, and win rates. When performance decays due to market regime drift, alpha decay, or execution friction, an anomaly detector extracts new empirical negative constraints and triggers an incremental ARC MCTS re-training loop automatically.

```
+------------------+      +-------------------------+      +---------------------------+
| BitPro Paper     | ---> | Paper Observation       | ---> | Anomaly Detector          |
| Instance PnL Feed|      | Monitor Daemon          |      | (Regime Drift / Drawdown) |
+------------------+      +-------------------------+      +---------------------------+
                                                                         |
                                                                         v
+------------------+      +-------------------------+      +---------------------------+
| Autonomous ARC   | <--- | Incremental Evolution   | <--- | Paper Reflexion Memory    |
| Re-training Loop |      | Mission Compiler        |      | (New Negative Constraints)|
+------------------+      +-------------------------+      +---------------------------+
```

---

## 2. Component Design

### 2.1 `PaperObservationMonitorDaemon`
Monitors active paper trading instances across configurable sampling windows (e.g., 5-minute ticks, 1-hour rollups).

```python
class PaperObservationSnapshot(BaseModel):
    instance_id: str
    symbol: str
    timeframe: str
    cumulative_return_pct: float
    current_drawdown_pct: float
    consecutive_losses: int
    win_rate_30d: float
    avg_slippage_bps: float
    sampled_at: datetime
```

### 2.2 `PaperAnomalyDetector`
Evaluates active snapshots against preset risk and alpha decay thresholds:
* **Max Allowable Drawdown Breach**: Drawdown > 10.0% in paper trading.
* **Win Rate Decay**: Win rate dropping below 45.0% over the last 20 trades.
* **Consecutive Loss Streak**: $\ge 4$ consecutive losing trades under high volatility regimes.
* **Execution Friction Surge**: Average slippage exceeding backtest assumptions by $> 3.0\times$.

When a breach occurs, the detector generates a `PaperAnomalyEvent` containing the exact market conditions and failure attributes.

### 2.3 `PaperReflexionTranslator` & `IncrementalEvolutionTrigger`
Translates `PaperAnomalyEvent` into structured negative constraints (e.g., `"DO NOT execute long breakouts when 1H ATR > 2.5 * 20-day mean ATR"`) and compiles an incremental `ARCGoalV1` mission with inherited memory, launching `run_autonomous_arc_loop` for live strategy auto-healing.

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_arc_paper_monitor.py`)**:
   * Verify snapshot calculation from simulated BitPro PnL series.
   * Verify anomaly detection triggers under simulated drawdown breaches ($\ge 10\%$).
   * Verify `PaperReflexionTranslator` generates valid negative constraints.
2. **Integration Test (`test_arc_paper_feedback_integration`)**:
   * Simulate a paper instance incurring a simulated regime drift drawdown, verify that `PaperAnomalyDetector` fires, compiles an incremental `ARCGoalV1`, and triggers `run_autonomous_arc_loop` to produce a mutated, healed strategy candidate.
