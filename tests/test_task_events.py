import json

from fastapi.testclient import TestClient
from hypertrade.agent.checkpoints import TaskCheckpointService
from hypertrade.agent.sessions import AgentSessionCreate, AgentSessionService
from hypertrade.agent.task_events import TaskEventService, task_event_to_dict
from hypertrade.agent.tasks import AgentTaskCreate, AgentTaskService
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app


def test_task_events_are_cursor_addressable_and_redacted() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    agent_session = AgentSessionService(db).create(AgentSessionCreate(title="events"))
    task = AgentTaskService(db).create(
        AgentTaskCreate(
            session_id=agent_session.id,
            objective="event task",
            idempotency_key="event-task-1",
        )
    )
    service = TaskEventService(db)
    event = service.append(
        task.id,
        "provider_call",
        payload={"model": "test", "authorization": "Bearer secret", "nested": {"token": "x"}},
    )
    payload = task_event_to_dict(event)
    assert payload["payload"]["authorization"] == "[REDACTED]"
    assert payload["payload"]["nested"]["token"] == "[REDACTED]"
    assert [row.sequence for row in service.list(task.id, after=1)] == [2]

    first = TaskCheckpointService(db).create(task.id, {"b": 2, "a": 1})
    second = TaskCheckpointService(db).create(task.id, {"a": 1, "b": 2})
    assert first.state_hash == second.state_hash
    assert first.resume_token != second.resume_token


def test_task_api_control_and_sse_cursor() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            DEEPSEEK_API_KEY="",
        ),
        db=db,
    )
    client = TestClient(app)
    assert (
        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret"},
        ).status_code
        == 200
    )
    agent_session = client.post(
        "/api/agent/sessions",
        json={"title": "API session", "surface": "api"},
    ).json()
    task = client.post(
        f"/api/agent/sessions/{agent_session['id']}/tasks",
        json={"objective": "API task", "idempotency_key": "api-task-1"},
    ).json()
    paused = client.post(
        f"/api/agent/tasks/{task['id']}/pause",
        json={"reason": "operator review", "idempotency_key": "api-pause-1"},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    events = client.get(f"/api/agent/tasks/{task['id']}/events?after=1").json()["events"]
    assert events[0]["sequence"] == 2
    stream = client.get(
        f"/api/agent/tasks/{task['id']}/stream",
        headers={"Last-Event-ID": "1"},
    )
    assert stream.status_code == 200
    data_lines = [line[6:] for line in stream.text.splitlines() if line.startswith("data: ")]
    decoded = [json.loads(line) for line in data_lines]
    assert decoded[0]["sequence"] == 2
