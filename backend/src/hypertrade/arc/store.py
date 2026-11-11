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

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hypertrade.arc.controller import ARCController, ARCEventV1, ARCMissionProjection
from hypertrade.db import ArcMission, ArcMissionEvent, Database

MISSIONS: dict[str, ARCController] = {}
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
    MISSIONS.clear()
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
    MISSIONS.clear()
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


def get_controller(mission_id: str) -> ARCController | None:
    """Return the mission as committed, reloading when another process advanced it."""
    live = MISSIONS.get(mission_id)
    if live is not None and not _is_stale(mission_id, live.revision):
        return live
    loaded = _load_persisted(mission_id)
    if loaded is not None:
        MISSIONS[mission_id] = loaded
        return loaded
    return live


def peek_controller(mission_id: str) -> ARCController | None:
    """The mission as committed, for a reader that does not want it kept in memory.

    Like ``get_controller``, except that a mission nobody holds is loaded and handed back
    *without* being added to ``MISSIONS``. A scan over many missions must not turn every mission it
    touches into a resident controller: the worker held ~2 GB of them, and every full garbage
    collection walked all of it, freezing the whole process (and its event loop) for seconds.
    """
    live = MISSIONS.get(mission_id)
    if live is not None and not _is_stale(mission_id, live.revision):
        return live
    return _load_persisted(mission_id) or live


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


def _cache(controller: ARCController, payload: dict[str, Any]) -> None:
    MISSIONS[controller.mission_id] = controller
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
