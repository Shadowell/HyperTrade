"""What the worker's periodic scans load of the ARC history, and what they keep of it.

Every few seconds the worker walked every mission it had ever stored, finished ones included, and
``get_controller`` parked each of them in ``store.MISSIONS`` for good: ~2 GB of event journals.
Every full garbage collection walked all of it with the GIL held, which froze the event loop for
seconds (``workers[].stalls_total``, cause ``gc``). These tests pin that a scan asks for the
missions it acts on, reads a journal only when it uses it, and leaves nothing resident behind.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, get_args

import pytest
from hypertrade import worker
from hypertrade.arc import (
    auto_review,
    avo,
    evolution,
    evolution_continuation,
    paper_effect_reconcile,
    research_budget,
    selection_bias,
    store,
)
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import (
    ARCController,
    ARCEventV1,
    ARCMissionProjection,
    ARCMissionState,
)
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.evolution_continuation import ContinuationLedger
from hypertrade.arc.evolution_models import EvolutionAcceptance, EvolutionContinuation
from hypertrade.db import ArcHypothesisNode, ArcMission, Database
from hypertrade.memory import arc_integration
from hypertrade.runtime import heartbeat
from hypertrade.runtime.heartbeat import flush_heartbeat, read_worker_status
from sqlalchemy import select

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)


@pytest.fixture
def db() -> Iterator[Database]:
    store.reset_store()
    database = Database("sqlite:///:memory:")
    database.create_all()
    store.configure_store(database)
    selection_bias._FACTS.clear()
    yield database
    selection_bias._FACTS.clear()
    store.reset_store()


@pytest.fixture
def journal_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The ids of the missions whose event journal is read, in order."""
    reads: list[str] = []
    real = store._stored_events

    def spy(session: Any, mission_id: str) -> Any:
        reads.append(mission_id)
        return real(session, mission_id)

    monkeypatch.setattr(store, "_stored_events", spy)
    return reads


def _goal(**overrides: Any) -> ARCGoalV1:
    return ARCGoalV1(
        objective="scan footprint",
        paper_review_required=True,
        research_mode="avo",
        research_windows=ResearchWindowsV1(),
        paper_initial_equity=Decimal("100"),
        budget=ARCBudgetV1(max_candidates=3),
        **overrides,
    )


def _attempt(name: str) -> ARCCandidateAttemptV1:
    return ARCCandidateAttemptV1(
        attempt_id=name,
        candidate_id=name,
        hypothesis=f"hypothesis {name}",
        strategy_code=f"class Strategy_{name}: pass",
        strategy_spec={"timeframe": "1D"},
    )


def _mission(state: str, *, reason: str = "avo_effect_unknown", **goal: Any) -> ARCController:
    controller = ARCController(goal=_goal(**goal))
    controller.apply_event("goal_compiled", {"goal": controller.projection.goal.model_dump()})
    if state == "paper_observing":
        attempt = _attempt("att_observed").model_dump(mode="json")
        controller.apply_event("candidate_proposed", {"attempt": attempt})
        controller.apply_event(
            "paper_started", {"attempt_id": "att_observed", "paper_instance_id": "42"}
        )
    elif state == "failed":
        controller.apply_event("mission_failed", {})
    elif state == "completed":
        controller.apply_event("mission_completed", {})
    elif state == "needs_operator":
        controller.apply_event("operator_needed", {"reason": reason})
    else:
        assert state == "exploring_candidates"
    assert controller.projection.state == state
    return controller


def _research_mission(state: str, number: int, **kwargs: Any) -> ARCController:
    """A mission the evolution loop launched for the source strategy ``7 + number``."""
    context = {
        "source_strategy_id": 7 + number,
        "source_instance_id": f"instance-{number}",
        "target_id": "bitpro",
        "trigger_source": "degradation",
    }
    return _mission(state, evolution_context=context, **kwargs)


STATES = ("exploring_candidates", "needs_operator", "paper_observing", "failed", "completed")


def _resident() -> tuple[int, int]:
    """How many missions, and how many events of them, this process holds."""
    stats = store.cache_stats()
    return stats["missions"], stats["events"]


# --- the store -----------------------------------------------------------------------------


def _assert_state_filters(ids: dict[str, str]) -> None:
    def listed(**kwargs: Any) -> list[str]:
        return sorted(store.list_mission_ids(**kwargs))

    assert listed() == sorted(ids.values())
    assert listed(state="failed") == [ids["failed"]]
    assert listed(states={"failed", "completed"}) == sorted([ids["failed"], ids["completed"]])
    assert listed(states=frozenset({"paper_observing"})) == [ids["paper_observing"]]
    assert listed(states=["needs_operator"]) == [ids["needs_operator"]]
    assert listed(states=set()) == []
    # Both given: a mission has to satisfy both.
    assert listed(state="failed", states={"failed", "completed"}) == [ids["failed"]]
    assert listed(state="failed", states={"completed"}) == []


def test_list_mission_ids_asks_the_database_for_the_wanted_states(db: Database) -> None:
    _assert_state_filters({state: _mission(state).mission_id for state in STATES})


def test_list_mission_ids_filters_the_in_memory_store_the_same_way() -> None:
    store.reset_store()
    try:
        _assert_state_filters({state: _mission(state).mission_id for state in STATES})
    finally:
        store.reset_store()


