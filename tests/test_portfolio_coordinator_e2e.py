import io
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypertrade.cli import main as cli_main
from hypertrade.config import Settings
from hypertrade.db import Database, MarketTicker, PaperSession
from hypertrade.main import create_app
from hypertrade.paper.portfolio import PortfolioCoordinatorService


def _test_setup(db_file: Path | None = None):
    url = f"sqlite:///{db_file}" if db_file else "sqlite:///:memory:"
    db = Database(url)
    db.create_all()
    settings = Settings(
        DATABASE_URL=url,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="test-secret-key-123",
        PAPER_STARTING_EQUITY_USDT="10000.0",
    )
    with db.session() as session:
        session.add(
            PaperSession(
                cash=Decimal("10000"),
                equity=Decimal("10000"),
                realized_pnl=Decimal("0"),
                config_json={},
            )
        )
        session.add(
            MarketTicker(
                inst_id="BTC-USDT-SWAP",
                last=Decimal("64000"),
                volume_ccy_24h=Decimal("5000000"),
                change_utc0_pct=Decimal("3.5"),
            )
        )
        session.add(
            MarketTicker(
                inst_id="ETH-USDT-SWAP",
                last=Decimal("3200"),
                volume_ccy_24h=Decimal("3000000"),
                change_utc0_pct=Decimal("-4.0"),
            )
        )
    return db, settings


def test_portfolio_coordinator_service():
    db, settings = _test_setup()
    service = PortfolioCoordinatorService(db, settings=settings)

    # 1. Summary
    summary = service.get_summary()
    assert summary["status"] == "running"
    assert summary["equity"] == "10000"
    assert len(summary["strategies"]) >= 4

    # 2. Strategies
    strats = service.get_strategies()
    keys = {s["strategy_key"] for s in strats}
    assert "rsi_reversal" in keys
    assert "momentum_breakout_v1" in keys

    # 3. Transition stage
    res = service.set_strategy_stage("rsi_reversal", "canary_live", reason="qa_test")
    assert res["updated"] is True
    assert res["stage"] == "canary_live"

    # 4. Rebalance
    rebal = service.trigger_rebalance()
    assert "run_result" in rebal
    assert rebal["portfolio"]["equity"] != ""


def test_portfolio_api_endpoints():
    db, settings = _test_setup()
    app = create_app(settings=settings, db=db)
    client = TestClient(app)

    # Login
    login_res = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert login_res.status_code == 200

    # Summary
    res = client.get("/api/portfolio/summary")
    assert res.status_code == 200
    data = res.json()
    assert "equity" in data
    assert "strategies" in data

    # Strategies
    res_strats = client.get("/api/portfolio/strategies")
    assert res_strats.status_code == 200
    assert len(res_strats.json()) >= 4

    # Stage update
    res_stage = client.post(
        "/api/portfolio/strategies/rsi_reversal/stage",
        json={"stage": "canary_live", "reason": "api_test"},
    )
    assert res_stage.status_code == 200
    assert res_stage.json()["stage"] == "canary_live"

    # Rebalance
    res_rebal = client.post("/api/portfolio/rebalance")
    assert res_rebal.status_code == 200
    assert "run_result" in res_rebal.json()


def test_portfolio_cli_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "cli_port.db"
    db, _ = _test_setup(db_file)
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("HYPERTRADE_DATABASE_URL", db_url)

    # CLI summary
    out = io.StringIO()
    code = cli_main(["--local", "portfolio", "summary"], output=out)
    assert code == 0
    assert "HyperTrade Multi-Strategy Portfolio Summary" in out.getvalue()

    # CLI strategies
    out = io.StringIO()
    code = cli_main(["--local", "portfolio", "strategies"], output=out)
    assert code == 0
    assert "Registered Execution Strategies" in out.getvalue()

    # CLI stage update
    out = io.StringIO()
    code = cli_main(
        ["--local", "portfolio", "stage", "--strategy", "rsi_reversal", "--stage", "canary_live"],
        output=out,
    )
    assert code == 0
    assert "stage updated to canary_live" in out.getvalue()

    # CLI rebalance
    out = io.StringIO()
    code = cli_main(["--local", "portfolio", "rebalance"], output=out)
    assert code == 0
    assert "Rebalance triggered" in out.getvalue()
