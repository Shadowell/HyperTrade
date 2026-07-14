from datetime import timedelta

import httpx
import pytest
from hypertrade.agent.checkpoints import TaskCheckpointService
from hypertrade.agent.sessions import AgentSessionCreate, AgentSessionService
from hypertrade.agent.task_executor import (
    AgentTaskExecutor,
    TaskControlInterrupted,
    TaskExecutionError,
)
from hypertrade.agent.tasks import (
    AgentTaskCreate,
    AgentTaskService,
    InvalidTaskTransition,
    TaskControl,
)
from hypertrade.db import AgentTask, Database, utc_now


def _task_service() -> tuple[Database, AgentTaskService, str]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    agent_session = AgentSessionService(db).create(AgentSessionCreate(title="Task tests"))
    return db, AgentTaskService(db), agent_session.id


def _control(key: str, reason: str = "operator test") -> TaskControl:
    return TaskControl(reason=reason, idempotency_key=key, actor="operator:test")


def test_task_state_machine_controls_are_idempotent_and_audited() -> None:
    _, service, session_id = _task_service()
    task = service.create(
        AgentTaskCreate(
            session_id=session_id,
            objective="bounded task",
            idempotency_key="task-state-1",
        )
    )
    assert (
        service.create(
            AgentTaskCreate(
                session_id=session_id,
                objective="ignored duplicate",
                idempotency_key="task-state-1",
            )
        ).id
        == task.id
    )

    paused = service.pause(task.id, _control("pause-1"))
    assert paused.status == "paused"
    assert (
        service.pause(task.id, _control("pause-1")).last_event_sequence
        == paused.last_event_sequence
    )
    assert service.resume(task.id, _control("resume-1")).status == "queued"

    running = service.claim_next("worker-a", lease_seconds=30)
    assert running is not None
    assert running.id == task.id
    assert running.status == "running"
    assert service.pause(task.id, _control("pause-2")).status == "pause_requested"
    assert (
        service.transition(
            task.id,
            "paused",
            actor="worker:worker-a",
            reason="safe_point",
        ).status
        == "paused"
    )
    branch = service.branch(task.id, _control("branch-1"))
    assert branch.parent_task_id == task.id
    assert branch.id != task.id

    with pytest.raises(InvalidTaskTransition):
        service.transition(task.id, "completed", actor="test", reason="invalid")


def test_expired_lease_recovers_only_from_checkpoint() -> None:
    db, service, session_id = _task_service()
    task = service.create(
        AgentTaskCreate(
            session_id=session_id,
            objective="recover me",
            idempotency_key="lease-1",
        )
    )
    claimed = service.claim_next("worker-a", lease_seconds=10)
    assert claimed is not None and claimed.id == task.id
    TaskCheckpointService(db).create(task.id, {"node": "planned"})
    with db.session() as session:
        row = session.get(AgentTask, task.id)
        assert row is not None
        row.lease_expires_at = utc_now() - timedelta(seconds=1)

    assert service.recover_expired_leases() == [task.id]
    recovered = service.get(task.id)
    assert recovered.status == "queued"
    assert recovered.last_checkpoint_id is not None
    assert recovered.lease_owner is None


def test_provider_timeout_becomes_retryable_task_error_and_checkpoint() -> None:
    db, service, session_id = _task_service()
    task = service.create(
        AgentTaskCreate(
            session_id=session_id,
            objective="timeout task",
            idempotency_key="timeout-1",
        )
    )

    class TimeoutKernel:
        def run_chat_with_events(self, prompt, *, event_sink=None):
            if event_sink:
                event_sink({"event": "run_started", "run_id": "run_timeout"})
            raise httpx.ReadTimeout("provider exceeded deadline")

    with pytest.raises(TaskExecutionError) as captured:
        AgentTaskExecutor(db).execute_chat(task.id, TimeoutKernel(), task.objective)  # type: ignore[arg-type]

    assert captured.value.error["code"] == "provider_timeout"
    assert captured.value.error["retryable"] is True
    stored = service.get(task.id)
    assert stored.status == "retry_wait"
    assert stored.error_json["source"] == "ReadTimeout"
    assert TaskCheckpointService(db).latest(task.id) is not None


def test_running_task_honors_pause_at_agent_event_safe_point() -> None:
    db, service, session_id = _task_service()
    task = service.create(
        AgentTaskCreate(
            session_id=session_id,
            objective="pause at safe point",
            idempotency_key="pause-running-1",
        )
    )

    class ControlledKernel:
        def run_chat_with_events(self, prompt, *, event_sink=None):
            assert event_sink is not None
            event_sink({"event": "run_started", "run_id": "run_pause"})
            raise AssertionError("pause safe point should interrupt before continuing")

    def request_pause(event) -> None:
        if event.get("event") == "run_started":
            service.pause(task.id, _control("pause-during-run"))

    with pytest.raises(TaskControlInterrupted, match="control requested: pause_requested"):
        AgentTaskExecutor(db).execute_chat(  # type: ignore[arg-type]
            task.id,
            ControlledKernel(),
            task.objective,
            external_event_sink=request_pause,
        )

    stored = service.get(task.id)
    assert stored.status == "paused"
    assert stored.last_checkpoint_id is not None
