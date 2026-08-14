"""Bar-replay evaluation of compiled research candidates.

`BacktestEngine` raises `KeyError` for any strategy key other than the one hand-written
demo, so compiled candidates had never been measured on a price series. Everything
downstream judged them by their declared parameters instead.
"""

import random

import pytest
from hypertrade.backtest.candidate import (
    BacktestCosts,
    Bar,
    CandidateBacktestError,
    bars_from_candles,
    load_candidate_class,
    replay_candidate,
)
from hypertrade.research.codegen import FAMILIES, generate_strategy


def _spec(**overrides):
    spec = {
        "schema_version": "research_strategy_spec.v1",
        "strategy_key": "replay_probe",
        "hypothesis": "快慢均线金叉确认趋势",
        "entry_logic": "快线上穿慢线",
        "exit_logic": "快线下穿慢线",
        "risk_conditions": ["stop loss"],
    }
    spec.update(overrides)
    return spec


def _trend_bars(count: int = 200, turn_at: int = 120) -> list[Bar]:
    """A clean up-then-down ramp, so a trend follower has an unambiguous outcome."""
    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        price *= 1.004 if index < turn_at else 0.997
        bars.append(
            Bar(
                symbol="BTC-USDT-SWAP",
                timestamp=f"2026-01-01T{index:04d}",
                open=price,
                high=price * 1.001,
                low=price * 0.999,
                close=price,
                volume=10.0,
            )
        )
    return bars


def _random_walk_bars(count: int = 400, seed: int = 11) -> list[Bar]:
    rnd = random.Random(seed)
    bars: list[Bar] = []
    price = 100.0
    for index in range(count):
        price *= 1.0 + rnd.gauss(0.0005, 0.012)
        bars.append(
            Bar(
                symbol="BTC-USDT-SWAP",
                timestamp=f"2026-01-01T{index:04d}",
                open=price,
                high=price * (1 + abs(rnd.gauss(0, 0.004))),
                low=price * (1 - abs(rnd.gauss(0, 0.004))),
                close=price,
                volume=10.0,
            )
        )
    return bars


def test_compiled_candidate_actually_trades_a_price_series():
    generated = generate_strategy(_spec())
    result = replay_candidate(
        generated.code, _trend_bars(), parameters=generated.tunable_parameters
    )

    assert result.class_name == generated.class_name
    assert not result.is_inert
    # A trend follower on an up-then-down ramp must ride the up leg and leave on the turn.
    assert result.trade_count == 1
    trade = result.trades[0]
    assert trade.side == "long"
    assert trade.pnl > 0
    assert result.total_return > 0
    assert 0.0 < result.exposure < 1.0
    assert result.fees_paid > 0


def test_every_family_and_direction_is_executable():
    """Codegen may emit a body no runtime can actually replay; each family is checked."""
    bars = _random_walk_bars()
    outcomes = {}
    for family in FAMILIES:
        for hint in ("仅做多", "多空双向"):
            generated = generate_strategy(
                _spec(
                    strategy_key=f"replay_{family.key}",
                    family_key=family.key,
                    hypothesis=hint,
                    entry_logic=hint,
                )
            )
            result = replay_candidate(
                generated.code, bars, parameters=generated.tunable_parameters
            )
            outcomes[(family.key, generated.direction)] = result
            assert result.bars == len(bars)
            assert result.trade_count > 0, f"{family.key} never traded"
            assert 0.0 <= result.max_drawdown < 1.0

    # A bidirectional variant must be able to hold through both legs, so it cannot be
    # indistinguishable from its long-only sibling.
    for family in FAMILIES:
        long_only = outcomes.get((family.key, "long_only"))
        both = outcomes.get((family.key, "long_short"))
        if long_only and both:
            assert both.exposure >= long_only.exposure


def test_replay_is_deterministic():
    """The ledger compares candidates across runs, so replay cannot drift."""
    generated = generate_strategy(_spec())
    bars = _random_walk_bars()
    first = replay_candidate(generated.code, bars, parameters=generated.tunable_parameters)
    second = replay_candidate(generated.code, bars, parameters=generated.tunable_parameters)
    assert first.equity_curve == second.equity_curve
    assert first.sharpe == second.sharpe


