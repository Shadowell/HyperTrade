from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database, MonitorAlertEvent
from hypertrade.main import create_app
from hypertrade.market.repository import MarketRepository
from hypertrade.world_model.service import WorldModelService


def _settings(
    *,
    enabled: bool = False,
    allowlist: str = "",
) -> Settings:
    return Settings(
        DEEPSEEK_API_KEY="test-key",
        OKX_REST_URL="http://127.0.0.1:9",
        WORLD_MODEL_DEFENSIVE_ACTIONS_ENABLED=enabled,
        WORLD_MODEL_DEFENSIVE_ACTION_ALLOWLIST=allowlist,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
    )


def _seed_market(db: Database) -> None:
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("2000000"),
        change_utc0_pct=Decimal("-3.5"),
    )


def _snapshot(db: Database, settings: Settings) -> dict[str, object]:
    _seed_market(db)
    return WorldModelService(db, settings=settings).snapshot()


def _alert_count(db: Database) -> int:
    with db.session() as session:
        return len(session.query(MonitorAlertEvent).all())


def test_defensive_actions_disabled_by_default_records_skipped_attempt() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    settings = _settings()
    world_state = _snapshot(db, settings)

    from hypertrade.world_model.defensive_actions import DefensiveActionEngine

    result = DefensiveActionEngine(db, settings=settings).execute(
        action_id="raise_human_confirmation_alert",
        idempotency_key="wm-test-disabled",
        world_state=world_state,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "defensive_actions_disabled"
    assert result["policy_decision"]["status"] == "allowed"
    assert _alert_count(db) == 0
    attempts = DefensiveActionEngine(db, settings=settings).list_attempts()
    assert attempts[0]["idempotency_key"] == "wm-test-disabled"
    assert attempts[0]["status"] == "skipped"


def test_allowlisted_defensive_action_executes_once_with_idempotency() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    settings = _settings(
        enabled=True,
        allowlist="raise_human_confirmation_alert",
    )
    world_state = _snapshot(db, settings)

    from hypertrade.world_model.defensive_actions import DefensiveActionEngine

    engine = DefensiveActionEngine(db, settings=settings)
    first = engine.execute(
        action_id="raise_human_confirmation_alert",
        idempotency_key="wm-test-once",
        world_state=world_state,
    )
    second = engine.execute(
        action_id="raise_human_confirmation_alert",
        idempotency_key="wm-test-once",
        world_state=world_state,
    )

    assert first["status"] == "executed"
    assert first["execution_result"]["alert_created"] is True
    assert second["status"] == "duplicate"
    assert second["execution_result"]["duplicate_of"] == first["action_attempt_id"]
    assert _alert_count(db) == 1
    assert len(engine.list_attempts()) == 1


def test_defensive_actions_reject_missing_idempotency_and_offensive_actions() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    settings = _settings(enabled=True, allowlist="raise_human_confirmation_alert")
    world_state = _snapshot(db, settings)

    from hypertrade.world_model.defensive_actions import DefensiveActionEngine

    engine = DefensiveActionEngine(db, settings=settings)
    missing_key = engine.execute(
        action_id="raise_human_confirmation_alert",
        idempotency_key="",
        world_state=world_state,
    )
    offensive = engine.execute(
        action_id="increase_risk",
        idempotency_key="wm-test-offensive",
        world_state=world_state,
    )

    assert missing_key["status"] == "rejected"
    assert missing_key["reason"] == "missing_idempotency_key"
    assert offensive["status"] == "rejected"
    assert offensive["reason"] == "offensive_action_blocked"
    assert _alert_count(db) == 0


def test_defensive_action_api_lists_config_and_attempts() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    settings = _settings(
        enabled=True,
        allowlist="raise_human_confirmation_alert",
    )
    _snapshot(db, settings)
    client = TestClient(create_app(settings=settings, db=db))
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    config = client.get("/api/world-model/defensive-actions").json()
    assert config["enabled"] is True
    assert config["allowlist"] == ["raise_human_confirmation_alert"]

    response = client.post(
        "/api/world-model/defensive-actions/execute",
        json={
            "action_id": "raise_human_confirmation_alert",
            "idempotency_key": "wm-api-once",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "executed"
    attempts = client.get("/api/world-model/defensive-action-attempts").json()
    assert attempts["attempts"][0]["idempotency_key"] == "wm-api-once"
