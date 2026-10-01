from decimal import Decimal

from hypertrade.paper.allocation import RiskParityAllocator
from hypertrade.paper.models import PaperTicker
from hypertrade.paper.strategies import StrategySignal


def test_risk_parity_inverse_volatility_sizing():
    allocator = RiskParityAllocator(
        max_leverage=Decimal("1.0"),
        max_symbol_notional_pct=Decimal("0.50"),
    )

    tickers = [
        PaperTicker(
            inst_id="BTC-USDT-SWAP",
            last=Decimal("60000"),
            volume_ccy_24h=Decimal("1000000"),
            change_utc0_pct=Decimal("1.5"),  # Low vol
        ),
        PaperTicker(
            inst_id="MEME-USDT-SWAP",
            last=Decimal("1.0"),
            volume_ccy_24h=Decimal("1000000"),
            change_utc0_pct=Decimal("15.0"),  # High vol
        ),
    ]

    signals = [
        StrategySignal(
            strategy_key="rsi_reversal",
            inst_id="BTC-USDT-SWAP",
            side="long",
            conviction=0.8,
            stop_loss_pct=Decimal("0.03"),
            take_profit_pct=Decimal("0.06"),
            reason="btc_long",
        ),
        StrategySignal(
            strategy_key="rsi_reversal",
            inst_id="MEME-USDT-SWAP",
            side="long",
            conviction=0.8,
            stop_loss_pct=Decimal("0.05"),
            take_profit_pct=Decimal("0.10"),
            reason="meme_long",
        ),
    ]

    plan = allocator.allocate(
        equity=Decimal("10000"),
        signals=signals,
        tickers=tickers,
    )

    assert len(plan.targets) == 2
    btc_target = next(t for t in plan.targets if t.inst_id == "BTC-USDT-SWAP")
    meme_target = next(t for t in plan.targets if t.inst_id == "MEME-USDT-SWAP")

    # Inverse volatility: lower vol asset BTC receives higher notional allocation
    assert btc_target.target_notional > meme_target.target_notional
    assert btc_target.volatility_est < meme_target.volatility_est
    assert plan.allocated_notional <= Decimal("10000")


def test_risk_parity_stage_multipliers():
    allocator = RiskParityAllocator()
    tickers = [
        PaperTicker(
            inst_id="BTC-USDT-SWAP",
            last=Decimal("60000"),
            volume_ccy_24h=Decimal("1000000"),
            change_utc0_pct=Decimal("2.0"),
        ),
        PaperTicker(
            inst_id="ETH-USDT-SWAP",
            last=Decimal("3000"),
            volume_ccy_24h=Decimal("1000000"),
            change_utc0_pct=Decimal("2.0"),
        ),
    ]
    signals = [
        StrategySignal(
            strategy_key="canary_strat",
            inst_id="BTC-USDT-SWAP",
            side="long",
            conviction=0.7,
            stop_loss_pct=Decimal("0.03"),
            take_profit_pct=Decimal("0.06"),
            reason="canary",
        ),
        StrategySignal(
            strategy_key="full_live_strat",
            inst_id="ETH-USDT-SWAP",
            side="long",
            conviction=0.7,
            stop_loss_pct=Decimal("0.03"),
            take_profit_pct=Decimal("0.06"),
            reason="full_live",
        ),
    ]

    stage_mults = {
        "canary_strat": 0.25,
        "full_live_strat": 1.0,
    }

    plan = allocator.allocate(
        equity=Decimal("10000"),
        signals=signals,
        tickers=tickers,
        stage_multipliers=stage_mults,
    )

    btc_target = next(t for t in plan.targets if t.inst_id == "BTC-USDT-SWAP")
    eth_target = next(t for t in plan.targets if t.inst_id == "ETH-USDT-SWAP")

    assert eth_target.target_notional > btc_target.target_notional
