"""End-to-end test suite for Spec 014: Autonomous Market Pulse & Live Perception Feeds."""

from __future__ import annotations

import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from hypertrade.agent.pulse import AutonomousMarketPulseService
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.market.client import OkxRestClient
from hypertrade.market.news import InMemoryNewsFeed, NewsIngestionService


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


def test_pulse_api_endpoints_e2e(tmp_path) -> None:
    db_file = tmp_path / "test_e2e.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_all()

    settings = Settings(
        database_url=f"sqlite:///{db_file}",
        autonomous_pulse_enabled=True,
        autonomous_pulse_symbols="BTC-USDT-SWAP,ETH-USDT-SWAP",
        enable_external_news_feed=False,
    )
    app = create_app(settings, db=db)
    client = TestClient(app)

    # 1. Test POST /api/agent/pulse/trigger
    resp = client.post(
        "/api/agent/pulse/trigger",
        json={"dry_run": True, "symbols": ["BTC-USDT-SWAP"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["trigger"] == "manual"
    assert data["status"] == "completed"
    assert data["symbols"] == ["BTC-USDT-SWAP"]
    assert len(data["decisions"]) == 1

    # 2. Test GET /api/agent/pulse/history
    resp_hist = client.get("/api/agent/pulse/history?limit=5")
    assert resp_hist.status_code == 200
    hist_data = resp_hist.json()
    assert "items" in hist_data
    assert len(hist_data["items"]) >= 1
    assert hist_data["items"][0]["id"] == data["id"]

    # 3. Test GET /api/market/news/latest
    resp_news = client.get("/api/market/news/latest?limit=10")
    assert resp_news.status_code == 200
    news_data = resp_news.json()
    assert "articles" in news_data
    assert "count" in news_data


@pytest.mark.anyio
async def test_worker_autonomous_market_pulse_loop_tick(tmp_path) -> None:
    db_file = tmp_path / "test_worker_pulse.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_all()

    from hypertrade.worker import autonomous_market_pulse_loop

    settings = Settings(
        database_url=f"sqlite:///{db_file}",
        autonomous_pulse_enabled=True,
        autonomous_pulse_symbols="BTC-USDT-SWAP",
        autonomous_pulse_interval_seconds=1,
        enable_external_news_feed=False,
    )
    news_svc = NewsIngestionService([InMemoryNewsFeed()])
    pulse_service = AutonomousMarketPulseService(
        db, settings=settings, news_service=news_svc
    )

    # Run the loop with a short sleep and cancel it after 1 tick
    task = asyncio.create_task(
        autonomous_market_pulse_loop(db, settings=settings, service=pulse_service)
    )
    await asyncio.sleep(0.3)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # Verify a pulse cycle was recorded
    history = pulse_service.list_history()
    assert len(history) >= 1
    assert history[0]["trigger"] == "scheduled"
