"""Tests for QuantLab Strategy Transpiler, Matrix Scaffold and Deployment Closed-Loop."""

from __future__ import annotations

import hashlib

import pytest
from hypertrade.paper.registry import StrategyRecord, StrategyRegistry, StrategyStage
from hypertrade.paper.self_healing import SelfHealingEvolutionEngine
from hypertrade.research.quantlab_transpiler import (
    QuantLabStrategyTranspiler,
    TranspiledQuantLabStrategy,
)
from hypertrade.targets.quantlab import QuantLabTargetAdapter

SAMPLE_EVOLUTION_STRATEGY_CODE = """from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class DualMaMomentumStrategy(BaseEvolutionStrategy):
    \"\"\"Dual MA Momentum Strategy for A-Share trend following.\"\"\"

    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features["ma_fast"] = features["close"].rolling(5).mean()
        features["ma_slow"] = features["close"].rolling(20).mean()
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=features.index)
        long_cond = features["ma_fast"] > features["ma_slow"]
        short_cond = features["ma_fast"] < features["ma_slow"]
        signals[long_cond] = 1
        signals[short_cond] = -1
        return signals

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        if signal == 0:
            return Decimal("0.0")
        return Decimal("1.0")
"""


def test_transpiler_transforms_base_evolution_strategy_to_quantlab_matrix() -> None:
    transpiled = QuantLabStrategyTranspiler.transpile_code(
        SAMPLE_EVOLUTION_STRATEGY_CODE,
        strategy_id="ai_dual_ma_trend",
        name="双均线动量趋势",
        market="cn",
        timeframe="1D",
        symbols=["600519.SH", "000858.SZ"],
        parameters={"fast_period": 5, "slow_period": 20},
    )

    assert isinstance(transpiled, TranspiledQuantLabStrategy)
    assert transpiled.strategy_id == "ai_dual_ma_trend"
    assert transpiled.name == "双均线动量趋势"
    assert transpiled.market == "cn"
    assert transpiled.timeframe == "1D"
    assert transpiled.symbols == ("600519.SH", "000858.SZ")

    # Verify embedded scaffold elements required by QuantLab matrix engine
    code = transpiled.code
    assert "META = {" in code
    assert '"execution_backend": "matrix_native"' in code
    assert 'ENTRY_SIGNALS = ["signal_long_entry"]' in code
    assert 'EXIT_SIGNALS = ["signal_long_exit"]' in code
    assert "EXECUTION_BACKEND = \"matrix_native\"" in code
    assert "class BaseEvolutionStrategy(ABC):" in code
    assert "class DualMaMomentumStrategy(BaseEvolutionStrategy):" in code
    assert "class DualMaMomentumStrategyMatrixAdapter(MatrixStrategy):" in code
    assert "MATRIX_STRATEGY = DualMaMomentumStrategyMatrixAdapter()" in code

    # Verify deterministic hash
    expected_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    assert transpiled.code_sha256 == expected_hash


def test_transpiler_preserves_native_quantlab_matrix_strategy() -> None:
    native_code = '''"""Native QuantLab Matrix Strategy."""
META = {
    "id": "native_trend_01",
    "name": "Native Trend",
    "execution_backend": "matrix_native"
}
ENTRY_SIGNALS = ["signal_long_entry"]
EXIT_SIGNALS = ["signal_long_exit"]
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 20
EXECUTION_BACKEND = "matrix_native"

class MockMatrixStrategy:
    pass

MATRIX_STRATEGY = MockMatrixStrategy()
'''
    transpiled = QuantLabStrategyTranspiler.transpile_code(
        native_code,
        strategy_id="native_trend_01",
        name="Native Trend",
    )
    assert transpiled.strategy_id == "native_trend_01"
    assert "MATRIX_STRATEGY" in transpiled.code
    assert transpiled.code_sha256 == hashlib.sha256(transpiled.code.encode("utf-8")).hexdigest()


def test_transpiler_rejects_lookahead_bias() -> None:
    lookahead_code = """from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class LeakyStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        # Negative shift leaks future price!
        features["future_close"] = features["close"].shift(-1)
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(0, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.0")
"""
    with pytest.raises(ValueError, match="transpiler_ast_validation_failed"):
        QuantLabStrategyTranspiler.transpile_code(lookahead_code)


