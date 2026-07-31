"""
Advanced Memory Management 2.0 Core Subsystem

Provides 3-Tier Hierarchical Memory Pyramid (Working, Episodic, Semantic),
Ebbinghaus Time-Decay Scorer, and Memory Consolidation Deduplicator.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Callable
from typing import Any


class HierarchicalMemoryPyramid:
    """
    3-Tier Hierarchical Memory Architecture:
    1. Working Memory: Short-term transient Scratchpad variables.
    2. Episodic Memory: Mid-term 7-day research task logs & backtest results.
    3. Semantic Memory: Long-term domain rules & market regime learnings.
    """

    def __init__(self) -> None:
        self.working_memory: dict[str, Any] = {}
        self.episodic_memory: list[dict[str, Any]] = []
        self.semantic_memory: list[dict[str, Any]] = []

    def set_working_variable(self, key: str, val: Any) -> None:
        self.working_memory[key] = val

    def get_working_variable(self, key: str, default: Any = None) -> Any:
        return self.working_memory.get(key, default)

    def add_episodic_item(
        self,
        task_id: str,
        summary: str,
        importance: float = 0.5,
        created_at: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": f"ep_{len(self.episodic_memory) + 1}",
            "task_id": task_id,
            "summary": summary,
            "importance": min(1.0, max(0.0, importance)),
            "created_at": created_at or datetime.datetime.now(datetime.UTC),
            "tier": "episodic",
        }
        self.episodic_memory.append(item)
        return item

    def add_semantic_item(
        self,
        concept: str,
        rule: str,
        importance: float = 0.8,
        created_at: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        item = {
            "id": f"sem_{len(self.semantic_memory) + 1}",
            "concept": concept,
            "rule": rule,
            "summary": f"[{concept}] {rule}",
            "importance": min(1.0, max(0.0, importance)),
            "created_at": created_at or datetime.datetime.now(datetime.UTC),
            "tier": "semantic",
        }
        self.semantic_memory.append(item)
        return item


class EbbinghausDecayScorer:
    """
    Ranks memory items using Ebbinghaus time-decay composite scoring formula:
    Score = 0.50 * Similarity + 0.30 * Exp(-decay_rate * days) + 0.20 * Importance
    """

    def __init__(self, decay_rate: float = 0.05) -> None:
        self.decay_rate = decay_rate

    def calculate_score(
        self,
        similarity: float,
        importance: float,
        created_at: datetime.datetime,
        now: datetime.datetime | None = None,
    ) -> float:
        current_time = now or datetime.datetime.now(datetime.UTC)
        delta_days = max(0.0, (current_time - created_at).total_seconds() / 86400.0)
        time_decay = math.exp(-self.decay_rate * delta_days)

        sim_score = min(1.0, max(0.0, similarity))
        imp_score = min(1.0, max(0.0, importance))

        return round(0.50 * sim_score + 0.30 * time_decay + 0.20 * imp_score, 4)


class MemoryConsolidator:
    """
    Deduplicates and merges incoming memory entries to prevent database pollution.
    """

    def __init__(self, similarity_threshold: float = 0.85) -> None:
        self.similarity_threshold = similarity_threshold

    def consolidate(
        self,
        new_item: dict[str, Any],
        existing_items: list[dict[str, Any]],
        similarity_fn: Callable[[str, str], float],
    ) -> tuple[list[dict[str, Any]], bool]:
        new_summary = new_item.get("summary", "")
        if not new_summary:
            return existing_items, False

        for item in existing_items:
            sim = similarity_fn(new_summary, item.get("summary", ""))
            if sim >= self.similarity_threshold:
                # Merge into existing item
                item["importance"] = min(1.0, item.get("importance", 0.5) + 0.1)
                item["consolidated_count"] = item.get("consolidated_count", 1) + 1
                item["last_seen_at"] = new_item.get(
                    "created_at", datetime.datetime.now(datetime.UTC)
                )
                return existing_items, True

        # Append as new distinct memory item
        existing_items.append(new_item)
        return existing_items, False