def test_a_projection_loaded_without_events_leaves_the_journal_unread(
    db: Database, journal_reads: list[str]
) -> None:
    mission = _mission("failed")
    with db.session() as session:
        row = session.get(ArcMission, mission.mission_id)
        assert row is not None
        light = store.load_projection(session, row, with_events=False)
        assert journal_reads == []
        full = store.load_projection(session, row)
    assert journal_reads == [mission.mission_id]
    assert light.events == []
    assert [e.event_id for e in full.events] == [e.event_id for e in mission.projection.events]
    # Everything that is not the journal is the same either way.
    assert light.model_dump(exclude={"events"}) == full.model_dump(exclude={"events"})


def test_events_kept_inline_in_the_row_survive_a_load_without_the_journal(
    db: Database, journal_reads: list[str]
) -> None:
    mission = _mission("failed")
    inline = mission.projection.events[-1].model_dump(mode="json")
    with db.session() as session:
        row = session.get(ArcMission, mission.mission_id)
        assert row is not None
        row.projection_json = {**row.projection_json, "events": [inline]}
        light = store.load_projection(session, row, with_events=False)
    assert [e.event_id for e in light.events] == [inline["event_id"]]
    assert journal_reads == []


def test_peek_controller_reads_a_mission_without_keeping_it(db: Database) -> None:
    mission = _mission("exploring_candidates")
    store.reset_runtime()

    peeked = store.peek_controller(mission.mission_id)

    assert peeked is not None and peeked.revision == mission.revision
    assert [e.event_id for e in peeked.projection.events] == [
        e.event_id for e in mission.projection.events
    ]
    assert mission.mission_id not in store.MISSIONS
    assert store.peek_controller("arc_missing") is None
    # get_controller is the one that keeps it; a fresh live controller is handed back as it is.
    kept = store.get_controller(mission.mission_id)
    assert store.MISSIONS[mission.mission_id] is kept
    assert store.peek_controller(mission.mission_id) is kept


def test_peek_controller_sees_what_another_process_committed(db: Database) -> None:
    mission = _mission("exploring_candidates")
    holding = dict(store.MISSIONS)  # another process, with a cold cache, advances the mission
    store.MISSIONS.clear()
    other = store.get_controller(mission.mission_id)
    assert other is not None
    other.apply_event("operator_needed", {"reason": "elsewhere"})
    store.MISSIONS.clear()
    store.MISSIONS.update(holding)

    peeked = store.peek_controller(mission.mission_id)

    assert peeked is not None and peeked.projection.state == "needs_operator"
    assert store.MISSIONS[mission.mission_id] is mission  # peeking never replaces what is cached


def test_committed_revisions_answers_for_many_missions_at_once(db: Database) -> None:
    first, last, next_ = _mission("failed"), _mission("exploring_candidates"), _mission("completed")
    unknown = [f"arc_unknown_{number}" for number in range(1200)]  # more than one query's worth
    # One known id on each side of the boundary between the first query and the second.
    ids = [first.mission_id, *unknown[:498], last.mission_id, next_.mission_id, *unknown[498:]]

    revisions = store.committed_revisions(ids)

    assert revisions == {m.mission_id: m.revision for m in (first, last, next_)}
    assert store.committed_revisions([]) == {}


def test_committed_revisions_without_a_database() -> None:
    store.reset_store()
    try:
        mission = _mission("failed")
        assert store.committed_revisions([mission.mission_id, "arc_unknown"]) == {
            mission.mission_id: mission.revision
        }
    finally:
        store.reset_store()


def test_cache_stats_counts_what_the_process_holds(db: Database) -> None:
    first, second, third = _mission("failed"), _mission("exploring_candidates"), _mission("failed")
    events = {m.mission_id: len(m.projection.events) for m in (first, second, third)}
    failed = events[first.mission_id] + events[third.mission_id]

    assert store.cache_stats() == {
        "missions": 3,
        "events": sum(events.values()),
        "by_state": {
            "failed": {"missions": 2, "events": failed},
            "exploring_candidates": {"missions": 1, "events": events[second.mission_id]},
        },
    }

    store.reset_runtime()
    assert store.cache_stats() == {"missions": 0, "events": 0, "by_state": {}}
    store.get_controller(first.mission_id)
    held = {"missions": 1, "events": events[first.mission_id]}
    assert store.cache_stats() == {**held, "by_state": {"failed": held}}


def test_a_parked_mission_stays_parked_only_until_it_changes(db: Database) -> None:
    mission = _mission("needs_operator")
    store.park("scan", mission.mission_id, mission.revision)

    assert store.is_parked("scan", mission.mission_id, mission.revision)
    assert not store.is_parked("another scan", mission.mission_id, mission.revision)
    assert not store.is_parked("scan", "arc_another_mission", mission.revision)
    assert not store.is_parked("scan", mission.mission_id, mission.revision + 1)
    assert not store.is_parked("scan", mission.mission_id, None)  # a mission that is not there
    store.reset_runtime()  # a restart forgets it
    assert not store.is_parked("scan", mission.mission_id, mission.revision)


def test_nothing_is_parked_without_a_database() -> None:
    store.reset_store()
    store.park("scan", "arc_mission", 3)
    assert not store.is_parked("scan", "arc_mission", 3)


