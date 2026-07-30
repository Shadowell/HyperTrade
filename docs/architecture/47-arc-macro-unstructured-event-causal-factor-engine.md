# 47. ARC Macro & Unstructured Event Causal Factor Engine

## 1. Executive Summary

This specification defines **Phase 6 of the ARC Production Evolution Upgrade**: the **Macro & Unstructured Event Causal Factor Engine**.

Macro events (such as FOMC interest rate announcements, EIA oil inventory reports, and geopolitics) frequently trigger systemic regime shifts and trend reversals that cannot be anticipated by purely technical/microstructure price indicators. Phase 6 equips ARC with an event causal factor extractor (`MacroEventCausalExtractor`) that parses raw unstructured news and economic release text into structured quantitative signals (sentiment bias $S \in [-1.0, 1.0]$, confidence $C \in [0.0, 1.0]$, and target macro regime class). These causal factors modulate strategy position sizing and regime-aware MCTS search descriptors in real time.

```
+---------------------------------------------------------------------------------------+
|                       Macro & Unstructured Event Text Stream                          |
|   (e.g., "FOMC raises interest rates by 50 bps; Powell reiterates hawkish stance")     |
+---------------------------------------------------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                            MacroEventCausalExtractor                                  |
|   - Sentiment Bias Extraction (-1.0 to +1.0)                                          |
|   - Confidence Score Calibration (0.0 to 1.0)                                         |
|   - Regime Classification (e.g. FED_HAWKISH, OPEC_CUT, GEOPOLITICAL_RISK_OFF)         |
+---------------------------------------------------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|                           MacroCausalFactor Output                                    |
|   - Directly modulates strategy position sizing & risk multipliers                    |
|   - Updates MCTS MAP-Elites regime feature descriptors                                |
+---------------------------------------------------------------------------------------+
```

---

## 2. Component Design

### 2.1 `MacroEventCausalExtractor`
Parses unstructured macro text payloads into `MacroCausalFactor` objects:
* **`MacroEventPayload`**: `event_id`, `source`, `raw_text`, `timestamp`.
* **`MacroCausalFactor`**:
  - `sentiment_bias`: $\in [-1.0, 1.0]$ (-1.0 = extremely bearish / risk-off, +1.0 = extremely bullish / risk-on).
  - `confidence_score`: $\in [0.0, 1.0]$ confidence level of causal extraction.
  - `regime_type`: Enum string (`FED_HAWKISH`, `FED_DOVISH`, `OPEC_CUT`, `GEOPOLITICAL_RISK_ON`, `GEOPOLITICAL_RISK_OFF`, `NEUTRAL`).
  - `position_multiplier`: Dynamic scaling factor applied to trade position limits $\in [0.0, 1.5]$.

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_arc_macro_event.py`)**:
   * Test extraction accuracy for hawkish/dovish Fed announcements.
   * Test position multiplier modulation under high-risk geopolitical events.
2. **Integration Verification**:
   * Run full `./scripts/check.sh` confirming 100% green test passing status across all 830+ test cases.
