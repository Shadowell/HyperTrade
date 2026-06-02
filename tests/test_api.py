from decimal import Decimal

from fastapi.testclient import TestClient
from hypertrade.agent.kernel import AgentKernel
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.market.repository import MarketRepository


def test_api_exposes_health_harness_and_agent_run(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("20000"),
        change_utc0_pct=Decimal("4.2"),
    )
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "risk.md").write_text(
        "Risk control comes before signal strength.",
        encoding="utf-8",
    )

    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
    )
    client = TestClient(app)

    assert client.get("/api/health").json()["status"] == "ok"
    login_response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert login_response.status_code == 200
    assert "secure" not in login_response.headers["set-cookie"].lower()
    assert client.get("/api/harness/tools").json()["tools"][-1]["requires_approval"] is True
    assert client.get("/api/harness/providers").json()["providers"][0]["name"] == "deepseek"

    response = client.post("/api/agent/runs", json={"prompt": "请做行情归纳"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert (
        "BTC-USDT-SWAP" in body["report_markdown"]
        or "当前无法获取实时 OKX 行情" in body["report_markdown"]
    )
    if "当前无法获取实时 OKX 行情" in body["report_markdown"]:
        assert body["report_json"]["data_source"] == "unavailable"
    assert body["trace_events"][0]["tool_name"] == "market.summary"

    overview = client.get("/api/harness/overview").json()

    assert overview["market"]["ticker_count"] == 1
    assert overview["market"]["top_movers"][0]["inst_id"] == "BTC-USDT-SWAP"
    assert overview["agent_runs"]["total_count"] == 1
    assert overview["rag"]["document_count"] == 1
    assert overview["memory"]["active_count"] == 1
    assert overview["trace"]["total_count"] == 3
    assert overview["providers"][0]["name"] == "deepseek"
    assert overview["tools"][-1]["requires_approval"] is True
    assert overview["paper"]["session"]["status"] == "running"

    paper_status = client.get("/api/paper/status").json()
    assert paper_status["session"]["status"] == "running"

    pause = client.post("/api/paper/control", json={"action": "pause"}).json()
    assert pause["session"]["status"] == "paused"
    reset = client.post("/api/paper/control", json={"action": "reset"}).json()
    assert reset["session"]["status"] == "running"
    close = client.post("/api/paper/control", json={"action": "close", "symbol": "BTC"}).json()
    assert close["closed_count"] == 0

    intent = client.post(
        "/api/live/order-intents",
        json={"symbol": "ETH", "side": "buy", "size": "0.01", "reason": "api smoke"},
    ).json()
    assert intent["status"] == "pending_approval"
    assert intent["inst_id"] == "ETH-USDT-SWAP"
    assert client.get("/api/live/order-intents").json()["items"][0]["id"] == intent["id"]
    approved = client.post(
        f"/api/live/order-intents/{intent['id']}/approve",
        json={"reason": "checked"},
    ).json()
    assert approved["status"] == "approved"
    duplicate_approval = client.post(
        f"/api/live/order-intents/{intent['id']}/approve",
        json={"reason": "again"},
    )
    assert duplicate_approval.status_code == 400

    paused_overview = client.get("/api/harness/overview").json()
    assert paused_overview["paper"]["session"]["status"] == "running"
    assert paused_overview["live_orders"]["total_count"] == 1


def test_api_streams_agent_run_events(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=knowledge_dir,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    with client.stream(
        "POST",
        "/api/agent/runs/stream",
        json={"prompt": "请做行情归纳"},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run_started" in body
    assert "event: tool_started" in body
    assert "event: tool_completed" in body
    assert "event: run_completed" in body


def test_api_exposes_deterministic_market_shortcuts(monkeypatch, tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("3500"),
        volume_ccy_24h=Decimal("987654"),
        change_utc0_pct=Decimal("1.23"),
    )
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    ).status_code == 200

    monkeypatch.setattr(
        AgentKernel,
        "_market_candles_payload",
        lambda self, *, symbol, bar, limit: {
            "found": True,
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "bar": bar,
            "candle_count": limit,
            "return_pct": "2.400000",
            "data_source": "okx_rest",
        },
    )
    monkeypatch.setattr(
        AgentKernel,
        "_market_compare_payload",
        lambda self, *, symbols, bar, limit: {
            "found": True,
            "symbols": symbols,
            "bar": bar,
            "limit": limit,
            "leader": "ETH-USDT-SWAP",
            "rankings": [{"rank": 1, "inst_id": "ETH-USDT-SWAP"}],
            "data_source": "okx_rest",
        },
    )

    ticker = client.get("/api/market/ticker/ETH").json()
    candles = client.get("/api/market/candles/ETH?bar=1H&limit=50").json()
    compare = client.post(
        "/api/market/compare",
        json={"symbols": ["ETH", "SOL"], "bar": "4H", "limit": 100},
    ).json()

    assert ticker["inst_id"] == "ETH-USDT-SWAP"
    assert ticker["found"] is True
    assert candles == {
        "found": True,
        "inst_id": "ETH-USDT-SWAP",
        "bar": "1H",
        "candle_count": 50,
        "return_pct": "2.400000",
        "data_source": "okx_rest",
    }
    assert compare["leader"] == "ETH-USDT-SWAP"
    assert compare["symbols"] == ["ETH", "SOL"]


def test_login_cookie_secure_flag_is_configurable():
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(ADMIN_PASSWORD="secret", COOKIE_SECURE=True),
        db=db,
    )
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()
