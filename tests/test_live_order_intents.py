import pytest
from hypertrade.config import Settings
from hypertrade.db import Database, LiveOrderIntent
from hypertrade.live.service import LiveOrderIntentService
from hypertrade.market.repository import MarketRepository


def test_live_order_intent_create_and_approve():
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = LiveOrderIntentService(db, settings=Settings(OKX_TESTNET=True))

    intent = service.create(
        symbol="ETH",
        side="buy",
        size="0.01",
        reason="operator testnet smoke",
    )
    approved = service.approve(intent["id"], reason="risk checked")

    assert intent["environment"] == "testnet"
    assert intent["status"] == "pending_approval"
    assert intent["inst_id"] == "ETH-USDT-SWAP"
    assert approved["status"] == "approved"
    assert approved["decision_reason"] == "risk checked"
    with db.session() as session:
        row = session.get(LiveOrderIntent, intent["id"])
        assert row is not None
        assert row.status == "approved"
        assert row.risk_status == "allowed"


def test_live_order_intent_rejects_invalid_order_shape():
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = LiveOrderIntentService(db, settings=Settings())

    with pytest.raises(ValueError, match="side must be buy or sell"):
        service.create(symbol="ETH", side="long", size="0.01")
    with pytest.raises(ValueError, match="limit order requires price"):
        service.create(symbol="ETH", side="buy", size="0.01", order_type="limit")
    with pytest.raises(ValueError, match="size must be positive"):
        service.create(symbol="ETH", side="buy", size="0")


def test_risk_engine_blocks_mainnet_and_oversized_intents():
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=10000,
        volume_ccy_24h=1000,
        change_utc0_pct=0,
    )
    mainnet_service = LiveOrderIntentService(db, settings=Settings(OKX_TESTNET=False))

    mainnet_intent = mainnet_service.create(
        symbol="ETH",
        side="buy",
        size="0.01",
        reason="mainnet should not execute",
    )

    assert mainnet_intent["status"] == "risk_blocked"
    assert mainnet_intent["risk_status"] == "blocked"
    assert "mainnet execution is forbidden" in mainnet_intent["risk"]["violations"]

    testnet_service = LiveOrderIntentService(
        db,
        settings=Settings(OKX_TESTNET=True, RISK_MAX_ORDER_NOTIONAL_USDT="100"),
    )
    oversized = testnet_service.create(symbol="ETH", side="buy", size="0.02")

    assert oversized["status"] == "risk_blocked"
    assert oversized["risk_status"] == "blocked"
    assert "order notional exceeds limit" in oversized["risk"]["violations"]


def test_testnet_execute_records_exchange_result(monkeypatch):
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=1000,
        volume_ccy_24h=1000,
        change_utc0_pct=0,
    )
    service = LiveOrderIntentService(
        db,
        settings=Settings(
            OKX_TESTNET=True,
            OKX_API_KEY="test-key",
            OKX_API_SECRET="test-secret",
            OKX_PASSPHRASE="test-passphrase",
        ),
    )
    intent = service.create(symbol="ETH", side="buy", size="0.01", reason="smoke")
    approved = service.approve(intent["id"], reason="checked")

    def fake_place_order(*args, **kwargs):
        assert kwargs["inst_id"] == "ETH-USDT-SWAP"
        return {
            "code": "0",
            "data": [{"ordId": "12345", "sCode": "0"}],
        }

    monkeypatch.setattr("hypertrade.live.service.OkxSignedRestClient.place_order", fake_place_order)
    executed = service.execute(approved["id"])

    assert executed["status"] == "executed_testnet"
    assert executed["exchange_order_id"] == "12345"
    assert executed["execution"]["request"]["api_key"] == "***"
