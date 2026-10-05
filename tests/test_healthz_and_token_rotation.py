from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.security.token_manager import (
    TokenRecord,
    TokenRotationService,
    TokenStatus,
)


def test_token_rotation_service_lifecycle(tmp_path: Path) -> None:
    storage = tmp_path / "tokens.json"
    svc = TokenRotationService(storage_path=storage)

    # 1. Issue token
    rec1, plaintext1 = svc.issue_token(
        label="test-crawler",
        scopes=["arc:read", "arc:start"],
        ttl_days=30,
    )
    assert rec1.token_label == "test-crawler"
    assert rec1.scopes == ["arc:read", "arc:start"]
    assert rec1.token_prefix.startswith("ht_sec_")
    assert plaintext1.startswith("ht_sec_")
    assert len(rec1.token_hash) == 64
    assert rec1.usage_count == 0

    # 2. Verify token
    verified1 = svc.verify_token(plaintext1)
    assert verified1 is not None
    assert verified1.token_id == rec1.token_id
    assert verified1.usage_count == 1
    assert verified1.last_used_at is not None

    # Invalid token check
    assert svc.verify_token("invalid_token_value") is None

    # 3. Rotate token with grace period
    old_rec, new_rec, plaintext2 = svc.rotate_token(
        rec1.token_id,
        grace_period_hours=12.0,
        ttl_days=30,
    )
    assert old_rec.grace_until is not None
    assert new_rec.token_id != old_rec.token_id
    assert new_rec.token_label == "test-crawler"

    # Both old and new token should be valid during grace period
    assert svc.verify_token(plaintext1) is not None
    assert svc.verify_token(plaintext2) is not None

    # 4. Revocation
    revoked = svc.revoke_token(rec1.token_id, reason="compromised")
    assert revoked.revoked_at is not None
    assert revoked.compute_status() == TokenStatus.REVOKED
    # Old token is now revoked and rejected
    assert svc.verify_token(plaintext1) is None
    # New token is still active
    assert svc.verify_token(plaintext2) is not None

    # 5. Reload from persistence
    svc_reloaded = TokenRotationService(storage_path=storage)
    assert svc_reloaded.verify_token(plaintext2) is not None
    tokens_list = svc_reloaded.list_tokens()
    assert len(tokens_list) == 2


def test_token_status_expiration() -> None:
    now = datetime.now(UTC)
    # Expiring soon (within 7 days)
    rec_soon = TokenRecord(
        token_id="tok_soon",
        token_label="soon",
        token_hash="hash1",
        token_prefix="ht_sec_abc",
        scopes=["arc:read"],
        created_at=now.isoformat(),
        expires_at=(now + timedelta(days=3)).isoformat(),
    )
    assert rec_soon.compute_status(now) == TokenStatus.EXPIRING_SOON

    # Expired
    rec_exp = TokenRecord(
        token_id="tok_exp",
        token_label="exp",
        token_hash="hash2",
        token_prefix="ht_sec_abc",
        scopes=["arc:read"],
        created_at=(now - timedelta(days=40)).isoformat(),
        expires_at=(now - timedelta(days=5)).isoformat(),
    )
    assert rec_exp.compute_status(now) == TokenStatus.EXPIRED

    # Grace period expired
    rec_grace_exp = TokenRecord(
        token_id="tok_grace",
        token_label="grace",
        token_hash="hash3",
        token_prefix="ht_sec_abc",
        scopes=["arc:read"],
        created_at=(now - timedelta(days=10)).isoformat(),
        expires_at=None,
        grace_until=(now - timedelta(hours=1)).isoformat(),
    )
    assert rec_grace_exp.compute_status(now) == TokenStatus.EXPIRED


def test_healthz_readyz_livez_endpoints() -> None:
    settings = Settings(
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="test-secret-123",
    )
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(settings=settings, db=db)
    client = TestClient(app)

    # 1. Livez probe
    res_live = client.get("/livez")
    assert res_live.status_code == 200
    live_data = res_live.json()
    assert live_data["status"] == "alive"

    res_live_api = client.get("/api/livez")
    assert res_live_api.status_code == 200

    # 2. Readyz probe
    res_ready = client.get("/readyz")
    assert res_ready.status_code == 200
    ready_data = res_ready.json()
    assert ready_data["status"] == "ready"
    assert ready_data["database"] == "connected"

    res_ready_api = client.get("/api/readyz")
    assert res_ready_api.status_code == 200

    # 3. Healthz diagnostic
    res_health = client.get("/healthz")
    assert res_health.status_code == 200
    health_data = res_health.json()
    assert health_data["status"] in ("healthy", "degraded")
    assert "uptime_seconds" in health_data
    assert health_data["database"]["status"] == "connected"
    assert "quantlab" in health_data["adapters"]
    assert "bitpro" in health_data["adapters"]
    assert "security" in health_data

    res_health_api = client.get("/api/healthz")
    assert res_health_api.status_code == 200


def test_security_tokens_api_and_arc_integration() -> None:
    settings = Settings(
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="test-secret-123",
    )
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(settings=settings, db=db)
    client = TestClient(app)

    # Login admin
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert login_res.status_code == 200

    # 1. Issue token via API
    issue_res = client.post(
        "/api/security/tokens/issue",
        json={
            "label": "quantlab-mcp-sync",
            "scopes": ["arc:read", "arc:start"],
            "ttl_days": 30,
        },
    )
    assert issue_res.status_code == 200
    issue_data = issue_res.json()
    token_id = issue_data["record"]["token_id"]
    plaintext_token = issue_data["token"]
    assert plaintext_token.startswith("ht_sec_")
    assert issue_data["record"]["token_label"] == "quantlab-mcp-sync"

    # 2. List tokens
    list_res = client.get("/api/security/tokens")
    assert list_res.status_code == 200
    toks = list_res.json()
    assert any(t["token_id"] == token_id for t in toks)

    # 3. Rotate token
    rotate_res = client.post(
        f"/api/security/tokens/{token_id}/rotate",
        json={"grace_period_hours": 48.0, "ttl_days": 60},
    )
    assert rotate_res.status_code == 200
    rotate_data = rotate_res.json()
    assert rotate_data["old_record"]["grace_until"] is not None
    assert rotate_data["new_record"]["token_id"] != token_id
    new_plaintext_token = rotate_data["token"]

    # 4. Revoke old token
    revoke_res = client.post(
        f"/api/security/tokens/{token_id}/revoke",
        json={"reason": "routine_rotation"},
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["record"]["status"] == "revoked"

    # 5. Verify that new rotated token can authenticate ARC external service request
    arc_client = TestClient(app)
    # Use Bearer header with new token
    arc_res = arc_client.get(
        "/api/arc/missions",
        headers={"Authorization": f"Bearer {new_plaintext_token}"},
    )
    # Should not be 401 Unauthorized
    assert arc_res.status_code in (200, 404, 422)

    # 6. Check expiring tokens endpoint
    exp_res = client.get("/api/security/tokens/expiring?warning_threshold_days=90")
    assert exp_res.status_code == 200
