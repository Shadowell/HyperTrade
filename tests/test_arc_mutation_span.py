from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCReflexionEventV1
from hypertrade.arc.findings import ARCReasonCode, extract_strategy_parameters
from hypertrade.arc.mutation import ARCGeneticMutator


def test_oos_sample_too_small_shortens_span_parameters() -> None:
    code = (
        "class Strat:\n"
        "    slow_window = 40\n"
        "    fast_window = 20\n"
        "    stop_loss = 0.08\n"
    )
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_span",
        candidate_id="cand_span",
        hypothesis="long span",
        strategy_code=code,
        strategy_spec={"parameter_bounds": {"stop_loss": {"min": 0.05, "max": 0.1}}},
    )
    reflexion = ARCReflexionEventV1(
        candidate_id=attempt.candidate_id,
        failure_class="red_team_attack_failed",
        reason_codes=[ARCReasonCode.OOS_SAMPLE_TOO_SMALL.value],
        failed_gates=["historical_evidence"],
        observed_metrics={"out_of_sample_trades": 3},
        negative_constraints=[],
    )
    mutated = ARCGeneticMutator(seed=1).mutate_attempt(attempt, [reflexion])
    assert "slow_window" in mutated.strategy_spec["remediated_parameters"]
    assert "fast_window" in mutated.strategy_spec["remediated_parameters"]
    before = extract_strategy_parameters(code)
    after = extract_strategy_parameters(mutated.strategy_code)
    assert after["slow_window"] < before["slow_window"]
    assert after["fast_window"] < before["fast_window"]
