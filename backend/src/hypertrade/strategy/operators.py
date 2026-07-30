"""
Higher-Order Quant Factor & Microstructure Operator Library
"""

import math
from typing import Any


def compute_orderbook_imbalance(
    bids: list[tuple[float, float]] | list[list[float]],
    asks: list[tuple[float, float]] | list[list[float]],
    depth: int = 5,
) -> float:
    """
    Computes normalized bid-ask orderbook volume imbalance ratio:
    Imbalance = (Sum(BidVolume) - Sum(AskVolume)) / (Sum(BidVolume) + Sum(AskVolume))
    Returns value in [-1.0, 1.0].
    """
    if not bids or not asks:
        return 0.0

    top_bids = bids[:depth]
    top_asks = asks[:depth]

    bid_vol = sum(float(b[1]) for b in top_bids)
    ask_vol = sum(float(a[1]) for a in top_asks)

    total_vol = bid_vol + ask_vol
    if total_vol <= 0.0:
        return 0.0

    return (bid_vol - ask_vol) / total_vol


def compute_vwap_zscore(
    candles: list[dict[str, Any]],
    window: int = 20,
) -> float:
    """
    Calculates Volume-Weighted Average Price (VWAP) and the z-score of current price distance:
    Z_vwap = (P_close - VWAP) / std(P_close - VWAP)
    """
    if len(candles) < 2:
        return 0.0

    recent_candles = candles[-window:]
    cumulative_pv = 0.0
    cumulative_v = 0.0
    diffs: list[float] = []

    for c in recent_candles:
        close = float(c.get("close", 0.0))
        high = float(c.get("high", close))
        low = float(c.get("low", close))
        vol = float(c.get("volume", 1.0))

        typical_price = (high + low + close) / 3.0
        cumulative_pv += typical_price * vol
        cumulative_v += vol
        diffs.append(close - typical_price)

    if cumulative_v <= 0.0:
        return 0.0

    vwap = cumulative_pv / cumulative_v
    current_close = float(candles[-1].get("close", 0.0))
    current_diff = current_close - vwap

    if len(diffs) < 2:
        return 0.0

    mean_diff = sum(diffs) / len(diffs)
    variance = sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)
    std_dev = math.sqrt(variance)

    if std_dev <= 1e-8:
        return 0.0

    return current_diff / std_dev


def compute_atr_volatility_channel(
    candles: list[dict[str, Any]],
    period: int = 14,
    multiplier: float = 2.0,
) -> tuple[float, float, float]:
    """
    Computes Average True Range (ATR) volatility channels:
    Returns (middle_band, upper_channel, lower_channel).
    """
    if len(candles) < period + 1:
        last_close = float(candles[-1]["close"]) if candles else 100.0
        return last_close, last_close * 1.05, last_close * 0.95

    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev = candles[i - 1]

        high = float(curr.get("high", curr.get("close", 0.0)))
        low = float(curr.get("low", curr.get("close", 0.0)))
        prev_close = float(prev.get("close", 0.0))

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    atr_window = true_ranges[-period:]
    atr = sum(atr_window) / len(atr_window)

    closes = [float(c["close"]) for c in candles[-period:]]
    middle_band = sum(closes) / len(closes)

    upper_channel = middle_band + (multiplier * atr)
    lower_channel = middle_band - (multiplier * atr)

    return middle_band, upper_channel, lower_channel
