"""Tests for Spec 031 QuantLab Console and HET Dashboard API endpoints."""

from decimal import Decimal

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.paper.relay_netting import PositionNettingRelayService


def test_quantlab_console_and_het_api_endpoints() -> None:
    settings = Settings(
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="test-secret-key-123",
        admin_tokens=["secret_token"],
        require_admin_token=False,
    )
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(settings=settings, db=db)
    client = TestClient(app)
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    assert login_res.status_code == 200

    # 1. Target switcher list
    res_targets = client.get("/api/portfolio/targets")
    assert res_targets.status_code == 200
    targets = res_targets.json()
    assert len(targets) == 2
    assert any(t["target_id"] == "bitpro" for t in targets)
    assert any(t["target_id"] == "quantlab" and t["market"] == "cn" for t in targets)

    # 2. QuantLab strategies list
    res_strats = client.get("/api/portfolio/targets/quantlab/strategies")
    assert res_strats.status_code == 200
    strats = res_strats.json()
    assert len(strats) >= 1
    strat = strats[0]
    assert strat["strategy_id"] == "quantlab:alpha_trend_01"
    assert "600519.SH" in strat["symbols"]
    assert strat["execution_backend"] == "matrix_native"
    assert len(strat["code_sha256"]) == 64

    # 3. QuantLab backtest trigger
    res_bt = client.post(
        f"/api/portfolio/targets/quantlab/strategies/{strat['strategy_id']}/backtest",
        headers={"Authorization": "Bearer secret_token"},
    )
    assert res_bt.status_code == 200
    bt_receipt = res_bt.json()
    assert bt_receipt["status"] == "success"
    assert "annualized_sharpe" in bt_receipt["metrics"] or "sharpe_ratio" in bt_receipt["metrics"]

    # 4. Position netting relay handovers list & step
    netting_svc = PositionNettingRelayService()
    plan = netting_svc.calculate_plan(
        parent_strategy_id="p_api_test",
        challenger_strategy_id="c_api_test",
        parent_holdings=[
            {"symbol": "600519.SH", "qty": Decimal("100"), "price": Decimal("1800")}
        ],
        challenger_target_holdings=[
            {"symbol": "600519.SH", "qty": Decimal("200"), "price": Decimal("1800")}
        ],
        slices_total=2,
    )

    res_plans = client.get("/api/portfolio/relay/handovers")
    assert res_plans.status_code == 200
    plans = res_plans.json()
    assert any(p["plan_id"] == plan.plan_id for p in plans)

    res_step = client.post(
        f"/api/portfolio/relay/handovers/{plan.plan_id}/step",
        headers={"Authorization": "Bearer secret_token"},
    )
    assert res_step.status_code == 200
    step_data = res_step.json()
    assert step_data["slice"] is not None
    assert step_data["plan"]["slices_completed"] == 1

    # 5. RD-Agent Hypothesis Evolution Tree
    res_tree = client.get("/api/research/hypothesis-tree?tree_id=test_tree_01")
    assert res_tree.status_code == 200
    nodes = res_tree.json()
    assert len(nodes) >= 2
    root_node = next(n for n in nodes if n["parent_id"] is None)
    assert "A股" in root_node["claim"]
    assert root_node["sharpe_ratio"] is not None
