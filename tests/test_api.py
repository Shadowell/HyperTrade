from decimal import Decimal

from fastapi.testclient import TestClient
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

    paused_overview = client.get("/api/harness/overview").json()
    assert paused_overview["paper"]["session"]["status"] == "paused"


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
