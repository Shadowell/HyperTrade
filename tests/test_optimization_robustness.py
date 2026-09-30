from __future__ import annotations

from hypertrade.research.optimization.matrix import (
    MatrixTrialResult,
)
from hypertrade.research.optimization.metrics import QuantitativeMetrics
from hypertrade.research.optimization.robustness import (
    RobustnessEvaluator,
    RobustnessScoreCard,
)
from hypertrade.research.optimization.space import IntParam, ParameterSpace


def _dummy_metrics(
    sharpe: float = 1.8,
    total_ret: float = 25.0,
    dd: float = 8.0,
    trades: int = 15,
) -> QuantitativeMetrics:
    return QuantitativeMetrics(
        total_return_pct=total_ret,
        annualized_return_pct=total_ret * 1.5,
        annualized_sharpe=sharpe,
        sortino_ratio=sharpe * 1.2,
        calmar_ratio=total_ret / max(0.1, dd),
        max_drawdown_pct=dd,
        win_rate=0.6,
        profit_factor=1.8,
        trade_count=trades,
        turnover=2.0,
        exposure_rate=0.3,
        avg_holding_bars=10.0,
        fees_paid=20.0,
        is_inert=trades == 0,
    )


def test_robustness_scorecard_serialization() -> None:
    card = RobustnessScoreCard(
        composite_score=82.5,
        return_sharpe_score=85.0,
        drawdown_calmar_score=80.0,
        oos_stability_score=90.0,
        sensitivity_flatness_score=75.0,
        is_promotable=True,
        verdict="OPTIMIZED_PROMOTABLE",
        reasons=("stable_plateau",),
        details={"is_sharpe": 2.1},
    )
    d = card.to_dict()
    assert d["composite_score"] == 82.5
    assert d["is_promotable"] is True

    restored = RobustnessScoreCard.from_dict(d)
    assert restored.composite_score == 82.5
    assert restored.verdict == "OPTIMIZED_PROMOTABLE"


def test_evaluator_promotable_candidate() -> None:
    space = ParameterSpace(parameters=[IntParam("fast", 5, 20), IntParam("slow", 25, 60)])
    evaluator = RobustnessEvaluator(space=space, min_trades=5, promotion_threshold=70.0)

    trial = MatrixTrialResult(
        trial_index=1,
        parameters={"fast": 10, "slow": 30},
        aggregated_is_metrics=_dummy_metrics(sharpe=2.2, total_ret=30.0, dd=7.0, trades=15),
        aggregated_oos_metrics=_dummy_metrics(sharpe=2.0, total_ret=25.0, dd=8.0, trades=10),
        dimension_results=(),
    )

    card = evaluator.evaluate_trial(trial)
    assert card.composite_score >= 70.0
    assert card.is_promotable is True
    assert card.verdict == "OPTIMIZED_PROMOTABLE"


def test_evaluator_overfit_rejection() -> None:
    space = ParameterSpace(parameters=[IntParam("fast", 5, 20)])
    evaluator = RobustnessEvaluator(space=space, min_trades=5)

    # Fantastic IS Sharpe 3.0, but OOS collapses to 0.2
    trial = MatrixTrialResult(
        trial_index=2,
        parameters={"fast": 10},
        aggregated_is_metrics=_dummy_metrics(sharpe=3.0, total_ret=50.0, dd=5.0, trades=20),
        aggregated_oos_metrics=_dummy_metrics(sharpe=0.2, total_ret=1.0, dd=18.0, trades=12),
        dimension_results=(),
    )

    card = evaluator.evaluate_trial(trial)
    assert card.is_promotable is False
    assert card.verdict == "OVERFIT_REJECTED"
    assert any("severe_oos_decay_overfit" in r for r in card.reasons)


def test_evaluator_insufficient_trades() -> None:
    space = ParameterSpace(parameters=[IntParam("fast", 5, 20)])
    evaluator = RobustnessEvaluator(space=space, min_trades=8)

    trial = MatrixTrialResult(
        trial_index=3,
        parameters={"fast": 10},
        aggregated_is_metrics=_dummy_metrics(sharpe=2.0, trades=2),
        aggregated_oos_metrics=_dummy_metrics(sharpe=1.8, trades=1),
        dimension_results=(),
    )

    card = evaluator.evaluate_trial(trial)
    assert card.is_promotable is False
    assert card.verdict == "INSUFFICIENT_TRADES"


def test_evaluator_excessive_drawdown() -> None:
    space = ParameterSpace(parameters=[IntParam("fast", 5, 20)])
    evaluator = RobustnessEvaluator(space=space, max_drawdown_limit_pct=20.0)

    trial = MatrixTrialResult(
        trial_index=4,
        parameters={"fast": 10},
        aggregated_is_metrics=_dummy_metrics(sharpe=1.5, dd=28.0, trades=15),
        aggregated_oos_metrics=_dummy_metrics(sharpe=1.2, dd=22.0, trades=10),
        dimension_results=(),
    )

    card = evaluator.evaluate_trial(trial)
    assert card.is_promotable is False
    assert card.verdict == "HIGH_RISK_REJECTED"
