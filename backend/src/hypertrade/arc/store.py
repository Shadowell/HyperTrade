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
from collections.abc import Callable, Iterator
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


def reset_runtime() -> None:
    """Drop in-process controllers. Persisted rows and the memory snapshot stay."""
    MISSIONS.clear()


def reset_store() -> None:
    MISSIONS.clear()
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


def load_projection(session: Session, row: ArcMission) -> ARCMissionProjection:
    """The committed projection: journalled events plus any inline legacy events.

    Rows written by pre-journal code keep events inline in ``projection_json``; a process
    still running that code during a deploy appends there too. Both layouts are merged
    by ``event_id`` so neither loses nor duplicates an event.
    """
    payload = dict(row.projection_json or {})
    inline = list(payload.get("events") or [])
    stored = _stored_events(session, row.mission_id)
    known = {event["event_id"] for event in stored}
    payload["events"] = stored + [event for event in inline if event.get("event_id") not in known]
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


def list_mission_ids(*, state: str | None = None) -> list[str]:
    if _database is not None:
        with _database.session() as session:
            stmt = select(ArcMission.mission_id)
            if state is not None:
                stmt = stmt.where(ArcMission.state == state)
            return [str(value) for value in session.scalars(stmt).all()]
    ids: list[str] = []
    for mission_id, payload in _MEMORY.items():
        if state is None or payload.get("state") == state:
            ids.append(mission_id)
    return ids


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
