"""Unit tests for StrategyRecord, StrategyFactory, and StrategyRegistry."""

import tempfile
from decimal import Decimal
from pathlib import Path

from hypertrade.paper.models import PaperTicker
from hypertrade.paper.registry import StrategyFactory, StrategyRecord, StrategyRegistry
from hypertrade.paper.stage_gate import StrategyStage
from hypertrade.paper.strategies import (
    FallbackUtc0Strategy,
    MacdTrendExecutionStrategy,
    MomentumBreakoutExecutionStrategy,
    MultiStrategySignalEngine,
    RsiReversalExecutionStrategy,
)


def test_strategy_record_serialization() -> None:
    record = StrategyRecord(
        strategy_id="test_rsi_v1",
        strategy_type="rsi_reversal",
        name="Test RSI Reversal",
        description="Testing serialization",
        parameters={"rsi_period": 14, "oversold_threshold": 28.0, "overbought_threshold": 72.0},
        stage=StrategyStage.PAPER_OBSERVING,
        generation=2,
        parent_strategy_id="rsi_reversal",
        reflexion_constraints=["tighten_stop_loss"],
        performance_metrics={"win_rate": 0.65},
    )
    d = record.to_dict()
    assert d["strategy_id"] == "test_rsi_v1"
    assert d["stage"] == "paper_observing"
    assert d["generation"] == 2
    assert d["reflexion_constraints"] == ["tighten_stop_loss"]

    reloaded = StrategyRecord.from_dict(d)
    assert reloaded.strategy_id == "test_rsi_v1"
    assert reloaded.stage == StrategyStage.PAPER_OBSERVING
    assert reloaded.parameters["rsi_period"] == 14
    assert reloaded.generation == 2
    assert reloaded.parent_strategy_id == "rsi_reversal"


def test_strategy_factory_instantiation() -> None:
    rec_rsi = StrategyRecord(
        strategy_id="rsi_test",
        strategy_type="rsi_reversal",
        name="RSI Test",
        parameters={"rsi_period": 10, "oversold_threshold": 25.0, "overbought_threshold": 75.0},
    )
    strat_rsi = StrategyFactory.build(rec_rsi)
    assert isinstance(strat_rsi, RsiReversalExecutionStrategy)
    assert strat_rsi.strategy_key == "rsi_test"
    assert strat_rsi.rsi_period == 10
    assert strat_rsi.oversold_threshold == 25.0

    rec_mom = StrategyRecord(
        strategy_id="mom_test",
        strategy_type="momentum_breakout",
        name="Mom Test",
        parameters={"breakout_threshold_pct": "3.5"},
    )
    strat_mom = StrategyFactory.build(rec_mom)
    assert isinstance(strat_mom, MomentumBreakoutExecutionStrategy)
    assert strat_mom.strategy_key == "mom_test"
    assert strat_mom.breakout_threshold_pct == Decimal("3.5")

    rec_macd = StrategyRecord(
        strategy_id="macd_test",
        strategy_type="macd_trend",
        name="MACD Test",
        parameters={"fast_period": 8, "slow_period": 21, "signal_period": 5},
    )
    strat_macd = StrategyFactory.build(rec_macd)
    assert isinstance(strat_macd, MacdTrendExecutionStrategy)
    assert strat_macd.fast_period == 8

    rec_utc = StrategyRecord(
        strategy_id="utc_test",
        strategy_type="utc0_momentum",
        name="UTC Test",
        parameters={"threshold_pct": "4.0"},
    )
    strat_utc = StrategyFactory.build(rec_utc)
    assert isinstance(strat_utc, FallbackUtc0Strategy)
    assert strat_utc.threshold_pct == Decimal("4.0")


def test_strategy_registry_lifecycle_and_engine_integration() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_file = Path(tmpdir) / "registry.json"
        registry = StrategyRegistry(storage_path=storage_file)

        # Pre-populated defaults
        all_records = registry.list_all()
        assert len(all_records) == 4
        assert any(r.strategy_id == "rsi_reversal" for r in all_records)

        # Register new evolved generation
        gen2 = StrategyRecord(
            strategy_id="rsi_reversal_gen2",
            strategy_type="rsi_reversal",
            name="RSI Mean Reversion Gen 2",
            parameters={"rsi_period": 14, "oversold_threshold": 25.0, "overbought_threshold": 75.0},
            stage=StrategyStage.PAPER_OBSERVING,
            generation=2,
            parent_strategy_id="rsi_reversal",
        )
        registry.register(gen2)
        assert len(registry.list_all()) == 5
        assert registry.get("rsi_reversal_gen2") is not None

        # Build active execution strategies
        active = registry.build_active_strategies()
        assert len(active) == 5

        # Degrade a strategy
        registry.update_stage(
            "rsi_reversal", StrategyStage.DEGRADED, reason="circuit breaker drawdown"
        )
        active_after_degrade = registry.build_active_strategies()
        assert len(active_after_degrade) == 4
        assert not any(s.strategy_key == "rsi_reversal" for s in active_after_degrade)

        # Dynamic integration with MultiStrategySignalEngine
        engine = MultiStrategySignalEngine(registry=registry)
        assert len(engine.strategies()) == 4

        # Add Gen 3 strategy dynamically into registry
        gen3 = StrategyRecord(
            strategy_id="rsi_reversal_gen3",
            strategy_type="rsi_reversal",
            name="RSI Mean Reversion Gen 3",
            parameters={"rsi_period": 14, "oversold_threshold": 20.0, "overbought_threshold": 80.0},
            stage=StrategyStage.PAPER_OBSERVING,
            generation=3,
        )
        registry.register(gen3)

        # Engine automatically sees Gen 3 on next access / generation
        assert len(engine.strategies()) == 5
        assert any(s.strategy_key == "rsi_reversal_gen3" for s in engine.strategies())

        # Test signal generation
        test_ticker = PaperTicker(
            inst_id="ETH-USDT-SWAP",
            last=Decimal("3000.0"),
            change_utc0_pct=Decimal("5.0"),
            volume_ccy_24h=Decimal("1000000.0"),
        )
        signals = engine.generate([test_ticker])
        assert len(signals) >= 1
