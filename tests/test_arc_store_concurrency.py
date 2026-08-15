"""api and worker advance one mission from two processes.

Each keeps its own ``store.MISSIONS`` cache over a shared row, which is modelled here
by swapping that cache. Before revisions, the API served a mission that had stopped
being true and its next write erased whatever the worker had committed.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from hypertrade.arc import store
from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.db import Database


@pytest.fixture
def db() -> Iterator[Database]:
    store.reset_store()
    database = Database("sqlite:///:memory:")
    database.create_all()
    store.configure_store(database)
    yield database
    store.reset_store()


def _paper_observing_mission() -> ARCController:
    controller = ARCController(
        goal=ARCGoalV1(objective="two writers", budget=ARCBudgetV1(max_candidates=2))
    )
    controller.apply_event("goal_compiled", {"goal": controller.projection.goal.model_dump()})
    controller.apply_event(
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
    controller.apply_event("paper_started", {"attempt_id": "att_1", "paper_instance_id": "42"})
    return controller


def _in_other_process(mission_id: str, event_type: str, payload: dict[str, Any]) -> None:
    """Advance the mission from a process whose controller cache is cold."""
    holding = dict(store.MISSIONS)
    store.MISSIONS.clear()
    other = store.get_controller(mission_id)
    assert other is not None
    other.apply_event(event_type, payload)
    store.MISSIONS.clear()
    store.MISSIONS.update(holding)


def test_reader_sees_a_mission_the_other_process_advanced(db: Database) -> None:
    controller = _paper_observing_mission()
    assert controller.projection.state == "paper_observing"

    _in_other_process(
        controller.mission_id,
        "operator_needed",
        {"reason": "paper_sample_insufficient"},
    )

    served = store.get_controller(controller.mission_id)
    assert served is not None
    assert served.projection.state == "needs_operator"


def test_writer_does_not_erase_what_the_other_process_committed(db: Database) -> None:
    controller = _paper_observing_mission()
    _in_other_process(
        controller.mission_id,
        "operator_needed",
        {"reason": "paper_sample_insufficient"},
    )

    # The stale controller writes. Its event must land on the committed mission.
    controller.apply_event("budget_extended", {"extra_candidates": 1})

    reasons = [
        event.payload.get("reason")
        for event in controller.projection.events
        if event.event_type == "operator_needed"
    ]
    assert "paper_sample_insufficient" in reasons
    assert controller.projection.goal is not None
    assert controller.projection.goal.budget.max_candidates == 3
    assert controller.projection.state == "exploring_candidates"

    reloaded = store.get_controller(controller.mission_id)
    assert reloaded is not None
    assert reloaded.projection.state == "exploring_candidates"


def test_paper_instance_survives_a_concurrent_writer(db: Database) -> None:
    """The stale writer must not resurrect a projection without the paper instance."""
    controller = ARCController(
        goal=ARCGoalV1(objective="paper id", budget=ARCBudgetV1(max_candidates=2))
    )
    controller.apply_event("goal_compiled", {"goal": controller.projection.goal.model_dump()})
    controller.apply_event(
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
    _in_other_process(
        controller.mission_id,
        "paper_started",
        {"attempt_id": "att_1", "paper_instance_id": "99"},
    )

    controller.apply_event("budget_extended", {"extra_candidates": 1})

    assert controller.projection.attempts[0].paper_instance_id == "99"


def test_revision_advances_with_every_committed_event(db: Database) -> None:
    controller = _paper_observing_mission()
    before = controller.revision
    controller.apply_event("budget_extended", {"extra_candidates": 1})
    assert controller.revision == before + 1

    reloaded = store.get_controller(controller.mission_id)
    assert reloaded is not None
    assert reloaded.revision == controller.revision


def test_single_process_keeps_the_live_controller_identity(db: Database) -> None:
    """A read with nobody else writing must not rebuild the controller."""
    controller = _paper_observing_mission()
    assert store.get_controller(controller.mission_id) is controller


def test_store_without_a_database_still_reduces_and_reads() -> None:
    store.reset_store()
    controller = _paper_observing_mission()
    assert controller.projection.state == "paper_observing"
    assert store.get_controller(controller.mission_id) is controller
    assert store.list_mission_ids(state="paper_observing") == [controller.mission_id]
    store.reset_store()
