from decimal import Decimal

import pytest
from hypertrade.arc.strategy_names import format_bitpro_strategy_name, logic_summary


def test_name_describes_actual_sma_parameters_and_capital():
    summary = logic_summary(
        {
            "family": "ma_crossover",
            "direction": "long_short",
            "tunable_parameters": {"fast_window": 12.0, "slow_window": 48.0},
        }
    )
    assert format_bitpro_strategy_name(
        "BTC/USDT:USDT", "1h", logic_summary=summary, capital_u=Decimal("100.50")
    ) == ("[合约][1H][CTA] BTC · SMA12/48双向趋势 · 100.5U")


def test_composite_indicator_name_does_not_claim_sma_or_remap_asset():
    summary = logic_summary(
        {
            "family": "ema_macd_kdj",
            "direction": "long_only",
            "tunable_parameters": {"fast_window": 5, "slow_window": 20},
        }
    )
    name = format_bitpro_strategy_name("SOL-USDT-SWAP", logic_summary=summary)
    assert name == "[合约][1H][CTA] SOL · EMA5/20+MACD+KDJ多头组合 · 100U"
    assert "OIL" in format_bitpro_strategy_name("OIL-USDT-SWAP")



@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeframe": "7H"},
        {"strategy_type": "trend"},
        {"asset_type": "future"},
        {"capital_u": 0},
        {"capital_u": -1},
        {"capital_u": True},
        {"capital_u": "Infinity"},
        {"capital_u": "NaN"},
        {"capital_u": "bad"},
        {"logic_summary": "ARC-" + "a" * 64},
        {"logic_summary": "cand_probe"},
        {"logic_summary": "ProbeStrategy"},
        {"logic_summary": ""},
        {"logic_summary": "方法 · 注入"},
        {"scope_label": "BTC[CTA]"},
        {"scope_label": ""},
        {"logic_summary": "方法\n换行"},
    ],
)
def test_name_rejects_invalid_protocol_fields(kwargs):
    with pytest.raises(ValueError, match="bitpro_strategy_name_invalid"):
        format_bitpro_strategy_name("BTC-USDT-SWAP", **kwargs)


def test_name_preserves_portfolio_scope_and_decimal_capital():
    assert (
        format_bitpro_strategy_name(
            "BTC-USDT-SWAP", "8h", scope_label="BTC/ETH/SOL等4", capital_u=Decimal("0.5")
        )
        == "[合约][8H][CTA] BTC/ETH/SOL等4 · 策略研究 · 0.5U"
    )
