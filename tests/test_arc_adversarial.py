"""
Sprint 133 — Test ARC Strategy Code AST Mutation & Red-Blue Adversarial Engine
"""

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant, RedTeamQuant
from hypertrade.arc.contracts import ARCReflexionEventV1
from hypertrade.arc.mutation import ARCGeneticMutator


def test_blue_team_strategy_generation():
    blue_team = BlueTeamQuant()
    attempt = blue_team.propose_initial_strategy("BTC 趋势打破策略", "BTC-USDT-SWAP")
    assert attempt.state == "proposed"
    assert "class Strategy_BTC_USDT_SWAP" in attempt.strategy_code
    assert "stop_loss = 0.12" in attempt.strategy_code


def test_red_team_adversarial_attack():
    blue_team = BlueTeamQuant()
    red_team = RedTeamQuant()

    # Initial strategy has stop_loss = 0.12, so Red Team attack should fail it!
    attempt = blue_team.propose_initial_strategy("BTC 策略", "BTC-USDT-SWAP")
    passed, metrics, reasons = red_team.evaluate_adversarial_attack(attempt)

    assert passed is False
    assert len(reasons) > 0
    assert "RED_TEAM_ATTACK_FAIL" in reasons[0]
    assert metrics["max_drawdown_after_attack"] > 0.15


def test_ast_mutation_and_red_team_survival():
    blue_team = BlueTeamQuant()
    mutator = ARCGeneticMutator(seed=123)
    engine = ARCAdversarialEngine()

    # 1. Blue Team initial proposal (stop_loss = 0.12)
    attempt = blue_team.propose_initial_strategy("ETH 震荡突破", "ETH-USDT-SWAP")

    # 2. Red Team attacks and fails it
    passed_1, metrics_1, reasons_1 = engine.run_adversarial_session(attempt)
    assert passed_1 is False

    # 3. Create reflexion event with negative constraints
    reflexion = ARCReflexionEventV1(
        candidate_id=attempt.candidate_id,
        failure_class="red_team_attack_failed",
        reason_codes=reasons_1,
        failed_gates=["stop_loss_gate"],
        observed_metrics=metrics_1,
        negative_constraints=["止损比例 (stop_loss) 必须限制在 10% 以内"],
    )

    # 4. Mutator applies AST mutation guided by negative constraints
    mutated_attempt = mutator.mutate_attempt(attempt, [reflexion])
    assert mutated_attempt.state == "mutated"
    assert "stop_loss = 0.08" in mutated_attempt.strategy_code

    # 5. Re-run Red Team attack on mutated strategy -> should PASS!
    passed_2, metrics_2, reasons_2 = engine.run_adversarial_session(mutated_attempt)
    assert passed_2 is True
    assert len(reasons_2) == 0
    assert metrics_2["sharpe_after_attack"] > 1.5
    assert metrics_2["max_drawdown_after_attack"] <= 0.15
