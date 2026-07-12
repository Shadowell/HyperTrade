from __future__ import annotations

from hypertrade.research.validation import ValidationGate


def test_validation_gate_fails_closed_when_locked_metrics_are_missing() -> None:
    result = ValidationGate().evaluate(
        results=[
            {
                "window": "locked_out_of_sample",
                "label": "baseline:locked_out_of_sample",
                "metrics": {"total_return_pct": "4.2", "max_drawdown_pct": "8.1"},
            }
        ],
        validation={"min_trade_count": 20, "max_drawdown_pct": 20},
        data_complete=True,
        costs_declared=True,
    )

    assert result["passed"] is False
    assert result["gate_results"]["reported_metrics_complete"] is False
    assert result["rejection_reasons"] == [
        "missing_metrics:baseline:locked_out_of_sample:trade_count"
    ]


def test_validation_gate_accepts_reported_cost_aware_locked_evidence() -> None:
    results = [
        {
            "window": window,
            "label": f"baseline:{window}",
            "metrics": {"total_return_pct": "4.2", "max_drawdown_pct": "8.1", "trade_count": "32"},
        }
        for window in ("in_sample", "validation", "locked_out_of_sample")
    ]

    result = ValidationGate().evaluate(
        results=results,
        validation={"min_trade_count": 20, "max_drawdown_pct": 20},
        data_complete=True,
        costs_declared=True,
    )

    assert result["passed"] is True
    assert all(result["gate_results"].values())
