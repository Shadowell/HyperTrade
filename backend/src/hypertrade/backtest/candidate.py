"""Bar-replay evaluation of codegen-produced strategy candidates.

`BacktestEngine` can only run one hand-written Backtrader strategy and raises `KeyError`
for anything else, so a compiled candidate had no way to be measured on historical data
at all. Everything downstream — the adversarial gate, the reflexion ledger, the paper
incubation decision — was therefore judging candidates by their declared parameters
rather than by what they did on a price series.

This module closes that gap for the code the research codegen emits. It is a research
simulator, not an execution venue: fills are at the bar close plus a fixed slippage
allowance, one position per symbol, and no partial fills or funding. Its purpose is to
produce comparable evidence across candidates, and its assumptions are recorded on the
result so a report can state what the numbers do and do not account for.

Production boundary: only source that passes the same static gate as the generator is
executed. The gate forbids network, filesystem, subprocess, dynamic evaluation and
secret access, and the loader re-checks it rather than trusting the caller, because this
is the one place in the research path that runs generated code.
"""

from __future__ import annotations

import ast
import asyncio
import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from hypertrade.research.codegen import static_code_rejections

# The BitPro runtime module a compiled candidate imports. It does not exist locally, so
# the loader swaps in a shim exposing the same surface the generated body uses.
_BITPRO_BASE_MODULE = "app.core.execution.base_strategy"

# Bars per year for the timeframes research mandates use, so Sharpe is comparable
# across candidates evaluated on different bar sizes.
_BARS_PER_YEAR: dict[str, float] = {
    "1M": 525_600.0,
    "5M": 105_120.0,
    "15M": 35_040.0,
    "30M": 17_520.0,
    "1H": 8_760.0,
    "4H": 2_190.0,
    "1D": 365.0,
}
_DEFAULT_BARS_PER_YEAR = _BARS_PER_YEAR["1H"]


class CandidateBacktestError(RuntimeError):
    """Raised when candidate source cannot be loaded or replayed."""


@dataclass(frozen=True)
class Bar:
    """One OHLCV observation, in the shape the generated `on_bar` reads."""

    symbol: str
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class BacktestCosts:
    """Friction applied to every fill. Defaults are taker-side crypto swap levels."""

    fee_rate: float = 0.0005
    slippage_rate: float = 0.0002


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: str
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    notional: float
    leverage: float
    pnl: float


@dataclass(frozen=True)
class CandidateBacktestResult:
    """What a candidate did on the series, plus the assumptions behind the numbers."""

    class_name: str
    bars: int
    trades: tuple[Trade, ...]
    starting_equity: float
    ending_equity: float
    total_return: float
    sharpe: float
    max_drawdown: float
    turnover: float
    exposure: float
    fees_paid: float
    equity_curve: tuple[float, ...]
    assumptions: Mapping[str, Any] = field(default_factory=dict)

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def is_inert(self) -> bool:
        """No trade means no evidence. A gate that reads only Sharpe would score an
        inert candidate as flawless, so callers need this distinguished explicitly."""
        return not self.trades


class _Position:
    __slots__ = ("side", "entry_price", "notional", "leverage", "entry_timestamp")

    def __init__(
        self, side: str, entry_price: float, notional: float, leverage: float, timestamp: str
    ) -> None:
        self.side = side
        self.entry_price = entry_price
        self.notional = notional
        self.leverage = leverage
        self.entry_timestamp = timestamp

    def unrealized(self, mark: float) -> float:
        if self.entry_price <= 0.0:
            return 0.0
        edge = (mark - self.entry_price) / self.entry_price
        if self.side == "short":
            edge = -edge
        return edge * self.notional * self.leverage


