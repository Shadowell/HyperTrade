"""ARC reaches BitPro live promote, so its routes must not answer anonymous callers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app


@pytest.fixture
def client() -> TestClient:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="arc-auth-test-secret",
    )
    with TestClient(create_app(settings=settings, db=database)) as test_client:
        yield test_client


def _login(client: TestClient) -> None:
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "secret"}
        ).status_code
        == 200
    )


def test_anonymous_callers_cannot_reach_any_arc_route(client: TestClient) -> None:
    """The router was mounted bare while every sibling router sat behind require_admin."""
    mission = "arc_anything"
    unauthenticated = [
        client.post(
            "/api/v1/arc/missions",
            json={"objective": "probe", "symbol": "BTC-USDT-SWAP", "max_candidates": 1},
        ),
        client.get("/api/v1/arc/missions"),
        client.get("/api/v1/arc/evidence/preflight"),
        client.get(f"/api/v1/arc/missions/{mission}"),
        client.get(f"/api/v1/arc/missions/{mission}/evidence"),
        client.get(f"/api/v1/arc/missions/{mission}/candidates/att_x"),
        client.get(f"/api/v1/arc/missions/{mission}/live-approval"),
        client.post(
            f"/api/v1/arc/missions/{mission}/live-approval/decide",
            json={"decision": "approve", "reason": "probe", "force": True},
            headers={"X-Operator-Id": "anyone", "Idempotency-Key": "k1"},
        ),
        client.post(
            f"/api/v1/arc/missions/{mission}/live-approval/revoke",
            json={"reason": "probe"},
            headers={"X-Operator-Id": "anyone", "Idempotency-Key": "k2"},
        ),
    ]

    for response in unauthenticated:
        assert response.status_code == 401, (response.request.url, response.status_code)


def test_an_authenticated_operator_still_gets_through(client: TestClient) -> None:
    _login(client)

    created = client.post(
        "/api/v1/arc/missions",
        json={"objective": "probe", "symbol": "BTC-USDT-SWAP", "max_candidates": 1},
    )
    assert created.status_code == 200
    mission_id = created.json()["mission_id"]
    assert client.get(f"/api/v1/arc/missions/{mission_id}").status_code == 200


def test_the_recorded_operator_is_the_session_not_the_header(client: TestClient) -> None:
    """A live decision is an audit record; a caller-supplied name would be forgeable."""
    _login(client)

    mission_id = client.post(
        "/api/v1/arc/missions",
        json={"objective": "probe", "symbol": "BTC-USDT-SWAP", "max_candidates": 1},
    ).json()["mission_id"]

    # Incomplete package, so the decision is refused - but the attempt is still recorded.
    client.post(
        f"/api/v1/arc/missions/{mission_id}/live-approval/decide",
        json={"decision": "reject", "reason": "probe"},
        headers={"X-Operator-Id": "someone-else", "Idempotency-Key": "k1"},
    )

    events = client.get(f"/api/v1/arc/missions/{mission_id}").json()
    decided = [
        event
        for event in events.get("events", [])
        if event.get("event_type") == "live_decided"
    ]
    assert decided, events.get("events")
    assert decided[-1]["payload"]["operator_id"] == "admin"
    assert decided[-1]["payload"]["identity_source"] == "hypertrade_session"