def test_what_was_parked_under_another_database_is_not_trusted(db: Database) -> None:
    mission = _mission("needs_operator")
    store.park("scan", mission.mission_id, mission.revision)

    store.configure_store(Database("sqlite:///:memory:"))  # the same id and revision, elsewhere

    assert not store.is_parked("scan", mission.mission_id, mission.revision)


def test_a_projection_tail_has_only_the_newest_event_of_each_type(
    db: Database, journal_reads: list[str]
) -> None:
    mission = _mission("exploring_candidates")
    mission.apply_event("operator_needed", {"reason": "first stop"})
    mission.apply_event("budget_extended", {"extra_candidates": 1})
    mission.apply_event("operator_needed", {"reason": "second stop"})
    with db.session() as session:
        row = session.get(ArcMission, mission.mission_id)
        assert row is not None
        types = ("operator_needed", "goal_compiled", "never_happened")
        tail = store.load_projection_tail(session, row, types)
        assert journal_reads == []
        full = store.load_projection(session, row)

    # In the order of the journal, whatever the order of the types asked for.
    assert [(e.event_type, e.payload.get("reason")) for e in tail.events] == [
        ("goal_compiled", None),
        ("operator_needed", "second stop"),
    ]
    assert (
        tail.events[-1].event_id
        == [e for e in full.events if e.event_type == "operator_needed"][-1].event_id
    )
    assert tail.model_dump(exclude={"events"}) == full.model_dump(exclude={"events"})


def test_a_row_with_inline_events_is_read_whole_for_a_projection_tail(
    db: Database, journal_reads: list[str]
) -> None:
    mission = _mission("needs_operator")
    inline = mission.projection.events[-1].model_dump(mode="json")
    with db.session() as session:
        row = session.get(ArcMission, mission.mission_id)
        assert row is not None
        row.projection_json = {**row.projection_json, "events": [inline]}
        tail = store.load_projection_tail(session, row, ("operator_needed",))

    assert journal_reads == [mission.mission_id]  # inline events follow the journal: both are read
    assert [e.event_id for e in tail.events] == [e.event_id for e in mission.projection.events]


# --- the AVO scan --------------------------------------------------------------------------


def _with_receipt(state: str) -> ARCMissionProjection:
    """A mission in ``state`` with everything that could make it need research at once."""
    attempt = _attempt("att")
    code_hash = hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
    pending = {
        "kind": "tool",
        "name": "develop",
        "id": "call_1",
        "arguments": {"attempt_id": "att"},
    }
    record = {
        "tool_call_id": "call_1",
        "attempt_id": "att",
        "backtest_id": "bt_1",
        "code_sha256": code_hash,
    }
    return ARCMissionProjection(
        mission_id="arc_receipt",
        state=state,  # type: ignore[arg-type]
        goal=_goal(),
        attempts=[attempt],
        avo={"pending": pending, "development": {"att": record}},
        events=[
            ARCEventV1(
                mission_id="arc_receipt",
                event_type="operator_needed",
                payload={"reason": "avo_effect_unknown"},
            )
        ],
    )


def test_needs_research_is_false_in_every_state_the_avo_scan_leaves_out() -> None:
    states = set(get_args(ARCMissionState))
    researchable = {state for state in states if avo.needs_research(_with_receipt(state))}

    # Exactly: a state missing from the scan would starve its missions of research, and a state
    # that cannot need research would only make the scan load missions for nothing.
    assert researchable == set(avo.AVO_SCAN_STATES)
    assert researchable < states


