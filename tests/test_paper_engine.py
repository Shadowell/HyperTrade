from decimal import Decimal

from hypertrade.paper.engine import PaperExecutionEngine, PaperSignalEngine
from hypertrade.paper.models import PaperTicker


def test_signal_engine_picks_positive_and_negative_movers():
    tickers = [
        PaperTicker("AAA-USDT-SWAP", Decimal("10"), Decimal("1000"), Decimal("4.2")),
        PaperTicker("BBB-USDT-SWAP", Decimal("20"), Decimal("900"), Decimal("-4.5")),
        PaperTicker("CCC-USDT-SWAP", Decimal("30"), Decimal("800"), Decimal("1.0")),
    ]

    signals = PaperSignalEngine().generate(tickers, max_signals=10)

    assert [(signal.inst_id, signal.side) for signal in signals] == [
        ("BBB-USDT-SWAP", "short"),
        ("AAA-USDT-SWAP", "long"),
    ]


def test_execution_engine_applies_fee_and_slippage():
    fill = PaperExecutionEngine(
        taker_fee_bps=Decimal("5"),
        slippage_bps=Decimal("2"),
    ).simulate_fill(
        inst_id="AAA-USDT-SWAP",
        side="long",
        target_notional=Decimal("1000"),
        last_price=Decimal("10"),
    )

    assert fill.price == Decimal("10.002000000000")
    assert fill.quantity == Decimal("99.980003999200")
    assert fill.fee == Decimal("0.500000000000")


def test_execution_engine_improves_short_fill_for_slippage_model():
    fill = PaperExecutionEngine(
        taker_fee_bps=Decimal("5"),
        slippage_bps=Decimal("2"),
    ).simulate_fill(
        inst_id="BBB-USDT-SWAP",
        side="short",
        target_notional=Decimal("1000"),
        last_price=Decimal("20"),
    )

    assert fill.price == Decimal("19.996000000000")
    assert fill.fee == Decimal("0.500000000000")
