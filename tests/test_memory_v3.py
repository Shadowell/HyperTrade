"""
Unit Tests for Autonomous Memory 3.0 (flusher, regime_filter, resolver)
"""

from hypertrade.memory.flusher import AutoReflexionMemoryFlusher
from hypertrade.memory.memory_v2 import HierarchicalMemoryPyramid
from hypertrade.memory.regime_filter import MarketRegimeMemoryFilter
from hypertrade.memory.resolver import MemoryContradictionResolver


def test_auto_reflexion_memory_flusher():
    pyramid = HierarchicalMemoryPyramid()
    flusher = AutoReflexionMemoryFlusher(pyramid)

    # Flush successful run
    item_success = flusher.flush_run_outcome(
        task_id="t_001",
        goal="Optimize ATR stop loss",
        status="completed",
        final_message="Achieved Sharpe 1.85",
        tool_call_count=5,
        regime="bull_trend",
    )
    assert item_success["tier"] == "semantic"
    assert item_success["market_regime"] == "bull_trend"
    assert len(pyramid.semantic_memory) == 1

    # Flush failed run
    item_fail = flusher.flush_run_outcome(
        task_id="t_002",
        goal="Backtest ETH momentum",
        status="failed",
        final_message="Order execution timeout",
        tool_call_count=2,
        regime="high_volatility",
    )
    assert item_fail["tier"] == "episodic"
    assert item_fail["market_regime"] == "high_volatility"
    assert len(pyramid.episodic_memory) == 1


def test_market_regime_memory_filter():
    filt = MarketRegimeMemoryFilter(cross_regime_penalty=0.5)

    memories = [
        {"id": "m1", "summary": "ETH momentum", "market_regime": "bull_trend", "score": 0.8},
        {"id": "m2", "summary": "BTC breakout", "market_regime": "sideways_range", "score": 0.8},
    ]

    ranked = filt.filter_and_rank(memories, current_regime="bull_trend")
    assert len(ranked) == 2
    assert ranked[0]["id"] == "m1"
    assert ranked[0]["effective_score"] == 0.8
    assert ranked[1]["id"] == "m2"
    assert ranked[1]["effective_score"] == 0.4  # 0.8 * 0.5 penalty


def test_memory_contradiction_resolver():
    resolver = MemoryContradictionResolver(contradiction_similarity_threshold=0.70)

    existing = [
        {
            "id": "mem_101",
            "summary": "ETH 30m breakout strategy is highly profitable",
            "deprecated": False,
        }
    ]

    new_mem = {
        "id": "mem_102",
        "summary": "ETH 30m breakout strategy failed in recent backtest",
    }

    def mock_sim(s1: str, s2: str) -> float:
        return 0.80 if "ETH 30m breakout" in s1 and "ETH 30m breakout" in s2 else 0.10

    def mock_contradiction(s1: str, s2: str) -> bool:
        return ("profitable" in s1 and "failed" in s2) or ("failed" in s1 and "profitable" in s2)

    updated, found = resolver.resolve_contradiction(
        new_mem, existing, mock_sim, mock_contradiction
    )

    assert found is True
    assert len(updated) == 2
    assert updated[0]["deprecated"] is True
    assert updated[0]["replaced_by"] == "mem_102"
