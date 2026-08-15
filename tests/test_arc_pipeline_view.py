"""The console reads mission progress from the projection, never from event payloads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc import store
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCGoalV1,
    LiveApprovalPackageV1,
    PaperObservationPolicyV1,
    PaperPreauthorizationV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence_view import build_mission_summary
from hypertrade.arc.pipeline_view import STAGES, build_pipeline_badge, build_pipeline_view

SECRET_CODE = "class SecretAlpha:\n    edge = 'do not leak'\n"


@pytest.fixture(autouse=True)
def _memory_store() -> None:
    store.reset_store()


def _mission(**goal_kwargs: object) -> ARCController:
    goal = ARCGoalV1(
        objective="find an edge",
        symbols=["ETH-USDT-SWAP"],
        timeframes=["1H"],
        budget=ARCBudgetV1(max_candidates=4),
        paper_authorization=PaperPreauthorizationV1(symbols=["ETH-USDT-SWAP"]),
        observation=PaperObservationPolicyV1(min_hours=24, min_trades=10),
        **goal_kwargs,
    )
    controller = ARCController(goal=goal)
    controller.apply_event("goal_compiled", {"goal": goal.model_dump()})
    return controller


def _propose(controller: ARCController, attempt_id: str) -> None:
    controller.apply_event(
        "candidate_proposed",
        {
            "attempt": {
                "attempt_id": attempt_id,
                "candidate_id": f"cand_{attempt_id}",
                "state": "proposed",
                "hypothesis": "h",
                "strategy_code": SECRET_CODE,
            }
        },
    )


def _stage(view: dict, key: str) -> dict:
    return next(item for item in view["stages"] if item["key"] == key)


def test_stage_list_is_ordered_and_complete() -> None:
    view = build_pipeline_view(_mission().projection)
    assert [item["key"] for item in view["stages"]] == [key for key, _ in STAGES]


def test_a_fresh_mission_sits_on_candidate_exploration() -> None:
    view = build_pipeline_view(_mission().projection)
    assert view["current_stage"] == "explore"
    assert _stage(view, "goal")["status"] == "done"
    assert _stage(view, "explore")["status"] == "active"
    assert _stage(view, "paper")["status"] == "pending"
    assert view["blocked"] is False


def test_progress_advances_with_the_mission() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    controller.apply_event(
        "red_team_tested",
        {"attempt_id": "att_1", "passed": True, "metrics": {"ranking_sharpe": 1.4}},
    )
    view = build_pipeline_view(controller.projection)
    assert _stage(view, "explore")["status"] == "done"
    assert _stage(view, "red_team")["status"] == "done"
    assert view["current_stage"] == "validate"
    assert _stage(view, "red_team")["metrics"] == {"tested": 1, "survived": 1, "ratio": 1.0}


def test_paper_stage_reports_window_progress() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    controller.apply_event("paper_started", {"attempt_id": "att_1", "paper_instance_id": "77"})
    controller.apply_event(
        "paper_observed",
        {"attempt_id": "att_1", "observation": {"trades": 5, "equity": 101.0}},
    )
    started = controller.projection.paper_started_at
    assert started is not None
    later = started.replace(tzinfo=UTC) + timedelta(hours=6)

    view = build_pipeline_view(controller.projection, now=later)
    paper = _stage(view, "paper")
    assert view["current_stage"] == "paper"
    assert paper["status"] == "active"
    assert paper["metrics"]["elapsed_hours"] == pytest.approx(6.0, abs=0.05)
    assert paper["metrics"]["trades"] == 5
    assert paper["metrics"]["instance_id"] == "77"
    # The window needs both hours and trades, so the shorter leg drives the bar.
    assert paper["metrics"]["ratio"] == pytest.approx(0.25, abs=0.01)


def test_a_stalled_mission_marks_the_stage_it_could_not_finish() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    controller.apply_event("red_team_tested", {"attempt_id": "att_1", "passed": False})
    controller.apply_event(
        "operator_needed",
        {"reason": "no_validated_candidate", "missing": ["oos_sharpe"]},
    )

    view = build_pipeline_view(controller.projection)
    assert view["blocked"] is True
    # Every candidate was tested and none survived, so the red team is where it stopped.
    assert _stage(view, "red_team")["status"] == "blocked"
    assert _stage(view, "explore")["status"] == "done"
    assert _stage(view, "validate")["status"] == "pending"
    assert view["blocked_reason"]["reason"] == "no_validated_candidate"
    assert view["blocked_reason"]["missing"] == ["oos_sharpe"]


def test_a_blocked_mission_does_not_animate_its_bar() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    controller.apply_event("operator_needed", {"reason": "evidence_window_unavailable"})
    view = build_pipeline_view(controller.projection)
    # One of seven stages behind it, and no partial credit for the stage it failed in.
    assert view["percent"] == pytest.approx(100 / 7, abs=0.1)
    assert _stage(view, "explore")["status"] == "blocked"


def test_a_promoted_mission_reports_every_stage_done() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    controller.apply_event(
        "live_promoted",
        {"attempt_id": "att_1", "live_instance_id": "live_9", "package_hash": "h"},
    )
    view = build_pipeline_view(controller.projection)
    assert view["finished"] is True
    assert view["percent"] == 100.0
    assert view["current_stage"] is None
    assert all(item["status"] == "done" for item in view["stages"])


def test_activity_never_carries_strategy_source() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    controller.apply_event(
        "candidate_mutated",
        {"attempt_id": "att_1", "strategy_code": SECRET_CODE},
    )
    view = build_pipeline_view(controller.projection)

    assert SECRET_CODE not in repr(view)
    assert all("strategy_code" not in row["detail"] for row in view["activity"])
    assert view["activity"][0]["label"] == "变异候选"
    assert view["activity"][0]["detail"]["attempt_id"] == "att_1"


def test_activity_is_newest_first_and_bounded() -> None:
    controller = _mission()
    for index in range(20):
        _propose(controller, f"att_{index}")
    view = build_pipeline_view(controller.projection)
    assert len(view["activity"]) == 12
    stamps = [row["at"] for row in view["activity"]]
    assert stamps == sorted(stamps, reverse=True)


def test_freshness_is_reported_so_the_console_can_show_staleness() -> None:
    controller = _mission()
    later = controller.projection.updated_at.replace(tzinfo=UTC) + timedelta(seconds=42)
    view = build_pipeline_view(controller.projection, now=later)
    assert view["seconds_since_update"] == pytest.approx(42.0, abs=0.5)


def test_mission_summary_carries_the_badge_a_list_row_renders() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    summary = build_mission_summary(controller.projection)
    badge = summary["pipeline"]
    assert badge["current_stage"] == "explore"
    assert badge["stage_total"] == len(STAGES)
    assert badge["blocked"] is False
    assert badge == build_pipeline_badge(controller.projection)


def test_approval_stage_refuses_to_look_ready_with_open_unknowns() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    controller.apply_event("paper_started", {"attempt_id": "att_1", "paper_instance_id": "77"})
    package = LiveApprovalPackageV1(
        mission_id=controller.mission_id,
        status="incomplete",
        recommendation="wait",
        package_hash="hash",
        unknowns=["paper_instance_unconfirmed"],
    )
    controller.apply_event("live_approval_ready", {"package": package.model_dump(mode="json")})

    view = build_pipeline_view(controller.projection)
    approval = _stage(view, "approval")
    assert view["blocked"] is True
    assert approval["status"] == "blocked"
    assert approval["metrics"]["unknowns"] == 1


def test_view_matches_the_projection_after_a_reload() -> None:
    controller = _mission()
    _propose(controller, "att_1")
    reloaded = store.get_controller(controller.mission_id)
    assert reloaded is not None
    now = datetime.now(UTC)
    assert build_pipeline_view(reloaded.projection, now=now) == build_pipeline_view(
        controller.projection, now=now
    )
