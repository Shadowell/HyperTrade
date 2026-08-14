"""
Unit & Integration Tests for Phase 3: Red Team Monte Carlo Overfitting Attack Matrix
"""

from hypertrade.arc.adversarial import (
    MonteCarloParamPerturbationAttack,
    RedTeamQuant,
)
from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.findings import MAX_ADMISSIBLE_DRAWDOWN, ARCReasonCode


def test_monte_carlo_param_perturbation_attack():
    attack_engine = MonteCarloParamPerturbationAttack()

    bad_attempt = ARCCandidateAttemptV1(
        attempt_id="att_001",
        candidate_id="cand_001",
        hypothesis="Bad Strategy",
        strategy_code="class Strategy_Test:\n    stop_loss = 0.12\n",
    )
    passed_bad, finding_bad, metrics_bad = attack_engine.attack(bad_attempt)
    assert not passed_bad
    assert finding_bad is not None
    assert finding_bad.code is ARCReasonCode.WIDE_STOP_LOSS
    assert metrics_bad["declared_stop_loss"] == 0.12

    good_attempt = ARCCandidateAttemptV1(
        attempt_id="att_002",
        candidate_id="cand_002",
        hypothesis="Good Strategy",
        strategy_code="class Strategy_Test:\n    stop_loss = 0.08\n",
    )
    passed_good, finding_good, metrics_good = attack_engine.attack(good_attempt)
    assert passed_good
    assert finding_good is None
    assert metrics_good["sharpe_degradation"] <= 0.25


def test_degradation_responds_to_parameter_fragility() -> None:
    """Jittering the outcome around its own mean made this metric constant."""
    attack_engine = MonteCarloParamPerturbationAttack()

    def degradation_for(stop_loss: float) -> float:
        attempt = ARCCandidateAttemptV1(
            attempt_id="att_deg",
            candidate_id="cand_deg",
            hypothesis="degradation probe",
            strategy_code=f"class S:\n    stop_loss = {stop_loss}\n",
        )
        return attack_engine.attack(attempt)[2]["sharpe_degradation"]

    # Comfortably inside the band: parameter error cannot cross the boundary.
    assert degradation_for(0.04) == 0.0
    # Parked against the boundary: a small error does cross it.
    assert degradation_for(0.098) > 0.10


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

    passed, metrics, findings = red_team.evaluate_adversarial_attack(attempt)
    assert passed
    assert findings == []
    assert metrics["max_drawdown_after_attack"] <= MAX_ADMISSIBLE_DRAWDOWN

    # Reported metrics come from the perturbation run rather than a constant
    # substituted on success, so two passing candidates of differing fragility must
    # not report the same Sharpe.
    fragile = ARCCandidateAttemptV1(
        attempt_id="att_004",
        candidate_id="cand_004",
        hypothesis="passing but closer to the ceiling",
        strategy_code="class S:\n    lookback_period = 20\n    stop_loss = 0.095\n",
    )
    fragile_passed, fragile_metrics, _ = red_team.evaluate_adversarial_attack(fragile)
    assert fragile_passed
    assert fragile_metrics["sharpe_after_attack"] < metrics["sharpe_after_attack"]
