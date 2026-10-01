"""Multi-strategy dynamic signal engine and production execution strategies.

Supports pluggable ExecutionStrategy protocols, conflict arbitration across
concurrent strategies, and dynamic bracket order parameter estimation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from hypertrade.paper.models import PaperTicker

MONEY_QUANT = Decimal("0.000000000001")


@dataclass(frozen=True)
class StrategySignal:
    """Standardized trading signal emitted by an ExecutionStrategy."""

    strategy_key: str
    inst_id: str
    side: str  # "long" or "short"
    conviction: float  # 0.0 to 1.0
    stop_loss_pct: Decimal  # e.g. Decimal("0.04") = 4% stop loss
    take_profit_pct: Decimal  # e.g. Decimal("0.08") = 8% take profit
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExecutionStrategy(Protocol):
    """Protocol for strategies executing against live market data."""

    strategy_key: str
    enabled: bool

    def evaluate(
        self,
        tickers: list[PaperTicker],
        *,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[StrategySignal]:
        """Evaluate market data and return actionable signals."""
        ...


class FallbackUtc0Strategy:
    """Preserves legacy UTC-0 momentum threshold behavior as a baseline strategy."""

    def __init__(self, *, threshold_pct: Decimal = Decimal("3.0"), enabled: bool = True) -> None:
        self.strategy_key = "utc0_momentum_legacy"
        self.threshold_pct = threshold_pct
        self.enabled = enabled

    def evaluate(
        self,
        tickers: list[PaperTicker],
        *,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[StrategySignal]:
        if not self.enabled:
            return []
        signals: list[StrategySignal] = []
        for ticker in tickers:
            if ticker.last <= 0 or ticker.volume_ccy_24h <= 0:
                continue
            if ticker.change_utc0_pct >= self.threshold_pct:
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="long",
                        conviction=min(1.0, float(ticker.change_utc0_pct / Decimal("10"))),
                        stop_loss_pct=Decimal("0.035"),
                        take_profit_pct=Decimal("0.070"),
                        reason="utc0_change_positive",
                        metadata={"change_utc0_pct": str(ticker.change_utc0_pct)},
                    )
                )
            elif ticker.change_utc0_pct <= -self.threshold_pct:
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="short",
                        conviction=min(1.0, float(abs(ticker.change_utc0_pct) / Decimal("10"))),
                        stop_loss_pct=Decimal("0.035"),
                        take_profit_pct=Decimal("0.070"),
                        reason="utc0_change_negative",
                        metadata={"change_utc0_pct": str(ticker.change_utc0_pct)},
                    )
                )
        return signals


class RsiReversalExecutionStrategy:
    """Adaptive RSI mean-reversion execution strategy.

    Emits counter-trend signals when RSI penetrates oversold/overbought boundaries.
    """

    def __init__(
        self,
        *,
        strategy_key: str = "rsi_reversal",
        rsi_period: int = 14,
        oversold_threshold: float = 30.0,
        overbought_threshold: float = 70.0,
        stop_loss_pct: Decimal = Decimal("0.04"),
        take_profit_pct: Decimal = Decimal("0.08"),
        enabled: bool = True,
    ) -> None:
        self.strategy_key = strategy_key
        self.rsi_period = rsi_period
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.enabled = enabled

    def evaluate(
        self,
        tickers: list[PaperTicker],
        *,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[StrategySignal]:
        if not self.enabled:
            return []
        signals: list[StrategySignal] = []
        for ticker in tickers:
            if ticker.last <= 0 or ticker.volume_ccy_24h <= 0:
                continue

            rsi_value: float | None = None
            if klines_by_symbol and ticker.inst_id in klines_by_symbol:
                closes = [
                    float(k.get("close", 0))
                    for k in klines_by_symbol[ticker.inst_id]
                    if float(k.get("close", 0)) > 0
                ]
                if len(closes) >= self.rsi_period + 1:
                    rsi_value = _compute_rsi(closes, self.rsi_period)

            # Fallback estimation from change_utc0_pct if klines not provided
            if rsi_value is None:
                rsi_value = 50.0 + float(ticker.change_utc0_pct) * 4.0
                rsi_value = max(5.0, min(95.0, rsi_value))

            if rsi_value <= self.oversold_threshold:
                # Oversold -> Long
                depth = (self.oversold_threshold - rsi_value) / self.oversold_threshold
                conviction = max(0.5, min(0.95, 0.5 + depth * 0.5))
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="long",
                        conviction=conviction,
                        stop_loss_pct=self.stop_loss_pct,
                        take_profit_pct=self.take_profit_pct,
                        reason=f"rsi_oversold_{rsi_value:.1f}",
                        metadata={"rsi": rsi_value, "period": self.rsi_period},
                    )
                )
            elif rsi_value >= self.overbought_threshold:
                # Overbought -> Short
                denom = 100.0 - self.overbought_threshold
                height = (rsi_value - self.overbought_threshold) / denom
                conviction = max(0.5, min(0.95, 0.5 + height * 0.5))
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="short",
                        conviction=conviction,
                        stop_loss_pct=self.stop_loss_pct,
                        take_profit_pct=self.take_profit_pct,
                        reason=f"rsi_overbought_{rsi_value:.1f}",
                        metadata={"rsi": rsi_value, "period": self.rsi_period},
                    )
                )
        return signals


class MomentumBreakoutExecutionStrategy:
    """Trend and momentum breakout execution strategy."""

    def __init__(
        self,
        *,
        strategy_key: str = "momentum_breakout_v1",
        breakout_threshold_pct: Decimal = Decimal("2.0"),
        stop_loss_pct: Decimal = Decimal("0.03"),
        take_profit_pct: Decimal = Decimal("0.06"),
        enabled: bool = True,
    ) -> None:
        self.strategy_key = strategy_key
        self.breakout_threshold_pct = breakout_threshold_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.enabled = enabled

    def evaluate(
        self,
        tickers: list[PaperTicker],
        *,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[StrategySignal]:
        if not self.enabled:
            return []
        signals: list[StrategySignal] = []
        for ticker in tickers:
            if ticker.last <= 0 or ticker.volume_ccy_24h <= 0:
                continue

            change = ticker.change_utc0_pct
            if change >= self.breakout_threshold_pct:
                conviction = min(0.9, 0.55 + float(change - self.breakout_threshold_pct) * 0.05)
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="long",
                        conviction=conviction,
                        stop_loss_pct=self.stop_loss_pct,
                        take_profit_pct=self.take_profit_pct,
                        reason=f"momentum_up_breakout_{change:.2f}%",
                        metadata={"change_pct": str(change)},
                    )
                )
            elif change <= -self.breakout_threshold_pct:
                excess = float(abs(change) - self.breakout_threshold_pct)
                conviction = min(0.9, 0.55 + excess * 0.05)
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="short",
                        conviction=conviction,
                        stop_loss_pct=self.stop_loss_pct,
                        take_profit_pct=self.take_profit_pct,
                        reason=f"momentum_down_breakdown_{change:.2f}%",
                        metadata={"change_pct": str(change)},
                    )
                )
        return signals


class MacdTrendExecutionStrategy:
    """Moving Average Convergence Divergence trend-following strategy."""

    def __init__(
        self,
        *,
        strategy_key: str = "macd_trend",
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        stop_loss_pct: Decimal = Decimal("0.035"),
        take_profit_pct: Decimal = Decimal("0.075"),
        enabled: bool = True,
    ) -> None:
        self.strategy_key = strategy_key
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.enabled = enabled

    def evaluate(
        self,
        tickers: list[PaperTicker],
        *,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[StrategySignal]:
        if not self.enabled:
            return []
        signals: list[StrategySignal] = []
        for ticker in tickers:
            if ticker.last <= 0 or ticker.volume_ccy_24h <= 0:
                continue

            macd_diff: float | None = None
            if klines_by_symbol and ticker.inst_id in klines_by_symbol:
                closes = [
                    float(k.get("close", 0))
                    for k in klines_by_symbol[ticker.inst_id]
                    if float(k.get("close", 0)) > 0
                ]
                if len(closes) >= self.slow_period + self.signal_period:
                    macd_diff = _compute_macd_histogram(
                        closes, self.fast_period, self.slow_period, self.signal_period
                    )

            if macd_diff is None:
                # Approximate trend from ticker change
                macd_diff = float(ticker.change_utc0_pct) * 0.1

            if macd_diff > 0.15:
                conviction = min(0.85, 0.5 + macd_diff * 0.2)
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="long",
                        conviction=conviction,
                        stop_loss_pct=self.stop_loss_pct,
                        take_profit_pct=self.take_profit_pct,
                        reason=f"macd_bullish_expansion_{macd_diff:.2f}",
                        metadata={"macd_diff": macd_diff},
                    )
                )
            elif macd_diff < -0.15:
                conviction = min(0.85, 0.5 + abs(macd_diff) * 0.2)
                signals.append(
                    StrategySignal(
                        strategy_key=self.strategy_key,
                        inst_id=ticker.inst_id,
                        side="short",
                        conviction=conviction,
                        stop_loss_pct=self.stop_loss_pct,
                        take_profit_pct=self.take_profit_pct,
                        reason=f"macd_bearish_expansion_{macd_diff:.2f}",
                        metadata={"macd_diff": macd_diff},
                    )
                )
        return signals


class MultiStrategySignalEngine:
    """Coordinates multiple active execution strategies with arbitration & deduplication."""

    def __init__(
        self,
        strategies: list[ExecutionStrategy] | None = None,
        *,
        registry: Any | None = None,
    ) -> None:
        self._registry = registry
        if strategies is not None:
            self._strategies: list[ExecutionStrategy] = strategies
        elif self._registry is not None:
            self._strategies = self._registry.build_active_strategies()
        else:
            self._strategies = [
                RsiReversalExecutionStrategy(),
                MomentumBreakoutExecutionStrategy(),
                MacdTrendExecutionStrategy(),
                FallbackUtc0Strategy(),
            ]

    def register(self, strategy: ExecutionStrategy) -> None:
        """Register a new strategy or replace existing by key."""
        self._strategies = [s for s in self._strategies if s.strategy_key != strategy.strategy_key]
        self._strategies.append(strategy)

    def strategies(self) -> list[ExecutionStrategy]:
        if self._registry is not None:
            self._strategies = self._registry.build_active_strategies()
        return list(self._strategies)

    def generate(
        self,
        tickers: list[PaperTicker],
        *,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
        max_signals: int = 10,
    ) -> list[StrategySignal]:
        """Evaluate all registered strategies and perform conflict arbitration."""
        if self._registry is not None:
            self._strategies = self._registry.build_active_strategies()

        raw_signals: list[StrategySignal] = []
        for strategy in self._strategies:
            if not getattr(strategy, "enabled", True):
                continue
            try:
                evaluated = strategy.evaluate(tickers, klines_by_symbol=klines_by_symbol)
                raw_signals.extend(evaluated)
            except Exception:
                # Provider isolation: single strategy failure must not crash execution engine
                continue

        # Group by inst_id for arbitration
        by_symbol: dict[str, list[StrategySignal]] = {}
        for sig in raw_signals:
            by_symbol.setdefault(sig.inst_id, []).append(sig)

        arbitrated: list[StrategySignal] = []
        for inst_id, symbol_signals in by_symbol.items():
            if len(symbol_signals) == 1:
                arbitrated.append(symbol_signals[0])
                continue

            longs = [s for s in symbol_signals if s.side == "long"]
            shorts = [s for s in symbol_signals if s.side == "short"]

            if longs and not shorts:
                # Unanimous long: reinforce conviction
                base = max(longs, key=lambda s: s.conviction)
                boosted_conviction = min(1.0, base.conviction + 0.05 * (len(longs) - 1))
                min_stop = min(s.stop_loss_pct for s in longs)
                max_tp = max(s.take_profit_pct for s in longs)
                arbitrated.append(
                    StrategySignal(
                        strategy_key=f"multi_consensus_{len(longs)}",
                        inst_id=inst_id,
                        side="long",
                        conviction=boosted_conviction,
                        stop_loss_pct=min_stop,
                        take_profit_pct=max_tp,
                        reason=f"consensus_long_{len(longs)}_strategies",
                        metadata={"contributors": [s.strategy_key for s in longs]},
                    )
                )
            elif shorts and not longs:
                # Unanimous short: reinforce conviction
                base = max(shorts, key=lambda s: s.conviction)
                boosted_conviction = min(1.0, base.conviction + 0.05 * (len(shorts) - 1))
                min_stop = min(s.stop_loss_pct for s in shorts)
                max_tp = max(s.take_profit_pct for s in shorts)
                arbitrated.append(
                    StrategySignal(
                        strategy_key=f"multi_consensus_{len(shorts)}",
                        inst_id=inst_id,
                        side="short",
                        conviction=boosted_conviction,
                        stop_loss_pct=min_stop,
                        take_profit_pct=max_tp,
                        reason=f"consensus_short_{len(shorts)}_strategies",
                        metadata={"contributors": [s.strategy_key for s in shorts]},
                    )
                )
            else:
                # Conflicting signals: compare aggregate convictions
                long_weight = sum(s.conviction for s in longs)
                short_weight = sum(s.conviction for s in shorts)
                diff = abs(long_weight - short_weight)
                if diff < 0.2:
                    # Ambiguous market conflict -> hold/skip to avoid whip-saw
                    continue
                if long_weight > short_weight:
                    winning = max(longs, key=lambda s: s.conviction)
                    net_conviction = max(0.5, winning.conviction - 0.15)
                    arbitrated.append(
                        StrategySignal(
                            strategy_key=winning.strategy_key,
                            inst_id=inst_id,
                            side="long",
                            conviction=net_conviction,
                            stop_loss_pct=winning.stop_loss_pct,
                            take_profit_pct=winning.take_profit_pct,
                            reason=f"arbitrated_long_over_short_diff_{diff:.2f}",
                            metadata={"dominant_side": "long", "diff": diff},
                        )
                    )
                else:
                    winning = max(shorts, key=lambda s: s.conviction)
                    net_conviction = max(0.5, winning.conviction - 0.15)
                    arbitrated.append(
                        StrategySignal(
                            strategy_key=winning.strategy_key,
                            inst_id=inst_id,
                            side="short",
                            conviction=net_conviction,
                            stop_loss_pct=winning.stop_loss_pct,
                            take_profit_pct=winning.take_profit_pct,
                            reason=f"arbitrated_short_over_long_diff_{diff:.2f}",
                            metadata={"dominant_side": "short", "diff": diff},
                        )
                    )

        # Sort by conviction descending
        arbitrated.sort(key=lambda s: s.conviction, reverse=True)
        return arbitrated[:max_signals]


def _compute_rsi(prices: list[float], period: int) -> float:
    """Compute standard Relative Strength Index."""
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(0.0, d) for d in deltas]
    losses = [max(0.0, -d) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_macd_histogram(
    prices: list[float], fast: int, slow: int, signal: int
) -> float:
    """Compute MACD histogram differential."""
    if len(prices) < slow + signal:
        return 0.0

    def ema(values: list[float], span: int) -> list[float]:
        alpha = 2.0 / (span + 1)
        res = [values[0]]
        for val in values[1:]:
            res.append(alpha * val + (1.0 - alpha) * res[-1])
        return res

    fast_ema = ema(prices, fast)
    slow_ema = ema(prices, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema, strict=False)]
    signal_line = ema(macd_line, signal)
    return macd_line[-1] - signal_line[-1]
