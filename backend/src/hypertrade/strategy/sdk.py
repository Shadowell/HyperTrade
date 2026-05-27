from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class StrategySpec:
    key: str
    title: str
    description: str
    parameters: dict[str, str]


def builtin_strategy_spec(strategy_key: str = "momentum_breakout_v1") -> StrategySpec:
    if strategy_key != "momentum_breakout_v1":
        raise KeyError(strategy_key)
    return StrategySpec(
        key="momentum_breakout_v1",
        title="趋势突破 V1",
        description="当收盘价突破短期均线阈值时开多，跌回均线时退出。",
        parameters={"sma_period": "5", "breakout_pct": "0.005"},
    )


def sample_candles() -> list[Candle]:
    return [
        Candle(
            timestamp=f"2026-05-27T00:{index:02d}:00+00:00",
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=Decimal("1000"),
        )
        for index in range(24)
    ]
