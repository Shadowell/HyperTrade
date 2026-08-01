"""
Unit & Integration Tests for Microstructure Alpha Factors & Vectorized MCTS Screening Engine
"""

from hypertrade.arc.microstructure import (
    compute_funding_rate_arbitrage_pressure,
    compute_liquidation_cascade_density,
    compute_order_flow_imbalance,
    compute_volume_order_imbalance,
)
from hypertrade.arc.vector_screening import VectorizedMCTSScreeningEngine


def test_order_flow_imbalance_ofi() -> None:
    bids_p = [100.0, 100.5, 101.0]
    bids_v = [10.0, 12.0, 15.0]
    asks_p = [101.0, 101.5, 102.0]
    asks_v = [8.0, 6.0, 5.0]

    ofi = compute_order_flow_imbalance(bids_p, bids_v, asks_p, asks_v)
    assert isinstance(ofi, float)
    assert ofi > 0.0  # Upward price + volume expansion = positive buying OFI


def test_volume_order_imbalance_voi() -> None:
    voi = compute_volume_order_imbalance([100.0, 200.0], [50.0, 50.0])
    assert voi == round((300.0 - 100.0) / 400.0, 4)
    assert voi == 0.5


def test_funding_rate_arbitrage_pressure() -> None:
    res = compute_funding_rate_arbitrage_pressure(
        funding_rate=0.001,
        predicted_funding_rate=0.0002,
    )
    assert res["signal_bias"] == -1
    assert res["arbitrage_opportunity"] is True
    assert res["annualized_apr_pct"] > 100.0


def test_liquidation_cascade_density() -> None:
    res = compute_liquidation_cascade_density(
        recent_liquidations_u=[200000.0, 400000.0],
        window_seconds=300,
        cascade_threshold_u=500000.0,
    )
    assert res["is_cascade_alert"] is True
    assert res["recommended_position_multiplier"] == 0.5


def test_vectorized_mcts_two_stage_screening() -> None:
    engine = VectorizedMCTSScreeningEngine(min_fast_sharpe=0.5, max_fast_drawdown=0.5)

    close_prices = [100.0 + i * 0.5 for i in range(50)]
    candidate_signals = [
        [1] * 50,  # Perfect trend follower
        [-1] * 50,  # Reverse trend follower
        [0] * 50,  # Neutral
    ]

    survivors = engine.stage1_vector_screening(close_prices, candidate_signals)
    assert len(survivors) >= 1
    assert survivors[0]["candidate_index"] == 0
    assert survivors[0]["fast_sharpe"] > 0.0

    def mock_backtrader_eval(idx: int, sigs: list[int]) -> dict[str, float]:
        return {"sharpe": 1.8 if idx == 0 else 0.2, "drawdown": 0.05}

    results = engine.execute_two_stage_pipeline(
        close_prices, candidate_signals, mock_backtrader_eval
    )
    assert len(results) >= 1
    assert results[0]["stage2_passed"] is True
    assert results[0]["stage2_backtrader_metrics"]["sharpe"] == 1.8
