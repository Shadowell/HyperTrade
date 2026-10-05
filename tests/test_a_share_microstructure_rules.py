"""Unit tests for China A-Share Market Microstructure Hard Rules & AST Gatekeeper."""

from __future__ import annotations

from datetime import datetime

from hypertrade.research.a_share_rules import (
    AShareMarketRules,
    ASharePromptContext,
    AShareRuleValidator,
)
from hypertrade.research.co_steer import ASTGatekeeper
from hypertrade.research.quantlab_transpiler import QuantLabStrategyTranspiler

VALID_ASHARE_STRATEGY = """from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class SpotMomentumStrategy(BaseEvolutionStrategy):
    \"\"\"Compliant A-share spot strategy (long-only, no shorting).\"\"\"

    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features["ma_fast"] = features["close"].rolling(5).mean()
        features["ma_slow"] = features["close"].rolling(20).mean()
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=features.index)
        long_cond = features["ma_fast"] > features["ma_slow"]
        short_cond = features["ma_fast"] <= features["ma_slow"]
        signals[long_cond] = 1
        signals[short_cond] = 0  # Exit to cash (spot compliant)
        return signals

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        if signal == 1:
            return Decimal("0.80")
        return Decimal("0.0")
"""


INVALID_SHORTING_STRATEGY = """from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class NakedShortStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=features.index)
        signals[features["close"] > 100] = 1
        signals[features["close"] <= 100] = -1  # Illegal naked shorting in A-Shares!
        return signals

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.5")
"""


INVALID_NEGATIVE_POSITION_STRATEGY = """from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class NegativePositionStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        # Negative position sizing is illegal in spot accounts
        return Decimal("-0.50")
"""


def test_ashare_market_rules_defaults() -> None:
    rules = AShareMarketRules()
    assert rules.t_plus_1_settlement is True
    assert rules.long_only_spot is True
    assert rules.allow_naked_short is False
    assert rules.price_limit_main_board == 0.10
    assert rules.price_limit_chinext_star == 0.20
    assert rules.price_limit_st == 0.05
    assert rules.stamp_duty_sell_only == 0.0005
    assert rules.broker_commission_rate == 0.00025
    assert rules.broker_commission_min_cny == 5.0


def test_ashare_prompt_context_rendering() -> None:
    prompt_text = ASharePromptContext.render_prompt_constraints(include_costs=True)
    assert "T+1 交易交收与可用仓位约束" in prompt_text
    assert "现货单向多头限制" in prompt_text
    assert "禁止裸做空" in prompt_text
    assert "±10%" in prompt_text
    assert "±20%" in prompt_text
    assert "0.05%" in prompt_text
    assert "万分之 2.5" in prompt_text


def test_ast_gatekeeper_blocks_negative_signals_for_ashare() -> None:
    # Under market="cn", negative signals must fail AST validation
    result_cn = ASTGatekeeper.validate(INVALID_SHORTING_STRATEGY, market="cn")
    assert result_cn.valid is False
    assert any("A-Share spot constraint violation" in err for err in result_cn.errors)

    # Under market="global" (crypto/futures), shorting is permissible
    result_global = ASTGatekeeper.validate(INVALID_SHORTING_STRATEGY, market="global")
    assert result_global.valid is True


def test_ast_gatekeeper_blocks_negative_position_sizing_for_ashare() -> None:
    result_cn = ASTGatekeeper.validate(INVALID_NEGATIVE_POSITION_STRATEGY, market="cn")
    assert result_cn.valid is False
    assert any("negative position sizing" in err for err in result_cn.errors)

    result_global = ASTGatekeeper.validate(INVALID_NEGATIVE_POSITION_STRATEGY, market="global")
    assert result_global.valid is True


def test_ast_gatekeeper_permits_compliant_ashare_strategy() -> None:
    result = ASTGatekeeper.validate(VALID_ASHARE_STRATEGY, market="cn")
    assert result.valid is True
    assert len(result.errors) == 0


