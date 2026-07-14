"""Bridge durable Agent tasks to legacy one-shot AgentKernel executions."""

from __future__ import annotations

from typing import Any

import httpx

from hypertrade.agent.checkpoints import TaskCheckpointService
from hypertrade.agent.kernel import AgentKernel, CompletedAgentRun
from hypertrade.agent.task_events import TaskEventService
from hypertrade.agent.tasks import AgentTaskService, TaskStatus, task_budget_violations
from hypertrade.db import AgentRun, Database


class TaskControlInterrupted(RuntimeError):
    def __init__(self, task_id: str, status: str) -> None:
        super().__init__(f"task {task_id} control requested: {status}")
        self.task_id = task_id
        self.status = status


class TaskExecutionError(RuntimeError):
    def __init__(self, task_id: str, error: dict[str, Any]) -> None:
        super().__init__(str(error.get("message") or error.get("code") or "task execution failed"))
        self.task_id = task_id
        self.error = error


class AgentTaskExecutor:
    """Run one AgentKernel attempt while Task remains the canonical state."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.tasks = AgentTaskService(db)
        self.events = TaskEventService(db)
        self.checkpoints = TaskCheckpointService(db)

    def execute_chat(
        self,
        task_id: str,
        kernel: AgentKernel,
        prompt: str,
        *,
        external_event_sink: Any | None = None,
    ) -> CompletedAgentRun:
        task = self.tasks.get(task_id)
        if task.status == "completed" and task.resource_type == "agent_run" and task.resource_id:
            return kernel.get_run(task.resource_id)
        if task.status == "queued":
            self.tasks.transition(
                task_id,
                "running",
                actor="task_executor",
                reason="agent_attempt_started",
            )
        elif task.status != "running":
            raise TaskExecutionError(
                task_id,
                {
                    "code": "task_not_runnable",
                    "category": "task_state",
                    "retryable": False,
                    "message": f"task status is {task.status}",
                },
            )

        run_id = ""

        def event_sink(event: dict[str, Any]) -> None:
            nonlocal run_id
            if event.get("event") == "run_started" and event.get("run_id"):
                run_id = str(event["run_id"])
                self.tasks.link_resource(task_id, resource_type="agent_run", resource_id=run_id)
            self.events.append(
                task_id,
                str(event.get("event") or "agent_event"),
                actor="agent_kernel",
                payload=event,
            )
            if external_event_sink is not None:
                external_event_sink({**event, "task_id": task_id})
            current = self.tasks.get(task_id)
            if current.status in {"pause_requested", "cancel_requested"}:
                raise TaskControlInterrupted(task_id, current.status)

        try:
            run = kernel.run_chat_with_events(prompt, event_sink=event_sink)
        except TaskControlInterrupted as exc:
            target: TaskStatus = "paused" if exc.status == "pause_requested" else "canceled"
            self.checkpoints.create(
                task_id,
                {"run_id": run_id, "control_status": exc.status},
                reconciliation_required=False,
            )
            self.tasks.transition(
                task_id,
                target,
                actor="task_executor",
                reason=f"safe_point_{target}",
            )
            raise
        except httpx.TimeoutException as exc:
            error = _execution_error(
                "provider_timeout",
                category="provider",
                retryable=True,
                exc=exc,
            )
            self.checkpoints.create(
                task_id,
                {"run_id": run_id, "error": error},
                reconciliation_required=False,
            )
            self.tasks.transition(
                task_id,
                "retry_wait",
                actor="task_executor",
                reason="provider_timeout",
                error=error,
            )
            raise TaskExecutionError(task_id, error) from exc
        except Exception as exc:
            error = _execution_error(
                "agent_execution_failed",
                category="runtime",
                retryable=False,
                exc=exc,
            )
            self.checkpoints.create(
                task_id,
                {"run_id": run_id, "error": error},
                reconciliation_required=_external_completion_unknown(exc),
            )
            self.tasks.transition(
                task_id,
                "failed",
                actor="task_executor",
                reason="agent_execution_failed",
                error=error,
            )
            raise TaskExecutionError(task_id, error) from exc

        self._link_run(task_id, run)
        self.checkpoints.create(
            task_id,
            {"run_id": run.id, "run_status": run.status, "completed": True},
        )
        updated = self.tasks.update_usage(task_id, _usage_from_run(run))
        violations = task_budget_violations(updated)
        if violations:
            error = {
                "code": "task_budget_exceeded",
                "category": "budget",
                "retryable": False,
                "message": "task usage exceeded its approved budget",
                "violations": violations,
                "reconciliation_required": False,
            }
            self.tasks.transition(
                task_id,
                "failed",
                actor="task_executor",
                reason="task_budget_exceeded",
                error=error,
            )
            raise TaskExecutionError(task_id, error)
        self.tasks.transition(
            task_id,
            "completed",
            actor="task_executor",
            reason="agent_attempt_completed",
        )
        return kernel.get_run(run.id)

    def _link_run(self, task_id: str, run: CompletedAgentRun) -> None:
        task = self.tasks.get(task_id)
        with self.db.session() as session:
            row = session.get(AgentRun, run.id)
            if row is None:
                raise KeyError(run.id)
            report = dict(row.report_json or {})
            report["task"] = {
                "task_id": task.id,
                "session_id": task.session_id,
                "legacy_adapter": True,
            }
            row.report_json = report
        self.tasks.link_resource(task_id, resource_type="agent_run", resource_id=run.id)


def _execution_error(
    code: str,
    *,
    category: str,
    retryable: bool,
    exc: Exception,
) -> dict[str, Any]:
    message = " ".join(str(exc).split())[:500] or exc.__class__.__name__
    return {
        "code": code,
        "category": category,
        "retryable": retryable,
        "source": exc.__class__.__name__,
        "message": message,
        "reconciliation_required": False,
    }


def _external_completion_unknown(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("bitpro", "external write", "upstream"))


def _usage_from_run(run: CompletedAgentRun) -> dict[str, Any]:
    observability = run.report_json.get("observability", {})
    if not isinstance(observability, dict):
        observability = {}
    totals = observability.get("usage", {})
    if not isinstance(totals, dict):
        totals = {}
    tool_calls = run.report_json.get("tool_calls", [])
    return {
        "tokens": int(totals.get("total_tokens") or observability.get("total_tokens") or 0),
        "model_calls": int(observability.get("model_call_count") or 0),
        "tool_calls": len(tool_calls) if isinstance(tool_calls, list) else 0,
        "backtests": 0,
        "duration_ms": int(float(observability.get("duration_ms") or 0)),
    }
