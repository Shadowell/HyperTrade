from decimal import Decimal

from hypertrade.backtest.engine import BacktestEngine
from hypertrade.strategy.sdk import Candle


def test_backtest_engine_runs_momentum_breakout_strategy():
    candles = [
        Candle(
            timestamp=f"2026-05-27T00:{index:02d}:00+00:00",
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=Decimal("1000"),
        )
        for index in range(20)
    ]

    result = BacktestEngine().run(
        strategy_key="momentum_breakout_v1",
        candles=candles,
        initial_cash=Decimal("100000"),
    )

    assert result.strategy_key == "momentum_breakout_v1"
    assert result.start_cash == Decimal("100000")
    assert result.end_value > Decimal("100000")
    assert result.total_return_pct > Decimal("0")
    assert result.trade_count >= 1
    assert "momentum_breakout_v1" in result.report_markdown
