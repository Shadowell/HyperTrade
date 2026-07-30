"""
Unit & Integration Tests for Phase 5: ARC Portfolio MCTS Co-Evolution Engine
"""

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.portfolio import (
    ARCPortfolioCoEvolutionEngine,
    PortfolioConstituent,
)


def test_pairwise_correlation_calculation():
    engine = ARCPortfolioCoEvolutionEngine()

    returns_a = [0.01, -0.02, 0.03, -0.01, 0.02]
    returns_b = [0.01, -0.02, 0.03, -0.01, 0.02]  # Perfectly correlated
    returns_c = [-0.01, 0.02, -0.03, 0.01, -0.02]  # Perfectly negatively correlated

    corr_ab = engine.compute_pairwise_correlation(returns_a, returns_b)
    corr_ac = engine.compute_pairwise_correlation(returns_a, returns_c)

    assert abs(corr_ab - 1.0) < 1e-5
    assert abs(corr_ac - (-1.0)) < 1e-5


def test_portfolio_candidate_rejection_due_to_high_correlation():
    engine = ARCPortfolioCoEvolutionEngine(max_correlation_threshold=0.35)

    existing = [
        PortfolioConstituent(
            attempt_id="att_1",
            strategy_name="Strategy A",
            historical_returns=[0.01, -0.02, 0.03, -0.01, 0.02],
        )
    ]
    cand = ARCCandidateAttemptV1(
        attempt_id="cand_high_corr",
        candidate_id="cand_high_corr",
        hypothesis="High Corr Candidate",
        strategy_code="class Strategy_HighCorr:\n    pass\n",
    )
    cand_returns = [0.01, -0.02, 0.03, -0.01, 0.02]  # Identical return series

    res = engine.evaluate_candidate_for_portfolio(cand, cand_returns, existing)
    assert res.is_accepted is False
    assert "CORRELATION_TOO_HIGH" in res.reasons[0]


def test_portfolio_candidate_acceptance_low_correlation():
    engine = ARCPortfolioCoEvolutionEngine(
        max_correlation_threshold=0.35, min_sharpe_improvement_pct=0.05
    )

    existing = [
        PortfolioConstituent(
            attempt_id="att_1",
            strategy_name="Strategy A",
            historical_returns=[0.01, -0.02, 0.03, -0.01, 0.02, 0.01, -0.01, 0.02],
        )
    ]
    cand = ARCCandidateAttemptV1(
        attempt_id="cand_uncorr",
        candidate_id="cand_uncorr",
        hypothesis="Uncorrelated Candidate",
        strategy_code="class Strategy_Uncorr:\n    pass\n",
    )
    # Low-correlated complementary returns
    cand_returns = [0.03, 0.02, -0.01, 0.02, 0.01, 0.02, 0.03, 0.01]

    res = engine.evaluate_candidate_for_portfolio(cand, cand_returns, existing)
    assert res.is_accepted is True
    assert res.max_pairwise_correlation < 0.35