class _SimulatedVenue:
    """Records the strategy's intents and marks them against the replayed series."""

    def __init__(self, starting_equity: float, costs: BacktestCosts) -> None:
        self.cash = starting_equity
        self.costs = costs
        self.positions: dict[str, _Position] = {}
        self.trades: list[Trade] = []
        self.fees_paid = 0.0
        self.gross_notional = 0.0
        self.marks: dict[str, float] = {}
        self.timestamp = ""

    def _charge(self, notional: float, leverage: float) -> None:
        exposure = notional * leverage
        cost = exposure * (self.costs.fee_rate + self.costs.slippage_rate)
        self.fees_paid += cost
        self.cash -= cost
        self.gross_notional += exposure

    def open_position(self, symbol: str, side: str, notional: float, leverage: float) -> None:
        # One position per symbol: a repeated entry is ignored rather than averaged, so
        # a candidate cannot accumulate unbounded exposure through a signal that fires
        # on consecutive bars.
        if symbol in self.positions or notional <= 0.0:
            return
        mark = self.marks.get(symbol, 0.0)
        if mark <= 0.0:
            return
        self._charge(notional, leverage)
        self.positions[symbol] = _Position(side, mark, notional, leverage, self.timestamp)

    def close_position(self, symbol: str, side: str | None = None) -> None:
        position = self.positions.get(symbol)
        if position is None:
            return
        if side is not None and side != position.side:
            return
        mark = self.marks.get(symbol, position.entry_price)
        pnl = position.unrealized(mark)
        self._charge(position.notional, position.leverage)
        self.cash += pnl
        self.trades.append(
            Trade(
                symbol=symbol,
                side=position.side,
                entry_timestamp=position.entry_timestamp,
                exit_timestamp=self.timestamp,
                entry_price=position.entry_price,
                exit_price=mark,
                notional=position.notional,
                leverage=position.leverage,
                pnl=pnl,
            )
        )
        del self.positions[symbol]

    def equity(self) -> float:
        open_pnl = sum(
            position.unrealized(self.marks.get(symbol, position.entry_price))
            for symbol, position in self.positions.items()
        )
        return self.cash + open_pnl


class SimulatedStrategyRuntime:
    """The surface a compiled candidate is written against, backed by the simulator.

    Deliberately narrow: a candidate that reaches for anything beyond declaring
    intent fails at load rather than silently doing something unaudited here.
    """

    def __init__(self, config: Mapping[str, Any], symbols: Sequence[str], venue: _SimulatedVenue):
        self.config = dict(config)
        self._symbols = tuple(symbols)
        self._venue = venue

    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    async def on_init(self) -> None:  # pragma: no cover - overridden by generated code
        return None

    async def on_bar(self, bar: Bar) -> None:  # pragma: no cover - overridden
        return None

    async def open_contract(
        self, symbol: str, side: str, notional: float, leverage: float = 1.0
    ) -> None:
        self._venue.open_position(symbol, side, float(notional), float(leverage))

    async def close_contract(self, symbol: str, side: str | None = None) -> None:
        self._venue.close_position(symbol, side)


def load_candidate_class(code: str) -> type[SimulatedStrategyRuntime]:
    """Load the candidate's strategy class against the simulator runtime.

    The BitPro base-class import is rewritten rather than installed, so the candidate
    that runs here is byte-identical to the one the ledger fingerprinted apart from
    where its base class comes from.
    """
    rejections = static_code_rejections(code)
    if rejections:
        raise CandidateBacktestError(f"candidate_rejected_by_static_gate:{','.join(rejections)}")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise CandidateBacktestError(f"candidate_syntax_error:{exc.lineno}") from exc

    tree.body = [
        node
        for node in tree.body
        if not (isinstance(node, ast.ImportFrom) and node.module == _BITPRO_BASE_MODULE)
    ]
    namespace: dict[str, Any] = {"BaseStrategy": SimulatedStrategyRuntime, "deque": deque}
    exec(compile(tree, filename="<candidate>", mode="exec"), namespace)  # noqa: S102

    classes = [
        value
        for key, value in namespace.items()
        if isinstance(value, type)
        and issubclass(value, SimulatedStrategyRuntime)
        and value is not SimulatedStrategyRuntime
        and not key.startswith("_")
    ]
    if len(classes) != 1:
        raise CandidateBacktestError(f"expected_one_strategy_class_found:{len(classes)}")
    return classes[0]


