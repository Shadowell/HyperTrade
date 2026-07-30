"""
Sprint 132 — Test ARC Universal Kernel, Domain Contracts & State Machine Reducer
"""

from decimal import Decimal

from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController


def test_arc_goal_and_budget_contracts():
    budget = ARCBudgetV1(max_candidates=2, max_backtests=3)
    assert not budget.is_exhausted()

    budget.candidates_used = 2
    assert budget.is_exhausted()

    preauth = PaperPreauthorizationV1(
        approved_by="operator_user",
        max_capital_per_instance=Decimal("5000"),
    )
    assert preauth.approved_by == "operator_user"
    assert preauth.max_capital_per_instance == Decimal("5000")

    goal = ARCGoalV1(
        objective="研究BTC突破策略",
        budget=budget,
        paper_authorization=preauth,
    )
    assert goal.objective == "研究BTC突破策略"
    assert goal.live_allowed is False


def test_arc_controller_state_machine_and_event_reduction():
    goal = ARCGoalV1(
        objective="自动搜索和进化策略",
        budget=ARCBudgetV1(max_candidates=2),
    )
    controller = ARCController(goal=goal)
    assert controller.projection.state == "created"

    # 1. Goal Compiled
    controller.apply_event("goal_compiled", {"goal": goal.model_dump()})
    assert controller.projection.state == "exploring_candidates"

    # 2. Candidate Proposed
    attempt_payload = {
        "attempt_id": "att_001",
        "candidate_id": "cand_001",
        "state": "proposed",
        "hypothesis": "突破上轨买入",
        "strategy_code": "class TestStrat: pass",
    }
    controller.apply_event("candidate_proposed", {"attempt": attempt_payload})
    assert len(controller.projection.attempts) == 1
    assert controller.projection.goal.budget.candidates_used == 1

    # 3. Candidate Mutated
    controller.apply_event(
        "candidate_mutated",
        {"attempt_id": "att_001", "strategy_code": "class TestStratMutated: pass"},
    )
    assert controller.projection.state == "mutating"
    assert controller.projection.attempts[0].strategy_code == "class TestStratMutated: pass"

    # 4. Red Team Tested & Validated
    controller.apply_event(
        "red_team_tested",
        {"attempt_id": "att_001", "passed": True, "metrics": {"sharpe": 1.8}},
    )
    assert controller.projection.state == "validating"

    controller.apply_event(
        "candidate_validated",
        {"attempt_id": "att_001", "validation_id": "val_123"},
    )
    assert controller.projection.state == "paper_authorizing"

    # 5. Paper Started
    controller.apply_event(
        "paper_started",
        {"attempt_id": "att_001", "paper_instance_id": "paper_inst_888"},
    )
    assert controller.projection.state == "paper_observing"
    assert controller.projection.attempts[0].paper_instance_id == "paper_inst_888"


def test_arc_controller_reflexion_and_budget_exhaustion():
    goal = ARCGoalV1(
        objective="高频反转策略",
        budget=ARCBudgetV1(max_candidates=1),
    )
    controller = ARCController(goal=goal)
    controller.apply_event("goal_compiled", {"goal": goal.model_dump()})

    # Propose 1 candidate
    attempt_payload = {
        "attempt_id": "att_fail",
        "candidate_id": "cand_fail",
        "state": "proposed",
        "hypothesis": "激进高杠杆",
        "strategy_code": "class BadStrat: pass",
    }
    controller.apply_event("candidate_proposed", {"attempt": attempt_payload})
    assert controller.projection.goal.budget.is_exhausted()

    # Reflexion event
    reflexion_payload = {
        "reflexion": {
            "candidate_id": "att_fail",
            "failure_class": "drawdown_exceeded",
            "reason_codes": ["MAX_DRAWDOWN_VIOLATION"],
            "failed_gates": ["max_drawdown"],
            "observed_metrics": {"drawdown": 0.35},
            "negative_constraints": ["止损比例必须设置在10%以内"],
        }
    }
    controller.apply_event("reflexion_recorded", reflexion_payload)

    # State should become needs_operator because max_candidates=1 is exhausted
    assert controller.projection.state == "needs_operator"
    assert len(controller.projection.reflexion_history) == 1
    assert controller.projection.attempts[0].state == "rejected"
