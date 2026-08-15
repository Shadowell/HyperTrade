"""Does the API container ever see what the worker container wrote?

hypertrade-api and hypertrade-worker each hold their own ``store.MISSIONS`` cache over
one shared row. Two processes are modelled by swapping that cache around a shared
database, so each side only ever sees controllers it loaded itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from sqlalchemy import text  # noqa: E402

from hypertrade.arc import store  # noqa: E402
from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1  # noqa: E402
from hypertrade.arc.controller import ARCController  # noqa: E402
from hypertrade.db import Database  # noqa: E402


def db_state(db: Database, mission_id: str) -> str:
    with db.session() as session:
        return str(
            session.execute(
                text("select state from arc_missions where mission_id = :m"),
                {"m": mission_id},
            ).scalar_one()
        )


def main() -> int:
    store.reset_store()
    db = Database("sqlite:///:memory:")
    db.create_all()
    store.configure_store(db)

    # --- api container: create the mission and keep it in this process's cache ---
    ctrl = ARCController(goal=ARCGoalV1(objective="cache", budget=ARCBudgetV1(max_candidates=2)))
    ctrl.apply_event("goal_compiled", {"goal": ctrl.projection.goal.model_dump()})
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": {
                "attempt_id": "att_1",
                "candidate_id": "cand_1",
                "state": "proposed",
                "hypothesis": "h",
                "strategy_code": "class X: pass",
            }
        },
    )
    ctrl.apply_event("paper_started", {"attempt_id": "att_1", "paper_instance_id": "42"})
    mission_id = ctrl.mission_id
    api_cache = dict(store.MISSIONS)
    print("api_state_after_create   ", ctrl.projection.state)

    # --- worker container: its own cache is empty, so it loads and advances the row ---
    store.MISSIONS.clear()
    worker_ctrl = store.get_controller(mission_id)
    assert worker_ctrl is not None
    worker_ctrl.apply_event(
        "operator_needed",
        {"reason": "paper_sample_insufficient", "missing": ["trades"]},
    )
    print("db_state_after_worker    ", db_state(db, mission_id))

    # --- api container again, still holding the controller it created ---
    store.MISSIONS.clear()
    store.MISSIONS.update(api_cache)
    served = store.get_controller(mission_id)
    assert served is not None
    print("api_serves_to_console    ", served.projection.state)
    print("console_sees_worker_work ", served.projection.state == "needs_operator")

    # --- api writes: does the worker's finding survive? ---
    served.apply_event("budget_extended", {"extra_candidates": 1})
    final = db_state(db, mission_id)
    reasons = [
        event.payload.get("reason")
        for event in served.projection.events
        if event.event_type == "operator_needed"
    ]
    print("db_state_after_api_write ", final)
    print("worker_finding_survived  ", "paper_sample_insufficient" in reasons)
    print("api_write_applied        ", served.projection.goal.budget.max_candidates == 3)
    store.reset_store()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
