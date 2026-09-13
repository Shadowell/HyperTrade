from decimal import Decimal

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
