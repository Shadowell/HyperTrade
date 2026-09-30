"""Multi-dimensional (Symbols x Timeframes x Parameters) backtest matrix execution."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hypertrade.backtest.candidate import (
    BacktestCosts,
    Bar,
    CandidateBacktestError,
    replay_candidate,
)
from hypertrade.research.optimization.metrics import (
    QuantitativeMetrics,
    compute_quantitative_metrics,
)


@dataclass(frozen=True)
class DimensionResult:
    symbol: str
    timeframe: str
    is_metrics: QuantitativeMetrics
    oos_metrics: QuantitativeMetrics


@dataclass(frozen=True)
class MatrixTrialResult:
    trial_index: int
    parameters: dict[str, Any]
    aggregated_is_metrics: QuantitativeMetrics
    aggregated_oos_metrics: QuantitativeMetrics
    dimension_results: tuple[DimensionResult, ...]
    error: str = ""

    @property
    def is_successful(self) -> bool:
        return not self.error


class BacktestMatrixEngine:
    """Executes parameter variants across a matrix of symbols and timeframes with IS/OOS split."""

    def __init__(
        self,
        strategy_code: str,
        symbols: Sequence[str] = ("BTC-USDT-SWAP",),
        timeframes: Sequence[str] = ("1H",),
        is_ratio: float = 0.70,
        starting_equity: float = 10_000.0,
        costs: BacktestCosts | None = None,
        trade_notional_usdt: float = 1_000.0,
        leverage: float = 1.0,
    ) -> None:
        if not (0.30 <= is_ratio <= 0.90):
            raise ValueError(f"is_ratio must be between 0.30 and 0.90, got {is_ratio}")
        self.strategy_code = strategy_code
        self.symbols = list(symbols)
        self.timeframes = [tf.upper() for tf in timeframes]
        self.is_ratio = is_ratio
        self.starting_equity = starting_equity
        self.costs = costs or BacktestCosts()
        self.trade_notional_usdt = trade_notional_usdt
        self.leverage = leverage

    def run_matrix(
        self,
        *,
        parameter_variants: Sequence[dict[str, Any]],
        bars_by_dimension: dict[tuple[str, str], Sequence[Bar]],
    ) -> list[MatrixTrialResult]:
        """Replay all parameter combinations across the matrix."""
        results: list[MatrixTrialResult] = []

        for idx, params in enumerate(parameter_variants):
            trial_result = self._evaluate_variant(
                trial_index=idx,
                parameters=params,
                bars_by_dimension=bars_by_dimension,
            )
            results.append(trial_result)

        return results

    def _evaluate_variant(
        self,
        trial_index: int,
        parameters: dict[str, Any],
        bars_by_dimension: dict[tuple[str, str], Sequence[Bar]],
    ) -> MatrixTrialResult:
        dim_results: list[DimensionResult] = []
        is_metrics_list: list[QuantitativeMetrics] = []
        oos_metrics_list: list[QuantitativeMetrics] = []

        for symbol in self.symbols:
            for tf in self.timeframes:
                key = (symbol, tf)
                bars = bars_by_dimension.get(key)
                if not bars or len(bars) < 20:
                    continue

                split_point = int(len(bars) * self.is_ratio)
                is_bars = bars[:split_point]
                oos_bars = bars[split_point:]

                try:
                    is_res = replay_candidate(
                        code=self.strategy_code,
                        bars=is_bars,
                        parameters=parameters,
                        symbols=[symbol],
                        starting_equity=self.starting_equity,
                        trade_notional_usdt=self.trade_notional_usdt,
                        leverage=self.leverage,
                        timeframe=tf,
                        costs=self.costs,
                    )
                    is_metrics = compute_quantitative_metrics(is_res, timeframe=tf)

                    oos_res = replay_candidate(
                        code=self.strategy_code,
                        bars=oos_bars,
                        parameters=parameters,
                        symbols=[symbol],
                        starting_equity=self.starting_equity,
                        trade_notional_usdt=self.trade_notional_usdt,
                        leverage=self.leverage,
                        timeframe=tf,
                        costs=self.costs,
                    )
                    oos_metrics = compute_quantitative_metrics(oos_res, timeframe=tf)

                    dim_results.append(
                        DimensionResult(
                            symbol=symbol,
                            timeframe=tf,
                            is_metrics=is_metrics,
                            oos_metrics=oos_metrics,
                        )
                    )
                    is_metrics_list.append(is_metrics)
                    oos_metrics_list.append(oos_metrics)

                except CandidateBacktestError as exc:
                    return MatrixTrialResult(
                        trial_index=trial_index,
                        parameters=parameters,
                        aggregated_is_metrics=_empty_metrics(),
                        aggregated_oos_metrics=_empty_metrics(),
                        dimension_results=tuple(dim_results),
                        error=f"backtest_error: {str(exc)}",
                    )
                except Exception as exc:
                    return MatrixTrialResult(
                        trial_index=trial_index,
                        parameters=parameters,
                        aggregated_is_metrics=_empty_metrics(),
                        aggregated_oos_metrics=_empty_metrics(),
                        dimension_results=tuple(dim_results),
                        error=f"unexpected_error: {str(exc)}",
                    )

        if not dim_results:
            return MatrixTrialResult(
                trial_index=trial_index,
                parameters=parameters,
                aggregated_is_metrics=_empty_metrics(),
                aggregated_oos_metrics=_empty_metrics(),
                dimension_results=(),
                error="no_valid_dimensions_evaluated",
            )

        agg_is = _aggregate_metrics(is_metrics_list)
        agg_oos = _aggregate_metrics(oos_metrics_list)

        return MatrixTrialResult(
            trial_index=trial_index,
            parameters=parameters,
            aggregated_is_metrics=agg_is,
            aggregated_oos_metrics=agg_oos,
            dimension_results=tuple(dim_results),
            error="",
        )


def _aggregate_metrics(metrics_list: list[QuantitativeMetrics]) -> QuantitativeMetrics:
    """Compute cross-dimension average metrics."""
    if not metrics_list:
        return _empty_metrics()
    n = len(metrics_list)
    total_trades = sum(m.trade_count for m in metrics_list)
    valid_win_rates = [m.win_rate for m in metrics_list if m.win_rate is not None]
    avg_win_rate = sum(valid_win_rates) / len(valid_win_rates) if valid_win_rates else None

    return QuantitativeMetrics(
        total_return_pct=sum(m.total_return_pct for m in metrics_list) / n,
        annualized_return_pct=sum(m.annualized_return_pct for m in metrics_list) / n,
        annualized_sharpe=sum(m.annualized_sharpe for m in metrics_list) / n,
        sortino_ratio=sum(m.sortino_ratio for m in metrics_list) / n,
        calmar_ratio=sum(m.calmar_ratio for m in metrics_list) / n,
        max_drawdown_pct=max(m.max_drawdown_pct for m in metrics_list),  # conservative worst DD
        win_rate=avg_win_rate,
        profit_factor=sum(m.profit_factor for m in metrics_list) / n,
        trade_count=total_trades,
        turnover=sum(m.turnover for m in metrics_list) / n,
        exposure_rate=sum(m.exposure_rate for m in metrics_list) / n,
        avg_holding_bars=sum(m.avg_holding_bars for m in metrics_list) / n,
        fees_paid=sum(m.fees_paid for m in metrics_list),
        is_inert=total_trades == 0,
        details={"dimensions_count": n},
    )


def _empty_metrics() -> QuantitativeMetrics:
    return QuantitativeMetrics(
        total_return_pct=0.0,
        annualized_return_pct=0.0,
        annualized_sharpe=0.0,
        sortino_ratio=0.0,
        calmar_ratio=0.0,
        max_drawdown_pct=0.0,
        win_rate=None,
        profit_factor=0.0,
        trade_count=0,
        turnover=0.0,
        exposure_rate=0.0,
        avg_holding_bars=0.0,
        fees_paid=0.0,
        is_inert=True,
    )


def generate_synthetic_bars(
    symbol: str = "BTC-USDT-SWAP",
    count: int = 200,
    timeframe: str = "1H",
    base_price: float = 50_000.0,
    volatility: float = 0.015,
    seed: int = 42,
) -> list[Bar]:
    """Generate realistic OHLCV bars with trending and oscillating regimes for testing."""
    rng = random.Random(seed)
    bars: list[Bar] = []
    current_price = base_price
    start_time = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    tf_delta = {
        "1M": timedelta(minutes=1),
        "5M": timedelta(minutes=5),
        "15M": timedelta(minutes=15),
        "30M": timedelta(minutes=30),
        "1H": timedelta(hours=1),
        "4H": timedelta(hours=4),
        "1D": timedelta(days=1),
    }.get(timeframe.upper(), timedelta(hours=1))

    for i in range(count):
        t = start_time + i * tf_delta
        # Add sine wave oscillation + random walk
        wave = math.sin(i / 15.0) * volatility * 0.5
        noise = rng.gauss(0, volatility)
        ret = wave + noise

        open_p = current_price
        close_p = open_p * (1.0 + ret)
        high_p = max(open_p, close_p) * (1.0 + abs(rng.gauss(0, volatility * 0.4)))
        low_p = min(open_p, close_p) * (1.0 - abs(rng.gauss(0, volatility * 0.4)))
        vol = abs(rng.gauss(100.0, 30.0))

        current_price = close_p
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=t.isoformat(),
                open=round(open_p, 2),
                high=round(high_p, 2),
                low=round(low_p, 2),
                close=round(close_p, 2),
                volume=round(vol, 2),
            )
        )
    return bars
