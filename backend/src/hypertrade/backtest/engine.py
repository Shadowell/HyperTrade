from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import backtrader as bt  # type: ignore[import-untyped]

from hypertrade.strategy.sdk import Candle


@dataclass(frozen=True)
class BacktestResult:
    strategy_key: str
    start_cash: Decimal
    end_value: Decimal
    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    trade_count: int
    report_markdown: str
    report_json: dict[str, object]


class MomentumBreakoutStrategy(bt.Strategy):  # type: ignore[misc]
    default_sma_period = 5
    default_breakout_pct = 0.0
    params = (("sma_period", 5), ("breakout_pct", 0.0))

    def __init__(self) -> None:
        runtime_params: Any = self.p
        self.sma_period = max(2, int(getattr(runtime_params, "sma_period", 5)))
        self.breakout_pct = float(getattr(runtime_params, "breakout_pct", 0.0))
        self.sma = bt.indicators.SimpleMovingAverage(
            self.data.close,
            period=self.sma_period,
        )
        self.completed_orders = 0

    def next(self) -> None:
        if not self.position and self.data.close[0] >= self.sma[0] * (
            1 + self.breakout_pct
        ):
            self.buy(size=1)
        elif self.position and self.data.close[0] < self.sma[0]:
            self.close()

    def notify_order(self, order: Any) -> None:
        if order.status == order.Completed:
            self.completed_orders += 1


class BacktestEngine:
    def run(
        self,
        *,
        strategy_key: str,
        candles: list[Candle],
        initial_cash: Decimal,
        strategy_params: dict[str, object] | None = None,
    ) -> BacktestResult:
        if strategy_key != "momentum_breakout_v1":
            raise KeyError(strategy_key)
        if len(candles) < 6:
            raise ValueError("At least 6 candles are required")
        params = _strategy_params(strategy_params)

        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "candles.csv"
            csv_path.write_text(_candles_to_csv(candles), encoding="utf-8")

            cerebro = bt.Cerebro()
            cerebro.broker.setcash(float(initial_cash))
            cerebro.broker.set_coc(True)
            data = bt.feeds.GenericCSVData(
                dataname=str(csv_path),
                dtformat="%Y-%m-%dT%H:%M:%S",
                datetime=0,
                open=1,
                high=2,
                low=3,
                close=4,
                volume=5,
                openinterest=-1,
                headers=True,
            )
            cerebro.adddata(data)
            cerebro.addstrategy(MomentumBreakoutStrategy, **params)
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
            strategies = cerebro.run()
            strategy = strategies[0]
            end_value = Decimal(str(cerebro.broker.getvalue()))
            drawdown = Decimal(str(strategy.analyzers.drawdown.get_analysis().max.drawdown))
            trade_count = int(strategy.completed_orders)

        total_return_pct = ((end_value - initial_cash) / initial_cash * Decimal("100")).quantize(
            Decimal("0.000001")
        )
        report_json: dict[str, object] = {
            "strategy_key": strategy_key,
            "strategy_params": {key: str(value) for key, value in params.items()},
            "start_cash": str(initial_cash),
            "end_value": str(end_value),
            "total_return_pct": str(total_return_pct),
            "max_drawdown_pct": str(drawdown),
            "trade_count": trade_count,
        }
        report_markdown = "\n".join(
            [
                f"# Backtest Report: {strategy_key}",
                "",
                f"- Start cash: {initial_cash}",
                f"- End value: {end_value}",
                f"- Return: {total_return_pct}%",
                f"- Max drawdown: {drawdown}%",
                f"- Trades: {trade_count}",
                "",
                "Research only. Not investment advice.",
            ]
        )
        return BacktestResult(
            strategy_key=strategy_key,
            start_cash=initial_cash,
            end_value=end_value,
            total_return_pct=total_return_pct,
            max_drawdown_pct=drawdown,
            trade_count=trade_count,
            report_markdown=report_markdown,
            report_json=report_json,
        )


def _candles_to_csv(candles: list[Candle]) -> str:
    rows = ["datetime,open,high,low,close,volume"]
    for candle in candles:
        parsed = datetime.fromisoformat(candle.timestamp)
        rows.append(
            ",".join(
                [
                    parsed.strftime("%Y-%m-%dT%H:%M:%S"),
                    str(candle.open),
                    str(candle.high),
                    str(candle.low),
                    str(candle.close),
                    str(candle.volume),
                ]
            )
        )
    return "\n".join(rows)


def _strategy_params(params: dict[str, object] | None) -> dict[str, int | float]:
    values = dict(params or {})
    sma_period = int(str(values.get("sma_period", 5)))
    breakout_pct = float(str(values.get("breakout_pct", 0.0)))
    return {
        "sma_period": max(2, min(sma_period, 100)),
        "breakout_pct": max(0.0, min(breakout_pct, 0.5)),
    }