def replay_candidate(
    code: str,
    bars: Sequence[Bar],
    *,
    parameters: Mapping[str, float] | None = None,
    symbols: Sequence[str] | None = None,
    starting_equity: float = 10_000.0,
    trade_notional_usdt: float = 1_000.0,
    leverage: float = 2.0,
    timeframe: str = "1H",
    costs: BacktestCosts | None = None,
) -> CandidateBacktestResult:
    """Replay `bars` through the candidate and report what it actually did.

    Bars are delivered in the order given; the caller owns the data window, which is
    what lets one series be split into in-sample and out-of-sample halves without the
    candidate being able to tell the difference.
    """
    if not bars:
        raise CandidateBacktestError("no_bars_supplied")
    costs = costs or BacktestCosts()
    resolved_symbols = tuple(symbols or dict.fromkeys(bar.symbol for bar in bars))
    venue = _SimulatedVenue(starting_equity, costs)
    strategy_class = load_candidate_class(code)
    strategy = strategy_class(
        {
            "research_parameters": dict(parameters or {}),
            "trade_notional_usdt": trade_notional_usdt,
            "leverage": leverage,
        },
        resolved_symbols,
        venue,
    )

    equity_curve: list[float] = []

    async def run() -> None:
        await strategy.on_init()
        for bar in bars:
            venue.timestamp = bar.timestamp
            venue.marks[bar.symbol] = bar.close
            await strategy.on_bar(bar)
            equity_curve.append(venue.equity())
        # Mark the book flat at the final bar so an open position's paper gain is
        # realised under the same friction as any other exit. Leaving it open would
        # let a candidate bank a favourable final mark it never paid to close.
        for symbol in list(venue.positions):
            venue.close_position(symbol)
        equity_curve.append(venue.equity())

    asyncio.run(run())

    exposure_bars = sum(1 for value in _position_bars(bars, venue) if value)
    ending_equity = equity_curve[-1]
    return CandidateBacktestResult(
        class_name=strategy_class.__name__,
        bars=len(bars),
        trades=tuple(venue.trades),
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        total_return=(ending_equity - starting_equity) / starting_equity,
        sharpe=_sharpe(equity_curve, timeframe),
        max_drawdown=_max_drawdown(equity_curve),
        turnover=venue.gross_notional / starting_equity if starting_equity > 0 else 0.0,
        exposure=exposure_bars / len(bars) if bars else 0.0,
        fees_paid=venue.fees_paid,
        equity_curve=tuple(equity_curve),
        assumptions={
            "fill": "bar_close_plus_slippage",
            "fee_rate": costs.fee_rate,
            "slippage_rate": costs.slippage_rate,
            "funding_modelled": False,
            "partial_fills_modelled": False,
            "one_position_per_symbol": True,
            "timeframe": timeframe,
            "leverage": leverage,
            "trade_notional_usdt": trade_notional_usdt,
        },
    )


def _position_bars(bars: Sequence[Bar], venue: _SimulatedVenue) -> list[bool]:
    """Reconstruct which bars were spent holding, from the closed trade log."""
    held = [False] * len(bars)
    index_by_timestamp: dict[str, int] = {}
    for index, bar in enumerate(bars):
        index_by_timestamp.setdefault(bar.timestamp, index)
    for trade in venue.trades:
        start = index_by_timestamp.get(trade.entry_timestamp)
        end = index_by_timestamp.get(trade.exit_timestamp)
        if start is None or end is None:
            continue
        for index in range(start, min(end + 1, len(held))):
            held[index] = True
    return held


def _sharpe(equity_curve: Sequence[float], timeframe: str) -> float:
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    deviation = math.sqrt(variance)
    if deviation <= 0.0:
        return 0.0
    periods = _BARS_PER_YEAR.get(timeframe.upper(), _DEFAULT_BARS_PER_YEAR)
    return (mean / deviation) * math.sqrt(periods)


def _max_drawdown(equity_curve: Sequence[float]) -> float:
    peak = equity_curve[0] if equity_curve else 0.0
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def bars_from_candles(symbol: str, candles: Sequence[Any]) -> tuple[Bar, ...]:
    """Adapt the market-data `Candle` shape onto the simulator's bar."""
    return tuple(
        Bar(
            symbol=symbol,
            timestamp=str(candle.timestamp),
            open=_as_float(candle.open),
            high=_as_float(candle.high),
            low=_as_float(candle.low),
            close=_as_float(candle.close),
            volume=_as_float(getattr(candle, "volume", 0)),
        )
        for candle in candles
    )


def _as_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value)
