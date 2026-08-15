"""Show why the canonical Web turn stops reaching a terminal state."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app

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
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    thread_id = client.post(
        "/api/agent/v1/threads",
        json={"title": "repro", "retention": "durable"},
    ).json()["thread"]["thread_id"]
    turn_id = client.post(
        f"/api/agent/v1/threads/{thread_id}/turns",
        json={"input": "看下 LAB 的价格", "client_message_id": "web-message-1"},
    ).json()["turn"]["turn_id"]

    archive = client.post(f"/api/agent/v1/threads/{thread_id}/archive")
    print(f"archive while active -> {archive.status_code}")

    for _ in range(200):
        payload = client.get(f"/api/agent/v1/threads/{thread_id}/turns/{turn_id}").json()
        if payload["turn"]["status"] in {"completed", "failed", "cancelled", "expired"}:
            break
        time.sleep(0.01)

    print(json.dumps(payload["turn"], indent=2, ensure_ascii=False)[:800])

    if payload["turn"]["status"] == "running":
        import faulthandler
        import sys

        print("\n=== stuck; all thread stacks ===")
        faulthandler.dump_traceback(file=sys.stdout)
