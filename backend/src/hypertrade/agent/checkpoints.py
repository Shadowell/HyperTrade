"""Minimal checkpoint persistence for durable Agent tasks."""

import hashlib
import json
from typing import Any

from sqlalchemy import desc, func, select

from hypertrade.agent.task_events import TaskEventService
from hypertrade.db import AgentTask, Database, TaskCheckpoint, new_id


class TaskCheckpointService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        task_id: str,
        state: dict[str, Any],
        *,
        node_run_id: str | None = None,
        reconciliation_required: bool = False,
    ) -> TaskCheckpoint:
        canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.db.session() as session:
            query = select(AgentTask).where(AgentTask.id == task_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            task = session.scalar(query)
            if task is None:
                raise KeyError(task_id)
            current = session.scalar(
                select(func.max(TaskCheckpoint.sequence)).where(TaskCheckpoint.task_id == task_id)
            )
            row = TaskCheckpoint(
                task_id=task_id,
                node_run_id=node_run_id,
                sequence=int(current or 0) + 1,
                state_json=dict(state),
                state_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                schema_version=1,
                resume_token=new_id("resume"),
                reconciliation_required=reconciliation_required,
            )
            session.add(row)
            session.flush()
            task.last_checkpoint_id = row.id
            TaskEventService.append_in_session(
                session,
                task,
                "checkpoint_created",
                payload={
                    "checkpoint_id": row.id,
                    "sequence": row.sequence,
                    "state_hash": row.state_hash,
                    "reconciliation_required": reconciliation_required,
                },
            )
            session.expunge(row)
            return row

    def latest(self, task_id: str) -> TaskCheckpoint | None:
        with self.db.session() as session:
            if session.get(AgentTask, task_id) is None:
                raise KeyError(task_id)
            row = session.scalar(
                select(TaskCheckpoint)
                .where(TaskCheckpoint.task_id == task_id)
                .order_by(desc(TaskCheckpoint.sequence))
                .limit(1)
            )
            if row is not None:
                session.expunge(row)
            return row


def checkpoint_to_dict(row: TaskCheckpoint) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "node_run_id": row.node_run_id,
        "sequence": row.sequence,
        "state": dict(row.state_json or {}),
        "state_hash": row.state_hash,
        "schema_version": row.schema_version,
        "resume_token": row.resume_token,
        "reconciliation_required": row.reconciliation_required,
        "created_at": row.created_at.isoformat(),
    }
