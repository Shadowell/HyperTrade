"""Comprehensive quantitative metrics computation for backtest evaluations."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from hypertrade.backtest.candidate import (
    _BARS_PER_YEAR,
    _DEFAULT_BARS_PER_YEAR,
    CandidateBacktestResult,
    Trade,
)


@dataclass(frozen=True)
class QuantitativeMetrics:
    total_return_pct: float
    annualized_return_pct: float
    annualized_sharpe: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    win_rate: float | None
    profit_factor: float
    trade_count: int
    turnover: float
    exposure_rate: float
    avg_holding_bars: float
    fees_paid: float
    is_inert: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_return_pct": round(self.total_return_pct, 4),
            "annualized_return_pct": round(self.annualized_return_pct, 4),
            "annualized_sharpe": round(self.annualized_sharpe, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "calmar_ratio": round(self.calmar_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "profit_factor": round(self.profit_factor, 4),
            "trade_count": self.trade_count,
            "turnover": round(self.turnover, 4),
            "exposure_rate": round(self.exposure_rate, 4),
            "avg_holding_bars": round(self.avg_holding_bars, 2),
            "fees_paid": round(self.fees_paid, 4),
            "is_inert": self.is_inert,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuantitativeMetrics:
        return cls(
            total_return_pct=float(data["total_return_pct"]),
            annualized_return_pct=float(data.get("annualized_return_pct", 0.0)),
            annualized_sharpe=float(data["annualized_sharpe"]),
            sortino_ratio=float(data.get("sortino_ratio", 0.0)),
            calmar_ratio=float(data.get("calmar_ratio", 0.0)),
            max_drawdown_pct=float(data["max_drawdown_pct"]),
            win_rate=float(data["win_rate"]) if data.get("win_rate") is not None else None,
            profit_factor=float(data.get("profit_factor", 0.0)),
            trade_count=int(data["trade_count"]),
            turnover=float(data.get("turnover", 0.0)),
            exposure_rate=float(data.get("exposure_rate", 0.0)),
            avg_holding_bars=float(data.get("avg_holding_bars", 0.0)),
            fees_paid=float(data.get("fees_paid", 0.0)),
            is_inert=bool(data.get("is_inert", False)),
            details=dict(data.get("details", {})),
        )


def compute_quantitative_metrics(
    result: CandidateBacktestResult,
    timeframe: str = "1H",
) -> QuantitativeMetrics:
    """Derive professional trading metrics from a CandidateBacktestResult."""
    total_return_pct = result.total_return * 100.0
    max_drawdown_pct = result.max_drawdown * 100.0
    trade_count = len(result.trades)
    is_inert = trade_count == 0

    periods_per_year = _BARS_PER_YEAR.get(timeframe.upper(), _DEFAULT_BARS_PER_YEAR)
    num_bars = max(1, result.bars)
    years = num_bars / periods_per_year

    # Annualized Return
    if years > 0 and result.starting_equity > 0 and result.ending_equity > 0:
        annualized_return_pct = (
            ((result.ending_equity / result.starting_equity) ** (1.0 / years) - 1.0) * 100.0
        )
    else:
        annualized_return_pct = total_return_pct

    # Sortino Ratio
    sortino = _compute_sortino(result.equity_curve, timeframe)

    # Calmar Ratio: Annualized Return % / Max Drawdown %
    if max_drawdown_pct > 0.01:
        calmar = annualized_return_pct / max_drawdown_pct
    else:
        calmar = annualized_return_pct if annualized_return_pct > 0 else 0.0

    # Win Rate & Profit Factor
    win_rate = result.win_rate
    gross_profit = sum(t.pnl for t in result.trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in result.trades if t.pnl < 0))
    if gross_loss > 1e-4:
        profit_factor = min(50.0, gross_profit / gross_loss)
    elif gross_profit > 0:
        profit_factor = 50.0
    else:
        profit_factor = 0.0

    # Average Holding Duration in bars
    avg_holding = 0.0
    if trade_count > 0:
        # Estimate from exposure bars
        avg_holding = (result.exposure * num_bars) / trade_count

    return QuantitativeMetrics(
        total_return_pct=total_return_pct,
        annualized_return_pct=annualized_return_pct,
        annualized_sharpe=result.sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        max_drawdown_pct=max_drawdown_pct,
        win_rate=win_rate,
        profit_factor=profit_factor,
        trade_count=trade_count,
        turnover=result.turnover,
        exposure_rate=result.exposure,
        avg_holding_bars=avg_holding,
        fees_paid=result.fees_paid,
        is_inert=is_inert,
        details={
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "years_sampled": round(years, 3),
        },
    )


def _compute_sortino(equity_curve: Sequence[float], timeframe: str) -> float:
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    negative_returns = [r for r in returns if r < 0]
    if not negative_returns:
        # Perfect series with no downside
        return 10.0 if mean > 0 else 0.0
    downside_variance = sum(r**2 for r in negative_returns) / len(returns)
    downside_dev = math.sqrt(downside_variance)
    if downside_dev <= 0:
        return 0.0
    periods = _BARS_PER_YEAR.get(timeframe.upper(), _DEFAULT_BARS_PER_YEAR)
    return (mean / downside_dev) * math.sqrt(periods)
