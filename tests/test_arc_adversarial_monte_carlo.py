"""
Unit & Integration Tests for Phase 3: Red Team Monte Carlo Overfitting Attack Matrix
"""

from hypertrade.arc.adversarial import (
    MonteCarloParamPerturbationAttack,
    RedTeamQuant,
)
from hypertrade.arc.contracts import ARCCandidateAttemptV1


def test_monte_carlo_param_perturbation_attack():
    attack_engine = MonteCarloParamPerturbationAttack()

    bad_attempt = ARCCandidateAttemptV1(
        attempt_id="att_001",
        candidate_id="cand_001",
        hypothesis="Bad Strategy",
        strategy_code="class Strategy_Test:\n    stop_loss = 0.12\n",
    )
    passed_bad, reason_bad, metrics_bad = attack_engine.attack(bad_attempt)
    assert not passed_bad
    assert "MONTE_CARLO_FAIL" in reason_bad

    good_attempt = ARCCandidateAttemptV1(
        attempt_id="att_002",
        candidate_id="cand_002",
        hypothesis="Good Strategy",
        strategy_code="class Strategy_Test:\n    stop_loss = 0.08\n",
    )
    passed_good, reason_good, metrics_good = attack_engine.attack(good_attempt)
    assert passed_good
    assert metrics_good["sharpe_degradation"] <= 0.25


def test_red_team_quant_3_tier_attack_matrix():
    red_team = RedTeamQuant()

    attempt = ARCCandidateAttemptV1(
        attempt_id="att_003",
        candidate_id="cand_003",
        hypothesis="Validated Candidate",
        strategy_code="""
class Strategy_CL_USDT_SWAP:
    symbol = 'CL-USDT-SWAP'
    timeframe = '1H'
    lookback_period = 20
    stop_loss = 0.08
""",
    )

    passed, metrics, reasons = red_team.evaluate_adversarial_attack(attempt)
    assert passed
    assert len(reasons) == 0
    assert metrics["sharpe_after_attack"] == 1.85
    assert metrics["max_drawdown_after_attack"] == 0.07
