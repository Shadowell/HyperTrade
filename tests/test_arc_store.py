from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.store import configure_store, get_controller, reset_runtime, reset_store
from hypertrade.db import Database


def test_mission_survives_runtime_restart() -> None:
    reset_store()
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    ctrl = ARCController(
        goal=ARCGoalV1(objective="persist", budget=ARCBudgetV1(max_candidates=2))
    )
    ctrl.apply_event("goal_compiled", {"goal": ctrl.projection.goal.model_dump()})
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": {
                "attempt_id": "att_p",
                "candidate_id": "cand_p",
                "state": "proposed",
                "hypothesis": "x",
                "strategy_code": "class X: pass",
            }
        },
    )
    ctrl.apply_event(
        "paper_started",
        {"attempt_id": "att_p", "paper_instance_id": "42"},
    )
    mission_id = ctrl.mission_id
    reset_runtime()
    loaded = get_controller(mission_id)
    assert loaded is not None
    assert loaded.projection.state == "paper_observing"
    assert loaded.projection.attempts[0].paper_instance_id == "42"
    reset_store()


def test_budget_extend_does_not_reset_attempts() -> None:
    reset_store()
    ctrl = ARCController(
        goal=ARCGoalV1(objective="continue", budget=ARCBudgetV1(max_candidates=1))
    )
    ctrl.apply_event("goal_compiled", {"goal": ctrl.projection.goal.model_dump()})
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": {
                "attempt_id": "att_c",
                "candidate_id": "cand_c",
                "state": "proposed",
                "hypothesis": "x",
                "strategy_code": "class X: pass",
            }
        },
    )
    ctrl.apply_event("operator_needed", {"reason": "budget"})
    ctrl.apply_event("budget_extended", {"extra_candidates": 3})
    assert ctrl.projection.state == "exploring_candidates"
    assert ctrl.projection.goal is not None
    assert ctrl.projection.goal.budget.max_candidates == 4
    assert len(ctrl.projection.attempts) == 1
    reset_store()
