"""
Test ARC Reflexion Memory Ledger & Multi-Regime Causal Attribution
"""

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant
from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.findings import ARCReasonCode, AttackFinding
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
        findings=[],
    )

    assert event1.candidate_id == "cand_fail_1"
    assert "max_drawdown" in event1.failed_gates
    assert len(event1.negative_constraints) > 0

    # 2. Record red team failure
    ledger.diagnose_and_record_failure(
        attempt=attempt,
        failure_class="red_team_attack_failed",
        observed_metrics={"max_drawdown": 0.18, "sharpe_after_attack": 0.6},
        findings=[
            AttackFinding(
                code=ARCReasonCode.WIDE_STOP_LOSS,
                gate="parameter_perturbation",
                detail="declared stop_loss 12.0% exceeds the admissible 10% ceiling",
            )
        ],
    )

    constraints = ledger.get_all_negative_constraints()
    assert len(constraints) > 0
    assert any("stop_loss" in c for c in constraints)


def test_red_team_output_reaches_the_reflexion_ledger_unchanged() -> None:
    """The loop was severed and no test caught it.

    The red team emitted prose like "BLACK_SWAN_FAIL: Wide stop-loss failed ..." while
    the ledger searched for "Stop loss is too wide". The two strings never matched, so
    the `red_team_attack_failed` attribution branch was unreachable. The old unit test
    hid this by hand-writing a reason string the red team never produces, which is why
    this asserts against the real engine's own output instead of a fixture.
    """
    engine = ARCAdversarialEngine()
    ledger = ARCReflexionLedger()

    attempt = BlueTeamQuant().propose_initial_strategy(
        "趋势策略",
        "BTC-USDT-SWAP",
        parameter_bounds={"stop_loss": {"min": 0.12, "max": 0.18}},
    )
    passed, metrics, findings = engine.run_adversarial_session(attempt)

    assert passed is False
    assert findings, "red team must raise at least one objection for a 12% stop loss"

    event = ledger.diagnose_and_record_failure(
        attempt=attempt,
        failure_class="red_team_attack_failed",
        observed_metrics=metrics,
        findings=findings,
    )

    # Every objection the reviewer raised is carried through as a stable code...
    assert event.reason_codes == [finding.code.value for finding in findings]
    # ...lands in the failed gate set...
    assert {finding.gate for finding in findings} <= set(event.failed_gates)
    assert "adversarial_survival" in event.failed_gates
    # ...and produces actionable remediation rather than being silently dropped.
    assert any("stop_loss" in constraint for constraint in event.negative_constraints)


def test_every_reason_code_a_finding_can_carry_maps_to_a_constraint() -> None:
    """A new code without remediation advice should be a visible gap, not dead code."""
    from hypertrade.arc.reflexion import _CONSTRAINT_BY_REASON_CODE

    attack_codes = {
        ARCReasonCode.WIDE_STOP_LOSS,
        ARCReasonCode.LIQUIDITY_CRASH_DRAWDOWN,
        ARCReasonCode.SHORT_LOOKBACK_OVERFIT,
        ARCReasonCode.PARAMETER_JITTER_DEGRADATION,
    }
    assert attack_codes <= set(_CONSTRAINT_BY_REASON_CODE)
