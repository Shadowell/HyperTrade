"""The observation loop reads BitPro at most once per interval, and closes what has ended."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from arc_observation_support import (
    NOW,
    FakeBitPro,
    finish_lane,
    observing_mission,
)
from hypertrade.arc.observation import observe_arc_missions_once, observe_mission
from hypertrade.arc.observation_exit import end_observation as real_end_observation
from hypertrade.arc.store import configure_store, get_controller, reset_store
from hypertrade.config import get_settings
from hypertrade.db import Database
from pydantic import ValidationError


@pytest.fixture
def db():
    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


def _observed(controller) -> list[Any]:
    return [
        event for event in controller.projection.events if event.event_type == "paper_observed"
    ]


def _result(results: list[dict[str, Any]], mission_id: str) -> dict[str, Any]:
    return next(item for item in results if item["mission_id"] == mission_id)


def test_a_first_round_records_and_then_waits_for_the_interval(db) -> None:
    observing_mission()
    client = FakeBitPro()

    first = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert first["observed"] == 1 and first["skipped"] == 0 and first["closed"] == 0
    assert client.snapshot_calls == 1
    assert client.health_calls >= 1
    controller = get_controller("arc_obs")
    assert controller is not None
    assert len(_observed(controller)) == 1
    observation = controller.projection.paper_observation
    assert observation["observed_at"] == NOW.isoformat()
    assert observation["ok"] is True
    assert observation["session_ended_at"] is None

    for offset in (60, 120, 300, 3599):
        sweep = observe_arc_missions_once(
            client, now=NOW + timedelta(seconds=offset), record_seconds=3600
        )
        assert sweep["observed"] == 0 and sweep["skipped"] == 1
        assert sweep["results"] == [
            {"mission_id": "arc_obs", "status": "paper_observing", "skipped": True}
        ]

    assert client.snapshot_calls == 1
    assert len(_observed(controller)) == 1

    due = observe_arc_missions_once(client, now=NOW + timedelta(seconds=3600), record_seconds=3600)

    assert due["observed"] == 1 and due["skipped"] == 0
    assert client.snapshot_calls == 2
    assert len(_observed(controller)) == 2
    assert controller.projection.paper_observation["observed_at"] == (
        NOW + timedelta(seconds=3600)
    ).isoformat()


def test_one_day_records_exactly_once_an_hour(db) -> None:
    observing_mission()
    client = FakeBitPro()
    controller = get_controller("arc_obs")
    assert controller is not None

    for step in range(1440):
        observe_arc_missions_once(
            client, now=NOW + timedelta(seconds=step * 60), record_seconds=3600
        )

    assert len(_observed(controller)) == 24
    assert client.snapshot_calls == 24


def test_a_failed_read_still_records_its_time_and_is_not_retried_at_once(db) -> None:
    observing_mission()
    client = FakeBitPro(error=RuntimeError("down"))

    first = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert first["observed"] == 1
    controller = get_controller("arc_obs")
    assert controller is not None
    observation = controller.projection.paper_observation
    assert observation["ok"] is False
    assert observation["observed_at"] == NOW.isoformat()

    retry = observe_arc_missions_once(
        client, now=NOW + timedelta(seconds=60), record_seconds=3600
    )

    assert retry["skipped"] == 1
    assert client.snapshot_calls == 1


def test_an_old_record_without_a_readable_observed_at_is_due_at_once(db) -> None:
    observing_mission(observation={"ok": True, "trades": 3})
    client = FakeBitPro()

    first = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert first["observed"] == 1

    observing_mission(
        "arc_old",
        parent=51,
        challenger="52",
        instance="paper_52",
        observation={"observed_at": "garbage"},
    )
    second = observe_arc_missions_once(
        FakeBitPro(instance="paper_52"), now=NOW, record_seconds=3600
    )

    assert second["observed"] == 1
    other = get_controller("arc_old")
    assert other is not None
    assert other.projection.paper_observation["observed_at"] == NOW.isoformat()


def test_the_default_interval_comes_from_settings(db) -> None:
    observing_mission(observation={"observed_at": NOW.isoformat(), "ok": True})
    client = FakeBitPro()

    before = observe_arc_missions_once(client, now=NOW + timedelta(seconds=3599))
    assert before["observed"] == 0 and before["skipped"] == 1

    at = observe_arc_missions_once(client, now=NOW + timedelta(seconds=3600))
    assert at["observed"] == 1 and at["skipped"] == 0


def test_the_interval_can_be_set_from_the_environment(db, monkeypatch) -> None:
    observing_mission(observation={"observed_at": NOW.isoformat(), "ok": True})
    monkeypatch.setenv("ARC_OBSERVATION_RECORD_SECONDS", "120")
    get_settings.cache_clear()
    client = FakeBitPro()

    before = observe_arc_missions_once(client, now=NOW + timedelta(seconds=119))
    assert before["observed"] == 0 and before["skipped"] == 1

    at = observe_arc_missions_once(client, now=NOW + timedelta(seconds=120))
    assert at["observed"] == 1 and at["skipped"] == 0

    get_settings.cache_clear()


def test_the_interval_has_a_lower_and_an_upper_bound(monkeypatch) -> None:
    monkeypatch.setenv("ARC_OBSERVATION_RECORD_SECONDS", "30")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()

    monkeypatch.setenv("ARC_OBSERVATION_RECORD_SECONDS", "86401")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()

    get_settings.cache_clear()


def test_a_finished_lane_closes_without_touching_bitpro(db) -> None:
    observing_mission()
    finish_lane(db, verdict="won")
    client = FakeBitPro()

    first = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert first["closed"] == 1 and first["observed"] == 0
    assert client.snapshot_calls == 0
    assert first["results"] == [
        {
            "mission_id": "arc_obs",
            "status": "completed",
            "reason": "race_finished",
            "verdict": "won",
        }
    ]
    controller = get_controller("arc_obs")
    assert controller is not None
    assert controller.projection.state == "completed"

    again = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert again["results"] == []
    assert again["observed"] == 0 and again["skipped"] == 0 and again["closed"] == 0


def test_the_exit_can_be_switched_off(db, monkeypatch) -> None:
    observing_mission()
    finish_lane(db)
    client = FakeBitPro()

    off = observe_arc_missions_once(client, now=NOW, record_seconds=3600, exit_enabled=False)

    assert off["observed"] == 1 and off["closed"] == 0
    controller = get_controller("arc_obs")
    assert controller is not None
    assert controller.projection.state == "paper_observing"

    monkeypatch.setenv("ARC_OBSERVATION_EXIT_ENABLED", "false")
    get_settings.cache_clear()
    from_env = observe_arc_missions_once(
        client, now=NOW + timedelta(seconds=3600), record_seconds=3600, exit_enabled=None
    )

    assert from_env["observed"] == 1 and from_env["closed"] == 0
    assert controller.projection.state == "paper_observing"

    on = observe_arc_missions_once(
        client, now=NOW + timedelta(seconds=7200), record_seconds=3600, exit_enabled=True
    )

    assert on["closed"] == 1
    assert controller.projection.state == "completed"


def test_a_session_that_ended_beyond_the_grace_closes_the_same_round(db) -> None:
    observing_mission()
    ended_at = (NOW - timedelta(hours=2)).isoformat()
    client = FakeBitPro(status="stopped", ended_at=ended_at)

    sweep = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert sweep["observed"] == 1 and sweep["closed"] == 1
    assert sweep["results"] == [
        {
            "mission_id": "arc_obs",
            "status": "completed",
            "reason": "paper_session_ended",
            "verdict": None,
        }
    ]
    controller = get_controller("arc_obs")
    assert controller is not None
    types = [event.event_type for event in controller.projection.events]
    assert types[-2:] == ["paper_observed", "paper_observation_ended"]
    assert controller.projection.paper_outcome["session_ended_at"] == ended_at


def test_a_session_end_inside_the_grace_waits_for_the_next_round(db) -> None:
    observing_mission()
    client = FakeBitPro(
        status="stopped", ended_at=(NOW - timedelta(minutes=10)).isoformat()
    )

    first = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert first["observed"] == 1 and first["closed"] == 0
    controller = get_controller("arc_obs")
    assert controller is not None
    assert controller.projection.state == "paper_observing"

    later = observe_arc_missions_once(
        client, now=NOW + timedelta(seconds=3600), record_seconds=3600
    )

    assert later["closed"] == 1


def test_one_missions_failing_exit_check_does_not_stop_the_others(db, monkeypatch) -> None:
    observing_mission("arc_a")
    observing_mission("arc_b", parent=51, challenger="52", instance="paper_52")
    finish_lane(db, parent=51, challenger="52")

    def fake(controller, attempt, **kwargs):
        if controller.mission_id == "arc_a":
            raise RuntimeError("boom")
        return real_end_observation(controller, attempt, **kwargs)

    monkeypatch.setattr("hypertrade.arc.observation.end_observation", fake)
    client = FakeBitPro()

    sweep = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert sweep["closed"] == 1
    assert sweep["observed"] == 1
    assert _result(sweep["results"], "arc_b")["status"] == "completed"
    a = get_controller("arc_a")
    b = get_controller("arc_b")
    assert a is not None and b is not None
    assert a.projection.state == "paper_observing"
    assert b.projection.state == "completed"
    assert len(_observed(a)) == 1


def test_feedback_runs_every_round_for_observing_missions_that_enabled_it(db, monkeypatch) -> None:
    observing_mission("arc_a", feedback=True)
    observing_mission(
        "arc_b", parent=51, challenger="52", instance="paper_52", feedback=True
    )
    observing_mission("arc_c", parent=61, challenger="62", instance="paper_62")
    finish_lane(db, parent=51, challenger="52")
    calls: list[str] = []

    def stub(mission_id, client=None):
        calls.append(mission_id)
        return {"status": "stub"}

    monkeypatch.setattr("hypertrade.arc.feedback.check_paper_feedback", stub)
    client = FakeBitPro()

    first = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert calls == ["arc_a"]
    assert _result(first["results"], "arc_a")["feedback"] == {"status": "stub"}
    assert "feedback" not in _result(first["results"], "arc_c")

    observe_arc_missions_once(client, now=NOW + timedelta(seconds=60), record_seconds=3600)

    assert calls == ["arc_a", "arc_a"]


def test_calling_observe_mission_directly_never_throttles(db) -> None:
    controller = observing_mission()

    observe_mission(controller, FakeBitPro(), now=NOW)
    observe_mission(controller, FakeBitPro(), now=NOW + timedelta(seconds=1))

    live = get_controller("arc_obs")
    assert live is not None
    assert len(_observed(live)) == 2
    assert live.projection.paper_observation["observed_at"] == (
        NOW + timedelta(seconds=1)
    ).isoformat()


def test_missions_in_other_states_are_not_swept(db) -> None:
    observing_mission(state="needs_operator")
    client = FakeBitPro()

    sweep = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert sweep == {"observed": 0, "skipped": 0, "closed": 0, "results": []}
    assert client.snapshot_calls == 0


def test_one_sweep_counts_observed_skipped_and_closed_separately(db) -> None:
    observing_mission("arc_a")
    observing_mission(
        "arc_b",
        parent=51,
        challenger="52",
        instance="paper_52",
        observation={"observed_at": (NOW - timedelta(minutes=5)).isoformat(), "ok": True},
    )
    observing_mission("arc_c", parent=61, challenger="62", instance="paper_62")
    finish_lane(db, parent=61, challenger="62")
    client = FakeBitPro()

    sweep = observe_arc_missions_once(client, now=NOW, record_seconds=3600)

    assert sweep["observed"] == 1
    assert sweep["skipped"] == 1
    assert sweep["closed"] == 1
    assert len(sweep["results"]) == 3
    assert _result(sweep["results"], "arc_b")["skipped"] is True
    assert _result(sweep["results"], "arc_c")["status"] == "completed"
