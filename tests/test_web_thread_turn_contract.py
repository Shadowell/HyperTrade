from __future__ import annotations

import time

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import AgentRun, AgentTask, Database
from hypertrade.main import create_app
from sqlalchemy import func, select


def test_web_thread_contract_archives_without_legacy_writes() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="web-thread-contract-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_CANARY_PERCENT=100,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret"},
        ).status_code == 200
        created = client.post(
            "/api/agent/v1/threads",
            json={"title": "Web canonical workspace", "retention": "durable"},
        )
        assert created.status_code == 200
        thread_id = created.json()["thread"]["thread_id"]

        started = client.post(
            f"/api/agent/v1/threads/{thread_id}/turns",
            json={"input": "看下 LAB 的价格", "client_message_id": "web-message-1"},
        )
        assert started.status_code == 202
        turn_id = started.json()["turn"]["turn_id"]

        active_archive = client.post(f"/api/agent/v1/threads/{thread_id}/archive")
        assert active_archive.status_code == 409
        _wait_for_terminal(client, thread_id, turn_id)

        archived = client.post(f"/api/agent/v1/threads/{thread_id}/archive")
        archived_again = client.post(f"/api/agent/v1/threads/{thread_id}/archive")
        assert archived.status_code == 200
        assert archived.json()["thread"]["status"] == "archived"
        assert archived_again.status_code == 200
        assert archived_again.json()["thread"]["version"] == archived.json()["thread"]["version"]
        rejected = client.post(
            f"/api/agent/v1/threads/{thread_id}/turns",
            json={"input": "继续", "client_message_id": "web-message-2"},
        )
        assert rejected.status_code == 409

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AgentRun)) == 0
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0


def _wait_for_terminal(client: TestClient, thread_id: str, turn_id: str) -> None:
    for _ in range(200):
        payload = client.get(
            f"/api/agent/v1/threads/{thread_id}/turns/{turn_id}"
        ).json()
        if payload["turn"]["status"] in {"completed", "failed", "cancelled", "expired"}:
            return
        time.sleep(0.01)
    raise AssertionError("canonical Web Turn did not reach a terminal state")
