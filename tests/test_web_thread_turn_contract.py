from __future__ import annotations

import threading
import time
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import AgentRun, AgentTask, Database
from hypertrade.main import create_app
from hypertrade.providers.chat import ChatResponse
from sqlalchemy import func, select


class _HeldChatProvider:
    """A planner call the test releases, instead of one the network happens to finish.

    The contract under test needs the turn to still be running at the first archive and
    terminal at the second. Driving that with a real provider made the test a race in
    both directions: with credentials present the call outran the wait budget, and
    without them it completed before the archive could observe an active turn.
    """

    name = "held"
    model = "held-1"

    def __init__(self) -> None:
        self.released = threading.Event()

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        self.released.wait(timeout=30)
        return ChatResponse(content="held response")


def test_web_thread_contract_archives_without_legacy_writes(monkeypatch) -> None:
    provider = _HeldChatProvider()
    monkeypatch.setattr(
        "hypertrade.agent.kernel.ProviderRuntime.get_chat_provider",
        lambda self, **kwargs: provider,
    )

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
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "secret"},
            ).status_code
            == 200
        )
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

        provider.released.set()
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
    """Poll to a wall-clock deadline, not a fixed iteration count.

    An iteration count silently shortens as each request gets slower, which is exactly
    when the extra time is needed.
    """
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        payload = client.get(f"/api/agent/v1/threads/{thread_id}/turns/{turn_id}").json()
        if payload["turn"]["status"] in {"completed", "failed", "cancelled", "expired"}:
            return
        time.sleep(0.01)
    raise AssertionError("canonical Web Turn did not reach a terminal state")
