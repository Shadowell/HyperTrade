from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app


def test_strategy_research_and_backtest_api(tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    research = client.post(
        "/api/strategy/research",
        json={"prompt": "研究一个趋势突破策略"},
    ).json()

    assert research["strategy_key"] == "momentum_breakout_v1"
    assert "趋势" in research["report_markdown"]

    backtest = client.post(
        "/api/backtests",
        json={"research_id": research["id"]},
    ).json()

    assert backtest["status"] == "completed"
    assert backtest["strategy_key"] == "momentum_breakout_v1"
    assert backtest["metrics"]["trade_count"] >= 1

    overview = client.get("/api/harness/overview").json()
    assert overview["strategy_lab"]["latest_research"]["id"] == research["id"]
    assert overview["strategy_lab"]["latest_backtest"]["id"] == backtest["id"]
