"""
Test ARC Reflexion Memory Ledger & Multi-Regime Causal Attribution
"""

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.reflexion import ARCReflexionLedger


def test_reflexion_ledger_failure_diagnosis():
    ledger = ARCReflexionLedger()

    attempt = ARCCandidateAttemptV1(
        attempt_id="att_fail_1",
        candidate_id="cand_fail_1",
        hypothesis="High drawdown breakout strategy",
        strategy_code="stop_loss = 0.12\nlookback_period = 20",
    )

    # 1. Record drawdown failure
    event1 = ledger.diagnose_and_record_failure(
        attempt=attempt,
        failure_class="drawdown_exceeded",
        observed_metrics={"max_drawdown": 0.22, "sharpe": 0.5},
        raw_reasons=["Max drawdown 22% exceeded 15% limit"],
    )

    assert event1.candidate_id == "cand_fail_1"
    assert "max_drawdown" in event1.failed_gates
    assert len(event1.negative_constraints) > 0

    # 2. Record red team failure
    ledger.diagnose_and_record_failure(
        attempt=attempt,
        failure_class="red_team_attack_failed",
        observed_metrics={"max_drawdown": 0.18, "sharpe_after_attack": 0.6},
        raw_reasons=["RED_TEAM_ATTACK_FAIL: Stop loss is too wide"],
    )

    constraints = ledger.get_all_negative_constraints()
    assert len(constraints) > 0
    assert any("stop_loss" in c for c in constraints)
