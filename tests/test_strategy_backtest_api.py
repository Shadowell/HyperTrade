from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.market.okx import parse_okx_candle


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


def test_strategy_experiment_workflow_api(tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    experiment = client.post(
        "/api/strategy/experiments",
        json={"prompt": "研究ETH趋势突破，给出回测和改进建议"},
    ).json()
    experiments = client.get("/api/strategy/experiments").json()["items"]
    overview = client.get("/api/harness/overview").json()

    assert experiment["id"].startswith("exp_")
    assert experiment["status"] == "completed"
    assert experiment["research_id"].startswith("srch_")
    assert experiment["backtest_id"].startswith("bt_")
    assert "critique" in experiment["report_json"]
    variants = experiment["report_json"]["variants"]
    winner = experiment["report_json"]["winner"]
    gates = experiment["report_json"]["evidence_gates"]
    assert len(variants) >= 3
    assert all(item["backtest_id"].startswith("bt_") for item in variants)
    assert all(item["metrics"]["trade_count"] >= 0 for item in variants)
    assert {item["variant_id"] for item in variants} >= {
        "baseline",
        "fast",
        "conservative",
    }
    assert winner["variant_id"] in {item["variant_id"] for item in variants}
    assert winner["backtest_id"] == experiment["backtest_id"]
    assert gates == {
        "min_trade_count": 1,
        "max_drawdown_pct": "20",
        "require_non_negative_return": True,
    }
    assert "## 候选版本对比" in experiment["report_markdown"]
    assert "## 胜出版本" in experiment["report_markdown"]
    assert "不构成投资建议" in experiment["report_markdown"]
    backtests = client.get("/api/backtests").json()["items"]
    assert len(backtests) >= 3
    assert experiments[0]["id"] == experiment["id"]
    assert overview["strategy_lab"]["latest_experiment"]["id"] == experiment["id"]


def test_backtest_api_accepts_live_okx_candle_options(monkeypatch, tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    captured: dict[str, object] = {}

    def fake_fetch(self, inst_id: str, bar: str, limit: int):
        captured.update({"inst_id": inst_id, "bar": bar, "limit": limit})
        return [
            parse_okx_candle(
                [
                    str(1764200000000 + index * 3600000),
                    str(100 + index),
                    str(101 + index),
                    str(99 + index),
                    str(100 + index),
                    "1000",
                    "1000",
                    "100000",
                    "1",
                ]
            )
            for index in range(24)
        ]

    monkeypatch.setattr(
        "hypertrade.backtest.service.BacktestService._fetch_okx_candles",
        fake_fetch,
    )

    response = client.post(
        "/api/backtests",
        json={
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": True,
            "symbol": "ETH",
            "bar": "1H",
            "candle_limit": 24,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert captured == {"inst_id": "ETH-USDT-SWAP", "bar": "1H", "limit": 24}
    assert body["report_json"]["data_source"] == "okx_rest_candles"
