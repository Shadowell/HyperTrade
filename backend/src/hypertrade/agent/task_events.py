"""Append-only task events and cursor-based projections."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hypertrade.db import AgentSession, AgentTask, Database, TaskEvent

_REDACTED_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "private_reasoning",
    "reasoning_text",
    "secret",
    "token",
}


class TaskEventService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        task_id: str,
        event: str,
        *,
        actor: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> TaskEvent:
        with self.db.session() as session:
            query = select(AgentTask).where(AgentTask.id == task_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            task = session.scalar(query)
            if task is None:
                raise KeyError(task_id)
            row = self.append_in_session(
                session,
                task,
                event,
                actor=actor,
                payload=payload,
            )
            session.flush()
            session.expunge(row)
            return row

    @staticmethod
    def append_in_session(
        session: Session,
        task: AgentTask,
        event: str,
        *,
        actor: str = "system",
        payload: dict[str, Any] | None = None,
    ) -> TaskEvent:
        task.last_event_sequence = int(task.last_event_sequence or 0) + 1
        if task.session_id:
            agent_session = session.get(AgentSession, task.session_id)
            if agent_session is not None:
                agent_session.last_event_sequence = int(agent_session.last_event_sequence or 0) + 1
        row = TaskEvent(
            task_id=task.id,
            sequence=task.last_event_sequence,
            event=event,
            actor=actor,
            payload_json=_safe_projection(payload or {}),
            redaction_version=1,
        )
        session.add(row)
        return row

    def list(self, task_id: str, *, after: int = 0, limit: int = 500) -> list[TaskEvent]:
        bounded = max(1, min(limit, 1000))
        with self.db.session() as session:
            if session.get(AgentTask, task_id) is None:
                raise KeyError(task_id)
            rows = session.scalars(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id, TaskEvent.sequence > max(after, 0))
                .order_by(TaskEvent.sequence)
                .limit(bounded)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)


def task_event_to_dict(row: TaskEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "sequence": row.sequence,
        "event": row.event,
        "occurred_at": row.created_at.isoformat(),
        "actor": row.actor,
        "payload": dict(row.payload_json or {}),
        "redaction_version": row.redaction_version,
    }


def _safe_projection(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _REDACTED_KEYS else _safe_projection(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_projection(item) for item in value[:100]]
    if isinstance(value, tuple):
        return [_safe_projection(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    if value is None or isinstance(value, int | float | bool):
        return value
    return str(value)[:2000]
