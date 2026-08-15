"""Durable ARC mission projection. Memory is a cache; the database is the restart truth.

``hypertrade-api`` and ``hypertrade-worker`` are separate processes that advance the
same mission: the API runs research and serves approvals, the worker advances paper
observation. Each holds its own controller and persists a whole projection snapshot,
so a cache that is never refreshed serves a mission that stopped being true, and a
snapshot written from it erases whatever the other process committed meanwhile. Every
read here is revision-checked and every write happens under the mission row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from hypertrade.arc.controller import ARCController, ARCEventV1, ARCMissionProjection
from hypertrade.db import ArcMission, Database

MISSIONS: dict[str, ARCController] = {}
_MEMORY: dict[str, dict[str, Any]] = {}
_MEMORY_REVISIONS: dict[str, int] = {}
_database: Database | None = None


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
            controller.rebase(
                ARCMissionProjection.model_validate(dict(row.projection_json)),
                int(row.revision or 0),
            )
        controller.absorb(event)
        payload = controller.projection.model_dump(mode="json")
        revision = controller.revision + 1
        if row is None:
            session.add(
                ArcMission(
                    mission_id=controller.mission_id,
                    state=controller.projection.state,
                    projection_json=payload,
                    revision=revision,
                )
            )
        else:
            row.state = controller.projection.state
            row.projection_json = payload
            row.revision = revision
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
            payload = controller.projection.model_dump(mode="json")
            controller.revision = 1
            session.add(
                ArcMission(
                    mission_id=controller.mission_id,
                    state=controller.projection.state,
                    projection_json=payload,
                    revision=1,
                )
            )
            _cache(controller, payload)
            return
        if int(row.revision or 0) != controller.revision:
            controller.rebase(
                ARCMissionProjection.model_validate(dict(row.projection_json)),
                int(row.revision or 0),
            )
            _cache(controller, dict(row.projection_json))
            return
        payload = controller.projection.model_dump(mode="json")
        revision = controller.revision + 1
        row.state = controller.projection.state
        row.projection_json = payload
        row.revision = revision
        controller.revision = revision
    _cache(controller, payload)


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
                payload = dict(row.projection_json)
                revision = int(row.revision or 0)
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
