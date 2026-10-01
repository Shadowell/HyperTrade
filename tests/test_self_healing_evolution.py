"""Unit tests for SelfHealingEvolutionEngine."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from hypertrade.paper.registry import StrategyRegistry
from hypertrade.paper.self_healing import SelfHealingEvolutionEngine
from hypertrade.paper.stage_gate import StrategyStage


def test_self_healing_evolution_cycle() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"

        registry = StrategyRegistry(storage_path=reg_file)
        engine = SelfHealingEvolutionEngine(registry=registry, history_file=hist_file)

        # Trigger degradation on rsi_reversal
        registry.update_stage(
            "rsi_reversal", StrategyStage.DEGRADED, reason="consecutive losses >= 4"
        )
        assert registry.get("rsi_reversal").stage == StrategyStage.DEGRADED

        # Mock dispatch_reflexion_alert to verify Feishu delivery path
        with patch(
            "hypertrade.paper.self_healing.dispatch_reflexion_alert", return_value=(True, "sent")
        ):
            healed = engine.heal_strategy("rsi_reversal")

        assert healed is not None
        assert healed.parent_strategy_id == "rsi_reversal"
        assert healed.offspring_strategy_id == "rsi_reversal_gen2"
        assert healed.generation == 2
        assert healed.registered is True
        assert healed.feishu_delivered is True
        assert "tighten_stop_loss_under_adverse_momentum" in healed.reflexion_constraints

        # Verify offspring in registry
        offspring_rec = registry.get("rsi_reversal_gen2")
        assert offspring_rec is not None
        assert offspring_rec.stage == StrategyStage.PAPER_OBSERVING
        assert offspring_rec.generation == 2
        assert offspring_rec.parent_strategy_id == "rsi_reversal"

        # Check mutated params: oversold widened from 30 to 25
        assert offspring_rec.parameters["oversold_threshold"] == 25.0

        # Verify history persistence
        history = engine.get_history()
        assert len(history) == 1
        assert history[0].offspring_strategy_id == "rsi_reversal_gen2"


def test_scan_and_heal_all_degraded() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"

        registry = StrategyRegistry(storage_path=reg_file)
        engine = SelfHealingEvolutionEngine(registry=registry, history_file=hist_file)

        # Degrade momentum_breakout_v1
        registry.update_stage(
            "momentum_breakout_v1", StrategyStage.DEGRADED, reason="max drawdown breached"
        )

        with patch(
            "hypertrade.paper.self_healing.dispatch_reflexion_alert",
            return_value=(False, "skipped"),
        ):
            healed_list = engine.scan_and_heal_all_degraded()

        assert len(healed_list) == 1
        assert healed_list[0].parent_strategy_id == "momentum_breakout_v1"
        assert healed_list[0].offspring_strategy_id == "momentum_breakout_v1_gen2"

        # Running scan again should skip because offspring already exists
        second_run = engine.scan_and_heal_all_degraded()
        assert len(second_run) == 0
