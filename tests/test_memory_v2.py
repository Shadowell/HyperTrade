"""
Unit Tests for Advanced Memory Management 2.0 (memory_v2.py)
"""

import datetime

from hypertrade.memory.memory_v2 import (
    EbbinghausDecayScorer,
    HierarchicalMemoryPyramid,
    MemoryConsolidator,
)


def test_hierarchical_memory_pyramid():
    pyramid = HierarchicalMemoryPyramid()

    # Working Memory
    pyramid.set_working_variable("stop_loss", 0.02)
    assert pyramid.get_working_variable("stop_loss") == 0.02

    # Episodic Memory
    ep = pyramid.add_episodic_item("task_123", "Backtest ATR stop loss strategy", 0.7)
    assert ep["tier"] == "episodic"
    assert len(pyramid.episodic_memory) == 1

    # Semantic Memory
    sem = pyramid.add_semantic_item("regime", "High volatility reduces breakout win rate", 0.9)
    assert sem["tier"] == "semantic"
    assert len(pyramid.semantic_memory) == 1


def test_ebbinghaus_decay_scorer():
    scorer = EbbinghausDecayScorer(decay_rate=0.05)
    now = datetime.datetime.now(datetime.UTC)

    # Recent memory (0 days old)
    recent_score = scorer.calculate_score(
        similarity=0.8, importance=0.8, created_at=now, now=now
    )

    # Old memory (10 days old)
    old_time = now - datetime.timedelta(days=10)
    old_score = scorer.calculate_score(
        similarity=0.8, importance=0.8, created_at=old_time, now=now
    )

    assert recent_score > old_score


def test_memory_consolidator():
    consolidator = MemoryConsolidator(similarity_threshold=0.80)

    existing = [
        {
            "id": "mem_1",
            "summary": "High volatility reduces breakout strategy win rate",
            "importance": 0.5,
            "consolidated_count": 1,
        }
    ]

    def mock_sim(s1: str, s2: str) -> float:
        return 0.85 if "breakout" in s1.lower() and "breakout" in s2.lower() else 0.10

    new_item = {
        "id": "mem_2",
        "summary": "Breakout strategy win rate drops in volatile market",
        "importance": 0.5,
    }

    updated, merged = consolidator.consolidate(new_item, existing, mock_sim)
    assert merged is True
    assert len(updated) == 1
    assert updated[0]["consolidated_count"] == 2
    assert updated[0]["importance"] == 0.6
