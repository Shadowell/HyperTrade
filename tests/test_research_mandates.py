from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.research.schemas import ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from pydantic import ValidationError


def _mandate_payload() -> dict[str, object]:
    return {
        "name": "BTC regime research",
        "symbols": ["btc", "ETH"],
        "timeframes": ["1h", "4h"],
        "strategy_categories": ["trend", "mean_reversion"],
    }


def test_mandate_is_versioned_and_only_allows_manual_paper_disabled_live() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = ResearchProgramService(db)

    mandate = service.create_mandate(ResearchMandateCreate.model_validate(_mandate_payload()))

    assert mandate["status"] == "active"
    assert mandate["symbols"] == ["BTC", "ETH"]
    assert mandate["paper_promotion_mode"] == "manual_approval"
    assert mandate["live_mode"] == "disabled"
    assert mandate["audit"][0]["trace_ref"] == "research.mandate.validate"

    paused = service.pause_mandate(str(mandate["id"]))
    assert paused["status"] == "paused"
    assert paused["version"] == 2
    with pytest.raises(ValueError, match="not active"):
        service.draft_strategy_spec(str(mandate["id"]), "test a trend hypothesis")
    assert service.resume_mandate(str(mandate["id"]))["status"] == "active"

    with pytest.raises(ValidationError):
        ResearchMandateCreate.model_validate({**_mandate_payload(), "live_mode": "enabled"})


def test_research_mandate_api_requires_admin_and_returns_draft_only() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="research-test-session",
        ),
        db=db,
    )
    client = TestClient(app)

    assert client.post("/api/research/mandates", json=_mandate_payload()).status_code == 401
    login = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert login.status_code == 200

    created = client.post("/api/research/mandates", json=_mandate_payload())
    assert created.status_code == 200
    mandate_id = created.json()["id"]
    draft = client.post(
        f"/api/research/mandates/{mandate_id}/strategy-specs/draft",
        json={"prompt": "test a stable trend following hypothesis"},
    )

    assert draft.status_code == 200
    body = draft.json()
    assert body["status"] == "draft"
    assert body["strategy_spec"]["mandate_id"] == mandate_id
    assert body["boundaries"] == [
        "schema_valid_draft_only",
        "no_bitpro_write",
        "no_paper_or_live_action",
    ]
