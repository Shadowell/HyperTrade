"""Tests for Position Netting and Smooth Relay Handover (Spec 030)."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from hypertrade.paper.race_judge import RaceJudgeDaemon, build_race_feishu_card
from hypertrade.paper.relay_netting import (
    PositionHolding,
    PositionNettingRelayService,
)
from hypertrade.targets.quantlab import QuantLabTargetAdapter


def test_position_netting_calculation_basic(tmp_path: Path) -> None:
    svc = PositionNettingRelayService(state_file=tmp_path / "relay.json")

    parent_holdings = [
        PositionHolding(symbol="600519.SH", qty=Decimal("1000"), price=Decimal("1800.0")),
        PositionHolding(symbol="000858.SZ", qty=Decimal("2000"), price=Decimal("150.0")),
    ]
    challenger_holdings = [
        PositionHolding(symbol="600519.SH", qty=Decimal("1200"), price=Decimal("1800.0")),
        PositionHolding(symbol="000858.SZ", qty=Decimal("1000"), price=Decimal("150.0")),
        PositionHolding(symbol="601318.SH", qty=Decimal("3000"), price=Decimal("50.0")),
    ]

    plan = svc.calculate_plan(
        parent_strategy_id="strat_parent_01",
        challenger_strategy_id="strat_challenger_02",
        parent_holdings=parent_holdings,
        challenger_target_holdings=challenger_holdings,
        target_id="quantlab",
        overlap_window_hours=24,
        slices_total=5,
        market="cn",
    )

    assert plan.plan_id.startswith("relay_plan_")
    assert plan.target_id == "quantlab"
    assert plan.state == "planned"
    assert len(plan.deltas) == 3

    # Check 600519: retained 1000, buy delta 200
    d_600519 = next(d for d in plan.deltas if d.symbol == "600519.SH")
    assert d_600519.retained_qty == Decimal("1000")
    assert d_600519.net_delta_qty == Decimal("200")
    assert d_600519.action == "BUY"

    # Check 000858: retained 1000, sell delta -1000
    d_000858 = next(d for d in plan.deltas if d.symbol == "000858.SZ")
    assert d_000858.retained_qty == Decimal("1000")
    assert d_000858.net_delta_qty == Decimal("-1000")
    assert d_000858.action == "SELL"

    # Check 601318: retained 0, buy delta 3000
    d_601318 = next(d for d in plan.deltas if d.symbol == "601318.SH")
    assert d_601318.retained_qty == Decimal("0")
    assert d_601318.net_delta_qty == Decimal("3000")
    assert d_601318.action == "BUY"

    # Significant turnover reduction (over 80%)
    assert plan.turnover_reduction_ratio > 0.80
    assert plan.total_friction_saved > Decimal("1000")  # Substantial CNY saved
    assert len(plan.plan_sha256) == 64


def test_smooth_relay_slicing_and_lot_sizes(tmp_path: Path) -> None:
    svc = PositionNettingRelayService(state_file=tmp_path / "relay.json")

    parent_holdings = [
        {"symbol": "600519.SH", "qty": "500", "price": "1800.0"},
    ]
    challenger_holdings = [
        {"symbol": "600519.SH", "qty": "1500", "price": "1800.0"},  # Buy 1000 net
    ]

    plan = svc.calculate_plan(
        parent_strategy_id="p1",
        challenger_strategy_id="c1",
        parent_holdings=parent_holdings,
        challenger_target_holdings=challenger_holdings,
        slices_total=5,
        market="cn",
    )

    assert len(plan.slices) == 5
    total_sliced = Decimal("0")
    for s in plan.slices:
        assert len(s.orders) == 1
        order = s.orders[0]
        assert order.side == "buy"
        # Lot size multiple of 100
        assert order.slice_qty % Decimal("100") == Decimal("0")
        total_sliced += order.slice_qty

    assert total_sliced == Decimal("1000")


def test_relay_handover_plan_step_lifecycle(tmp_path: Path) -> None:
    svc = PositionNettingRelayService(state_file=tmp_path / "relay.json")

    plan = svc.calculate_plan(
        parent_strategy_id="p1",
        challenger_strategy_id="c1",
        parent_holdings=[{"symbol": "000858.SZ", "qty": "1000", "price": "150.0"}],
        challenger_target_holdings=[{"symbol": "000858.SZ", "qty": "500", "price": "150.0"}],
        slices_total=3,
        market="cn",
    )

    assert plan.state == "planned"
    assert plan.slices_completed == 0

    # Step 1
    slice1, updated_plan = svc.step_slice(plan.plan_id)
    assert slice1 is not None
    assert slice1.slice_index == 1
    assert slice1.executed is True
    assert updated_plan.state == "in_progress"
    assert updated_plan.slices_completed == 1

    # Step 2
    slice2, updated_plan = svc.step_slice(plan.plan_id)
    assert slice2 is not None
    assert updated_plan.slices_completed == 2
    assert updated_plan.state == "in_progress"

    # Step 3 (final)
    slice3, updated_plan = svc.step_slice(plan.plan_id)
    assert slice3 is not None
    assert updated_plan.slices_completed == 3
    assert updated_plan.state == "completed"

    # Extra step does nothing
    slice_extra, final_plan = svc.step_slice(plan.plan_id)
    assert slice_extra is None
    assert final_plan.state == "completed"


def test_quantlab_target_adapter_netting_plan() -> None:
    adapter = QuantLabTargetAdapter(simulation=True)
    plan_dict = adapter.paper_relay_netting_plan(
        parent_id="quantlab:alpha_trend_01",
        challenger_id="quantlab:alpha_trend_01_offspring",
        slices_total=5,
    )

    assert plan_dict["target_id"] == "quantlab"
    assert plan_dict["state"] == "planned"
    assert plan_dict["turnover_reduction_ratio"] > 0.0
    assert Decimal(plan_dict["total_friction_saved"]) > Decimal("0")
    assert len(plan_dict["slices"]) == 5

    # Test adopt trigger with netting plan
    ctrl = adapter.paper_relay_control(
        parent_id="quantlab:alpha_trend_01",
        action="adopt",
        challenger_id="quantlab:alpha_trend_01_offspring",
    )
    assert ctrl["status"] == "success"
    assert ctrl["netting_plan"] is not None
    assert ctrl["netting_plan"]["turnover_reduction_ratio"] > 0


def test_race_judge_daemon_adoption_with_netting(tmp_path: Path) -> None:
    history_file = tmp_path / "history.json"
    state_file = tmp_path / "state.json"
    netting_file = tmp_path / "netting.json"

    netting_svc = PositionNettingRelayService(state_file=netting_file)
    mock_adapter = MagicMock()
    mock_adapter.paper_relay_status.return_value = {
        "status": "observing",
        "proof": {
            "eligible": True,
            "proof_sha256": "abcdef1234567890",
            "observed_points": 340,
            "sign_test_p": 0.01,
            "excess_return_pct": 5.2,
            "net_return_pct": [2.0, 7.2],
            "observed_drawdown_pct": [5.0, 3.2],
            "closed_fills": [50, 60],
        },
    }
    mock_adapter.paper_relay_control.return_value = {"status": "ok"}

    daemon = RaceJudgeDaemon(
        bitpro_adapter=mock_adapter,
        history_file=history_file,
        state_file=state_file,
        auto_adopt=True,
        netting_service=netting_svc,
    )

    record = daemon.evaluate_pair(
        parent_id="101",
        challenger_id="202",
        generation=2,
        target_id="bitpro",
    )

    assert record.state == "draining"
    assert record.action_taken == "adopted"
    assert record.handover_plan_id is not None
    assert record.turnover_reduction_ratio > 0.0
    assert record.friction_saved_cny > 0.0
    assert record.handover_slices_total == 5

    # Check Feishu card rendering with netting metrics
    card = build_race_feishu_card(record, "ADOPTED")
    elements = card["card"]["elements"]
    text_content = elements[0]["text"]["content"]
    assert "净额平滑换仓" in text_content
    assert "换手节省" in text_content

    # Subsequent sweep while in draining steps next slice
    record_step = daemon.evaluate_pair(
        parent_id="101",
        challenger_id="202",
        generation=2,
        target_id="bitpro",
    )
    assert record_step.handover_slices_completed >= 1


def test_portfolio_coordinator_service_relay_integration(tmp_path: Path) -> None:
    from hypertrade.db import Database
    from hypertrade.paper.portfolio import PortfolioCoordinatorService

    db = Database("sqlite:///:memory:")
    db.create_all()
    coord = PortfolioCoordinatorService(db=db)

    # Initially empty or default
    plans = coord.get_relay_handover_plans()
    assert isinstance(plans, list)

    # Create a plan through netting service
    svc = PositionNettingRelayService()
    plan = svc.calculate_plan(
        parent_strategy_id="p_test",
        challenger_strategy_id="c_test",
        parent_holdings=[{"symbol": "600519.SH", "qty": "100", "price": "1800.0"}],
        challenger_target_holdings=[{"symbol": "600519.SH", "qty": "200", "price": "1800.0"}],
        slices_total=2,
    )

    plans_after = coord.get_relay_handover_plans()
    assert any(p["plan_id"] == plan.plan_id for p in plans_after)

    # Step slice through coordinator
    res = coord.step_relay_handover_slice(plan.plan_id)
    assert res["slice"] is not None
    assert res["plan"]["slices_completed"] == 1

