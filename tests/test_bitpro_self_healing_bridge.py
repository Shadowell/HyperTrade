"""Unit tests for BitPro Anomaly Monitoring and HyperTrade Self-Healing Bridge."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from hypertrade.bitpro.paper_monitor import (
    IncrementalEvolutionTrigger,
    PaperAnomalyDetector,
    PaperObservationSnapshot,
)
from hypertrade.paper.registry import StrategyRecord, StrategyRegistry
from hypertrade.paper.self_healing import (
    SelfHealingEvolutionEngine,
    generate_7d_attribution_report,
)
from hypertrade.paper.stage_gate import StrategyStage


def test_self_healing_cta_ema_mutation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"
        registry = StrategyRegistry(storage_path=reg_file)
        engine = SelfHealingEvolutionEngine(registry=registry, history_file=hist_file)

        rec = StrategyRecord(
            strategy_id="333",
            strategy_type="cta_trend_following",
            name="[合约][1H][CTA] KAITO · EMA5/20趋势跟踪激进版 · 100U",
            parameters={
                "fast_window": 5,
                "slow_window": 20,
                "hard_stop_loss_pct": "0.04",
                "profit_peak_pullback_pct": "0.30",
                "atr_stop_mult": "1.5",
            },
            stage=StrategyStage.DEGRADED,
            generation=1,
        )
        registry.register(rec)

        with patch(
            "hypertrade.paper.self_healing.dispatch_reflexion_alert",
            return_value=(True, "ok"),
        ):
            healed = engine.heal_strategy("333")

        assert healed is not None
        assert healed.parent_strategy_id == "333"
        assert healed.generation == 2
        assert healed.mutated_parameters["fast_window"] == 8
        assert healed.mutated_parameters["slow_window"] == 25
        assert Decimal(healed.mutated_parameters["hard_stop_loss_pct"]) <= Decimal("0.025")
        assert "smooth_ema_entry_windows_to_filter_chop" in healed.reflexion_constraints

        dims = healed.attribution_report.get("dimensions", {})
        assert len(dims) == 7
        for key in (
            "entry_timing",
            "exit_timing",
            "costs",
            "long_short",
            "holding_duration",
            "sample_coverage",
            "regime",
        ):
            assert key in dims
            assert dims[key]["state"] == "observed"
            assert len(dims[key]["reason"]) > 0


def test_heal_bitpro_strategy_creates_and_registers_generation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"
        registry = StrategyRegistry(storage_path=reg_file)
        engine = SelfHealingEvolutionEngine(registry=registry, history_file=hist_file)

        with patch(
            "hypertrade.paper.self_healing.dispatch_reflexion_alert",
            return_value=(True, "ok"),
        ):
            healed = engine.heal_bitpro_strategy(
                333,
                {
                    "name": "[合约][1H][CTA] KAITO · EMA5/20趋势跟踪激进版 · 100U",
                    "strategy_type": "cta_trend_following",
                    "config": {
                        "fast_window": 5,
                        "slow_window": 20,
                        "hard_stop_loss_pct": "0.04",
                    },
                },
            )

        assert healed is not None
        assert healed.parent_strategy_id == "333"
        assert healed.offspring_strategy_id == "333_gen2"
        assert healed.generation == 2
        assert healed.mutated_parameters["fast_window"] == 8
        assert healed.mutated_parameters["slow_window"] == 25


def test_paper_anomaly_detector_evaluate_and_heal() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"
        registry = StrategyRegistry(storage_path=reg_file)
        engine = SelfHealingEvolutionEngine(registry=registry, history_file=hist_file)
        trigger = IncrementalEvolutionTrigger(self_healing_engine=engine)
        detector = PaperAnomalyDetector(max_drawdown_threshold=0.10)

        snapshot = PaperObservationSnapshot(
            instance_id="333",
            symbol="KAITO-USDT",
            timeframe="1H",
            cumulative_return_pct=-0.15,
            current_drawdown_pct=0.12,
            consecutive_losses=4,
            win_rate_30d=0.35,
            avg_slippage_bps=8.0,
        )

        with patch(
            "hypertrade.paper.self_healing.dispatch_reflexion_alert",
            return_value=(True, "ok"),
        ):
            healed_list = detector.evaluate_and_heal(snapshot, trigger=trigger)

        assert len(healed_list) >= 1
        assert healed_list[0].parent_strategy_id == "333"
        assert healed_list[0].generation == 2
        assert healed_list[0].attribution_report is not None


def test_generate_7d_attribution_report_structure() -> None:
    report = generate_7d_attribution_report(
        strategy_name="KAITO EMA Test",
        strategy_type="cta_trend_following",
        parameters={"fast_window": 8, "slow_window": 25, "hard_stop_loss_pct": "0.025"},
        metrics={"win_rate": 0.60, "simulated_trades": 40},
        strategy_id="333",
    )
    assert report["schema_version"] == "paper_attribution.v1"
    assert report["causal_conclusion"] == "established_via_self_healing"
    assert len(report["dimensions"]) == 7
    assert "EMA8/25" in report["dimensions"]["entry_timing"]["reason"]
    assert report["dimensions"]["sample_coverage"]["metrics"]["execution_count"] == 40


def test_heal_bitpro_fallback() -> None:
    from hypertrade.arc.evolution import _heal_bitpro_fallback

    mock_ports = MagicMock()
    snapshot = {
        "strategy_id": 333,
        "instance_id": "inst_333",
        "strategy_name": "[合约][1H][CTA] KAITO · EMA5/20趋势跟踪激进版 · 100U",
        "parameters": {
            "fast_window": 5,
            "slow_window": 20,
            "strategy_type": "cta_trend_following",
        },
    }
    with patch(
        "hypertrade.paper.self_healing.dispatch_reflexion_alert",
        return_value=(True, "ok"),
    ):
        res = _heal_bitpro_fallback(333, snapshot, mock_ports)

    assert res is not None
    diag_patch, _ = res
    assert diag_patch["status"] == "opportunity"
    assert diag_patch["trigger_source"] == "self_healing_fallback"
    assert diag_patch["candidate_id"] == "333_gen2"
    assert diag_patch["candidate_parameters"]["fast_window"] == 8
    assert len(diag_patch["attribution_report"]["dimensions"]) == 7


def test_self_healing_real_bitpro_deployment_and_backtest() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"
        registry = StrategyRegistry(storage_path=reg_file)

        mock_adapter = MagicMock()
        mock_adapter.strategy_get.return_value = {
            "status": "ok",
            "strategy": {
                "id": 333,
                "name": "[合约][1H][CTA] KAITO · EMA5/20趋势跟踪激进版 · 100U",
                "script_content": "class DemoStrategy: pass",
                "config": {"fast_window": 5, "slow_window": 20, "hard_stop_loss_pct": "0.04"},
                "symbols": ["KAITO-USDT-SWAP"],
                "exchange": "okx",
            },
        }
        mock_adapter.backtest_start_job.return_value = {
            "status": "ok",
            "result": {
                "id": "bt_1001",
                "win_rate": 0.64,
                "profit_factor": 1.95,
                "sharpe_ratio": 1.82,
                "max_drawdown": 0.038,
                "total_trades": 58,
            },
        }
        mock_adapter.strategy_create.return_value = {
            "status": "ok",
            "strategy": {
                "id": 999,
                "name": "[合约][1H][CTA] KAITO · EMA5/20趋势跟踪激进版自愈(Gen 2) · 100U",
            },
        }
        mock_adapter.paper_configure.return_value = {
            "status": "ok",
            "paper": {"strategy_id": 999, "status": "configured"},
        }
        mock_adapter.paper_start.return_value = {
            "status": "ok",
            "paper": {"strategy_id": 999, "instance_id": "inst_999", "status": "running"},
        }

        engine = SelfHealingEvolutionEngine(
            registry=registry, history_file=hist_file, bitpro_adapter=mock_adapter
        )

        with patch("hypertrade.paper.self_healing.dispatch_reflexion_alert") as mock_alert:
            mock_alert.return_value = (True, "sent")
            healed = engine.heal_bitpro_strategy(
                333,
                {
                    "name": "[合约][1H][CTA] KAITO · EMA5/20趋势跟踪激进版 · 100U",
                    "strategy_type": "cta_trend_following",
                    "config": {"fast_window": 5, "slow_window": 20, "hard_stop_loss_pct": "0.04"},
                },
            )

        assert healed is not None
        assert healed.bitpro_deployed is True
        assert healed.bitpro_strategy_id == 999
        assert healed.bitpro_instance_id == "inst_999"
        assert healed.validation_metrics["source"] == "bitpro_backtest"
        assert healed.validation_metrics["win_rate"] == 0.64
        assert healed.validation_metrics["sharpe_ratio"] == 1.82

        # Verify calls to adapter
        mock_adapter.backtest_start_job.assert_called_once()
        mock_adapter.strategy_create.assert_called_once()
        create_kwargs = mock_adapter.strategy_create.call_args.kwargs
        assert "[合约][1H][CTA]" in create_kwargs["name"]
        assert "自愈(Gen 2)" in create_kwargs["name"]
        assert create_kwargs["config"]["_parent_strategy_id"] == 333
        assert create_kwargs["config"]["_evolution_generation"] == 2
        mock_adapter.paper_configure.assert_called_once_with(
            strategy_id=999,
            initial_equity=10000.0,
            exchange="okx",
            idempotency_key="paper_cfg_999",
        )
        mock_adapter.paper_start.assert_called_once_with(
            strategy_id=999,
            idempotency_key="paper_start_999",
        )

        # Verify Feishu alert payload reported real deployment
        mock_alert.assert_called_once()
        alert_payload = mock_alert.call_args[0][0]
        assert "BitPro 真实回测" in alert_payload.evolution_action
        assert "已上线 BitPro 孪生模拟盘 (策略 #999)" in alert_payload.evolution_action


def test_expanded_mutations_across_families() -> None:
    from hypertrade.paper.self_healing import mutate_strategy_parameters

    # 1. Grid
    grid_params, grid_c = mutate_strategy_parameters(
        "grid_trading",
        {"grid_spacing_pct": "0.01", "grid_levels": 10, "stop_loss_pct": "0.05"},
        strategy_name="[合约][15M][网格] BTC · ATR网格 · 100U",
    )
    assert Decimal(grid_params["grid_spacing_pct"]) > Decimal("0.01")
    assert grid_params["grid_levels"] == 8
    assert Decimal(grid_params["stop_loss_pct"]) <= Decimal("0.04")
    assert "widen_grid_spacing_to_absorb_volatility" in grid_c

    # 2. Martingale
    mart_params, mart_c = mutate_strategy_parameters(
        "martingale",
        {"martingale_multiplier": "1.8", "step_pct": "0.02", "max_add_counts": 6},
        strategy_name="[合约][5M][马丁] ETH · 马丁加仓 · 100U",
    )
    assert Decimal(mart_params["martingale_multiplier"]) < Decimal("1.8")
    assert Decimal(mart_params["step_pct"]) > Decimal("0.02")
    assert mart_params["max_add_counts"] <= 4
    assert "reduce_martingale_multiplier_risk" in mart_c

    # 3. Dynamic pool / Basket
    pool_params, pool_c = mutate_strategy_parameters(
        "dynamic_pool",
        {"momentum_window": 14, "rebalance_interval_days": 7, "top_k": 10},
        strategy_name="[现货][1D][轮动] Top20 · 动量轮动 · 1000U",
    )
    assert pool_params["momentum_window"] == 18
    assert pool_params["rebalance_interval_days"] == 9
    assert pool_params["top_k"] == 8
    assert "tighten_basket_momentum_selection_filter" in pool_c

    # 4. Universal numeric fallback
    gen_params, gen_c = mutate_strategy_parameters(
        "unknown_custom_algo",
        {"stop_loss_pct": "0.05", "take_profit_pct": "0.10"},
        strategy_name="Custom Algo",
    )
    assert Decimal(gen_params["stop_loss_pct"]) < Decimal("0.05")
    assert Decimal(gen_params["take_profit_pct"]) > Decimal("0.10")
    assert "tighten_risk_parameters_under_chop" in gen_c


def test_organic_and_self_healed_provenance_suppresses_alarm() -> None:
    from datetime import UTC, datetime

    from hypertrade.arc.evolution import EvolutionConfig
    from hypertrade.arc.evolution_continuation import readiness

    now = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)

    # 1. Organic strategy with provenance gap
    organic_snapshot = {
        "instance_id": "inst_333",
        "strategy_id": 333,
        "strategy_version": "v1",
        "config_version": "c1",
        "status": "running",
        "trade_count": 50,
        "is_organic": True,
        "session": {"started_at": "2026-09-01T00:00:00Z"},
    }
    diagnostic = {
        "status": "stable",
        "attribution_report": {
            "provenance": {
                "status": "unknown",
                "blocking_reasons": ["historical_cost_metadata_missing"],
            }
        },
    }
    state = readiness(organic_snapshot, diagnostic, EvolutionConfig(), now)
    assert state["attention_required"] is False
    assert state["evidence_cursor"].get("is_organic") is True

    # 2. Self healed candidate
    healed_diag = {
        "status": "opportunity",
        "trigger_source": "self_healing_fallback",
        "candidate_id": "333_gen2",
        "attribution_report": {
            "provenance": {
                "status": "unknown",
                "blocking_reasons": ["historical_cost_metadata_missing"],
            }
        },
    }
    healed_state = readiness(organic_snapshot, healed_diag, EvolutionConfig(), now)
    assert healed_state["attention_required"] is False