def test_transpiler_rejects_banned_modules() -> None:
    malicious_code = """import os
from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class MaliciousStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(0, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.0")
"""
    with pytest.raises(ValueError, match="transpiler_ast_validation_failed"):
        QuantLabStrategyTranspiler.transpile_code(malicious_code)


def test_transpiler_generates_default_evolution_code() -> None:
    generated_code = QuantLabStrategyTranspiler.generate_default_evolution_code(
        class_name="AdaptiveMaStrategy",
        fast_window=8,
        slow_window=26,
    )
    assert "class AdaptiveMaStrategy(BaseEvolutionStrategy):" in generated_code
    assert ".rolling(8).mean()" in generated_code
    assert ".rolling(26).mean()" in generated_code

    # Verify that the generated code transpiles cleanly into QuantLab format
    transpiled = QuantLabStrategyTranspiler.transpile_code(
        generated_code,
        strategy_id="adaptive_ma_01",
    )
    assert transpiled.strategy_id == "adaptive_ma_01"
    assert "AdaptiveMaStrategyMatrixAdapter" in transpiled.code


def test_quantlab_adapter_deploy_and_run_backtest_with_transpiler() -> None:
    adapter = QuantLabTargetAdapter(simulation=True)

    # 1. Deploy strategy written in BaseEvolutionStrategy format
    deploy_res = adapter.deploy_strategy(
        name="A股趋势跟踪Alpha",
        code=SAMPLE_EVOLUTION_STRATEGY_CODE,
        config={"symbols": ["600519.SH"], "timeframe": "1D", "fast_period": 5, "slow_period": 20},
    )
    assert deploy_res["status"] == "deployed"
    sid = deploy_res["strategy_id"]
    code_hash = deploy_res["code_sha256"]
    assert sid in adapter._strategies
    assert adapter._strategies[sid]["code_sha256"] == code_hash
    # The recorded code in adapter._strategies must be transpiled matrix code
    assert "MATRIX_STRATEGY" in adapter._strategies[sid]["code"]

    # 2. Run backtest with transpiled code
    bt_res = adapter.run_backtest(
        strategy_id=sid,
        strategy_code=SAMPLE_EVOLUTION_STRATEGY_CODE,
        symbols=["600519.SH"],
        timeframe="1D",
        timeout_seconds=5.0,
    )
    assert bt_res["win_rate"] >= 0.40
    assert bt_res["annualized_sharpe"] > 0.0
    assert bt_res["total_trades"] > 0
    assert "job_id" in bt_res


def test_self_healing_quantlab_closed_loop_with_transpiler() -> None:
    registry = StrategyRegistry()
    parent_record = StrategyRecord(
        strategy_id="quantlab_parent_01",
        strategy_type="a_share_trend",
        name="贵州茅台动量趋势",
        description="A股日线动量趋势策略",
        parameters={
            "symbols": ["600519.SH"],
            "timeframe": "1D",
            "fast_window": 5,
            "slow_window": 20,
            "market_target": "quantlab",
            "strategy_code": SAMPLE_EVOLUTION_STRATEGY_CODE,
        },
        stage=StrategyStage.PAPER_OBSERVING,
        generation=1,
    )
    registry.register(parent_record)

    adapter = QuantLabTargetAdapter(simulation=True)
    engine = SelfHealingEvolutionEngine(registry=registry, quantlab_adapter=adapter)

    # Trigger self-healing evolution
    offspring = engine.heal_strategy("quantlab_parent_01")
    assert offspring is not None

    # Offspring record assertions
    offspring_id = offspring.offspring_strategy_id
    assert offspring_id == "quantlab_parent_01_gen2"
    assert offspring.generation == 2
    assert offspring.target_id == "quantlab"
    assert offspring.quantlab_deployed is True
    assert offspring.quantlab_strategy_id is not None
    assert offspring.quantlab_instance_id is not None

    # Verify registered in StrategyRegistry
    rec = registry.get(offspring_id)
    assert rec is not None
    assert rec.stage == StrategyStage.PAPER_OBSERVING
    assert rec.performance_metrics.get("validation_passed") is True
    assert rec.performance_metrics.get("source") == "quantlab_backtest"

    # Verify session active in QuantLab target adapter
    snap = adapter.paper_snapshot(strategy_id=offspring.quantlab_strategy_id)
    assert snap["status"] == "running"
    assert snap["strategy_id"] == offspring.quantlab_strategy_id
    assert snap["instance_id"] == offspring.quantlab_instance_id
