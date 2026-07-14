"""Canonical Agent task state machine, control actions, budgets, and leases."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hypertrade.agent.task_events import TaskEventService
from hypertrade.db import AgentSession, AgentTask, Database, utc_now

TaskStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "pause_requested",
    "paused",
    "cancel_requested",
    "canceled",
    "retry_wait",
    "failed",
    "completed",
]

TERMINAL_TASK_STATUSES = frozenset({"canceled", "failed", "completed"})

TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "paused", "canceled"}),
    "running": frozenset(
        {
            "awaiting_approval",
            "pause_requested",
            "cancel_requested",
            "retry_wait",
            "failed",
            "completed",
        }
    ),
    "awaiting_approval": frozenset({"running", "pause_requested", "cancel_requested", "failed"}),
    "pause_requested": frozenset({"paused", "cancel_requested", "failed"}),
    "paused": frozenset({"queued", "canceled"}),
    "cancel_requested": frozenset({"canceled", "failed"}),
    "retry_wait": frozenset({"queued", "canceled", "failed"}),
    "failed": frozenset({"queued"}),
    "canceled": frozenset(),
    "completed": frozenset(),
}


class TaskBudget(BaseModel):
    max_tokens: int = Field(default=100_000, ge=1)
    max_model_calls: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=40, ge=0)
    max_backtests: int = Field(default=0, ge=0)
    max_duration_seconds: int = Field(default=900, ge=1)
    max_concurrency: int = Field(default=1, ge=1, le=16)


class AgentTaskCreate(BaseModel):
    session_id: str | None = None
    parent_task_id: str | None = None
    kind: Literal["chat_run", "research_graph", "evaluation", "triggered_research"] = "chat_run"
    objective: str = Field(min_length=1, max_length=20_000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    resource_type: str = Field(default="", max_length=64)
    resource_id: str = Field(default="", max_length=64)
    budget: TaskBudget = Field(default_factory=TaskBudget)


class TaskControl(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(min_length=1, max_length=128)
    actor: str = Field(default="operator", min_length=1, max_length=128)


class InvalidTaskTransition(ValueError):
    def __init__(self, task_id: str, current: str, target: str) -> None:
        super().__init__(f"invalid task transition {task_id}: {current} -> {target}")
        self.task_id = task_id
        self.current = current
        self.target = target


class AgentTaskService:
    """Deterministic control plane; LLMs never decide task state transitions."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        payload: AgentTaskCreate,
        *,
        actor: str = "operator",
        start_immediately: bool = False,
    ) -> AgentTask:
        with self.db.session() as session:
            existing = session.scalar(
                select(AgentTask).where(AgentTask.idempotency_key == payload.idempotency_key)
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            if payload.session_id and session.get(AgentSession, payload.session_id) is None:
                raise KeyError(payload.session_id)
            if payload.parent_task_id and session.get(AgentTask, payload.parent_task_id) is None:
                raise KeyError(payload.parent_task_id)
            row = AgentTask(
                session_id=payload.session_id,
                parent_task_id=payload.parent_task_id,
                kind=payload.kind,
                objective=payload.objective.strip(),
                idempotency_key=payload.idempotency_key.strip(),
                resource_type=payload.resource_type.strip(),
                resource_id=payload.resource_id.strip(),
                budget_json=payload.budget.model_dump(mode="json"),
                usage_json={
                    "tokens": 0,
                    "model_calls": 0,
                    "tool_calls": 0,
                    "backtests": 0,
                    "duration_ms": 0,
                },
                control_json={"requests": []},
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                raced = session.scalar(
                    select(AgentTask).where(AgentTask.idempotency_key == payload.idempotency_key)
                )
                if raced is None:
                    raise
                session.expunge(raced)
                return raced
            TaskEventService.append_in_session(
                session,
                row,
                "task_created",
                actor=actor,
                payload={"kind": row.kind, "status": row.status, "session_id": row.session_id},
            )
            if start_immediately:
                self._transition_in_session(
                    session,
                    row,
                    "running",
                    actor=actor,
                    reason="inline_execution_reserved",
                )
            session.flush()
            session.expunge(row)
            return row

    def get(self, task_id: str) -> AgentTask:
        with self.db.session() as session:
            row = session.get(AgentTask, task_id)
            if row is None:
                raise KeyError(task_id)
            session.expunge(row)
            return row

    def get_by_idempotency(self, idempotency_key: str) -> AgentTask | None:
        with self.db.session() as session:
            row = session.scalar(
                select(AgentTask).where(AgentTask.idempotency_key == idempotency_key)
            )
            if row is not None:
                session.expunge(row)
            return row

    def list_tasks(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[AgentTask]:
        query = select(AgentTask)
        if session_id:
            query = query.where(AgentTask.session_id == session_id)
        if status:
            query = query.where(AgentTask.status == status)
        query = query.order_by(desc(AgentTask.created_at)).limit(max(1, min(limit, 500)))
        with self.db.session() as session:
            rows = session.scalars(query).all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        actor: str = "system",
        reason: str,
        error: dict[str, Any] | None = None,
    ) -> AgentTask:
        with self.db.session() as session:
            row = self._locked_task(session, task_id)
            self._transition_in_session(
                session,
                row,
                target,
                actor=actor,
                reason=reason,
                error=error,
            )
            session.flush()
            session.expunge(row)
            return row

    def pause(self, task_id: str, control: TaskControl) -> AgentTask:
        row = self.get(task_id)
        if self._control_was_applied(row, control.idempotency_key):
            return row
        target: TaskStatus = (
            "pause_requested" if row.status in {"running", "awaiting_approval"} else "paused"
        )
        return self._apply_control(task_id, "pause", target, control)

    def resume(self, task_id: str, control: TaskControl) -> AgentTask:
        row = self.get(task_id)
        if self._control_was_applied(row, control.idempotency_key):
            return row
        if row.status != "paused":
            raise InvalidTaskTransition(task_id, row.status, "queued")
        return self._apply_control(task_id, "resume", "queued", control)

    def cancel(self, task_id: str, control: TaskControl) -> AgentTask:
        row = self.get(task_id)
        if self._control_was_applied(row, control.idempotency_key):
            return row
        target: TaskStatus = (
            "cancel_requested"
            if row.status in {"running", "awaiting_approval", "pause_requested"}
            else "canceled"
        )
        return self._apply_control(task_id, "cancel", target, control)

    def retry(self, task_id: str, control: TaskControl) -> AgentTask:
        row = self.get(task_id)
        if self._control_was_applied(row, control.idempotency_key):
            return row
        if row.status not in {"failed", "retry_wait"}:
            raise InvalidTaskTransition(task_id, row.status, "queued")
        return self._apply_control(task_id, "retry", "queued", control)

    def branch(self, task_id: str, control: TaskControl) -> AgentTask:
        parent = self.get(task_id)
        existing = self.get_by_idempotency(control.idempotency_key)
        if existing is not None:
            return existing
        return self.create(
            AgentTaskCreate(
                session_id=parent.session_id,
                parent_task_id=parent.id,
                kind=parent.kind,
                objective=parent.objective,
                idempotency_key=control.idempotency_key,
                budget=TaskBudget.model_validate(parent.budget_json or {}),
            ),
            actor=control.actor,
        )

    def claim_next(self, worker_id: str, *, lease_seconds: int = 60) -> AgentTask | None:
        self.recover_expired_leases()
        with self.db.session() as session:
            query = (
                select(AgentTask).where(AgentTask.status == "queued").order_by(AgentTask.created_at)
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = session.scalar(query.limit(1))
            if row is None:
                return None
            self._transition_in_session(
                session,
                row,
                "running",
                actor=f"worker:{worker_id}",
                reason="task_claimed",
            )
            now = utc_now()
            row.lease_owner = worker_id
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=max(10, lease_seconds))
            session.flush()
            session.expunge(row)
            return row

    def heartbeat(self, task_id: str, worker_id: str, *, lease_seconds: int = 60) -> AgentTask:
        with self.db.session() as session:
            row = self._locked_task(session, task_id)
            if row.status != "running" or row.lease_owner != worker_id:
                raise PermissionError(f"worker {worker_id} does not own task {task_id}")
            now = utc_now()
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=max(10, lease_seconds))
            TaskEventService.append_in_session(
                session,
                row,
                "task_heartbeat",
                actor=f"worker:{worker_id}",
                payload={"lease_expires_at": row.lease_expires_at.isoformat()},
            )
            session.flush()
            session.expunge(row)
            return row

    def recover_expired_leases(self) -> list[str]:
        now = utc_now()
        recovered = []
        with self.db.session() as session:
            rows = session.scalars(
                select(AgentTask).where(
                    AgentTask.status == "running",
                    AgentTask.lease_expires_at.is_not(None),
                    AgentTask.lease_expires_at < now,
                )
            ).all()
            for row in rows:
                reason = (
                    "lease_expired_resume_checkpoint"
                    if row.last_checkpoint_id
                    else "lease_expired_checkpoint_missing"
                )
                error = None
                if not row.last_checkpoint_id:
                    error = {
                        "code": "checkpoint_missing",
                        "category": "recovery",
                        "retryable": True,
                        "reconciliation_required": True,
                    }
                self._transition_in_session(
                    session,
                    row,
                    "retry_wait",
                    actor="task_recovery",
                    reason=reason,
                    error=error,
                )
                if row.last_checkpoint_id:
                    self._transition_in_session(
                        session,
                        row,
                        "queued",
                        actor="task_recovery",
                        reason="resume_from_last_checkpoint",
                    )
                recovered.append(row.id)
        return recovered

    def link_resource(self, task_id: str, *, resource_type: str, resource_id: str) -> AgentTask:
        with self.db.session() as session:
            row = self._locked_task(session, task_id)
            row.resource_type = resource_type
            row.resource_id = resource_id
            row.version += 1
            session.flush()
            session.expunge(row)
            return row

    def update_usage(self, task_id: str, usage: dict[str, Any]) -> AgentTask:
        with self.db.session() as session:
            row = self._locked_task(session, task_id)
            row.usage_json = dict(usage)
            row.version += 1
            TaskEventService.append_in_session(
                session,
                row,
                "task_usage_updated",
                payload=row.usage_json,
            )
            session.flush()
            session.expunge(row)
            return row

    def _apply_control(
        self,
        task_id: str,
        action: str,
        target: TaskStatus,
        control: TaskControl,
    ) -> AgentTask:
        with self.db.session() as session:
            row = self._locked_task(session, task_id)
            if self._control_was_applied(row, control.idempotency_key):
                session.expunge(row)
                return row
            requests = list((row.control_json or {}).get("requests", []))
            requests.append(
                {
                    "action": action,
                    "actor": control.actor,
                    "reason": control.reason,
                    "idempotency_key": control.idempotency_key,
                    "requested_at": utc_now().isoformat(),
                }
            )
            row.control_json = {"requests": requests[-100:]}
            self._transition_in_session(
                session,
                row,
                target,
                actor=control.actor,
                reason=control.reason,
            )
            session.flush()
            session.expunge(row)
            return row

    @staticmethod
    def _control_was_applied(row: AgentTask, idempotency_key: str) -> bool:
        return any(
            request.get("idempotency_key") == idempotency_key
            for request in (row.control_json or {}).get("requests", [])
            if isinstance(request, dict)
        )

    @staticmethod
    def _locked_task(session: Session, task_id: str) -> AgentTask:
        query = select(AgentTask).where(AgentTask.id == task_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise KeyError(task_id)
        return row

    @staticmethod
    def _transition_in_session(
        session: Session,
        row: AgentTask,
        target: TaskStatus,
        *,
        actor: str,
        reason: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        current = row.status
        if target == current:
            return
        if target not in TASK_TRANSITIONS.get(current, frozenset()):
            raise InvalidTaskTransition(row.id, current, target)
        row.status = target
        row.version += 1
        if error is not None:
            row.error_json = dict(error)
        if target in TERMINAL_TASK_STATUSES or target in {"paused", "retry_wait", "queued"}:
            row.lease_owner = None
            row.lease_expires_at = None
            row.heartbeat_at = None
        TaskEventService.append_in_session(
            session,
            row,
            "task_status_changed",
            actor=actor,
            payload={"from": current, "to": target, "reason": reason, "error": error or {}},
        )


def task_to_dict(row: AgentTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "parent_task_id": row.parent_task_id,
        "kind": row.kind,
        "status": row.status,
        "objective": row.objective,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "budget": dict(row.budget_json or {}),
        "usage": dict(row.usage_json or {}),
        "control": dict(row.control_json or {}),
        "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
        "heartbeat_at": row.heartbeat_at.isoformat() if row.heartbeat_at else None,
        "last_checkpoint_id": row.last_checkpoint_id,
        "last_event_sequence": row.last_event_sequence,
        "error": dict(row.error_json or {}),
        "version": row.version,
        "legacy_run": False,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def task_budget_violations(row: AgentTask) -> list[dict[str, Any]]:
    budget = TaskBudget.model_validate(row.budget_json or {})
    usage = dict(row.usage_json or {})
    checks = (
        ("tokens", budget.max_tokens),
        ("model_calls", budget.max_model_calls),
        ("tool_calls", budget.max_tool_calls),
        ("backtests", budget.max_backtests),
        ("duration_ms", budget.max_duration_seconds * 1000),
    )
    return [
        {"metric": metric, "used": int(usage.get(metric) or 0), "limit": limit}
        for metric, limit in checks
        if int(usage.get(metric) or 0) > limit
    ]
