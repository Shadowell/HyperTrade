from __future__ import annotations

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.main import create_app
from paper_incubation_fixtures import mandate_request, seeded_paper_incubation


def test_operator_can_inspect_and_drive_mandate_bound_paper_incubation(tmp_path) -> None:
    db, refs, validation, adapter, _ = seeded_paper_incubation()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
        bitpro_adapter=adapter,
    )
    request = mandate_request(
        refs,
        validation,
        updates={"approved_by": "admin"},
    )

    with TestClient(app) as client:
        assert client.get("/api/research/paper-incubation/mandates").status_code == 401
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "secret"},
            ).status_code
            == 200
        )
        created = client.post(
            "/api/research/paper-incubation/mandates",
            json=request.model_dump(mode="json"),
        )
        assert created.status_code == 200
        mandate = created.json()
        member_id = mandate["members"][0]["id"]

        configured = client.post(
            "/api/research/paper-incubation/actions",
            json={
                "member_id": member_id,
                "action": "configure",
                "reason": "Enter bounded Paper from validated intake",
                "idempotency_key": "paper-api-configure-001",
            },
        )
        listed = client.get("/api/research/paper-incubation/mandates")
        member = client.get(f"/api/research/paper-incubation/members/{member_id}")
        captured = client.post(
            "/api/research/paper-incubation/windows/capture",
            json={
                "mandate_id": mandate["id"],
                "idempotency_key": "paper-api-window-capture-001",
            },
        )

    assert configured.status_code == 200
    assert configured.json()["status"] == "succeeded"
    assert listed.json()["items"][0]["id"] == mandate["id"]
    assert member.json()["status"] == "configured"
    assert captured.status_code == 200
    assert len(captured.json()["windows"]) == 3
    assert adapter.calls.count("configure") == 1