def test_parameters_change_the_outcome():
    """A knob the replay ignores would make the whole sensitivity matrix meaningless."""
    generated = generate_strategy(_spec())
    bars = _random_walk_bars()
    slow = replay_candidate(
        generated.code, bars, parameters={**generated.tunable_parameters, "fast_window": 5}
    )
    slower = replay_candidate(
        generated.code, bars, parameters={**generated.tunable_parameters, "fast_window": 20}
    )
    assert slow.equity_curve != slower.equity_curve


def test_friction_erodes_a_high_turnover_candidate():
    generated = generate_strategy(_spec())
    bars = _random_walk_bars()
    free = replay_candidate(
        generated.code,
        bars,
        parameters=generated.tunable_parameters,
        costs=BacktestCosts(fee_rate=0.0, slippage_rate=0.0),
    )
    costly = replay_candidate(
        generated.code,
        bars,
        parameters=generated.tunable_parameters,
        costs=BacktestCosts(fee_rate=0.002, slippage_rate=0.001),
    )
    assert costly.fees_paid > free.fees_paid
    assert costly.total_return < free.total_return


def test_open_position_is_marked_flat_at_the_end():
    """An open book at the last bar must pay to exit like any other trade."""
    generated = generate_strategy(_spec())
    # Pure uptrend: a trend follower is still long when the series runs out.
    result = replay_candidate(
        generated.code,
        _trend_bars(turn_at=10_000),
        parameters=generated.tunable_parameters,
    )
    assert result.trade_count == 1
    assert result.trades[0].exit_timestamp == "2026-01-01T0199"


def test_a_stop_loss_that_never_arms_cannot_be_confused_with_one_that_holds():
    """Risk overlays must actually fire during replay, not just appear in the source."""
    generated = generate_strategy(_spec(hypothesis="均线金叉", risk_conditions=["stop loss"]))
    bars = _random_walk_bars(seed=3)
    tight = replay_candidate(
        generated.code, bars, parameters={**generated.tunable_parameters, "stop_loss": 0.01}
    )
    loose = replay_candidate(
        generated.code, bars, parameters={**generated.tunable_parameters, "stop_loss": 0.45}
    )
    def stopped_out(result, threshold: float) -> int:
        stops = 0
        for trade in result.trades:
            edge = (trade.exit_price - trade.entry_price) / trade.entry_price
            if trade.side == "short":
                edge = -edge
            if edge <= -threshold:
                stops += 1
        return stops

    # The tight stop must actually fire and cut positions; the loose one never arms, so
    # it holds through the same dips.
    assert tight.trade_count > loose.trade_count
    assert stopped_out(tight, 0.01) > 0
    assert stopped_out(loose, 0.45) == 0


def test_source_failing_the_static_gate_is_never_executed():
    """This is the one place the research path runs generated code."""
    with pytest.raises(CandidateBacktestError, match="static_gate"):
        load_candidate_class(
            "import socket\n"
            "from app.core.execution.base_strategy import BaseStrategy\n"
            "class Bad(BaseStrategy):\n    pass\n"
        )


def test_ambiguous_and_malformed_sources_are_rejected_before_execution():
    """The shared static gate catches both, so neither reaches `exec`."""
    with pytest.raises(CandidateBacktestError, match="static_gate"):
        load_candidate_class("class Broken(:\n")
    with pytest.raises(CandidateBacktestError, match="single_basestrategy_subclass"):
        load_candidate_class(
            "from app.core.execution.base_strategy import BaseStrategy\n"
            "class A(BaseStrategy):\n    pass\n"
            "class B(BaseStrategy):\n    pass\n"
        )


def test_empty_series_is_rejected_rather_than_scored_as_flawless():
    generated = generate_strategy(_spec())
    with pytest.raises(CandidateBacktestError, match="no_bars_supplied"):
        replay_candidate(generated.code, [])


def test_candles_adapt_onto_the_simulator_bar():
    from decimal import Decimal

    from hypertrade.strategy.sdk import Candle

    candles = [
        Candle(
            timestamp="2026-01-01T00:00:00",
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("12"),
        )
    ]
    bars = bars_from_candles("ETH-USDT-SWAP", candles)
    assert bars[0].symbol == "ETH-USDT-SWAP"
    assert bars[0].close == 100.5
    assert bars[0].volume == 12.0
