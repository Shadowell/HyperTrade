from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypertrade.arc.contracts import ResearchWindowsV1
from hypertrade.arc.evolution_memory import bind_hypothesis, experiment_key
from hypertrade.arc.regime import regime_metrics, validate_structural_changes
from hypertrade.strategy.sdk import Candle


def candles():
    return [
        Candle(
            (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i)).isoformat(),
            Decimal(100 + i),
            Decimal(102 + i),
            Decimal(99 + i),
            Decimal(101 + i),
            Decimal(100 if i < 99 else 20),
        )
        for i in range(100)
    ]


def test_measured_regime_has_real_trend_volatility_and_volume():
    metrics = regime_metrics(candles())
    assert metrics["adx_14"] == pytest.approx(100)
    assert metrics["atr_pct"] > 0
    assert metrics["volume_ratio"] == pytest.approx(0.2)
    assert 0 <= metrics["parkinson_percentile"] <= 100
    with pytest.raises(ValueError):
        regime_metrics(candles()[:10])


def test_structural_policy_rejects_risk_and_nonfinite():
    policy = {
        "volatility_filter": {
            "window": {"type": "integer", "min": 5, "max": 120},
            "max_atr_pct": {"type": "number", "min": 0.1, "max": 20},
        }
    }
    validate_structural_changes({"volatility_filter": {"window": 14, "max_atr_pct": 3}}, policy)
    for changes in (
        {"stop_loss": 0},
        {"volatility_filter": {"window": True, "max_atr_pct": 3}},
        {"volatility_filter": {"window": 14, "max_atr_pct": float("nan")}},
    ):
        with pytest.raises(ValueError):
            validate_structural_changes(changes, policy)


def test_structural_hypothesis_requires_observed_regime_field_and_distinct_identity():
    proposal = {
        "structural_changes": {"direction_bias": {"side": "long"}},
        "evolution_hypothesis": {
            "evidence_refs": ["regime:r:BTC:adx_14"],
            "expected_metric": "net_return",
            "expected_direction": "increase",
            "falsification": "Reject if same-window excess return is nonpositive",
        },
    }
    context = {
        "market_regime": {
            "report_id": "r",
            "symbols": {"BTC": {"state": "observed", "metrics": {"adx_14": 50}}},
        }
    }
    assert bind_hypothesis(proposal, context, {})["status"] == "hypothesis_not_causal_fact"
    context["market_regime"]["symbols"]["BTC"]["state"] = "unknown"
    with pytest.raises(ValueError):
        bind_hypothesis(proposal, context, {})
    windows = ResearchWindowsV1(as_of="2026-09-30")
    a = {"symbol": "BTC", "timeframe": "1h", "structural_changes": proposal["structural_changes"]}
    assert experiment_key("a", a, 100, windows) != experiment_key(
        "a", {**a, "structural_changes": {"direction_bias": {"side": "short"}}}, 100, windows
    )
