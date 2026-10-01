from decimal import Decimal

from hypertrade.paper.models import PaperTicker
from hypertrade.paper.strategies import (
    MacdTrendExecutionStrategy,
    MomentumBreakoutExecutionStrategy,
    MultiStrategySignalEngine,
    RsiReversalExecutionStrategy,
    StrategySignal,
)


def test_rsi_reversal_execution_strategy_signals():
    strat = RsiReversalExecutionStrategy(
        oversold_threshold=30.0,
        overbought_threshold=70.0,
    )
    tickers = [
        PaperTicker(
            inst_id="BTC-USDT-SWAP",
            last=Decimal("60000"),
            volume_ccy_24h=Decimal("5000000"),
            change_utc0_pct=Decimal("-6.0"),  # Oversold proxy
        ),
        PaperTicker(
            inst_id="ETH-USDT-SWAP",
            last=Decimal("3000"),
            volume_ccy_24h=Decimal("3000000"),
            change_utc0_pct=Decimal("6.0"),  # Overbought proxy
        ),
        PaperTicker(
            inst_id="SOL-USDT-SWAP",
            last=Decimal("150"),
            volume_ccy_24h=Decimal("1000000"),
            change_utc0_pct=Decimal("0.5"),  # Neutral
        ),
    ]

    signals = strat.evaluate(tickers)
    assert len(signals) == 2
    btc_sig = next(s for s in signals if s.inst_id == "BTC-USDT-SWAP")
    assert btc_sig.side == "long"
    assert btc_sig.strategy_key == "rsi_reversal"
    assert btc_sig.conviction >= 0.5

    eth_sig = next(s for s in signals if s.inst_id == "ETH-USDT-SWAP")
    assert eth_sig.side == "short"
    assert eth_sig.strategy_key == "rsi_reversal"


def test_momentum_and_macd_execution_strategies():
    mom = MomentumBreakoutExecutionStrategy(breakout_threshold_pct=Decimal("2.0"))
    macd = MacdTrendExecutionStrategy()

    tickers = [
        PaperTicker(
            inst_id="DOGE-USDT-SWAP",
            last=Decimal("0.15"),
            volume_ccy_24h=Decimal("2000000"),
            change_utc0_pct=Decimal("4.5"),
        )
    ]

    mom_sigs = mom.evaluate(tickers)
    assert len(mom_sigs) == 1
    assert mom_sigs[0].side == "long"
    assert mom_sigs[0].conviction > 0.5

    macd_sigs = macd.evaluate(tickers)
    assert len(macd_sigs) == 1
    assert macd_sigs[0].side == "long"


def test_multi_strategy_arbitration_consensus():
    engine = MultiStrategySignalEngine()
    tickers = [
        PaperTicker(
            inst_id="BTC-USDT-SWAP",
            last=Decimal("62000"),
            volume_ccy_24h=Decimal("10000000"),
            change_utc0_pct=Decimal("4.0"),
        )
    ]

    signals = engine.generate(tickers, max_signals=5)
    assert len(signals) >= 1
    btc_sig = signals[0]
    assert btc_sig.inst_id == "BTC-USDT-SWAP"
    assert btc_sig.side == "long"
    assert btc_sig.conviction > 0.5


def test_multi_strategy_arbitration_conflicting_signals():
    class DummyBullish:
        strategy_key = "dummy_bull"
        enabled = True

        def evaluate(self, tickers, **kwargs):
            return [
                StrategySignal(
                    strategy_key=self.strategy_key,
                    inst_id=tickers[0].inst_id,
                    side="long",
                    conviction=0.90,
                    stop_loss_pct=Decimal("0.03"),
                    take_profit_pct=Decimal("0.06"),
                    reason="strong_bull",
                )
            ]

    class DummyBearish:
        strategy_key = "dummy_bear"
        enabled = True

        def evaluate(self, tickers, **kwargs):
            return [
                StrategySignal(
                    strategy_key=self.strategy_key,
                    inst_id=tickers[0].inst_id,
                    side="short",
                    conviction=0.55,
                    stop_loss_pct=Decimal("0.03"),
                    take_profit_pct=Decimal("0.06"),
                    reason="weak_bear",
                )
            ]

    engine = MultiStrategySignalEngine([DummyBullish(), DummyBearish()])
    ticker = [
        PaperTicker(
            inst_id="ETH-USDT-SWAP",
            last=Decimal("3100"),
            volume_ccy_24h=Decimal("2000000"),
            change_utc0_pct=Decimal("1.0"),
        )
    ]

    signals = engine.generate(ticker)
    assert len(signals) == 1
    assert signals[0].side == "long"
    assert "arbitrated_long_over_short" in signals[0].reason
