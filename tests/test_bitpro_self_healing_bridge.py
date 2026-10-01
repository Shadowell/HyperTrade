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