@pytest.fixture
def avo_scan(db: Database, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """The missions the AVO scan looked at and the ones it started research on, by name."""
    calls: dict[str, list[str]] = {"looked": [], "started": []}
    real = avo.peek_controller

    def peek_controller(mission_id: str) -> ARCController | None:
        calls["looked"].append(mission_id)
        return real(mission_id)

    def run_avo_research(mission_id: str) -> dict[str, Any]:
        calls["started"].append(mission_id)
        return {"status": "busy"}

    monkeypatch.setattr(avo, "peek_controller", peek_controller)
    monkeypatch.setattr(avo, "run_avo_research", run_avo_research)
    return calls


def test_the_avo_scan_looks_without_keeping_and_parks_what_cannot_need_research(
    db: Database, avo_scan: dict[str, list[str]]
) -> None:
    missions = {state: _mission(state) for state in STATES}
    ids = {state: mission.mission_id for state, mission in missions.items()}
    store.reset_runtime()
    live, waiting = ids["exploring_candidates"], ids["needs_operator"]

    assert avo.run_pending_avo_once() == {"status": "idle"}

    # Only the missions in a state that could need research are looked at, and none stays resident.
    assert sorted(avo_scan["looked"]) == sorted([live, waiting])
    assert avo_scan["started"] == [live]
    assert _resident() == (0, 0)

    # The one that cannot need research is not looked at again, the one that can still is.
    avo_scan["looked"].clear()
    avo_scan["started"].clear()
    avo.run_pending_avo_once()
    assert avo_scan["looked"] == [live] and avo_scan["started"] == [live]

    # Until it changes: it is looked at again, and now it does need research.
    missions["needs_operator"].apply_event("budget_extended", {"extra_candidates": 1})
    avo_scan["looked"].clear()
    avo_scan["started"].clear()
    avo.run_pending_avo_once()
    assert sorted(avo_scan["looked"]) == sorted([live, waiting])
    assert sorted(avo_scan["started"]) == sorted([live, waiting])


def test_the_avo_scan_does_not_park_a_mission_a_later_clock_could_resume(
    db: Database, avo_scan: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    mission = _mission("exploring_candidates").mission_id
    store.reset_runtime()
    # A backtest that is not due yet: no research now, research once it is.
    monkeypatch.setattr(avo, "recoverable", lambda projection, *, due=True: not due)

    avo.run_pending_avo_once()
    avo.run_pending_avo_once()
    assert avo_scan["looked"] == [mission, mission] and avo_scan["started"] == []

    monkeypatch.setattr(avo, "recoverable", lambda projection, *, due=True: True)
    avo.run_pending_avo_once()
    assert avo_scan["started"] == [mission]


# --- the Paper effect reconciliation -------------------------------------------------------


@pytest.fixture
def reconcile(db: Database, monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """What the sweep did: the missions it looked at, loaded for good, and tried to reconcile."""
    calls: dict[str, list[str]] = {"looked": [], "loaded": [], "reconciled": []}
    real_peek = paper_effect_reconcile.peek_controller
    real_get = paper_effect_reconcile.get_controller

    def peek_controller(mission_id: str) -> ARCController | None:
        calls["looked"].append(mission_id)
        return real_peek(mission_id)

    def get_controller(mission_id: str) -> ARCController | None:
        calls["loaded"].append(mission_id)
        return real_get(mission_id)

    def reconcile_paper_start(controller: ARCController, client: Any) -> dict[str, Any]:
        calls["reconciled"].append(controller.mission_id)
        return {"status": "unverified", "reasons": []}

    monkeypatch.setattr(paper_effect_reconcile, "_last_checked", {})
    monkeypatch.setattr(paper_effect_reconcile, "peek_controller", peek_controller)
    monkeypatch.setattr(paper_effect_reconcile, "get_controller", get_controller)
    monkeypatch.setattr(paper_effect_reconcile, "reconcile_paper_start", reconcile_paper_start)
    return calls


def test_the_paper_effect_sweep_looks_without_keeping_and_parks_what_has_nothing_to_adopt(
    db: Database, reconcile: dict[str, list[str]]
) -> None:
    unknown = _mission("needs_operator")
    unknown.projection.paper_review = {"status": "effect_unknown"}
    store.save_mission(unknown)
    quiet = _mission("needs_operator")
    _mission("failed")
    store.reset_runtime()
    sweep = paper_effect_reconcile.reconcile_paper_effects_once
    recheck = paper_effect_reconcile.RECHECK_SECONDS

    first = sweep(now=1000.0)

    assert sorted(reconcile["looked"]) == sorted([unknown.mission_id, quiet.mission_id])
    assert reconcile["loaded"] == [unknown.mission_id]  # only the mission it works on is kept
    assert reconcile["reconciled"] == [unknown.mission_id] and first["checked"] == 1
    assert _resident()[0] == 1

    # When the unknown one is due again the quiet one is not looked at again.
    reconcile["looked"].clear()
    sweep(now=1000.0 + recheck + 1)
    assert reconcile["looked"] == [unknown.mission_id]

    # While the unknown one is not due, neither of them is looked at.
    reconcile["looked"].clear()
    sweep(now=1000.0 + recheck + 2)
    assert reconcile["looked"] == []

    # The quiet one changes (and stays waiting for the operator): it is looked at again.
    quiet.apply_event("operator_needed", {"reason": "once more"})
    sweep(now=1000.0 + recheck + 3)
    assert reconcile["looked"] == [quiet.mission_id]


# --- the automatic review -----------------------------------------------------------------


def test_auto_review_neither_locks_nor_loads_missions_it_cannot_act_on(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    EvolutionService(db).configure(
        EvolutionConfig(enabled=True, paper_review_mode="agent"), revision=0, actor="user"
    )
    live = _mission("exploring_candidates").mission_id
    others = [_mission(state).mission_id for state in ("failed", "completed", "needs_operator")]
    store.reset_runtime()
    locked: list[str] = []
    loaded: list[str] = []
    real_lock, real_get = auto_review.research_lock, auto_review.get_controller

    @contextmanager
    def research_lock(mission_id: str) -> Iterator[Any]:
        locked.append(mission_id)
        with real_lock(mission_id) as owner:
            yield owner

    def get_controller(mission_id: str) -> ARCController | None:
        loaded.append(mission_id)
        return real_get(mission_id)

    monkeypatch.setattr(auto_review, "research_lock", research_lock)
    monkeypatch.setattr(auto_review, "get_controller", get_controller)

    auto_review.auto_review_once(db)

    assert loaded == [live]
    assert live in locked and not set(locked) & set(others)
    assert not set(store.MISSIONS) & set(others)


# --- the research budget, the memory of past research, the acceptance ledger ---------------


def test_usage_reads_no_journal_but_the_last_stop_of_missions_waiting_on_the_operator(
    db: Database, journal_reads: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    missions = [
        _research_mission("exploring_candidates", 0),
        _research_mission("needs_operator", 1),  # the reason it stopped is in its journal
        _research_mission("needs_operator", 2, reason="avo_context_budget_exhausted"),
        _research_mission("paper_observing", 3),
        _research_mission("failed", 4),
        _research_mission("completed", 5),
        _mission("failed"),  # not a research mission at all
    ]
    waiting = {missions[1].mission_id, missions[2].mission_id}
    store.reset_runtime()
    config = EvolutionConfig()
    tails: list[str] = []
    real_tail = research_budget.load_projection_tail

    def load_projection_tail(session: Any, row: Any, types: Any) -> Any:
        assert tuple(types) == ("operator_needed",)
        tails.append(row.mission_id)
        return real_tail(session, row, types)

    monkeypatch.setattr(research_budget, "load_projection_tail", load_projection_tail)
    with db.session() as session:
        fast = research_budget.usage(session, config, NOW)
    assert journal_reads == [] and set(tails) == waiting and len(tails) == 2

    # The same answer as when every mission's whole journal is read.
    real = research_budget.load_projection
    monkeypatch.setattr(research_budget, "load_projection", lambda s, row, **_: real(s, row))
    monkeypatch.setattr(research_budget, "load_projection_tail", lambda s, row, types: real(s, row))
    reference = None
    with db.session() as session:
        reference = research_budget.usage(session, config, NOW)
    assert set(journal_reads) == {mission.mission_id for mission in missions}
    assert fast == reference
    assert fast["total_used"] == 6 and fast["active"] >= 1 and fast["sources"]


def _ledger(db: Database) -> tuple[dict[str, Any], dict[str, Any]]:
    """What the acceptance ledger holds: the checkpoints and the entries."""
    with db.session() as session:
        checkpoints = {r.id: r.payload_json for r in session.scalars(select(EvolutionContinuation))}
        entries = {r.id: r.payload_json for r in session.scalars(select(EvolutionAcceptance))}
    return checkpoints, entries


def test_the_continuation_ledger_reads_a_journal_only_for_the_missions_it_tracks(
    db: Database, journal_reads: list[str]
) -> None:
    plain = _mission("failed")
    unusable = _mission("failed", evolution_context={"source_instance_id": "instance-x"})
    tracked = _research_mission("exploring_candidates", 1)
    assert plain.mission_id and unusable.mission_id
    store.reset_runtime()

    ContinuationLedger(db).refresh(NOW)

    assert journal_reads == [tracked.mission_id]
    assert len(_ledger(db)[0]) == 1


def test_the_continuation_ledger_records_the_same_whether_or_not_it_skips_journals(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    for number, state in enumerate(STATES):
        _research_mission(state, number)
    _mission("failed")
    store.reset_runtime()
    ContinuationLedger(db).refresh(NOW)
    fast = _ledger(db)
    with db.session() as session:
        for table in (EvolutionAcceptance, EvolutionContinuation):
            for row in session.scalars(select(table)).all():
                session.delete(row)

    real = store.load_projection
    monkeypatch.setattr(store, "load_projection", lambda s, row, **_: real(s, row))
    monkeypatch.setattr(evolution_continuation, "_REFRESHED", None)  # compute it all again
    ContinuationLedger(db).refresh(NOW)

    assert fast[0] and fast[1]
    assert _ledger(db) == fast


def test_the_continuation_ledger_does_nothing_while_no_mission_has_changed(
    db: Database, journal_reads: list[str]
) -> None:
    moving = _research_mission("exploring_candidates", 1)
    still = _research_mission("failed", 2)
    store.reset_runtime()
    ledger = ContinuationLedger(db)

    ledger.refresh(NOW)
    first = _ledger(db)
    assert set(journal_reads) == {moving.mission_id, still.mission_id}

    journal_reads.clear()
    ledger.refresh(NOW + timedelta(minutes=1))
    assert journal_reads == [] and _ledger(db) == first  # not even the checked_at stamp moves

    # Once a mission has changed the whole ledger is computed again, and stamped.
    moving.apply_event("operator_needed", {"reason": "something happened"})
    ledger.refresh(NOW + timedelta(minutes=2))
    assert set(journal_reads) == {moving.mission_id, still.mission_id}
    assert _ledger(db) != first

    # A mission that is created is a change as well.
    journal_reads.clear()
    _research_mission("failed", 3)
    ledger.refresh(NOW + timedelta(minutes=3))
    assert len(journal_reads) == 3


def test_a_ledger_pass_that_failed_is_not_taken_for_a_complete_one(
    db: Database, journal_reads: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _research_mission("exploring_candidates", 1)
    store.reset_runtime()
    ledger = ContinuationLedger(db)
    real = evolution_continuation.acceptance_entries

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("the pass fails half way")

    monkeypatch.setattr(evolution_continuation, "acceptance_entries", failing)
    with pytest.raises(RuntimeError):
        ledger.refresh(NOW)
    assert _ledger(db) == ({}, {})  # nothing of it committed

    monkeypatch.setattr(evolution_continuation, "acceptance_entries", real)
    journal_reads.clear()
    ledger.refresh(NOW)
    assert journal_reads and all(_ledger(db))  # nothing changed, yet it is computed in full


def test_what_the_ledger_remembers_belongs_to_its_database(
    db: Database, journal_reads: list[str]
) -> None:
    _research_mission("exploring_candidates", 1)
    store.reset_runtime()
    ledger = ContinuationLedger(db)
    ledger.refresh(NOW)
    seen = evolution_continuation._REFRESHED
    assert seen is not None

    evolution_continuation._REFRESHED = (Database("sqlite:///:memory:"), seen[1])  # not this one
    journal_reads.clear()
    ledger.refresh(NOW)

    assert journal_reads  # it was not taken for the same missions of the same database


def test_the_research_memory_reads_no_journal(
    db: Database, journal_reads: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    mission = _mission("exploring_candidates")
    attempt = _attempt("att_memory").model_dump(mode="json")
    mission.apply_event("candidate_proposed", {"attempt": attempt})
    mission.projection.avo["development"] = {"att_memory": {"backtest_id": "bt_1", "metrics": {}}}
    store.save_mission(mission)
    _mission("failed")
    store.reset_runtime()
    base = {
        "baseline": {"strategy_spec": {"symbols": ["BTC-USDT-SWAP"], "timeframe": "1H"}},
        "target_id": "bitpro",
        "source_strategy_id": 7,
    }
    service = EvolutionService(db)

    fast_context = copy.deepcopy(base)
    fast = service._memory(fast_context, NOW)
    assert journal_reads == []

    # The same answer as when every mission's journal is read.
    real = evolution.load_projection
    monkeypatch.setattr(evolution, "load_projection", lambda s, row, **_: real(s, row))
    reference_context = copy.deepcopy(base)
    reference = service._memory(reference_context, NOW)
    assert len(journal_reads) == 2
    assert fast == reference and fast_context == reference_context


# --- the memory replay ---------------------------------------------------------------------


@pytest.fixture
def replay_state(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arc_integration, "_REPLAY_CURSOR", 0)


def test_the_replay_ingests_a_mission_once_until_it_moves_on(
    db: Database, replay_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingested: list[str] = []
    monkeypatch.setattr(
        arc_integration,
        "ingest_projection",
        lambda database, mission_id, projection, **_: ingested.append(mission_id),
    )
    live, done = _mission("exploring_candidates"), _mission("failed")
    store.reset_runtime()

    first = arc_integration.replay_arc_cognitive_memory_once()
    assert first == {"status": "ok", "missions": 2, "unchanged": 0}
    assert sorted(ingested) == sorted([live.mission_id, done.mission_id])
    assert _resident() == (0, 0)  # nothing stays resident

    second = arc_integration.replay_arc_cognitive_memory_once()
    assert second == {"status": "ok", "missions": 0, "unchanged": 2}
    assert len(ingested) == 2 and _resident() == (0, 0)

    live.apply_event("operator_needed", {"reason": "something new"})  # the mission moves on
    third = arc_integration.replay_arc_cognitive_memory_once()
    assert third == {"status": "ok", "missions": 1, "unchanged": 1}
    assert ingested[2:] == [live.mission_id]


def test_the_replay_tries_again_for_a_mission_whose_ingest_failed(
    db: Database, replay_state: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []

    def flaky(database: Database, mission_id: str, projection: Any, **_: Any) -> None:
        attempts.append(mission_id)
        if len(attempts) == 1:
            raise RuntimeError("memory database unavailable")

    monkeypatch.setattr(arc_integration, "ingest_projection", flaky)
    mission = _mission("failed")
    store.reset_runtime()

    with pytest.raises(RuntimeError):
        arc_integration.replay_arc_cognitive_memory_once()
    retried = arc_integration.replay_arc_cognitive_memory_once()

    assert retried == {"status": "ok", "missions": 1, "unchanged": 0}
    assert attempts == [mission.mission_id, mission.mission_id]


def test_the_replay_still_backfills_the_cognitive_memory(db: Database, replay_state: None) -> None:
    mission = _mission("exploring_candidates")
    mission.apply_event(
        "candidate_proposed", {"attempt": _attempt("att_a").model_dump(mode="json")}
    )
    store.reset_runtime()

    assert arc_integration.replay_arc_cognitive_memory_once()["missions"] == 1

    with db.session() as session:
        claims = [node.claim for node in session.scalars(select(ArcHypothesisNode))]
    assert claims == ["hypothesis att_a"]


# --- the selection-bias evidence -----------------------------------------------------------


def _develop(mission: ARCController, name: str, sharpe: float, *, other_code: bool = False) -> None:
    """One development trial: proposed, requested, and answered with a receipt."""
    attempt = _attempt(name)
    code_hash = hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
    mission.apply_event("candidate_proposed", {"attempt": attempt.model_dump(mode="json")})
    mission.apply_event("avo_development_requested", {"attempt_id": name})
    mission.apply_event(
        "avo_development_result",
        {
            "attempt_id": name,
            "result": {
                "backtest_id": f"bt-{name}-{sharpe}",
                "code_sha256": "0" * 64 if other_code else code_hash,
                "metrics": {"return_statistics": _stats(sharpe)},
            },
        },
    )


def _replay(
    mission: ARCController,
    name: str,
    sharpe: float,
    *,
    basis: str = "out_of_sample",
    available: bool = True,
    code: str | None = None,
) -> None:
    """The replay of a trial. Only an out-of-sample one that proves its code takes precedence."""
    attempt = _attempt(name)
    mission.apply_event(
        "red_team_tested",
        {
            "attempt_id": name,
            "code_sha256": code or hashlib.sha256(attempt.strategy_code.encode()).hexdigest(),
            "passed": True,
            "metrics": {
                "return_statistics": _stats(sharpe),
                "evidence_available": available,
                "ranking_basis": basis,
            },
        },
    )


def _final(mission: ARCController, name: str, sharpe: float) -> None:
    """The final holdout of a trial: never part of the search distribution."""
    attempt = _attempt(name)
    mission.apply_event(
        "bitpro_self_tested",
        {
            "attempt_id": name,
            "passed": True,
            "purpose": "final",
            "backtest_id": f"final-{name}",
            "code_sha256": hashlib.sha256(attempt.strategy_code.encode()).hexdigest(),
            "metrics": {"return_statistics": _stats(sharpe)},
        },
    )


def _stats(sharpe: float) -> dict[str, Any]:
    return {
        "schema_version": "return_statistics.v1",
        "status": "observed",
        "sample_length": 500,
        "period_seconds": 86400,
        "period_sharpe": sharpe,
        "skewness": 0.0,
        "kurtosis": 3.0,
        "series_sha256": "a" * 64,
    }


def _search() -> tuple[ARCController, dict[str, ARCController]]:
    """The mission being judged and the others: three of its family, one of another family."""

    def compiled(**goal: Any) -> ARCController:
        controller = ARCController(goal=_goal(**goal))
        controller.apply_event("goal_compiled", {"goal": controller.projection.goal.model_dump()})
        return controller

    current = compiled()
    _develop(current, "t4", 0.25)
    _develop(current, "t1", 0.12)  # a trial another mission ran as well: the others' come later
    first, second, third = compiled(), compiled(), compiled()
    _develop(first, "t1", 0.10)
    _develop(first, "t2", 0.30)
    _replay(first, "t2", 0.31)  # out of sample, with its code: replaces the development numbers
    _develop(second, "t3", 0.20, other_code=True)  # a receipt for other code: a trial, no numbers
    _develop(second, "t1", 0.15)  # the same trial as the first mission's: the later one wins
    _replay(second, "t1", 0.99, basis="in_sample")  # none of these three replays counts:
    _replay(second, "t3", 0.88, code="0" * 64)  # in sample, for other code,
    _develop(third, "t6", 0.35)
    _replay(third, "t6", 0.77, available=False)  # and without its evidence
    _final(third, "t6", 0.95)  # a final holdout never joins the search distribution
    third.apply_event("candidate_proposed", {"attempt": _attempt("t7").model_dump(mode="json")})
    _final(third, "t7", 0.60)  # but a final for a candidate nobody developed here is a trial
    _develop(third, "baseline_b", 0.50)  # a baseline is no trial
    elsewhere = compiled(symbols=["ETH-USDT-SWAP"])  # another family: never counted
    _develop(elsewhere, "t9", 0.90)
    return current, {"first": first, "second": second, "third": third, "elsewhere": elsewhere}


def _the_loop_before_the_facts_were_remembered(
    controller: ARCController, family: str
) -> tuple[dict[str, Any], dict[str, str]]:
    """The collection of trials in ``selection_evidence`` as it was, verbatim.

    It reads every other mission with ``get_controller``, which keeps each of them.
    """
    from hypertrade.arc.selection_bias import _family, _statistics, _trial

    trials: dict[str, dict[str, Any] | None] = {}
    refs: dict[str, str] = {}
    controllers = {controller.mission_id: controller}
    for mission_id in store.list_mission_ids():
        if mission_id != controller.mission_id:
            other = store.get_controller(mission_id)
            if (
                other is not None
                and other.projection.goal is not None
                and _family(other.projection.goal) == family
            ):
                controllers[mission_id] = other
    for owner in controllers.values():
        attempts = {item.attempt_id: item for item in owner.projection.attempts}
        for event in owner.projection.events:
            payload = event.payload
            attempt = attempts.get(str(payload.get("attempt_id")))
            if attempt is None or attempt.attempt_id.startswith("baseline_"):
                continue
            key = _trial(attempt)
            if event.event_type in {
                "avo_development_requested",
                "avo_final_requested",
                "red_team_tested",
            }:
                trials.setdefault(key, None)
            if event.event_type == "red_team_tested":
                replay_metrics = payload.get("metrics") or {}
                observed = _statistics(replay_metrics)
                if (
                    observed is not None
                    and replay_metrics.get("evidence_available") is True
                    and replay_metrics.get("ranking_basis") == "out_of_sample"
                    and payload.get("code_sha256")
                    == hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
                ):
                    trials[key] = observed
                    refs[key] = "arc-event:" + event.event_id
            if event.event_type not in {"avo_development_result", "bitpro_self_tested"}:
                continue
            trials.setdefault(key, None)
            receipt = payload.get("result", payload)
            code_hash = hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
            if not receipt.get("backtest_id") or receipt.get("code_sha256") != code_hash:
                continue
            if event.event_type == "avo_development_result":
                observed = _statistics(receipt.get("metrics") or {})
                if observed is not None:
                    trials[key] = observed
                    refs[key] = str(receipt["backtest_id"])
    return trials, refs


@pytest.mark.parametrize("durable", [True, False], ids=["database", "in-memory"])
def test_selection_evidence_collects_the_trials_it_always_did(durable: bool) -> None:
    store.reset_store()
    selection_bias._FACTS.clear()
    if durable:
        database = Database("sqlite:///:memory:")
        database.create_all()
        store.configure_store(database)
    try:
        current, _ = _search()
        family = selection_bias._family(current.projection.goal)  # type: ignore[arg-type]
        store.reset_runtime()  # as a worker that has just started

        cold = selection_bias._collect_trials(current, family)
        warm = selection_bias._collect_trials(current, family)  # now from what it remembered
        expected = _the_loop_before_the_facts_were_remembered(current, family)

        assert cold == warm == expected
        trials, refs = expected
        # t1 t2 t3 t4 t6 t7 are the trials of the family (t3 and t7 have no numbers); the replay
        # of t2 and the later t1 won.
        assert len(trials) == 6 and sum(v is not None for v in trials.values()) == 4
        assert len(refs) == 4 and sum(ref.startswith("arc-event:") for ref in refs.values()) == 1
        assert bool(selection_bias._FACTS) is durable  # nothing is remembered without a database
    finally:
        selection_bias._FACTS.clear()
        store.reset_store()


def test_selection_evidence_does_not_keep_the_missions_it_walks(
    db: Database, journal_reads: list[str]
) -> None:
    current, others = _search()
    family = selection_bias._family(current.projection.goal)  # type: ignore[arg-type]
    other_ids = {mission.mission_id for mission in others.values()}
    store.reset_runtime()
    journal_reads.clear()

    before, _ = selection_bias._collect_trials(current, family)

    assert not set(store.MISSIONS) & other_ids  # none of them became resident
    assert set(journal_reads) == other_ids  # each was read once

    journal_reads.clear()
    again, _ = selection_bias._collect_trials(current, family)
    assert journal_reads == [] and again == before  # nothing moved: nothing to read

    # A mission of the family moves on in another process: that one is read again, no other.
    store.reset_runtime()
    mover = store.get_controller(others["first"].mission_id)
    assert mover is not None
    _develop(mover, "t5", 0.40)
    store.reset_runtime()
    journal_reads.clear()
    after, _ = selection_bias._collect_trials(current, family)
    assert journal_reads == [others["first"].mission_id]
    assert len(after) == len(before) + 1

    # What was remembered about another database is not trusted.
    for mission_id, entry in list(selection_bias._FACTS.items()):
        selection_bias._FACTS[mission_id] = (object(), *entry[1:])  # type: ignore[assignment]
    journal_reads.clear()
    assert selection_bias._collect_trials(current, family)[0] == after
    assert set(journal_reads) == other_ids


# --- what the worker publishes about it ----------------------------------------------------


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    registered: dict[str, Any] = {}
    monkeypatch.setattr(heartbeat, "_PROCESS_PROBES", registered)
    return registered


def _published(db: Database, **kwargs: Any) -> dict[str, Any] | None:
    flush_heartbeat(db, worker_id="worker", started_at=NOW, now=NOW, **kwargs)
    (view,) = read_worker_status(db, now=NOW + timedelta(seconds=1))["instances"]
    return view["process"]  # type: ignore[no-any-return]


def test_a_registered_probe_is_published_with_the_process_statistics(
    db: Database, probes: dict[str, Any]
) -> None:
    heartbeat.register_process_probe("arc_cache", lambda: {"missions": 3, "events": 90})

    process = _published(db)

    assert process is not None
    assert process["arc_cache"] == {"missions": 3, "events": 90}
    assert process["python"] and process["gc"]  # the rest of the statistics are still there


def test_the_arc_cache_is_published_by_state_within_the_bounds_on_what_is_published(
    db: Database, probes: dict[str, Any]
) -> None:
    _mission("failed")
    _mission("needs_operator")
    heartbeat.register_process_probe("arc_cache", store.cache_stats)

    process = _published(db)

    assert process is not None
    assert process["arc_cache"] == store.cache_stats()
    assert set(process["arc_cache"]["by_state"]) == {"failed", "needs_operator"}


def test_a_failing_probe_costs_the_heartbeat_nothing_else(
    db: Database, probes: dict[str, Any]
) -> None:
    def broken() -> Any:
        raise RuntimeError("a bug in a probe")

    heartbeat.register_process_probe("broken", broken)
    heartbeat.register_process_probe("arc_cache", lambda: {"missions": 1, "events": 2})

    process = _published(db)

    assert process is not None
    assert "broken" not in process and process["arc_cache"] == {"missions": 1, "events": 2}
    assert process["python"]


def test_probes_do_not_add_to_statistics_a_caller_supplied(
    db: Database, probes: dict[str, Any]
) -> None:
    heartbeat.register_process_probe("arc_cache", lambda: {"missions": 3, "events": 90})

    assert _published(db, stats=lambda: {"rss_mb": 12}) == {"rss_mb": 12}


def test_the_worker_publishes_how_much_of_the_arc_history_it_holds(
    monkeypatch: pytest.MonkeyPatch, probes: dict[str, Any]
) -> None:
    class Watchdog:
        def __init__(self, registry: Any) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    monkeypatch.setattr(worker, "get_settings", lambda: SimpleNamespace(database_url="sqlite://"))
    monkeypatch.setattr(worker, "build_loops", lambda db, settings: [])
    monkeypatch.setattr(worker, "LoopWatchdog", Watchdog)

    asyncio.run(worker.main())

    assert probes == {"arc_cache": store.cache_stats}
