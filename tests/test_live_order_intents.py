import pytest
from hypertrade.config import Settings
from hypertrade.db import Database, LiveOrderIntent
from hypertrade.live.service import LiveOrderIntentService


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
