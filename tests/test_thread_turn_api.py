from __future__ import annotations

import time

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import AgentRun, AgentTask, Database
from hypertrade.main import create_app
from sqlalchemy import func, select


def test_thread_turn_api_is_idempotent_replayable_and_avoids_legacy_writes() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="thread-turn-api-secret",
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_CANARY_PERCENT=100,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "secret"},
        )
        assert login.status_code == 200
        created = client.post(
            "/api/agent/v1/threads",
            json={"title": "Canonical CLI", "retention": "durable"},
        )
        assert created.status_code == 200
        thread_id = created.json()["thread"]["thread_id"]

        first = client.post(
            f"/api/agent/v1/threads/{thread_id}/turns",
            json={"input": "主网满仓买入 ETH", "client_message_id": "message-1"},
        )
        replay = client.post(
            f"/api/agent/v1/threads/{thread_id}/turns",
            json={"input": "主网满仓买入 ETH", "client_message_id": "message-1"},
        )
        conflict = client.post(
            f"/api/agent/v1/threads/{thread_id}/turns",
            json={"input": "改成 BTC", "client_message_id": "message-1"},
        )
        assert first.status_code == 202
        assert replay.status_code == 202
        assert replay.json()["created"] is False
        assert replay.json()["turn"]["turn_id"] == first.json()["turn"]["turn_id"]
        assert conflict.status_code == 409

        turn_id = first.json()["turn"]["turn_id"]
        terminal = _wait_for_terminal(client, thread_id, turn_id)
        assert terminal["turn"]["status"] == "failed"
        assert terminal["turn"]["mission_id"].startswith("mis_")
        assert any(item["item_type"] == "agent_message" for item in terminal["items"])

        events = client.get(f"/api/agent/v1/threads/{thread_id}/events").json()
        assert events["next_cursor"] >= 5
        midpoint = events["events"][len(events["events"]) // 2]["thread_sequence"]
        resumed = client.get(
            f"/api/agent/v1/threads/{thread_id}/events/stream?after={midpoint}",
            headers={"Last-Event-ID": str(midpoint)},
        )
        assert resumed.status_code == 200
        replay_ids = [
            int(line.removeprefix("id: "))
            for line in resumed.text.splitlines()
            if line.startswith("id: ")
        ]
        assert replay_ids and min(replay_ids) > midpoint
        assert resumed.text.count("event: turn.failed") == 1

        interrupted = client.post(f"/api/agent/v1/threads/{thread_id}/turns/{turn_id}/interrupt")
        assert interrupted.status_code == 200
        assert interrupted.json()["turn"]["status"] == "failed"

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AgentRun)) == 0
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0


def _wait_for_terminal(
    client: TestClient,
    thread_id: str,
    turn_id: str,
) -> dict[str, object]:
    for _ in range(200):
        response = client.get(f"/api/agent/v1/threads/{thread_id}/turns/{turn_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["turn"]["status"] in {"completed", "failed", "cancelled", "expired"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("canonical Turn did not reach a terminal state")
