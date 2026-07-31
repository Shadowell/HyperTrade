"""
AutoReflexion Memory Flusher for Autonomous Memory 3.0

Intercepts completed run outcomes, extracts structured lessons & strategy insights,
and automatically flushes them into the 3-tier memory pyramid.
"""

from __future__ import annotations

import datetime
from typing import Any

from hypertrade.memory.memory_v2 import HierarchicalMemoryPyramid


class AutoReflexionMemoryFlusher:
    """
    Autonomous post-task self-reflection and memory flushing engine.
    Extracts key takeaways and updates the hierarchical memory pyramid.
    """

    def __init__(self, memory_pyramid: HierarchicalMemoryPyramid) -> None:
        self.memory_pyramid = memory_pyramid

    def flush_run_outcome(
        self,
        task_id: str,
        goal: str,
        status: str,
        final_message: str,
        tool_call_count: int = 0,
        regime: str = "sideways_range",
    ) -> dict[str, Any]:
        importance = 0.8 if status == "completed" else 0.9

        if status == "completed":
            summary = (
                f"[Success Takeaway] Task '{goal}' completed via {tool_call_count} steps. "
                f"Regime: {regime}. Outcome: {final_message[:150]}"
            )
            item = self.memory_pyramid.add_semantic_item(
                concept=f"Task:{goal[:30]}",
                rule=summary,
                importance=importance,
                created_at=datetime.datetime.now(datetime.UTC),
            )
        else:
            summary = (
                f"[Failure Lesson] Task '{goal}' failed ({status}) under {regime}. "
                f"Error details: {final_message[:150]}"
            )
            item = self.memory_pyramid.add_episodic_item(
                task_id=task_id,
                summary=summary,
                importance=importance,
                created_at=datetime.datetime.now(datetime.UTC),
            )

        item["market_regime"] = regime
        return item
