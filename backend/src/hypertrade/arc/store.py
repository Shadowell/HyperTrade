"""Durable ARC mission projection. Memory is a cache; the database is the restart truth."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from hypertrade.arc.controller import ARCController, ARCMissionProjection
from hypertrade.db import ArcMission, Database

MISSIONS: dict[str, ARCController] = {}
_MEMORY: dict[str, dict[str, Any]] = {}
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
    configure_store(None)


def save_mission(controller: ARCController) -> None:
    MISSIONS[controller.mission_id] = controller
    payload = controller.projection.model_dump(mode="json")
    _MEMORY[controller.mission_id] = payload
    if _database is None:
        return
    with _database.session() as session:
        row = session.get(ArcMission, controller.mission_id)
        if row is None:
            session.add(
                ArcMission(
                    mission_id=controller.mission_id,
                    state=controller.projection.state,
                    projection_json=payload,
                )
            )
            return
        row.state = controller.projection.state
        row.projection_json = payload


def get_controller(mission_id: str) -> ARCController | None:
    live = MISSIONS.get(mission_id)
    if live is not None:
        return live
    loaded = _load_persisted(mission_id)
    if loaded is not None:
        MISSIONS[mission_id] = loaded
    return loaded


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


def _load_persisted(mission_id: str) -> ARCController | None:
    payload: dict[str, Any] | None = None
    if _database is not None:
        with _database.session() as session:
            row = session.get(ArcMission, mission_id)
            if row is not None and isinstance(row.projection_json, dict):
                payload = dict(row.projection_json)
    if payload is None:
        stored = _MEMORY.get(mission_id)
        payload = dict(stored) if stored is not None else None
    if payload is None:
        return None
    controller = ARCController(mission_id=mission_id)
    controller.projection = ARCMissionProjection.model_validate(payload)
    return controller
