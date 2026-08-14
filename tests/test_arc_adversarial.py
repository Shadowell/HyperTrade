"""
Sprint 133 — Test ARC Strategy Code AST Mutation & Red-Blue Adversarial Engine
"""

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant, RedTeamQuant
from hypertrade.arc.contracts import ARCReflexionEventV1
from hypertrade.arc.findings import ARCReasonCode
from hypertrade.arc.mutation import ARCGeneticMutator


def test_blue_team_strategy_generation():
    blue_team = BlueTeamQuant()
    attempt = blue_team.propose_initial_strategy("BTC 趋势打破策略", "BTC-USDT-SWAP")
    assert attempt.state == "proposed"
    assert "class ResearchArcBtcUsdtSwap" in attempt.strategy_code
    # Proposals are compiled, so the parameters the red team will read are declared as
    # research parameters rather than as module-level literals.
    assert 'params.get("stop_loss"' in attempt.strategy_code
    assert attempt.strategy_spec["source"] == "blue_team_codegen"


def test_blue_team_proposal_follows_the_objective_instead_of_one_template():
    """Every objective used to compile to the same ATR breakout body."""
    blue_team = BlueTeamQuant()
    objectives = {
        "快慢均线金叉确认趋势": "ma_crossover",
        "z-score 偏离均值两个标准差后回归": "mean_reversion_zscore",
        "RSI 超买超卖反转": "rsi_reversal",
        "唐奇安通道突破前高": "donchian_breakout",
        "ATR 波动率通道突破": "atr_breakout",
        "动量 ROC 变化率反转": "momentum_roc",
    }
    proposals = {
        objective: blue_team.propose_initial_strategy(objective, "BTC-USDT-SWAP")
        for objective in objectives
    }
    for objective, expected_family in objectives.items():
        assert proposals[objective].strategy_spec["family"] == expected_family
    # Distinct logic, not merely distinct docstrings.
    assert len({p.strategy_code for p in proposals.values()}) == len(objectives)
    assert len({p.attempt_id for p in proposals.values()}) == len(objectives)


def test_blue_team_proposal_is_reproducible():
    """The experiment ledger fingerprints code, so the same mandate must recompile identically."""
    blue_team = BlueTeamQuant()
    first = blue_team.propose_initial_strategy("ATR 通道突破", "ETH-USDT-SWAP")
    second = blue_team.propose_initial_strategy("ATR 通道突破", "ETH-USDT-SWAP")
    assert first.strategy_code == second.strategy_code
    assert first.attempt_id == second.attempt_id


def test_red_team_adversarial_attack():
    blue_team = BlueTeamQuant()
    red_team = RedTeamQuant()

    # A mandate that insists on a 12% stop loss must not survive review.
    attempt = blue_team.propose_initial_strategy(
        "BTC 策略",
        "BTC-USDT-SWAP",
        parameter_bounds={"stop_loss": {"min": 0.12, "max": 0.18}},
    )
    passed, metrics, findings = red_team.evaluate_adversarial_attack(attempt)

    assert passed is False
    assert ARCReasonCode.WIDE_STOP_LOSS in {finding.code for finding in findings}
    assert metrics["declared_stop_loss"] == 0.12


def test_red_team_accepts_the_blue_team_default_risk_envelope():
    """The default proposal is admissible; only an operator override makes it reckless."""
    attempt = BlueTeamQuant().propose_initial_strategy("BTC 策略", "BTC-USDT-SWAP")
    passed, _, findings = RedTeamQuant().evaluate_adversarial_attack(attempt)
    assert passed is True
    assert findings == []


def test_attack_verdict_tracks_the_declared_value_not_a_known_literal():
    """The gate used to recognise only 0.08 and 0.12, passing every other value."""
    red_team = RedTeamQuant()

    def attempt_with(stop_loss: float):
        from hypertrade.arc.contracts import ARCCandidateAttemptV1

        return ARCCandidateAttemptV1(
            attempt_id="att_probe",
            candidate_id="cand_probe",
            hypothesis="probe",
            strategy_code=f"class S:\n    lookback_period = 20\n    stop_loss = {stop_loss}\n",
        )

    # A value far outside the admissible band, and one nowhere near either literal.
    reckless_passed, reckless_metrics, reckless_findings = red_team.evaluate_adversarial_attack(
        attempt_with(0.30)
    )
    assert reckless_passed is False
    assert ARCReasonCode.WIDE_STOP_LOSS in {finding.code for finding in reckless_findings}

    safe_passed, safe_metrics, _ = red_team.evaluate_adversarial_attack(attempt_with(0.03))
    assert safe_passed is True

    # Severity has to respond continuously, not snap between two constants.
    assert reckless_metrics["sharpe_after_attack"] < safe_metrics["sharpe_after_attack"]
    assert reckless_metrics["max_drawdown_after_attack"] > safe_metrics["max_drawdown_after_attack"]


def test_parameter_parked_on_the_admissibility_cliff_is_flagged_as_fragile():
    """Jitter must expose a candidate whose small parameter error crosses the bound."""
    from hypertrade.arc.contracts import ARCCandidateAttemptV1

    on_the_edge = ARCCandidateAttemptV1(
        attempt_id="att_edge",
        candidate_id="cand_edge",
        hypothesis="parked exactly on the admissible ceiling",
        strategy_code="class S:\n    lookback_period = 20\n    stop_loss = 0.10\n",
    )
    passed, _, findings = RedTeamQuant().evaluate_adversarial_attack(on_the_edge)
    assert passed is False
    assert ARCReasonCode.PARAMETER_JITTER_DEGRADATION in {finding.code for finding in findings}


def test_ast_mutation_and_red_team_survival():
    blue_team = BlueTeamQuant()
    mutator = ARCGeneticMutator(seed=123)
    engine = ARCAdversarialEngine()

    # 1. Blue Team proposal under a mandate demanding a 12% stop loss
    attempt = blue_team.propose_initial_strategy(
        "ETH 震荡突破",
        "ETH-USDT-SWAP",
        parameter_bounds={"stop_loss": {"min": 0.12, "max": 0.18}},
    )

    # 2. Red Team attacks and fails it
    passed_1, metrics_1, findings_1 = engine.run_adversarial_session(attempt)
    assert passed_1 is False

    # 3. Create reflexion event with negative constraints
    reflexion = ARCReflexionEventV1(
        candidate_id=attempt.candidate_id,
        failure_class="red_team_attack_failed",
        reason_codes=[finding.code.value for finding in findings_1],
        failed_gates=["stop_loss_gate"],
        observed_metrics=metrics_1,
        negative_constraints=["止损比例 (stop_loss) 必须限制在 10% 以内"],
    )

    # 4. Mutator applies AST mutation guided by the reviewer's reason codes
    mutated_attempt = mutator.mutate_attempt(attempt, [reflexion])
    assert mutated_attempt.state == "mutated"
    assert "'stop_loss', 0.08" in mutated_attempt.strategy_code
    assert mutated_attempt.strategy_spec["remediated_parameters"] == ["stop_loss"]

    # 5. Re-run Red Team attack on mutated strategy -> should PASS!
    passed_2, metrics_2, findings_2 = engine.run_adversarial_session(mutated_attempt)
    assert passed_2 is True
    assert findings_2 == []
    assert metrics_2["sharpe_after_attack"] > 1.5
    assert metrics_2["max_drawdown_after_attack"] <= 0.15
