"""Durable TaskNodeRun attempts used as the graph execution fact source."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select

from hypertrade.agent.task_events import TaskEventService
from hypertrade.db import AgentTask, Database, TaskNodeRun, utc_now


@dataclass(frozen=True)
class NodeStart:
    node: TaskNodeRun
    replayed: bool


class TaskNodeRunService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def start(
        self,
        task_id: str,
        *,
        node_key: str,
        role_key: str,
        depends_on: list[str],
        input_ref: dict[str, Any],
        tool_policy: dict[str, Any],
    ) -> NodeStart:
        with self.db.session() as session:
            task_query = select(AgentTask).where(AgentTask.id == task_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                task_query = task_query.with_for_update()
            task = session.scalar(task_query)
            if task is None:
                raise KeyError(task_id)
            latest = session.scalar(
                select(TaskNodeRun)
                .where(TaskNodeRun.task_id == task_id, TaskNodeRun.node_key == node_key)
                .order_by(desc(TaskNodeRun.attempt))
                .limit(1)
            )
            if latest is not None and latest.status == "completed":
                session.expunge(latest)
                return NodeStart(latest, True)
            attempt = int(latest.attempt if latest is not None else 0) + 1
            row = TaskNodeRun(
                task_id=task_id,
                node_key=node_key,
                role_key=role_key,
                attempt=attempt,
                status="running",
                depends_on_json=sorted(set(depends_on)),
                input_ref_json=dict(input_ref),
                output_ref_json={},
                tool_policy_json=dict(tool_policy),
                usage_json={},
                started_at=utc_now(),
            )
            session.add(row)
            session.flush()
            TaskEventService.append_in_session(
                session,
                task,
                "research_node_started",
                actor=f"role:{role_key}",
                payload={
                    "node_run_id": row.id,
                    "node_key": node_key,
                    "role_key": role_key,
                    "attempt": attempt,
                    "prompt_hash": input_ref.get("prompt_hash", ""),
                    "tool_catalog_hash": tool_policy.get("catalog_hash", ""),
                },
            )
            session.expunge(row)
            return NodeStart(row, False)

    def complete(
        self,
        node_run_id: str,
        *,
        output_ref: dict[str, Any],
        usage: dict[str, Any],
    ) -> TaskNodeRun:
        return self._finish(
            node_run_id,
            status="completed",
            output_ref=output_ref,
            usage=usage,
            error={},
        )

    def fail(self, node_run_id: str, *, error: dict[str, Any]) -> TaskNodeRun:
        return self._finish(
            node_run_id,
            status="failed",
            output_ref={},
            usage={},
            error=error,
        )

    def interrupt(self, node_run_id: str, *, status: str, reason: str) -> TaskNodeRun:
        return self._finish(
            node_run_id,
            status=status,
            output_ref={},
            usage={},
            error={"code": "task_control_interrupted", "reason": reason},
        )

    def _finish(
        self,
        node_run_id: str,
        *,
        status: str,
        output_ref: dict[str, Any],
        usage: dict[str, Any],
        error: dict[str, Any],
    ) -> TaskNodeRun:
        with self.db.session() as session:
            node_query = select(TaskNodeRun).where(TaskNodeRun.id == node_run_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                node_query = node_query.with_for_update()
            row = session.scalar(node_query)
            if row is None:
                raise KeyError(node_run_id)
            task_query = select(AgentTask).where(AgentTask.id == row.task_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                task_query = task_query.with_for_update()
            task = session.scalar(task_query)
            if task is None:
                raise KeyError(row.task_id)
            row.status = status
            row.output_ref_json = dict(output_ref)
            row.usage_json = dict(usage)
            row.error_json = dict(error)
            row.completed_at = utc_now()
            TaskEventService.append_in_session(
                session,
                task,
                f"research_node_{status}",
                actor=f"role:{row.role_key}",
                payload={
                    "node_run_id": row.id,
                    "node_key": row.node_key,
                    "attempt": row.attempt,
                    "evidence_ids": output_ref.get("evidence_ids", []),
                    "error": error,
                },
            )
            session.flush()
            session.expunge(row)
            return row

    def list(self, task_id: str) -> list[TaskNodeRun]:
        with self.db.session() as session:
            rows = session.scalars(
                select(TaskNodeRun)
                .where(TaskNodeRun.task_id == task_id)
                .order_by(TaskNodeRun.created_at, TaskNodeRun.attempt)
            ).all()
            for row in rows:
                session.expunge(row)
            return list(rows)


def node_run_to_dict(row: TaskNodeRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "node_key": row.node_key,
        "role_key": row.role_key,
        "attempt": row.attempt,
        "status": row.status,
        "depends_on": list(row.depends_on_json),
        "input_ref": dict(row.input_ref_json),
        "output_ref": dict(row.output_ref_json),
        "tool_policy": dict(row.tool_policy_json),
        "usage": dict(row.usage_json),
        "error": dict(row.error_json),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }
