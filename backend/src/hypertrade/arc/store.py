"""Durable ARC mission projection. Memory is a cache; the database is the restart truth.

``hypertrade-api`` and ``hypertrade-worker`` are separate processes that advance the
same mission: the API runs research and serves approvals, the worker advances paper
observation. Each holds its own controller and persists a whole projection snapshot,
so a cache that is never refreshed serves a mission that stopped being true, and a
snapshot written from it erases whatever the other process committed meanwhile. Every
read here is revision-checked and every write happens under the mission row.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager, suppress
from threading import Lock
from typing import Any
from weakref import WeakValueDictionary

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    and_,
    case,
    func,
    literal_column,
    select,
    text,
    type_coerce,
)
from sqlalchemy.orm import Session

from hypertrade.arc.controller import ARCController, ARCEventV1, ARCMissionProjection
from hypertrade.db import ArcMission, ArcMissionEvent, Database

MISSIONS: dict[str, ARCController] = {}
# Terminal and long-lived observing controllers are kept only weakly while a caller holds a
# reference, so single-process object identity survives within one call chain without pinning
# megabytes of historical event journals across worker sweeps or API requests.
_NON_RESIDENT_STATES = frozenset(
    {
        "paper_observing",
        "completed",
        "failed",
        "rejected",
        "retired",
        "needs_operator",
    }
)
_EPHEMERAL_MISSIONS: WeakValueDictionary[str, ARCController] = WeakValueDictionary()
_CACHE_LOCK = Lock()
_SUMMARY_EVENT_TYPES = (
    "goal_compiled",
    "provider_status",
    "operator_needed",
    "mission_failed",
    "red_team_tested",
)
_MEMORY: dict[str, dict[str, Any]] = {}
_MEMORY_REVISIONS: dict[str, int] = {}
_database: Database | None = None
_research_locks: dict[str, Any] = {}
_research_lock_guard = Lock()
# What a periodic scan concluded about a mission, by the revision it concluded it at:
# (scan, mission id) -> (database, revision). See ``park``.
_PARKED: dict[tuple[str, str], tuple[Database, int]] = {}


@contextmanager
def research_lock(mission_id: str) -> Iterator[Callable[[], None] | None]:
    """One research owner. PostgreSQL locks survive commits and release on session death.

    SQLite/in-memory are single-process development backends; their local mutex is
    deliberately not advertised as distributed locking.
    """
    with _research_lock_guard:
        lock = _research_locks.setdefault(mission_id, Lock())
    if not lock.acquire(blocking=False):
        yield None
        return
    try:
        if _database is None or _database.engine.dialect.name != "postgresql":
            yield lambda: None
            return
        key = int.from_bytes(
            hashlib.sha256(f"avo/{mission_id}".encode()).digest()[:8], "big", signed=True
        )
        with _database.engine.connect() as connection:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            ).scalar()
            pid = connection.execute(text("SELECT pg_backend_pid()")).scalar()
            connection.commit()
            if not acquired:
                yield None
                return

            def check_owner() -> None:
                current = connection.execute(text("SELECT pg_backend_pid()")).scalar()
                connection.commit()
                if current != pid:
                    raise RuntimeError("research_lock_lost")

            try:
                yield check_owner
            finally:
                with suppress(Exception):
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    connection.commit()
    finally:
        lock.release()


def configure_store(database: Database | None) -> None:
    global _database
    _database = database


def get_configured_database() -> Database | None:
    """Return the process ARC database without constructing a second truth source."""
    return _database


def reset_runtime() -> None:
    """Drop in-process controllers. Persisted rows and the memory snapshot stay."""
    with _CACHE_LOCK:
        MISSIONS.clear()
        _EPHEMERAL_MISSIONS.clear()
    _PARKED.clear()


def cache_stats() -> dict[str, Any]:
    """How much of the ARC history this process holds in memory: missions and their events, in
    all and by the state the missions are in.

    Published with the worker heartbeat, because what the process keeps resident decides how long
    each full garbage collection freezes it, and nothing else shows what is being kept.
    """
    by_state: dict[str, dict[str, int]] = {}
    missions = events = 0
    for controller in list(MISSIONS.values()):
        count = len(controller.projection.events)
        held = by_state.setdefault(controller.projection.state, {"missions": 0, "events": 0})
        held["missions"] += 1
        held["events"] += count
        missions += 1
        events += count
    return {"missions": missions, "events": events, "by_state": by_state}


def park(scan: str, mission_id: str, revision: int) -> None:
    """Remember that ``scan`` has nothing to do with this mission at this revision.

    A scan that runs every few seconds over missions that are done with, and cannot be resumed,
    must not read each of them again every time (a read is the whole event journal, and what is
    read stays resident). A mission has moved on when its committed revision has, which is also
    when the scan has to look again. Without a database there is no revision to trust.
    """
    if _database is not None:
        _PARKED[(scan, mission_id)] = (_database, revision)


def is_parked(scan: str, mission_id: str, revision: int | None) -> bool:
    """Whether ``park`` holds for this mission, which is at ``revision`` now."""
    parked = _PARKED.get((scan, mission_id))
    return (
        parked is not None
        and revision is not None
        and parked[0] is _database
        and parked[1] == revision
    )


def reset_store() -> None:
    with _CACHE_LOCK:
        MISSIONS.clear()
        _EPHEMERAL_MISSIONS.clear()
    _PARKED.clear()
    _MEMORY.clear()
    _MEMORY_REVISIONS.clear()
    configure_store(None)


def commit_event(controller: ARCController, event: ARCEventV1) -> None:
    """Reduce one event onto the committed projection and persist the result.

    When the row moved on since this controller last read it, the controller is
    rebased onto the committed projection and the event replays there. That is what
    an event means: a transition of the mission, not of one process's copy of it.
    """
    if _database is None:
        _commit_in_memory(controller, event)
        return
    with _database.session() as session:
        row = session.get(ArcMission, controller.mission_id, with_for_update=True)
        if row is not None and int(row.revision or 0) != controller.revision:
            controller.rebase(load_projection(session, row), int(row.revision or 0))
        controller.absorb(event)
        revision = controller.revision + 1
        if row is None:
            payload = insert_mission(session, controller, revision)
        else:
            payload = _write(session, row, controller, revision)
        controller.revision = revision
    _cache(controller, payload)


def save_mission(controller: ARCController) -> None:
    """Persist a projection that no event produced, which only mission creation does.

    A snapshot carries no transition to replay, so when the row has moved on this
    refreshes the controller instead of overwriting the mission with older facts.
    """
    if _database is None:
        _MEMORY_REVISIONS[controller.mission_id] = controller.revision
        _cache(controller, controller.projection.model_dump(mode="json"))
        return
    with _database.session() as session:
        row = session.get(ArcMission, controller.mission_id, with_for_update=True)
        if row is None:
            controller.revision = 1
            _cache(controller, insert_mission(session, controller, 1))
            return
        if int(row.revision or 0) != controller.revision:
            controller.rebase(load_projection(session, row), int(row.revision or 0))
            _cache(controller, controller.projection.model_dump(mode="json"))
            return
        revision = controller.revision + 1
        payload = _write(session, row, controller, revision)
        controller.revision = revision
    _cache(controller, payload)


def load_projection(
    session: Session, row: ArcMission, *, with_events: bool = True
) -> ARCMissionProjection:
    """The committed projection: journalled events plus any inline legacy events.

    Rows written by pre-journal code keep events inline in ``projection_json``; a process
    still running that code during a deploy appends there too. Both layouts are merged
    by ``event_id`` so neither loses nor duplicates an event.

    ``with_events=False`` leaves the journal unread: every other field of the projection is in
    ``projection_json``, and the journal is by far the largest part of a mission (thousands of
    events, each a JSON document that is parsed and validated). A reader that never looks at
    ``projection.events`` must not pay for it; whatever is inline stays, as it is part of the row.
    """
    payload = dict(row.projection_json or {})
    if not with_events:
        return ARCMissionProjection.model_validate(payload)
    inline = list(payload.get("events") or [])
    stored = _stored_events(session, row.mission_id)
    known = {event["event_id"] for event in stored}
    payload["events"] = stored + [event for event in inline if event.get("event_id") not in known]
    return ARCMissionProjection.model_validate(payload)


def load_projection_tail(
    session: Session, row: ArcMission, event_types: Collection[str]
) -> ARCMissionProjection:
    """The projection without its journal, except for the newest event of each of ``event_types``.

    For a reader that asks what the last such event was and nothing else about the history: it
    costs a lookup per type instead of the parsing and validation of every event the mission has
    had. A row that still keeps events inline (written by pre-journal code) is read whole: inline
    events follow the journal, so finding the newest takes both.
    """
    payload = dict(row.projection_json or {})
    if payload.get("events"):
        return load_projection(session, row)
    newest: list[tuple[int, dict[str, Any]]] = []
    for event_type in event_types:
        found = session.execute(
            select(ArcMissionEvent.seq, ArcMissionEvent.event_json)
            .where(
                ArcMissionEvent.mission_id == row.mission_id,
                ArcMissionEvent.event_type == event_type,
            )
            .order_by(ArcMissionEvent.seq.desc())
            .limit(1)
        ).first()
        if found is not None:
            newest.append((int(found[0]), dict(found[1])))
    payload["events"] = [event for _, event in sorted(newest, key=lambda item: item[0])]
    return ARCMissionProjection.model_validate(payload)


def load_projection_events(
    session: Session,
    row: ArcMission,
    event_types: Collection[str],
    *,
    include_first: bool = False,
    include_last: bool = False,
) -> ARCMissionProjection:
    """Load projection metadata plus only the requested ``event_types`` (and optional ends).

    Rows with inline legacy events fall back to ``load_projection`` so inline + stored merge
    is preserved. Journaled rows skip irrelevant high-volume events (such as thousands of
    ``paper_observed`` ticks) while returning events in ascending journal order.
    """
    payload = dict(row.projection_json or {})
    if payload.get("events"):
        return load_projection(session, row)
    events_by_seq: dict[int, dict[str, Any]] = {}
    wanted = sorted(set(event_types))
    if wanted:
        for seq, event_json in session.execute(
            select(ArcMissionEvent.seq, ArcMissionEvent.event_json)
            .where(
                ArcMissionEvent.mission_id == row.mission_id,
                ArcMissionEvent.event_type.in_(wanted),
            )
            .order_by(ArcMissionEvent.seq)
        ):
            events_by_seq[int(seq)] = dict(event_json)
    if include_first:
        first = session.execute(
            select(ArcMissionEvent.seq, ArcMissionEvent.event_json)
            .where(ArcMissionEvent.mission_id == row.mission_id)
            .order_by(ArcMissionEvent.seq.asc())
            .limit(1)
        ).first()
        if first is not None:
            events_by_seq.setdefault(int(first[0]), dict(first[1]))
    if include_last:
        last = session.execute(
            select(ArcMissionEvent.seq, ArcMissionEvent.event_json)
            .where(ArcMissionEvent.mission_id == row.mission_id)
            .order_by(ArcMissionEvent.seq.desc())
            .limit(1)
        ).first()
        if last is not None:
            events_by_seq.setdefault(int(last[0]), dict(last[1]))
    payload["events"] = [events_by_seq[seq] for seq in sorted(events_by_seq)]
    return ARCMissionProjection.model_validate(payload)


def load_latest_events_by_type(
    session: Session, mission_ids: Collection[str], event_type: str
) -> dict[str, dict[str, Any]]:
    """Load the newest event of ``event_type`` per mission in batched SQL queries."""
    ids = list(dict.fromkeys(str(mid) for mid in mission_ids if mid))
    if not ids:
        return {}
    latest: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        latest_seq = (
            select(
                ArcMissionEvent.mission_id.label("mission_id"),
                func.max(ArcMissionEvent.seq).label("max_seq"),
            )
            .where(
                ArcMissionEvent.mission_id.in_(chunk),
                ArcMissionEvent.event_type == event_type,
            )
            .group_by(ArcMissionEvent.mission_id)
            .subquery()
        )
        rows = session.execute(
            select(ArcMissionEvent.mission_id, ArcMissionEvent.event_json).join(
                latest_seq,
                and_(
                    ArcMissionEvent.mission_id == latest_seq.c.mission_id,
                    ArcMissionEvent.seq == latest_seq.c.max_seq,
                ),
            )
        )
        for mission_id, event_json in rows:
            latest[str(mission_id)] = dict(event_json)
    return latest


def _sqlite_typed_json(value: Any, json_type: str | None) -> Any:
    if json_type == "true":
        return True
    if json_type == "false":
        return False
    return value


def _sqlite_budget_mission_rows(session: Session) -> list[dict[str, Any]]:
    pj = ArcMission.projection_json
    jtype = func.json_type
    jget = func.json_extract
    state_expr = case(
        (jtype(pj, "$.state") == "text", jget(pj, "$.state")),
        else_="created",
    )
    fb_is_obj = jtype(pj, "$.goal.feedback_parent") == "object"
    fb_ev_is_obj = and_(fb_is_obj, jtype(pj, "$.goal.feedback_parent.evidence") == "object")
    ctx_is_obj = jtype(pj, "$.goal.evolution_context") == "object"
    vp_is_obj = and_(ctx_is_obj, jtype(pj, "$.goal.evolution_context.variant_policy") == "object")
    is_observing = state_expr == "paper_observing"

    stmt = select(
        ArcMission.mission_id.label("mission_id"),
        ArcMission.created_at.label("created_at"),
        ArcMission.updated_at.label("updated_at"),
        ArcMission.revision.label("revision"),
        case(
            (
                jtype(pj, "$.events") == "array",
                func.json_array_length(pj, "$.events") > 0,
            ),
            else_=False,
        ).label("has_inline_events"),
        state_expr.label("state"),
        (jtype(pj, "$.goal") == "object").label("has_goal"),
        case(
            (jtype(pj, "$.goal.provider_name") == "text", jget(pj, "$.goal.provider_name")),
            else_=None,
        ).label("provider_name"),
        case(
            (
                fb_is_obj,
                literal_column(
                    "EXISTS (SELECT 1 FROM json_each("
                    "arc_missions.projection_json, '$.goal.feedback_parent'))",
                    type_=Boolean(),
                ),
            ),
            else_=False,
        ).label("fb_present"),
        case(
            (fb_is_obj, jtype(pj, "$.goal.feedback_parent.target_id").is_not(None)),
            else_=False,
        ).label("fb_target_id_exists"),
        case(
            (
                and_(fb_is_obj, jtype(pj, "$.goal.feedback_parent.target_id") == "text"),
                jget(pj, "$.goal.feedback_parent.target_id"),
            ),
            else_=None,
        ).label("fb_target_id"),
        case(
            (
                and_(fb_is_obj, jtype(pj, "$.goal.feedback_parent.instance_id") == "text"),
                jget(pj, "$.goal.feedback_parent.instance_id"),
            ),
            else_=None,
        ).label("fb_instance_id"),
        fb_ev_is_obj.label("fb_evidence_is_dict"),
        case(
            (fb_ev_is_obj, jtype(pj, "$.goal.feedback_parent.evidence.strategy_id").is_not(None)),
            else_=False,
        ).label("fb_evidence_sid_exists"),
        case(
            (fb_ev_is_obj, jtype(pj, "$.goal.feedback_parent.evidence.strategy_id")),
            else_=None,
        ).label("fb_evidence_sid_type"),
        case(
            (fb_ev_is_obj, pj[("goal", "feedback_parent", "evidence", "strategy_id")]),
            else_=None,
        ).label("fb_evidence_sid"),
        case(
            (ctx_is_obj, jtype(pj, "$.goal.evolution_context.target_id").is_not(None)),
            else_=False,
        ).label("ctx_target_id_exists"),
        case(
            (
                and_(ctx_is_obj, jtype(pj, "$.goal.evolution_context.target_id") == "text"),
                jget(pj, "$.goal.evolution_context.target_id"),
            ),
            else_=None,
        ).label("ctx_target_id"),
        case(
            (
                and_(
                    ctx_is_obj,
                    jtype(pj, "$.goal.evolution_context.source_instance_id") == "text",
                ),
                jget(pj, "$.goal.evolution_context.source_instance_id"),
            ),
            else_=None,
        ).label("ctx_source_instance_id"),
        case(
            (ctx_is_obj, jtype(pj, "$.goal.evolution_context.source_strategy_id")),
            else_=None,
        ).label("ctx_source_strategy_id_type"),
        case(
            (ctx_is_obj, pj[("goal", "evolution_context", "source_strategy_id")]),
            else_=None,
        ).label("ctx_source_strategy_id"),
        case(
            (ctx_is_obj, jtype(pj, "$.goal.evolution_context.trigger_source").is_not(None)),
            else_=False,
        ).label("ctx_trigger_source_exists"),
        case(
            (
                and_(ctx_is_obj, jtype(pj, "$.goal.evolution_context.trigger_source") == "text"),
                jget(pj, "$.goal.evolution_context.trigger_source"),
            ),
            else_=None,
        ).label("ctx_trigger_source"),
        case(
            (
                and_(ctx_is_obj, jtype(pj, "$.goal.evolution_context.source_snapshot") == "object"),
                pj[("goal", "evolution_context", "source_snapshot")],
            ),
            else_=None,
        ).label("ctx_source_snapshot"),
        case(
            (
                and_(ctx_is_obj, jtype(pj, "$.goal.evolution_context.relay_seats") == "object"),
                pj[("goal", "evolution_context", "relay_seats")],
            ),
            else_=None,
        ).label("ctx_relay_seats"),
        vp_is_obj.label("ctx_vp_is_dict"),
        case(
            (
                and_(
                    vp_is_obj,
                    jtype(pj, "$.goal.evolution_context.variant_policy.baseline_backtest")
                    == "object",
                ),
                pj[("goal", "evolution_context", "variant_policy", "baseline_backtest")],
            ),
            else_=None,
        ).label("ctx_vp_baseline_backtest"),
        case(
            (
                vp_is_obj,
                jtype(pj, "$.goal.evolution_context.variant_policy.variant_creation_supported")
                == "true",
            ),
            else_=False,
        ).label("ctx_vp_supported"),
        case(
            (
                and_(
                    vp_is_obj,
                    jtype(pj, "$.goal.evolution_context.variant_policy.relay") == "object",
                    jtype(pj, "$.goal.evolution_context.variant_policy.relay.slots") == "array",
                ),
                func.json_array_length(
                    pj, "$.goal.evolution_context.variant_policy.relay.slots"
                ),
            ),
            else_=None,
        ).label("ctx_vp_slots_len"),
        case(
            (
                and_(
                    ctx_is_obj,
                    jtype(pj, "$.goal.evolution_context.baseline") == "object",
                    jtype(pj, "$.goal.evolution_context.baseline.strategy_spec") == "object",
                ),
                jtype(pj, "$.goal.evolution_context.baseline.strategy_spec.is_source_variant")
                == "true",
            ),
            else_=False,
        ).label("ctx_baseline_is_source_variant"),
        case(
            (
                and_(
                    jtype(pj, "$.paper_review") == "object",
                    jtype(pj, "$.paper_review.status") == "text",
                ),
                jget(pj, "$.paper_review.status"),
            ),
            else_=None,
        ).label("paper_review_status"),
        case(
            (jtype(pj, "$.avo") == "object", jtype(pj, "$.avo.pending")),
            else_=None,
        ).label("avo_pending_type"),
        case(
            (jtype(pj, "$.avo") == "object", pj[("avo", "pending")]),
            else_=None,
        ).label("avo_pending"),
        case(
            (
                and_(
                    state_expr == "failed",
                    jtype(pj, "$.avo") == "object",
                    jtype(pj, "$.avo.terminal_execution_failure") == "object",
                ),
                pj[("avo", "terminal_execution_failure")],
            ),
            else_=None,
        ).label("avo_terminal_failure"),
        case(
            (
                and_(is_observing, jtype(pj, "$.paper_started_at") == "text"),
                jget(pj, "$.paper_started_at"),
            ),
            else_=None,
        ).label("paper_started_at"),
        case(
            (
                and_(
                    is_observing,
                    jtype(pj, "$.paper_review") == "object",
                    jtype(pj, "$.paper_review.attempt_id") == "text",
                ),
                jget(pj, "$.paper_review.attempt_id"),
            ),
            else_=None,
        ).label("paper_review_attempt_id"),
        case(
            (
                and_(
                    is_observing,
                    jtype(pj, "$.avo") == "object",
                    jtype(pj, "$.avo.final") == "object",
                    jtype(pj, "$.avo.final.attempt_id") == "text",
                ),
                jget(pj, "$.avo.final.attempt_id"),
            ),
            else_=None,
        ).label("avo_final_attempt_id"),
        case(
            (
                and_(is_observing, jtype(pj, "$.current_attempt_id") == "text"),
                jget(pj, "$.current_attempt_id"),
            ),
            else_=None,
        ).label("current_attempt_id"),
        type_coerce(
            literal_column(
                """
                CASE WHEN json_type(arc_missions.projection_json, '$.state') = 'text'
                      AND json_extract(arc_missions.projection_json, '$.state') = 'paper_observing'
                      AND json_type(arc_missions.projection_json, '$.attempts') = 'array'
                THEN (
                    SELECT json_group_array(json_object(
                        'attempt_id', json_extract(je.value, '$.attempt_id'),
                        'parameter_changes', CASE
                            WHEN json_type(je.value, '$.strategy_spec') = 'object'
                             AND json_type(
                                 je.value, '$.strategy_spec.parameter_changes'
                             ) = 'object'
                            THEN json(json_extract(
                                je.value, '$.strategy_spec.parameter_changes'
                            ))
                            ELSE NULL
                        END
                    ))
                    FROM json_each(arc_missions.projection_json, '$.attempts') AS je
                )
                ELSE NULL END
                """
            ),
            JSON(),
        ).label("observing_attempts"),
        case(
            (
                and_(
                    state_expr == "needs_operator",
                    jtype(pj, "$.avo") == "object",
                ),
                case(
                    (jtype(pj, "$.avo.final_window_consumed") == "true", True),
                    (
                        jtype(pj, "$.avo.final_window_consumed") == "integer",
                        jget(pj, "$.avo.final_window_consumed") != 0,
                    ),
                    (
                        jtype(pj, "$.avo.final_window_consumed") == "real",
                        jget(pj, "$.avo.final_window_consumed") != 0.0,
                    ),
                    (
                        jtype(pj, "$.avo.final_window_consumed") == "text",
                        jget(pj, "$.avo.final_window_consumed") != "",
                    ),
                    (
                        jtype(pj, "$.avo.final_window_consumed") == "array",
                        func.json_array_length(pj, "$.avo.final_window_consumed") > 0,
                    ),
                    (
                        jtype(pj, "$.avo.final_window_consumed") == "object",
                        literal_column(
                            "EXISTS (SELECT 1 FROM json_each("
                            "arc_missions.projection_json, '$.avo.final_window_consumed'))",
                            type_=Boolean(),
                        ),
                    ),
                    else_=False,
                ),
            ),
            else_=False,
        ).label("avo_final_window_consumed"),
    )

    out: list[dict[str, Any]] = []
    for row in session.execute(stmt):
        item = dict(row._mapping)
        item["has_inline_events"] = bool(item["has_inline_events"])
        item["has_goal"] = bool(item["has_goal"])
        item["fb_present"] = bool(item["fb_present"])
        item["fb_target_id_exists"] = bool(item["fb_target_id_exists"])
        item["fb_evidence_is_dict"] = bool(item["fb_evidence_is_dict"])
        item["fb_evidence_sid_exists"] = bool(item["fb_evidence_sid_exists"])
        item["fb_evidence_sid"] = _sqlite_typed_json(
            item.pop("fb_evidence_sid"), item.pop("fb_evidence_sid_type")
        )
        item["ctx_target_id_exists"] = bool(item["ctx_target_id_exists"])
        item["ctx_source_strategy_id"] = _sqlite_typed_json(
            item.pop("ctx_source_strategy_id"), item.pop("ctx_source_strategy_id_type")
        )
        item["ctx_trigger_source_exists"] = bool(item["ctx_trigger_source_exists"])
        item["ctx_vp_is_dict"] = bool(item["ctx_vp_is_dict"])
        item["ctx_vp_supported"] = bool(item["ctx_vp_supported"])
        item["ctx_baseline_is_source_variant"] = bool(item["ctx_baseline_is_source_variant"])
        item["avo_pending"] = _sqlite_typed_json(
            item.pop("avo_pending"), item.pop("avo_pending_type")
        )
        item["avo_final_window_consumed"] = bool(item["avo_final_window_consumed"])
        out.append(item)
    return out


def _postgres_budget_mission_rows(session: Session) -> list[dict[str, Any]]:
    stmt = text(
        """
        SELECT m.mission_id,
               m.created_at,
               m.updated_at,
               m.revision,
               CASE WHEN r.events IS NOT NULL AND json_typeof(r.events) = 'array'
                    THEN json_array_length(r.events) > 0
                    ELSE false END AS has_inline_events,
               COALESCE(
                   CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                        THEN r.state #>> '{}' END,
                   'created'
               ) AS state,
               (r.goal IS NOT NULL AND json_typeof(r.goal) = 'object') AS has_goal,
               CASE WHEN g.provider_name IS NOT NULL AND json_typeof(g.provider_name) = 'string'
                    THEN g.provider_name #>> '{}' ELSE NULL END AS provider_name,
               CASE WHEN g.feedback_parent IS NOT NULL
                         AND json_typeof(g.feedback_parent) = 'object'
                    THEN EXISTS (SELECT 1 FROM json_object_keys(g.feedback_parent))
                    ELSE false END AS fb_present,
               (g.feedback_parent IS NOT NULL AND json_typeof(g.feedback_parent) = 'object'
                AND (g.feedback_parent #> '{target_id}') IS NOT NULL) AS fb_target_id_exists,
               g.feedback_parent #> '{target_id}' AS fb_target_id,
               g.feedback_parent #> '{instance_id}' AS fb_instance_id,
               (g.feedback_parent IS NOT NULL AND json_typeof(g.feedback_parent) = 'object'
                AND json_typeof(g.feedback_parent #> '{evidence}') = 'object'
               ) AS fb_evidence_is_dict,
               (g.feedback_parent IS NOT NULL AND json_typeof(g.feedback_parent) = 'object'
                AND json_typeof(g.feedback_parent #> '{evidence}') = 'object'
                AND (g.feedback_parent #> '{evidence,strategy_id}') IS NOT NULL
               ) AS fb_evidence_sid_exists,
               g.feedback_parent #> '{evidence,strategy_id}' AS fb_evidence_sid,
               (g.evolution_context IS NOT NULL AND json_typeof(g.evolution_context) = 'object'
                AND (g.evolution_context #> '{target_id}') IS NOT NULL) AS ctx_target_id_exists,
               ec.target_id AS ctx_target_id,
               ec.source_instance_id AS ctx_source_instance_id,
               ec.source_strategy_id AS ctx_source_strategy_id,
               (g.evolution_context IS NOT NULL AND json_typeof(g.evolution_context) = 'object'
                AND (g.evolution_context #> '{trigger_source}') IS NOT NULL
               ) AS ctx_trigger_source_exists,
               ec.trigger_source AS ctx_trigger_source,
               CASE WHEN ec.source_snapshot IS NOT NULL
                         AND json_typeof(ec.source_snapshot) = 'object'
                    THEN ec.source_snapshot ELSE NULL END AS ctx_source_snapshot,
               CASE WHEN ec.relay_seats IS NOT NULL AND json_typeof(ec.relay_seats) = 'object'
                    THEN ec.relay_seats ELSE NULL END AS ctx_relay_seats,
               (ec.variant_policy IS NOT NULL
                AND json_typeof(ec.variant_policy) = 'object') AS ctx_vp_is_dict,
               CASE WHEN ec.variant_policy IS NOT NULL AND json_typeof(ec.variant_policy) = 'object'
                         AND json_typeof(ec.variant_policy #> '{baseline_backtest}') = 'object'
                    THEN ec.variant_policy #> '{baseline_backtest}'
                    ELSE NULL END AS ctx_vp_baseline_backtest,
               CASE WHEN ec.variant_policy IS NOT NULL AND json_typeof(ec.variant_policy) = 'object'
                         AND json_typeof(
                             ec.variant_policy #> '{variant_creation_supported}'
                         ) = 'boolean'
                    THEN (ec.variant_policy #>> '{variant_creation_supported}')::boolean
                    ELSE false END AS ctx_vp_supported,
               CASE WHEN ec.variant_policy IS NOT NULL AND json_typeof(ec.variant_policy) = 'object'
                         AND json_typeof(ec.variant_policy #> '{relay}') = 'object'
                         AND json_typeof(ec.variant_policy #> '{relay,slots}') = 'array'
                    THEN json_array_length(ec.variant_policy #> '{relay,slots}')
                    ELSE NULL END AS ctx_vp_slots_len,
               CASE WHEN ec.baseline IS NOT NULL AND json_typeof(ec.baseline) = 'object'
                         AND json_typeof(ec.baseline #> '{strategy_spec}') = 'object'
                         AND json_typeof(
                             ec.baseline #> '{strategy_spec,is_source_variant}'
                         ) = 'boolean'
                    THEN (ec.baseline #>> '{strategy_spec,is_source_variant}')::boolean
                    ELSE false END AS ctx_baseline_is_source_variant,
               CASE WHEN r.paper_review IS NOT NULL AND json_typeof(r.paper_review) = 'object'
                    THEN r.paper_review #> '{status}' ELSE NULL END AS paper_review_status,
               CASE WHEN r.avo IS NOT NULL AND json_typeof(r.avo) = 'object'
                    THEN r.avo #> '{pending}' ELSE NULL END AS avo_pending,
               CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                         AND (r.state #>> '{}') = 'failed'
                         AND r.avo IS NOT NULL AND json_typeof(r.avo) = 'object'
                    THEN r.avo #> '{terminal_execution_failure}'
                    ELSE NULL END AS avo_terminal_failure,
               CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                         AND (r.state #>> '{}') = 'paper_observing'
                         AND r.paper_started_at IS NOT NULL
                         AND json_typeof(r.paper_started_at) = 'string'
                    THEN r.paper_started_at #>> '{}' ELSE NULL END AS paper_started_at,
               CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                         AND (r.state #>> '{}') = 'paper_observing'
                         AND r.paper_review IS NOT NULL AND json_typeof(r.paper_review) = 'object'
                    THEN r.paper_review #> '{attempt_id}' ELSE NULL END AS paper_review_attempt_id,
               CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                         AND (r.state #>> '{}') = 'paper_observing'
                         AND r.avo IS NOT NULL AND json_typeof(r.avo) = 'object'
                         AND json_typeof(r.avo #> '{final}') = 'object'
                    THEN r.avo #> '{final,attempt_id}' ELSE NULL END AS avo_final_attempt_id,
               CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                         AND (r.state #>> '{}') = 'paper_observing'
                    THEN r.current_attempt_id ELSE NULL END AS current_attempt_id,
               CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                         AND (r.state #>> '{}') = 'paper_observing'
                         AND r.attempts IS NOT NULL AND json_typeof(r.attempts) = 'array'
                    THEN (
                        SELECT json_agg(json_build_object(
                            'attempt_id', a.attempt_id,
                            'parameter_changes', CASE
                                WHEN a.strategy_spec IS NOT NULL
                                     AND json_typeof(a.strategy_spec) = 'object'
                                THEN a.strategy_spec #> '{parameter_changes}'
                                ELSE NULL
                            END
                        ))
                        FROM json_to_recordset(r.attempts) AS a(attempt_id text, strategy_spec json)
                    )
                    ELSE NULL END AS observing_attempts,
               CASE WHEN r.state IS NOT NULL AND json_typeof(r.state) = 'string'
                         AND (r.state #>> '{}') = 'needs_operator'
                         AND r.avo IS NOT NULL AND json_typeof(r.avo) = 'object'
                    THEN (
                        CASE json_typeof(r.avo #> '{final_window_consumed}')
                            WHEN 'boolean' THEN (r.avo #>> '{final_window_consumed}')::boolean
                            WHEN 'number'
                                THEN (r.avo #>> '{final_window_consumed}')::double precision != 0
                            WHEN 'string' THEN (r.avo #>> '{final_window_consumed}') != ''
                            WHEN 'array'
                                THEN json_array_length(r.avo #> '{final_window_consumed}') > 0
                            WHEN 'object' THEN EXISTS (
                                SELECT 1 FROM json_object_keys(r.avo #> '{final_window_consumed}')
                            )
                            ELSE false
                        END
                    )
                    ELSE false END AS avo_final_window_consumed
        FROM arc_missions m
        LEFT JOIN LATERAL json_to_record(m.projection_json) AS r(
            state json, goal json, paper_review json, avo json, events json,
            current_attempt_id json, paper_started_at json, attempts json
        ) ON m.projection_json IS NOT NULL AND json_typeof(m.projection_json) = 'object'
        LEFT JOIN LATERAL json_to_record(r.goal) AS g(
            provider_name json, feedback_parent json, evolution_context json
        ) ON r.goal IS NOT NULL AND json_typeof(r.goal) = 'object'
        LEFT JOIN LATERAL json_to_record(g.evolution_context) AS ec(
            target_id json, source_instance_id json, source_strategy_id json, trigger_source json,
            source_snapshot json, relay_seats json, variant_policy json, baseline json
        ) ON g.evolution_context IS NOT NULL AND json_typeof(g.evolution_context) = 'object'
        """
    ).columns(
        mission_id=String,
        created_at=DateTime(timezone=True),
        updated_at=DateTime(timezone=True),
        revision=Integer,
        has_inline_events=Boolean,
        state=String,
        has_goal=Boolean,
        provider_name=String,
        fb_present=Boolean,
        fb_target_id_exists=Boolean,
        fb_target_id=JSON,
        fb_instance_id=JSON,
        fb_evidence_is_dict=Boolean,
        fb_evidence_sid_exists=Boolean,
        fb_evidence_sid=JSON,
        ctx_target_id_exists=Boolean,
        ctx_target_id=JSON,
        ctx_source_instance_id=JSON,
        ctx_source_strategy_id=JSON,
        ctx_trigger_source_exists=Boolean,
        ctx_trigger_source=JSON,
        ctx_source_snapshot=JSON,
        ctx_relay_seats=JSON,
        ctx_vp_is_dict=Boolean,
        ctx_vp_baseline_backtest=JSON,
        ctx_vp_supported=Boolean,
        ctx_vp_slots_len=Integer,
        ctx_baseline_is_source_variant=Boolean,
        paper_review_status=JSON,
        avo_pending=JSON,
        avo_terminal_failure=JSON,
        paper_started_at=String,
        paper_review_attempt_id=JSON,
        avo_final_attempt_id=JSON,
        current_attempt_id=JSON,
        observing_attempts=JSON,
        avo_final_window_consumed=Boolean,
    )
    out: list[dict[str, Any]] = []
    for row in session.execute(stmt):
        item = dict(row._mapping)
        item["has_inline_events"] = bool(item["has_inline_events"])
        item["has_goal"] = bool(item["has_goal"])
        item["fb_present"] = bool(item["fb_present"])
        item["fb_target_id_exists"] = bool(item["fb_target_id_exists"])
        item["fb_evidence_is_dict"] = bool(item["fb_evidence_is_dict"])
        item["fb_evidence_sid_exists"] = bool(item["fb_evidence_sid_exists"])
        item["ctx_target_id_exists"] = bool(item["ctx_target_id_exists"])
        item["ctx_trigger_source_exists"] = bool(item["ctx_trigger_source_exists"])
        item["ctx_vp_is_dict"] = bool(item["ctx_vp_is_dict"])
        item["ctx_vp_supported"] = bool(item["ctx_vp_supported"])
        item["ctx_baseline_is_source_variant"] = bool(item["ctx_baseline_is_source_variant"])
        item["avo_final_window_consumed"] = bool(item["avo_final_window_consumed"])
        out.append(item)
    return out


def load_budget_mission_rows(session: Session) -> list[dict[str, Any]] | None:
    """Load lightweight ``ArcMission`` summaries for ``research_budget.usage()``.

    Returns ``None`` on dialects without JSON extraction support so callers can fall back to
    full projection loading. Rows with legacy inline ``events`` are flagged via
    ``has_inline_events`` so the caller loads only those specific rows via ``load_projection``.
    """
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    if dialect == "postgresql":
        return _postgres_budget_mission_rows(session)
    if dialect == "sqlite":
        return _sqlite_budget_mission_rows(session)
    return None


def load_final_validation_records(
    session: Session, mission_ids: Collection[str]
) -> dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    """Load only ``goal.success_criteria`` and the last ``self_test_records`` entry."""
    ids = list(dict.fromkeys(str(mid) for mid in mission_ids if mid))
    if not ids:
        return {}
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else ""
    results: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        if dialect == "postgresql":
            stmt = select(
                ArcMission.mission_id,
                type_coerce(
                    literal_column(
                        "CASE WHEN arc_missions.projection_json IS NOT NULL"
                        " AND json_typeof(arc_missions.projection_json) = 'object'"
                        " AND json_typeof(arc_missions.projection_json #> '{goal}') = 'object'"
                        " AND json_typeof("
                        "arc_missions.projection_json #> '{goal,success_criteria}') = 'object'"
                        " THEN arc_missions.projection_json #> '{goal,success_criteria}'"
                        " ELSE NULL END"
                    ),
                    JSON(),
                ).label("success_criteria"),
                type_coerce(
                    literal_column(
                        "CASE WHEN arc_missions.projection_json IS NOT NULL"
                        " AND json_typeof(arc_missions.projection_json) = 'object'"
                        " AND json_typeof("
                        "arc_missions.projection_json #> '{self_test_records}') = 'array'"
                        " THEN arc_missions.projection_json #> '{self_test_records,-1}'"
                        " ELSE NULL END"
                    ),
                    JSON(),
                ).label("last_self_test"),
            ).where(ArcMission.mission_id.in_(chunk))
            for mission_id, sc, last_record in session.execute(stmt):
                results[str(mission_id)] = (
                    dict(sc) if isinstance(sc, dict) else None,
                    dict(last_record) if isinstance(last_record, dict) else None,
                )
        elif dialect == "sqlite":
            pj = ArcMission.projection_json
            stmt = select(
                ArcMission.mission_id,
                case(
                    (
                        and_(
                            func.json_type(pj, "$.goal") == "object",
                            func.json_type(pj, "$.goal.success_criteria") == "object",
                        ),
                        pj[("goal", "success_criteria")],
                    ),
                    else_=None,
                ).label("success_criteria"),
                type_coerce(
                    case(
                        (
                            func.json_type(pj, "$.self_test_records") == "array",
                            func.json_extract(pj, "$.self_test_records[#-1]"),
                        ),
                        else_=None,
                    ),
                    JSON(),
                ).label("last_self_test"),
            ).where(ArcMission.mission_id.in_(chunk))
            for mission_id, sc, last_record in session.execute(stmt):
                results[str(mission_id)] = (
                    dict(sc) if isinstance(sc, dict) else None,
                    dict(last_record) if isinstance(last_record, dict) else None,
                )
        else:
            for row in session.scalars(select(ArcMission).where(ArcMission.mission_id.in_(chunk))):
                projection = load_projection(session, row, with_events=False)
                sc_dict = (
                    projection.goal.success_criteria.model_dump()
                    if projection.goal is not None
                    else None
                )
                last_rec = (
                    dict(projection.self_test_records[-1])
                    if projection.self_test_records
                    else None
                )
                results[row.mission_id] = (sc_dict, last_rec)
    return results


def _stored_events(session: Session, mission_id: str) -> list[dict[str, Any]]:
    return [
        dict(value)
        for value in session.scalars(
            select(ArcMissionEvent.event_json)
            .where(ArcMissionEvent.mission_id == mission_id)
            .order_by(ArcMissionEvent.seq)
        )
    ]


def insert_mission(session: Session, controller: ARCController, revision: int) -> dict[str, Any]:
    row = ArcMission(
        mission_id=controller.mission_id,
        state=controller.projection.state,
        projection_json={},
        revision=revision,
        event_count=0,
    )
    session.add(row)
    session.flush()
    return _write(session, row, controller, revision)


def _write(
    session: Session, row: ArcMission, controller: ARCController, revision: int
) -> dict[str, Any]:
    """Append the controller's unjournalled events, then store the projection without them.

    The controller was read at this row's revision, so its first ``event_count`` events
    are exactly the journalled ones; the check on the last one guards that invariant.
    """
    payload = controller.projection.model_dump(mode="json")
    events = payload["events"]
    stored = int(row.event_count or 0)
    if stored > len(events):
        raise RuntimeError("arc_event_journal_ahead_of_projection")
    if stored:
        last = session.scalars(
            select(ArcMissionEvent.event_id).where(
                ArcMissionEvent.mission_id == row.mission_id, ArcMissionEvent.seq == stored
            )
        ).one_or_none()
        if last != events[stored - 1]["event_id"]:
            raise RuntimeError("arc_event_journal_diverged")
    for seq, event in enumerate(events[stored:], start=stored + 1):
        session.add(
            ArcMissionEvent(
                mission_id=row.mission_id,
                seq=seq,
                event_id=event["event_id"],
                event_type=event["event_type"],
                event_json=event,
            )
        )
    row.event_count = len(events)
    row.state = controller.projection.state
    row.projection_json = {**payload, "events": []}
    row.revision = revision
    session.flush()
    return payload


def _cached_live_controller(
    mission_id: str,
) -> tuple[ARCController | None, ARCController | None]:
    """Return ``(fresh_cached, fallback_cached)`` from ``MISSIONS`` / ``_EPHEMERAL_MISSIONS``."""
    with _CACHE_LOCK:
        live = MISSIONS.get(mission_id)
        ephemeral = _EPHEMERAL_MISSIONS.get(mission_id)
    if live is not None and not _is_stale(mission_id, live.revision):
        return live, live
    if ephemeral is not None and not _is_stale(mission_id, ephemeral.revision):
        return ephemeral, ephemeral
    return None, live if live is not None else ephemeral


def _load_uncached_with(
    mission_id: str,
    loader: Callable[[Session, ArcMission], tuple[ARCMissionProjection, int]],
) -> ARCController | None:
    fresh, fallback = _cached_live_controller(mission_id)
    if fresh is not None:
        return fresh
    if _database is not None:
        with _database.session() as session:
            row = session.get(ArcMission, mission_id)
            if row is not None and isinstance(row.projection_json, dict):
                projection, revision = loader(session, row)
                controller = ARCController(mission_id=mission_id)
                controller.projection = projection
                controller.revision = revision
                return controller
        return fallback
    return _load_persisted(mission_id) or fallback


def get_controller(mission_id: str) -> ARCController | None:
    """Return the mission as committed, reloading when another process advanced it."""
    fresh, fallback = _cached_live_controller(mission_id)
    if fresh is not None:
        return fresh
    loaded = _load_persisted(mission_id)
    if loaded is not None:
        _store_cached_controller(loaded)
        return loaded
    return fallback


def peek_controller(mission_id: str) -> ARCController | None:
    """The mission as committed, for a reader that does not want it kept in memory.

    Like ``get_controller``, except that a mission nobody holds is loaded and handed back
    *without* being added to ``MISSIONS``. A scan over many missions must not turn every mission it
    touches into a resident controller: the worker held ~2 GB of them, and every full garbage
    collection walked all of it, freezing the whole process (and its event loop) for seconds.
    """
    fresh, fallback = _cached_live_controller(mission_id)
    if fresh is not None:
        return fresh
    return _load_persisted(mission_id) or fallback


def peek_light_controller(mission_id: str) -> ARCController | None:
    """Load the mission without its journal unless an up-to-date copy is already held.

    When loaded from DB without events, ``controller.revision`` is set to ``-1`` if the row
    has unloaded journal events, so any subsequent ``commit_event`` automatically rebases onto
    the full committed projection before writing.
    """

    def _load(session: Session, row: ArcMission) -> tuple[ARCMissionProjection, int]:
        projection = load_projection(session, row, with_events=False)
        has_unloaded_journal = int(row.event_count or 0) > 0 and not (
            row.projection_json or {}
        ).get("events")
        revision = -1 if has_unloaded_journal else int(row.revision or 0)
        return projection, revision

    return _load_uncached_with(mission_id, _load)


def peek_controller_tail(
    mission_id: str, event_types: Collection[str]
) -> ARCController | None:
    """Load an uncached controller with only the newest event of each of ``event_types``."""
    if not mission_id:
        return None
    return _load_uncached_with(
        mission_id,
        lambda session, row: (
            load_projection_tail(session, row, event_types),
            int(row.revision or 0),
        ),
    )


def peek_controller_events(
    mission_id: str, event_types: Collection[str]
) -> ARCController | None:
    """Load an uncached controller with only ``event_types`` hydrated (or cached live copy)."""
    if not mission_id:
        return None
    return _load_uncached_with(
        mission_id,
        lambda session, row: (
            load_projection_events(session, row, event_types),
            int(row.revision or 0),
        ),
    )


def load_progress_projection(mission_id: str) -> tuple[ARCMissionProjection, int] | None:
    """Load projection + event count for progress polling without caching or full journal read.

    In database mode for journaled rows (empty inline ``events``), reads at most the newest
    100 ``ArcMissionEvent`` rows plus earlier stage/summary events (never ``paper_observed``).
    Legacy rows with inline events fall back to ``load_projection``.
    """
    with _CACHE_LOCK:
        live = MISSIONS.get(mission_id)
        ephemeral = _EPHEMERAL_MISSIONS.get(mission_id)
    if live is not None and not _is_stale(mission_id, live.revision):
        return live.projection, len(live.projection.events)
    if ephemeral is not None and not _is_stale(mission_id, ephemeral.revision):
        return ephemeral.projection, len(ephemeral.projection.events)
    if _database is None:
        loaded = _load_persisted(mission_id) or live or ephemeral
        if loaded is None:
            return None
        return loaded.projection, len(loaded.projection.events)
    with _database.session() as session:
        row = session.get(ArcMission, mission_id)
        if row is None or not isinstance(row.projection_json, dict):
            fallback = live or ephemeral
            if fallback is None:
                return None
            return fallback.projection, len(fallback.projection.events)
        payload = dict(row.projection_json or {})
        if payload.get("events"):
            projection = load_projection(session, row)
            return projection, len(projection.events)
        tail_rows = session.execute(
            select(ArcMissionEvent.seq, ArcMissionEvent.event_json)
            .where(ArcMissionEvent.mission_id == mission_id)
            .order_by(ArcMissionEvent.seq.desc())
            .limit(100)
        ).all()
        events_by_seq: dict[int, dict[str, Any]] = {
            int(seq): dict(event_json) for seq, event_json in tail_rows
        }
        min_tail_seq = min(events_by_seq) if events_by_seq else 0
        latest_seq = max(events_by_seq) if events_by_seq else 0
        if min_tail_seq > 1:
            for seq, event_json in session.execute(
                select(ArcMissionEvent.seq, ArcMissionEvent.event_json)
                .where(
                    ArcMissionEvent.mission_id == mission_id,
                    ArcMissionEvent.seq < min_tail_seq,
                    ArcMissionEvent.event_type.in_(_SUMMARY_EVENT_TYPES),
                )
                .order_by(ArcMissionEvent.seq)
            ):
                events_by_seq.setdefault(int(seq), dict(event_json))
        payload["events"] = [events_by_seq[seq] for seq in sorted(events_by_seq)]
        projection = ARCMissionProjection.model_validate(payload)
        total_events = max(int(row.event_count or 0), latest_seq)
        return projection, total_events


def list_mission_summaries(*, state: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Return bounded mission list summaries without polluting ``MISSIONS`` or reading full logs."""
    from hypertrade.arc.evidence_view import build_mission_summary

    if limit <= 0:
        return []
    if _database is None:
        projections: list[ARCMissionProjection] = []
        seen_ids: set[str] = set()
        for mission_id, payload in _MEMORY.items():
            if state is not None and payload.get("state") != state:
                continue
            projections.append(ARCMissionProjection.model_validate(payload))
            seen_ids.add(mission_id)
        with _CACHE_LOCK:
            cached = list(MISSIONS.items())
        for mission_id, controller in cached:
            if mission_id in seen_ids:
                continue
            if state is not None and controller.projection.state != state:
                continue
            projections.append(controller.projection)
        summaries = [build_mission_summary(projection) for projection in projections]
        summaries.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return summaries[:limit]

    with _database.session() as session:
        stmt = select(ArcMission)
        if state is not None:
            stmt = stmt.where(ArcMission.state == state)
        rows = session.scalars(
            stmt.order_by(ArcMission.updated_at.desc(), ArcMission.mission_id.desc()).limit(limit)
        ).all()
        valid_rows = [row for row in rows if isinstance(row.projection_json, dict)]
        non_inline_rows = [
            row for row in valid_rows if not (row.projection_json or {}).get("events")
        ]
        non_inline_ids = [row.mission_id for row in non_inline_rows]
        first_by_mission: dict[str, tuple[int, dict[str, Any]]] = {}
        summary_events_by_mission: dict[str, dict[int, dict[str, Any]]] = {
            mid: {} for mid in non_inline_ids
        }
        if non_inline_ids:
            for mid, seq, event_json in session.execute(
                select(
                    ArcMissionEvent.mission_id,
                    ArcMissionEvent.seq,
                    ArcMissionEvent.event_json,
                ).where(
                    ArcMissionEvent.mission_id.in_(non_inline_ids),
                    ArcMissionEvent.seq == 1,
                )
            ):
                first_by_mission[str(mid)] = (int(seq), dict(event_json))
            for row in non_inline_rows:
                if row.mission_id not in first_by_mission and int(row.event_count or 0) > 0:
                    first = session.execute(
                        select(ArcMissionEvent.seq, ArcMissionEvent.event_json)
                        .where(ArcMissionEvent.mission_id == row.mission_id)
                        .order_by(ArcMissionEvent.seq.asc())
                        .limit(1)
                    ).first()
                    if first is not None:
                        first_by_mission[row.mission_id] = (int(first[0]), dict(first[1]))
            for mid, seq, event_json in session.execute(
                select(
                    ArcMissionEvent.mission_id,
                    ArcMissionEvent.seq,
                    ArcMissionEvent.event_json,
                )
                .where(
                    ArcMissionEvent.mission_id.in_(non_inline_ids),
                    ArcMissionEvent.event_type.in_(_SUMMARY_EVENT_TYPES),
                )
                .order_by(ArcMissionEvent.mission_id, ArcMissionEvent.seq)
            ):
                summary_events_by_mission[str(mid)][int(seq)] = dict(event_json)
        summaries = []
        for row in valid_rows:
            raw = dict(row.projection_json or {})
            if raw.get("events"):
                projection = load_projection(session, row)
            else:
                events_map = summary_events_by_mission[row.mission_id]
                if row.mission_id in first_by_mission:
                    seq1, ev1 = first_by_mission[row.mission_id]
                    events_map.setdefault(seq1, ev1)
                raw["events"] = [events_map[seq] for seq in sorted(events_map)]
                projection = ARCMissionProjection.model_validate(raw)
            summaries.append(build_mission_summary(projection))
    summaries.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return summaries[:limit]


def list_mission_ids(
    *, state: str | None = None, states: Collection[str] | None = None
) -> list[str]:
    """Mission ids, optionally only those whose state is ``state`` or one of ``states``.

    The state column is written with the projection on every commit, so a scan can ask the
    database which missions could possibly interest it instead of loading every mission ever
    created to find the few that are not finished.
    """
    wanted = _wanted_states(state, states)
    if _database is not None:
        with _database.session() as session:
            stmt = select(ArcMission.mission_id)
            if wanted is not None:
                stmt = stmt.where(ArcMission.state.in_(sorted(wanted)))
            return [str(value) for value in session.scalars(stmt).all()]
    return [
        mission_id
        for mission_id, payload in _MEMORY.items()
        if wanted is None or payload.get("state") in wanted
    ]


def _wanted_states(state: str | None, states: Collection[str] | None) -> set[str] | None:
    if state is None and states is None:
        return None
    wanted = set(states) if states is not None else None
    if state is not None:
        wanted = {state} if wanted is None else wanted & {state}
    return wanted


def committed_revisions(mission_ids: Collection[str]) -> dict[str, int]:
    """The committed revision of each of these missions (those that exist), in one query."""
    if _database is None:
        return {m: _MEMORY_REVISIONS[m] for m in mission_ids if m in _MEMORY_REVISIONS}
    ids = list(mission_ids)
    revisions: dict[str, int] = {}
    with _database.session() as session:
        for start in range(0, len(ids), 500):
            rows = session.execute(
                select(ArcMission.mission_id, ArcMission.revision).where(
                    ArcMission.mission_id.in_(ids[start : start + 500])
                )
            )
            revisions.update({str(mission_id): int(revision or 0) for mission_id, revision in rows})
    return revisions


def _commit_in_memory(controller: ARCController, event: ARCEventV1) -> None:
    controller.absorb(event)
    controller.revision += 1
    _MEMORY_REVISIONS[controller.mission_id] = controller.revision
    _cache(controller, controller.projection.model_dump(mode="json"))


def _store_cached_controller(controller: ARCController) -> None:
    mission_id = controller.mission_id
    with _CACHE_LOCK:
        if controller.projection.state in _NON_RESIDENT_STATES:
            MISSIONS.pop(mission_id, None)
            _EPHEMERAL_MISSIONS[mission_id] = controller
        else:
            _EPHEMERAL_MISSIONS.pop(mission_id, None)
            MISSIONS[mission_id] = controller


def _cache(controller: ARCController, payload: dict[str, Any]) -> None:
    _store_cached_controller(controller)
    _MEMORY[controller.mission_id] = payload


def _is_stale(mission_id: str, revision: int) -> bool:
    """Without a database this process is the only writer, so the cache is the truth."""
    if _database is None:
        return False
    committed = _committed_revision(mission_id)
    return committed is not None and committed != revision


def _committed_revision(mission_id: str) -> int | None:
    if _database is None:
        return _MEMORY_REVISIONS.get(mission_id)
    with _database.session() as session:
        value = session.scalars(
            select(ArcMission.revision).where(ArcMission.mission_id == mission_id)
        ).one_or_none()
    return None if value is None else int(value)


def _load_persisted(mission_id: str) -> ARCController | None:
    payload: dict[str, Any] | None = None
    revision = 0
    if _database is not None:
        with _database.session() as session:
            row = session.get(ArcMission, mission_id)
            if row is not None and isinstance(row.projection_json, dict):
                projection = load_projection(session, row)
                controller = ARCController(mission_id=mission_id)
                controller.projection = projection
                controller.revision = int(row.revision or 0)
                return controller
    if payload is None:
        stored = _MEMORY.get(mission_id)
        payload = dict(stored) if stored is not None else None
        revision = _MEMORY_REVISIONS.get(mission_id, 0)
    if payload is None:
        return None
    controller = ARCController(mission_id=mission_id)
    controller.projection = ARCMissionProjection.model_validate(payload)
    controller.revision = revision
    return controller


def save_avo_context(mission_id: str, record: dict[str, Any]) -> str:
    """Private context snapshot; durable deployments must journal before dispatch."""
    from hypertrade.agent.compaction import digest
    from hypertrade.agent.context_journal import save_context_record

    if _database is None:
        # The in-memory store is used only by ephemeral/test controllers.
        return "ephemeral:" + digest(record)
    return save_context_record(_database, mission_id, record)
