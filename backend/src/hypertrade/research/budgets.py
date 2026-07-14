"""Atomic pre-dispatch budget reservations for parallel research roles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from hypertrade.agent.task_events import TaskEventService
from hypertrade.db import AgentTask, Database, new_id, utc_now
from hypertrade.research.roles.definitions import RoleBudget


class TaskBudgetExceeded(RuntimeError):
    def __init__(self, task_id: str, dimension: str) -> None:
        super().__init__(f"task {task_id} budget exhausted: {dimension}")
        self.task_id = task_id
        self.dimension = dimension


@dataclass(frozen=True)
class BudgetReservation:
    id: str
    task_id: str
    role_key: str
    model_calls: int
    tool_calls: int
    tokens: int


class TaskBudgetGuard:
    """Reserve before model/tool dispatch so parallel branches cannot oversubscribe."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def reserve(
        self,
        task_id: str,
        role_key: str,
        *,
        role_budget: RoleBudget,
        model_calls: int = 0,
        tool_calls: int = 0,
        tokens: int = 0,
    ) -> BudgetReservation:
        if model_calls > role_budget.max_model_calls:
            raise TaskBudgetExceeded(task_id, f"role:{role_key}:model_calls")
        if tool_calls > role_budget.max_tool_calls:
            raise TaskBudgetExceeded(task_id, f"role:{role_key}:tool_calls")
        if tokens > role_budget.max_tokens:
            raise TaskBudgetExceeded(task_id, f"role:{role_key}:tokens")
        with self.db.session() as session:
            query = select(AgentTask).where(AgentTask.id == task_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            task = session.scalar(query)
            if task is None:
                raise KeyError(task_id)
            budget = dict(task.budget_json)
            usage = dict(task.usage_json)
            control = dict(task.control_json)
            reservations = [
                dict(item)
                for item in control.get("budget_reservations", [])
                if isinstance(item, dict)
            ]
            reserved = {
                "model_calls": sum(int(item.get("model_calls", 0)) for item in reservations),
                "tool_calls": sum(int(item.get("tool_calls", 0)) for item in reservations),
                "tokens": sum(int(item.get("tokens", 0)) for item in reservations),
            }
            requested = {
                "model_calls": max(0, model_calls),
                "tool_calls": max(0, tool_calls),
                "tokens": max(0, tokens),
            }
            limits = {
                "model_calls": int(budget.get("max_model_calls", 0)),
                "tool_calls": int(budget.get("max_tool_calls", 0)),
                "tokens": int(budget.get("max_tokens", 0)),
            }
            for dimension in ("model_calls", "tool_calls", "tokens"):
                projected = (
                    int(usage.get(dimension, 0))
                    + reserved[dimension]
                    + requested[dimension]
                )
                if projected > limits[dimension]:
                    raise TaskBudgetExceeded(task_id, dimension)
            elapsed = (utc_now() - _aware(task.created_at)).total_seconds()
            if elapsed > int(budget.get("max_duration_seconds", 0)):
                raise TaskBudgetExceeded(task_id, "duration")
            reservation = BudgetReservation(
                id=new_id("bres"),
                task_id=task_id,
                role_key=role_key,
                model_calls=requested["model_calls"],
                tool_calls=requested["tool_calls"],
                tokens=requested["tokens"],
            )
            reservations.append(
                {
                    "id": reservation.id,
                    "role_key": role_key,
                    **requested,
                }
            )
            task.control_json = {**control, "budget_reservations": reservations}
            TaskEventService.append_in_session(
                session,
                task,
                "task_budget_reserved",
                actor=f"role:{role_key}",
                payload={"reservation_id": reservation.id, **requested},
            )
            return reservation

    def settle(
        self,
        reservation: BudgetReservation,
        *,
        actual_model_calls: int,
        actual_tool_calls: int,
        actual_tokens: int,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            query = select(AgentTask).where(AgentTask.id == reservation.task_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            task = session.scalar(query)
            if task is None:
                raise KeyError(reservation.task_id)
            control = dict(task.control_json)
            reservations = [
                dict(item)
                for item in control.get("budget_reservations", [])
                if isinstance(item, dict) and item.get("id") != reservation.id
            ]
            usage = dict(task.usage_json)
            usage["model_calls"] = int(usage.get("model_calls", 0)) + max(
                0, actual_model_calls
            )
            usage["tool_calls"] = int(usage.get("tool_calls", 0)) + max(0, actual_tool_calls)
            usage["tokens"] = int(usage.get("tokens", 0)) + max(0, actual_tokens)
            task.usage_json = usage
            task.control_json = {**control, "budget_reservations": reservations}
            TaskEventService.append_in_session(
                session,
                task,
                "task_budget_settled",
                actor=f"role:{reservation.role_key}",
                payload={
                    "reservation_id": reservation.id,
                    "model_calls": max(0, actual_model_calls),
                    "tool_calls": max(0, actual_tool_calls),
                    "tokens": max(0, actual_tokens),
                },
            )
            return dict(usage)

    def release(self, reservation: BudgetReservation, *, reason: str) -> None:
        with self.db.session() as session:
            query = select(AgentTask).where(AgentTask.id == reservation.task_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            task = session.scalar(query)
            if task is None:
                raise KeyError(reservation.task_id)
            control = dict(task.control_json)
            reservations = [
                dict(item)
                for item in control.get("budget_reservations", [])
                if isinstance(item, dict) and item.get("id") != reservation.id
            ]
            task.control_json = {**control, "budget_reservations": reservations}
            TaskEventService.append_in_session(
                session,
                task,
                "task_budget_released",
                actor=f"role:{reservation.role_key}",
                payload={"reservation_id": reservation.id, "reason": reason},
            )


def _aware(value: Any) -> Any:
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=utc_now().tzinfo)
    return value
