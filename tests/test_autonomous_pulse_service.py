"""Unit tests for AutonomousMarketPulseService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypertrade.agent.pulse import AutonomousMarketPulseService
from hypertrade.config import Settings
from hypertrade.db import Database, MarketTicker
from hypertrade.market.client import OkxRestClient
from hypertrade.market.news import InMemoryNewsFeed, NewsArticle, NewsIngestionService
from hypertrade.providers.chat import ChatResponse


@pytest.fixture(autouse=True)
def mock_okx_intelligence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _mock_funding(*args, **kwargs):
        return {
            "fundingRate": "0.0001",
            "nextFundingRate": "0.0001",
            "fundingTime": "1700000000000",
        }

    async def _mock_oi(*args, **kwargs):
        return {"oi": "1000", "oiCcy": "3500000", "ts": "1700000000000"}
    monkeypatch.setattr(OkxRestClient, "fetch_funding_rate", _mock_funding)
    monkeypatch.setattr(OkxRestClient, "fetch_open_interest", _mock_oi)


def _build_test_db() -> Database:
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


def test_pulse_fast_filter_calm_market() -> None:
    db = _build_test_db()
    service = AutonomousMarketPulseService(
        db,
        settings=Settings(enable_external_news_feed=False),
        news_service=NewsIngestionService([InMemoryNewsFeed()]),
    )

    # Empty news, quiet market -> should trigger fast-filter HOLD
    res = service.run_pulse_once(symbols=["BTC-USDT-SWAP"], dry_run=True)
    assert res["status"] == "completed"
    assert len(res["decisions"]) == 1
    decision = res["decisions"][0]
    assert decision["action"] == "hold"
    assert "calm_market" in decision["reason"]
    assert res["orders_executed"] == []


def test_pulse_bullish_catalyst_triggers_buy_order() -> None:
    db = _build_test_db()
    # Seed a ticker
    with db.session() as session:
        session.add(
            MarketTicker(
                inst_id="ETH-USDT-SWAP",
                last=3500.0,
                volume_ccy_24h=50000.0,
                change_utc0_pct=2.5,
            )
        )

    # Ingest breaking bullish news
    news_svc = NewsIngestionService(
        [
            InMemoryNewsFeed(
                [
                    NewsArticle.create(
                        title="Massive ETF inflow and approval surges ETH to new highs",
                        symbols=["ETH"],
                        source="bloomberg",
                    )
                ]
            )
        ]
    )

    settings = Settings(
        autonomous_pulse_min_conviction=0.70,
        risk_max_order_notional_usdt="100",
        enable_external_news_feed=False,
    )
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"code": "0", "data": [{"ordId": "ord_pulse_123"}]}
    from hypertrade.live.service import AutonomousExecutionManager

    exec_mgr = AutonomousExecutionManager(db, settings=settings, client=mock_client)
    service = AutonomousMarketPulseService(
        db,
        settings=settings,
        news_service=news_svc,
        execution_manager=exec_mgr,
    )

    res = service.run_pulse_once(
        symbols=["ETH-USDT-SWAP"],
        dry_run=False,
        autonomous_override=True,
    )
    assert res["status"] == "completed"
    decision = res["decisions"][0]
    assert decision["action"] == "buy"
    assert decision["confidence"] >= 0.70

    # Verify execution order was logged
    assert len(res["orders_executed"]) == 1
    order = res["orders_executed"][0]
    assert order["inst_id"] == "ETH-USDT-SWAP"
    assert order["side"] == "buy"
    assert order["executed"] is True


def test_pulse_llm_reasoning_integration() -> None:
    db = _build_test_db()
    mock_provider = MagicMock()
    mock_provider.chat.return_value = ChatResponse(
        content=(
            '{"action": "sell", "confidence": 0.88, "suggested_size": "2", '
            '"reason": "macro_rate_hike_dump", "risk_assessment": "short_hedge"}'
        )
    )

    # Feed some news so fast-filter passes to LLM
    news_svc = NewsIngestionService(
        [
            InMemoryNewsFeed(
                [
                    NewsArticle.create(
                        title="SEC issues emergency subpoena, crash expected",
                        symbols=["SOL"],
                        source="reuters",
                    )
                ]
            )
        ]
    )

    service = AutonomousMarketPulseService(
        db,
        settings=Settings(autonomous_pulse_min_conviction=0.70),
        chat_provider=mock_provider,
        news_service=news_svc,
    )

    res = service.run_pulse_once(
        symbols=["SOL-USDT-SWAP"],
        dry_run=True,
    )
    assert res["status"] == "completed"
    decision = res["decisions"][0]
    assert decision["action"] == "sell"
    assert decision["confidence"] == 0.88
    assert decision["reason"] == "macro_rate_hike_dump"
    # Dry run should record simulated_dry_run
    assert res["orders_executed"][0]["status"] == "simulated_dry_run"


def test_pulse_history_retrieval() -> None:
    db = _build_test_db()
    service = AutonomousMarketPulseService(
        db,
        settings=Settings(enable_external_news_feed=False),
        news_service=NewsIngestionService([InMemoryNewsFeed()]),
    )

    service.run_pulse_once(symbols=["BTC-USDT-SWAP"], trigger="scheduled", dry_run=True)
    service.run_pulse_once(symbols=["ETH-USDT-SWAP"], trigger="manual", dry_run=True)

    history = service.list_history(limit=10)
    assert len(history) == 2
    assert history[0]["trigger"] == "manual"
    assert history[0]["symbols"] == ["ETH-USDT-SWAP"]
    assert history[1]["trigger"] == "scheduled"
    assert history[1]["symbols"] == ["BTC-USDT-SWAP"]
