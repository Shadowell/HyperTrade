"""
Unit Tests for Phase 2: Higher-Order Quant Factor Operators
"""

import pytest
from hypertrade.strategy.operators import (
    compute_atr_volatility_channel,
    compute_orderbook_imbalance,
    compute_vwap_zscore,
)


def test_compute_orderbook_imbalance():
    bids = [(100.0, 10.0), (99.5, 20.0), (99.0, 30.0)]
    asks = [(100.5, 5.0), (101.0, 5.0), (101.5, 10.0)]

    imbalance = compute_orderbook_imbalance(bids, asks, depth=3)
    assert pytest.approx(imbalance, rel=1e-3) == 0.5


def test_compute_vwap_zscore():
    candles = [
        {"close": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "volume": 1000.0}
        for i in range(30)
    ]
    zscore = compute_vwap_zscore(candles, window=20)
    assert isinstance(zscore, float)


def test_compute_atr_volatility_channel():
    candles = [
        {"close": 100.0 + (i % 3), "high": 102.0 + (i % 3), "low": 98.0 + (i % 3), "volume": 500.0}
        for i in range(30)
    ]
    mid, upper, lower = compute_atr_volatility_channel(candles, period=14, multiplier=2.0)

    assert upper > mid
    assert lower < mid
    assert pytest.approx(mid, rel=0.1) == 101.0