def test_ashare_rule_validator_signals_and_positions() -> None:
    # 1. Compliant signals and positions
    report_ok = AShareRuleValidator.validate_signals_and_positions(
        signals=[1, 0, 1, 0],
        positions=[0.8, 0.0, 0.5, 0.0],
    )
    assert report_ok.valid is True
    assert len(report_ok.violations) == 0

    # 2. Negative signal violation
    report_bad_sig = AShareRuleValidator.validate_signals_and_positions(
        signals=[1, -1, 0],
        positions=[0.5, 0.0, 0.0],
    )
    assert report_bad_sig.valid is False
    assert any("Long-Only Violation" in v for v in report_bad_sig.violations)

    # 3. Negative position violation
    report_bad_pos = AShareRuleValidator.validate_signals_and_positions(
        signals=[1, 0],
        positions=[0.5, -0.2],
    )
    assert report_bad_pos.valid is False
    assert any("Spot Violation" in v for v in report_bad_pos.violations)


def test_ashare_rule_validator_t1_sequence() -> None:
    # Scenario A: Compliant T+1 in position mode: Buy Day 1 (1), Hold Day 1 (1), Sell Day 2 (0)
    ts_ok = [
        datetime(2026, 3, 2, 9, 30),
        datetime(2026, 3, 2, 14, 55),
        datetime(2026, 3, 3, 10, 0),
    ]
    sigs_ok = [1, 1, 0]  # Buy day 1, Hold day 1, Sell day 2
    rep_ok = AShareRuleValidator.validate_t1_sequence(ts_ok, sigs_ok, signal_mode="position")
    assert rep_ok.valid is True

    # Scenario A2: Compliant T+1 in action mode: Buy (1), Hold (0), Sell (-1) on Day 2
    rep_action_ok = AShareRuleValidator.validate_t1_sequence(
        ts_ok, [1, 0, -1], signal_mode="action"
    )
    assert rep_action_ok.valid is True

    # Scenario B: Violation: Buy at 09:30 on Day 1, Sell at 14:00 on same Day 1
    ts_viol = [
        datetime(2026, 3, 2, 9, 30),
        datetime(2026, 3, 2, 14, 0),
    ]
    sigs_viol = [1, 0]  # Buy at 9:30, Sell at 14:00 same day
    rep_viol = AShareRuleValidator.validate_t1_sequence(ts_viol, sigs_viol, signal_mode="position")
    assert rep_viol.valid is False
    assert any("T+1 Settlement Violation" in v for v in rep_viol.violations)


def test_ashare_friction_cost_calculation() -> None:
    res = AShareRuleValidator.calculate_friction_costs(
        buy_turnover=100000.0,
        sell_turnover=100000.0,
        slippage_bps=1.5,
    )
    # Stamp duty: 100000 * 0.0005 = 50.0
    assert res["stamp_duty"] == 50.0
    # Transfer fee: 200000 * 0.00001 = 2.0
    assert res["transfer_fee"] == 2.0
    # Commission: 25.0 buy + 25.0 sell = 50.0
    assert res["commission"] == 50.0
    # Slippage: 200000 * 0.00015 = 30.0
    assert res["slippage_cost"] == 30.0
    # Total friction
    assert res["total_friction"] > 130.0
    assert res["effective_friction_bps"] > 6.0


def test_quantlab_transpiler_default_ashare_code() -> None:
    code = QuantLabStrategyTranspiler.generate_default_evolution_code(
        class_name="AshareMaTrend",
        fast_window=8,
        slow_window=25,
        market="cn",
    )
    assert "signals[short_cond] = 0" in code
    assert "-1" not in code

    # Validate AST Gatekeeper
    ast_res = ASTGatekeeper.validate(code, market="cn")
    assert ast_res.valid is True

    # Transpile to QuantLab Matrix Module
    transpiled = QuantLabStrategyTranspiler.transpile_code(
        code,
        strategy_id="ashare_ma_trend_01",
        market="cn",
    )
    assert transpiled.strategy_id == "ashare_ma_trend_01"
    assert "AshareMaTrendMatrixAdapter" in transpiled.code
    assert "MATRIX_STRATEGY" in transpiled.code
