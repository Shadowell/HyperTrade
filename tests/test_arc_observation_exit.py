"""An observing mission closes when its race lane ended, or when BitPro says its session is over."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from arc_observation_support import (
    CHALLENGER,
    INSTANCE,
    NOW,
    PARENT,
    STARTED,
    finish_lane,
    observing_mission,
)
from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution_continuation import acceptance_entries
from hypertrade.arc.forward_outcomes import EVIDENCE_VERDICTS, NEUTRAL_VERDICTS
from hypertrade.arc.observation import collect_paper_observation, paper_attempt
from hypertrade.arc.observation_exit import (
    _FINAL_OBSERVATION_KEYS,
    SESSION_ENDED_GRACE,
    end_observation,
    lane_key,
    parse_moment,
)
from hypertrade.arc.pipeline_view import build_pipeline_view
from hypertrade.arc.store import configure_store, list_mission_ids, reset_store
from hypertrade.db import Database

ALL_VERDICTS = (*EVIDENCE_VERDICTS, *NEUTRAL_VERDICTS)


@pytest.fixture
def db():
    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


def _end(controller: ARCController, **kwargs: Any) -> dict[str, Any] | None:
    attempt = paper_attempt(controller)
    assert attempt is not None
    return end_observation(controller, attempt, now=NOW, **kwargs)


def _ended_observation(hours_ago: float, **overrides: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "instance_id": INSTANCE,
        "instance_matched": True,
        "status": "stopped",
        "trades": 7,
        "equity": 100.5,
        "net_return": 0.5,
        "session_ended_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
        "observed_at": (NOW - timedelta(minutes=5)).isoformat(),
        **overrides,
    }


def test_the_verdict_set_is_every_verdict_the_ledger_can_hold() -> None:
    # A new ledger verdict must be looked at here before it can silently close a mission.
    assert set(ALL_VERDICTS) == {
        "won",
        "lost_futility",
        "lost_exam",
        "expired_timeout",
        "superseded",
        "cancelled_operator",
        "cancelled_unknown",
        "ended_unknown",
    }


@pytest.mark.parametrize("verdict", ALL_VERDICTS)
def test_a_finished_lane_closes_the_mission_with_the_ledger_verdict(db, verdict: str) -> None:
    controller = observing_mission()
    row = finish_lane(db, verdict=verdict, ended_at=NOW - timedelta(hours=2))

    result = _end(controller)

    assert result == {"status": "completed", "reason": "race_finished", "verdict": verdict}
    projection = controller.projection
    assert projection.state == "completed"
    assert projection.events[-1].event_type == "paper_observation_ended"
    outcome = projection.paper_outcome
    assert outcome["reason"] == "race_finished"
    assert outcome["verdict"] == verdict
    assert outcome["verdict_source"] == "race_judge"
    assert outcome["outcome_id"] == row["id"]
    assert outcome["parent_strategy_id"] == str(PARENT)
    assert outcome["challenger_strategy_id"] == CHALLENGER
    assert outcome["ended_at"] == row["ended_at"]
    assert outcome["metrics"]["excess_return_pct"] == 1.5
    assert outcome["attempt_id"] == "att1"
    assert outcome["paper_instance_id"] == INSTANCE
    assert list_mission_ids(state="paper_observing") == []
    assert list_mission_ids(state="completed") == ["arc_obs"]


def test_a_lane_that_has_no_row_yet_keeps_the_mission_observing(db) -> None:
    controller = observing_mission()

    assert _end(controller) is None
    assert controller.projection.state == "paper_observing"
    assert controller.projection.paper_outcome == {}


@pytest.mark.parametrize(
    ("parent", "challenger", "target"),
    [(40, CHALLENGER, "bitpro"), (PARENT, "43", "bitpro"), (PARENT, CHALLENGER, "quantlab")],
)
def test_only_the_missions_own_lane_closes_it(
    db, parent: int, challenger: str, target: str
) -> None:
    controller = observing_mission()
    finish_lane(db, parent=parent, challenger=challenger, target=target)

    assert _end(controller) is None
    assert controller.projection.state == "paper_observing"


def test_an_integer_parent_id_matches_its_string_form_in_the_ledger(db) -> None:
    controller = observing_mission(parent=41, challenger="42")
    finish_lane(db, parent="41", challenger="42")

    assert _end(controller) == {
        "status": "completed",
        "reason": "race_finished",
        "verdict": "won",
    }


def test_a_row_written_before_the_session_began_is_another_race_of_the_pair(db) -> None:
    controller = observing_mission()
    finish_lane(db, recorded_at=STARTED - timedelta(seconds=1))

    assert _end(controller) is None
    assert controller.projection.state == "paper_observing"


def test_a_row_written_when_the_session_began_or_later_closes_the_mission(db) -> None:
    controller = observing_mission()
    finish_lane(db, recorded_at=STARTED)

    result = _end(controller)

    assert result is not None and result["reason"] == "race_finished"


def test_a_mission_without_a_start_time_accepts_any_row(db) -> None:
    controller = observing_mission(started=None)
    finish_lane(db, recorded_at=STARTED - timedelta(days=30))

    result = _end(controller)

    assert result is not None and result["reason"] == "race_finished"


def test_a_strategy_the_evolution_loop_did_not_create_is_nobodys_challenger(db) -> None:
    controller = observing_mission(parent=None, challenger="501")
    finish_lane(db, parent=900, challenger="501", verdict="won")

    assert lane_key(controller.projection, paper_attempt(controller)) is None  # type: ignore[arg-type]
    assert _end(controller) is None
    assert controller.projection.state == "paper_observing"


def _lane(context: dict[str, Any] | None, challenger: str | None) -> tuple[str, str, str] | None:
    controller = observing_mission(challenger=challenger)
    assert controller.projection.goal is not None
    controller.projection.goal.evolution_context = context
    return lane_key(controller.projection, controller.projection.attempts[0])


@pytest.mark.parametrize(
    ("context", "challenger", "expected"),
    [
        ({"target_id": "bitpro", "source_strategy_id": 41}, "42", ("bitpro", "41", "42")),
        ({"target_id": "bitpro", "source_strategy_id": "41"}, "42", ("bitpro", "41", "42")),
        ({"target_id": "bitpro", "source_strategy_id": 0}, "42", ("bitpro", "0", "42")),
        ({"source_strategy_id": 41}, "42", None),
        ({"target_id": "", "source_strategy_id": 41}, "42", None),
        ({"target_id": "bitpro"}, "42", None),
        ({"target_id": "bitpro", "source_strategy_id": None}, "42", None),
        ({"target_id": "bitpro", "source_strategy_id": 41}, None, None),
        ({"target_id": "bitpro", "source_strategy_id": 41}, "", None),
        (None, "42", None),
    ],
)
def test_the_lane_key_needs_a_target_a_parent_and_a_challenger(
    db, context: dict[str, Any] | None, challenger: str | None, expected: tuple[str, ...] | None
) -> None:
    assert _lane(context, challenger) == expected


def test_a_mission_that_needs_no_paper_review_is_not_closed_this_way(db) -> None:
    controller = observing_mission(review_required=False)
    finish_lane(db)

    assert _end(controller) is None
    assert controller.projection.state == "paper_observing"


def test_an_attempt_without_a_paper_instance_is_never_closed(db) -> None:
    controller = observing_mission()
    finish_lane(db)
    bare = ARCCandidateAttemptV1(
        attempt_id="att1",
        candidate_id="cand1",
        hypothesis="x",
        strategy_code="class X: pass",
        bitpro_strategy_id=CHALLENGER,
    )

    assert end_observation(controller, bare, now=NOW) is None
    assert controller.projection.state == "paper_observing"


def test_only_an_observing_mission_closes(db) -> None:
    controller = observing_mission(state="needs_operator")
    finish_lane(db)

    assert _end(controller) is None
    assert controller.projection.state == "needs_operator"
    assert controller.projection.paper_outcome == {}


def test_closing_twice_changes_nothing_the_second_time(db) -> None:
    controller = observing_mission()
    finish_lane(db)
    assert _end(controller) is not None
    events = len(controller.projection.events)

    assert _end(controller) is None
    assert len(controller.projection.events) == events
    assert controller.projection.state == "completed"


def test_a_mission_that_moved_on_between_the_read_and_the_write_is_left_alone(db) -> None:
    from hypertrade.arc import store

    controller = observing_mission()
    finish_lane(db)
    # Another process (the api) commits first; this controller still believes it is observing.
    other = store._load_persisted("arc_obs")
    assert other is not None and other is not controller
    other.apply_event("operator_needed", {"reason": "paper_sample_insufficient"})
    assert controller.projection.state == "paper_observing"

    result = _end(controller)

    # The stale controller is rebased onto needs_operator, where the reducer refuses.
    assert result is not None and result["status"] == "skipped"
    assert "not bound to the observed attempt" in result["reason"]
    assert controller.projection.state == "needs_operator"
    assert controller.projection.paper_outcome == {}
    assert not any(
        event.event_type == "paper_observation_ended" for event in controller.projection.events
    )


# --- reducer guards -------------------------------------------------------------------


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "attempt_id": "att1",
        "paper_instance_id": INSTANCE,
        "reason": "race_finished",
        "verdict": "won",
        **overrides,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"attempt_id": "other"},
        {"attempt_id": None},
        {"paper_instance_id": "paper_other"},
        {"paper_instance_id": None},
        {"reason": "because"},
        {"reason": None},
    ],
)
def test_the_reducer_refuses_an_end_that_is_not_bound_to_the_observed_attempt(
    db, overrides: dict[str, Any]
) -> None:
    controller = observing_mission()
    events = len(controller.projection.events)

    with pytest.raises(PermissionError, match="not bound to the observed attempt"):
        controller.apply_event("paper_observation_ended", _payload(**overrides))

    assert controller.projection.state == "paper_observing"
    assert len(controller.projection.events) == events
    assert list_mission_ids(state="paper_observing") == ["arc_obs"]


def test_the_reducer_refuses_an_attempt_that_holds_no_paper_instance(db) -> None:
    controller = observing_mission(instance=None)

    with pytest.raises(PermissionError, match="not bound to the observed attempt"):
        controller.apply_event("paper_observation_ended", _payload(paper_instance_id=None))

    assert controller.projection.state == "paper_observing"


@pytest.mark.parametrize(
    "state", ["paper_provisioning", "needs_operator", "completed", "failed", "live_approval_ready"]
)
def test_the_reducer_closes_only_from_paper_observing(db, state: str) -> None:
    controller = observing_mission(state=state)

    with pytest.raises(PermissionError):
        controller.apply_event("paper_observation_ended", _payload())

    assert controller.projection.state == state


@pytest.mark.parametrize("reason", ["race_finished", "paper_session_ended"])
def test_the_reducer_accepts_both_documented_reasons(db, reason: str) -> None:
    controller = observing_mission()

    controller.apply_event("paper_observation_ended", _payload(reason=reason))

    assert controller.projection.state == "completed"
    assert controller.projection.paper_outcome["reason"] == reason


def test_a_mission_closed_by_the_reducer_leaves_the_review_record_as_it_was(db) -> None:
    controller = observing_mission()
    review = dict(controller.projection.paper_review)

    controller.apply_event("paper_observation_ended", _payload())

    assert controller.projection.paper_review == review
    assert controller.projection.attempts[0].state == "paper_observing"
    assert controller.projection.attempts[0].paper_instance_id == INSTANCE


# --- the session BitPro says is over --------------------------------------------------


def test_a_session_that_ended_long_ago_closes_a_mission_with_no_ledger_row(db) -> None:
    controller = observing_mission(observation=_ended_observation(hours_ago=2))

    result = _end(controller)

    assert result == {"status": "completed", "reason": "paper_session_ended", "verdict": None}
    outcome = controller.projection.paper_outcome
    assert outcome["reason"] == "paper_session_ended"
    assert outcome["session_ended_at"] == (NOW - timedelta(hours=2)).isoformat()
    assert "verdict" not in outcome and "outcome_id" not in outcome
    assert controller.projection.state == "completed"


def test_the_grace_period_gives_the_race_judge_time_to_write_the_verdict(db) -> None:
    just_ended = observing_mission(
        "arc_just", observation=_ended_observation(hours_ago=0.99)
    )
    exactly_grace = observing_mission(
        "arc_grace",
        observation=_ended_observation(hours_ago=SESSION_ENDED_GRACE.total_seconds() / 3600),
    )

    assert _end(just_ended) is None
    assert just_ended.projection.state == "paper_observing"
    result = _end(exactly_grace)
    assert result is not None and result["reason"] == "paper_session_ended"


@pytest.mark.parametrize(
    "overrides",
    [
        {"instance_matched": False},
        {"instance_matched": None},
        {"instance_matched": 1},
        {"instance_matched": "true"},
        {"instance_id": "paper_other"},
        {"session_ended_at": None},
        {"session_ended_at": "soon"},
        {"session_ended_at": 123},
    ],
)
def test_an_unconfirmed_or_unreadable_session_end_does_not_close(
    db, overrides: dict[str, Any]
) -> None:
    controller = observing_mission(observation=_ended_observation(5, **overrides))

    assert _end(controller) is None
    assert controller.projection.state == "paper_observing"


def test_a_ledger_verdict_wins_over_a_reported_session_end(db) -> None:
    controller = observing_mission(observation=_ended_observation(hours_ago=5))
    finish_lane(db, verdict="lost_exam")

    result = _end(controller)

    assert result == {"status": "completed", "reason": "race_finished", "verdict": "lost_exam"}
    assert "session_ended_at" not in controller.projection.paper_outcome


def test_the_closing_event_carries_only_the_allowlisted_final_observation(db) -> None:
    controller = observing_mission(
        observation=_ended_observation(3, raw_keys=["secret"], reported_instance_id="x")
    )

    _end(controller)

    final = controller.projection.paper_outcome["final_observation"]
    assert set(final) == set(_FINAL_OBSERVATION_KEYS)
    assert final["trades"] == 7 and final["equity"] == 100.5


def test_without_a_database_only_the_session_end_can_close_a_mission() -> None:
    reset_store()
    still_running = observing_mission("arc_mem_a")
    over = observing_mission("arc_mem_b", observation=_ended_observation(2))

    assert _end(still_running) is None
    assert _end(over) == {"status": "completed", "reason": "paper_session_ended", "verdict": None}
    reset_store()


def test_parse_moment_reads_iso_strings_and_datetimes_as_utc() -> None:
    assert parse_moment("2026-11-02T12:00:00Z") == NOW
    assert parse_moment("2026-11-02T12:00:00") == NOW
    assert parse_moment(NOW.replace(tzinfo=None)) == NOW
    assert parse_moment("2026-11-02T20:00:00+08:00") == NOW
    for unreadable in (None, "", "yesterday", 5, 1.5, {}):
        assert parse_moment(unreadable) is None


# --- what the rest of the system sees after the mission closed -----------------------


def test_a_closed_mission_no_longer_holds_its_parent_busy(db) -> None:
    from hypertrade.arc.evolution import EvolutionConfig
    from hypertrade.arc.research_budget import source_key, usage

    controller = observing_mission()
    key = source_key("bitpro", PARENT, "paper_parent")
    with db.session() as session:
        before = usage(session, EvolutionConfig(), NOW)
    assert before["sources"][key]["busy"] is True

    finish_lane(db)
    assert _end(controller) is not None

    with db.session() as session:
        after = usage(session, EvolutionConfig(), NOW)
    assert after["sources"][key]["busy"] is False


def test_the_pipeline_shows_how_the_observation_ended(db) -> None:
    controller = observing_mission()
    assert _paper_stage(controller)["detail"] == "持续模拟观察，运行数据用于下一轮研究"
    finish_lane(db, verdict="lost_exam")
    _end(controller)

    view = build_pipeline_view(controller.projection, now=NOW)
    stage = _paper_stage(controller)

    assert view["finished"] is True
    assert stage["status"] == "done"
    assert stage["detail"] == "模拟盘观察已结束：终考未通过，被淘汰"
    assert stage["metrics"]["outcome"]["verdict"] == "lost_exam"
    assert stage["metrics"]["outcome"]["reason"] == "race_finished"


def test_the_pipeline_words_a_session_end_and_an_unknown_verdict_plainly(db) -> None:
    ended = observing_mission(observation=_ended_observation(2))
    _end(ended)
    assert _paper_stage(ended)["detail"] == "模拟盘观察已结束：BitPro 的模拟盘会话已结束"

    odd = observing_mission("arc_odd")
    odd.apply_event("paper_observation_ended", _payload(verdict="brand_new_verdict"))
    assert _paper_stage(odd)["detail"] == "模拟盘观察已结束：赛道已结束"


def _paper_stage(controller: ARCController) -> dict[str, Any]:
    view = build_pipeline_view(controller.projection, now=NOW)
    return next(stage for stage in view["stages"] if stage["key"] == "paper")


def test_the_acceptance_ledger_records_the_close_as_a_terminal_stage(db) -> None:
    controller = observing_mission()
    finish_lane(db)
    _end(controller)

    entries = acceptance_entries(controller.projection, NOW)

    terminal = [entry for entry in entries if entry["stage"] == "terminal"]
    assert len(terminal) == 1
    assert terminal[0]["payload"]["reason"] == "race_finished"


def test_the_effectiveness_report_counts_a_closed_mission_as_completed(db) -> None:
    from hypertrade.arc.effectiveness import build_effectiveness_report

    controller = observing_mission()
    assert build_effectiveness_report(db, now=NOW).missions_completed == 0
    finish_lane(db)
    _end(controller)

    report = build_effectiveness_report(db, now=NOW)

    assert report.missions_total == 1 and report.missions_completed == 1
    assert report.missions_active == 0


@pytest.mark.parametrize(
    ("verdict", "label"),
    [
        ("won", "挑战者胜出，已接班"),
        ("lost_futility", "中途判定落后，被淘汰"),
        ("lost_exam", "终考未通过，被淘汰"),
        ("expired_timeout", "超过期限仍无结论，被淘汰"),
        ("superseded", "位置被其他挑战者接管"),
        ("cancelled_operator", "被人工取消"),
        ("cancelled_unknown", "被取消，原因未知"),
        ("ended_unknown", "BitPro 已不再保留该赛道"),
    ],
)
def test_every_ledger_verdict_has_a_plain_label_in_the_pipeline(
    db, verdict: str, label: str
) -> None:
    controller = observing_mission()
    finish_lane(db, verdict=verdict)
    _end(controller)

    assert _paper_stage(controller)["detail"] == f"模拟盘观察已结束：{label}"


_NO_SESSION = object()


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ({"ended_at": "2026-11-02T10:00:00+00:00"}, "2026-11-02T10:00:00+00:00"),
        ({"ended_at": None}, None),
        ({}, None),
        ({"ended_at": 12345}, None),
        ("stopped", None),
        (None, None),
        (_NO_SESSION, None),
    ],
)
def test_the_observation_names_a_session_end_only_when_bitpro_sent_one(
    session: object, expected: str | None
) -> None:
    body: dict[str, Any] = {"instance_id": INSTANCE, "status": "stopped", "trade_count": 3}
    if session is not _NO_SESSION:
        body["session"] = session

    class _Client:
        def paper_snapshot(self, **kwargs: object) -> dict[str, object]:
            return {"snapshot": body}

        def health(self) -> dict[str, object]:
            return {"status": "ok"}

    attempt = ARCCandidateAttemptV1(
        attempt_id="att1",
        candidate_id="cand1",
        hypothesis="x",
        strategy_code="class X: pass",
        bitpro_strategy_id=CHALLENGER,
        paper_instance_id=INSTANCE,
    )

    observation = collect_paper_observation(attempt, _Client())

    assert observation["session_ended_at"] == expected
    assert observation["instance_matched"] is True
