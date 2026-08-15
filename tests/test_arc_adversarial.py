"""
Sprint 133 — Test ARC Strategy Code AST Mutation & Red-Blue Adversarial Engine
"""

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant, RedTeamQuant
from hypertrade.arc.contracts import ARCReflexionEventV1
from hypertrade.arc.findings import ARCReasonCode, FindingSeverity
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


def test_every_proposal_carries_the_exits_bitpro_requires_to_validate():
    """A candidate without a profit exit cannot be validated, whatever its evidence.

    BitPro's `strategy_validate_code` requires a contract strategy to implement a stop
    loss, a take profit or trailing lock, and a close_contract path. ARC declared only
    the loss guard, so on real ETH history the best-scoring candidate cleared held-out
    evidence and was then refused at validation, with the refusal recorded as a platform
    outage rather than as a missing exit.
    """
    blue_team = BlueTeamQuant()
    frontier = blue_team.propose_diverse_frontier("find an edge on ETH", "ETH-USDT-SWAP", 6)

    assert frontier
    for attempt in frontier:
        code = attempt.strategy_code
        family = attempt.strategy_spec["family"]
        assert 'params.get("stop_loss"' in code, family
        assert 'params.get("take_profit"' in code, family
        assert "self.p_take_profit" in code, family
        assert "close_contract" in code, family


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


def test_frontier_explores_both_sides_when_the_mandate_does_not_pick_one():
    """On real BTC history that fell 45%, every long-only family failed on evidence.

    Direction was fixed for the whole frontier and defaults to long only, so a mission
    would spend its budget on one side of the market and report `needs_operator` without
    recording that the other side was never proposed.
    """
    frontier = BlueTeamQuant().propose_diverse_frontier(
        "find an edge on BTC", "BTC-USDT-SWAP", 3
    )

    directions = {a.strategy_spec["direction"] for a in frontier}
    assert len(directions) > 1, directions
    assert "long_short" in directions
    # Structural variety in both dimensions, not one traded three ways.
    assert len({a.strategy_spec["family"] for a in frontier}) > 1
    # Same family on two sides is two hypotheses, so ids must not collide.
    assert len({a.attempt_id for a in frontier}) == len(frontier)


def test_an_explicit_prohibition_is_a_constraint_not_a_preference():
    """"仅做多" has to survive the direction exploration that silence now triggers."""
    frontier = BlueTeamQuant().propose_diverse_frontier(
        "仅做多，寻找 BTC 趋势机会", "BTC-USDT-SWAP", 4
    )

    assert {a.strategy_spec["direction"] for a in frontier} == {"long_only"}
    for attempt in frontier:
        assert 'await self._enter(symbol, "short"' not in attempt.strategy_code


def test_a_requested_direction_is_compiled_rather_than_inferred_from_prose():
    blue = BlueTeamQuant()
    short = blue.propose_initial_strategy(
        "BTC 机会", "BTC-USDT-SWAP", family_key="atr_breakout", direction="short_only"
    )

    assert short.strategy_spec["direction"] == "short_only"
    assert 'await self._enter(symbol, "short"' in short.strategy_code
    assert 'await self._enter(symbol, "long"' not in short.strategy_code


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
    from hypertrade.arc.findings import FindingSeverity

    attempt = BlueTeamQuant().propose_initial_strategy("BTC 策略", "BTC-USDT-SWAP")
    passed, metrics, findings = RedTeamQuant().evaluate_adversarial_attack(attempt)
    assert passed is True
    assert [f for f in findings if f.severity is FindingSeverity.BLOCKING] == []
    # With no data window configured the verdict is annotated as evidence-free rather
    # than silently presented as a clean pass.
    assert metrics["evidence_available"] is False
    assert metrics["advisories"]


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


def test_successive_mutations_explore_more_than_the_one_repaired_knob():
    """Repair-only mutation converged on one body, so extra rounds re-tested one strategy."""
    from hypertrade.arc.findings import extract_strategy_parameters
    from hypertrade.arc.reflexion import ARCReflexionLedger

    engine = ARCAdversarialEngine()
    ledger = ARCReflexionLedger()
    mutator = ARCGeneticMutator(seed=7)

    candidate = BlueTeamQuant().propose_initial_strategy(
        "均线金叉趋势",
        "BTC-USDT-SWAP",
        parameter_bounds={"stop_loss": {"min": 0.12, "max": 0.18}},
    )
    bodies: set[str] = set()
    explored: set[str] = set()
    for _ in range(4):
        survived, metrics, findings = engine.run_adversarial_session(candidate)
        if not survived:
            ledger.diagnose_and_record_failure(
                attempt=candidate,
                failure_class="red_team_attack_failed",
                observed_metrics=metrics,
                findings=findings,
            )
        candidate = mutator.mutate_attempt(candidate, ledger.get_history())
        bodies.add(candidate.strategy_code)
        explored.update(candidate.strategy_spec["explored_parameters"])
        # The compliance repair must survive every later exploratory round.
        assert extract_strategy_parameters(candidate.strategy_code)["stop_loss"] <= 0.10

    assert len(bodies) == 4, "each generation must differ from the last"
    assert len(explored) >= 2, "exploration must rotate across dimensions"


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
    assert [f for f in findings_2 if f.severity is FindingSeverity.BLOCKING] == []
    assert metrics_2["sharpe_after_attack"] > 1.5
    assert metrics_2["max_drawdown_after_attack"] <= 0.15
