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
from hypertrade.paper.registry import StrategyRecord, StrategyRegistry
from hypertrade.paper.self_healing import SelfHealingEvolutionEngine
from hypertrade.paper.stage_gate import StrategyStage


def _test_setup(db_file: Path | None = None, tmp_path: Path | None = None):
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

    reg_path = tmp_path / "reg.json" if tmp_path else None
    hist_path = tmp_path / "hist.json" if tmp_path else None
    registry = StrategyRegistry(storage_path=reg_path)
    self_healing = SelfHealingEvolutionEngine(registry=registry, history_file=hist_path)
    return db, settings, registry, self_healing


def test_portfolio_registry_and_evolution_endpoints(tmp_path: Path):
    db, settings, registry, self_healing = _test_setup(tmp_path=tmp_path)
    service = PortfolioCoordinatorService(
        db, settings=settings, registry=registry, self_healing=self_healing
    )
    app = create_app(settings=settings, db=db)
    # Inject service into app dependency if needed or use coordinator directly
    client = TestClient(app)

    # Login
    login_res = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert login_res.status_code == 200

    # 1. GET /api/portfolio/registry
    res_reg = client.get("/api/portfolio/registry")
    assert res_reg.status_code == 200
    reg_items = res_reg.json()
    assert len(reg_items) >= 4

    # 2. POST /api/portfolio/registry
    new_strat = {
        "strategy_id": "custom_alpha_v1",
        "strategy_type": "rsi_reversal",
        "name": "Custom Alpha V1",
        "parameters": {"rsi_period": 14, "oversold_threshold": 25.0},
        "stage": "paper_observing",
    }
    res_post = client.post("/api/portfolio/registry", json=new_strat)
    assert res_post.status_code == 200
    assert res_post.json()["strategy_id"] == "custom_alpha_v1"

    # 3. POST /api/portfolio/strategies/{key}/evolve
    res_evolve = client.post("/api/portfolio/strategies/rsi_reversal/evolve")
    assert res_evolve.status_code == 200
    evolve_data = res_evolve.json()
    assert evolve_data["parent_strategy_id"] == "rsi_reversal"
    assert evolve_data["offspring_strategy_id"] == "rsi_reversal_gen2"
    assert evolve_data["generation"] == 2

    # 4. GET /api/portfolio/evolution/history
    res_hist = client.get("/api/portfolio/evolution/history")
    assert res_hist.status_code == 200
    hist_items = res_hist.json()
    assert len(hist_items) >= 1
    assert any(h["offspring_strategy_id"] == "rsi_reversal_gen2" for h in hist_items)


def test_portfolio_registry_and_evolution_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "cli_port_evo.db"
    db, _, _, _ = _test_setup(db_file=db_file, tmp_path=tmp_path)
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("HYPERTRADE_DATABASE_URL", db_url)

    # CLI registry
    out = io.StringIO()
    code = cli_main(["--local", "portfolio", "registry"], output=out)
    assert code == 0
    assert "Persistent Strategy Registry" in out.getvalue()
    assert "rsi_reversal" in out.getvalue()

    # CLI evolve
    out = io.StringIO()
    code = cli_main(["--local", "portfolio", "evolve", "--strategy", "rsi_reversal"], output=out)
    assert code == 0
    assert "Strategy self-healing evolution complete" in out.getvalue()
    assert "rsi_reversal_gen2" in out.getvalue()

    # CLI history
    out = io.StringIO()
    code = cli_main(["--local", "portfolio", "history"], output=out)
    assert code == 0
    assert "Self-Healing Evolution Events" in out.getvalue()
    assert "rsi_reversal -> rsi_reversal_gen2" in out.getvalue()
