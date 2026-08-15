"""Can an unauthenticated caller reach the ARC live-promote endpoints?"""

from __future__ import annotations

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
    SESSION_SECRET="probe-secret",
)

with TestClient(create_app(settings=settings, db=database)) as client:
    # No login at all.
    created = client.post(
        "/api/v1/arc/missions",
        json={"objective": "probe", "symbol": "BTC-USDT-SWAP", "max_candidates": 1},
    )
    print(f"POST /arc/missions (no auth)            -> {created.status_code}")

    mission_id = created.json().get("mission_id") if created.status_code < 400 else "mis_x"

    for method, path, body in (
        ("GET", f"/api/v1/arc/missions/{mission_id}", None),
        ("GET", f"/api/v1/arc/missions/{mission_id}/live-approval", None),
        (
            "POST",
            f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
            {"decision": "approve", "reason": "probe", "force": True},
        ),
    ):
        response = (
            client.get(path)
            if method == "GET"
            else client.post(
                path,
                json=body,
                headers={"X-Operator-Id": "anyone", "Idempotency-Key": "k1"},
            )
        )
        print(f"{method:4s} {path.split('/', 4)[-1]:52s} -> {response.status_code}")
        if response.status_code < 400:
            print(f"      body: {str(response.json())[:200]}")

    # For comparison, an endpoint that is behind auth.
    print(f"\nGET  /api/agent/v1/threads (no auth)     -> {client.get('/api/agent/v1/threads').status_code}")
