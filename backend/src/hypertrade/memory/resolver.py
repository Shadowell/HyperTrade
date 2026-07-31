"""
Memory Contradiction Resolver for Autonomous Memory 3.0

Detects semantic contradictions between newly acquired insights and existing memories,
automatically deprecating invalidated historical items.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class MemoryContradictionResolver:
    """
    Semantic contradiction resolver maintaining consistency in stored knowledge.
    """

    def __init__(self, contradiction_similarity_threshold: float = 0.70) -> None:
        self.contradiction_similarity_threshold = contradiction_similarity_threshold

    def resolve_contradiction(
        self,
        new_memory: dict[str, Any],
        existing_memories: list[dict[str, Any]],
        similarity_fn: Callable[[str, str], float],
        is_contradictory_fn: Callable[[str, str], bool],
    ) -> tuple[list[dict[str, Any]], bool]:
        new_summary = new_memory.get("summary", "")
        if not new_summary:
            return existing_memories, False

        contradiction_found = False
        for item in existing_memories:
            if item.get("deprecated"):
                continue

            existing_summary = item.get("summary", "")
            sim = similarity_fn(new_summary, existing_summary)

            if (
                sim >= self.contradiction_similarity_threshold
                and is_contradictory_fn(new_summary, existing_summary)
            ):
                # Flag older memory item as deprecated
                item["deprecated"] = True
                item["deprecated_reason"] = (
                    f"Contradicted by new memory {new_memory.get('id')}"
                )
                item["replaced_by"] = new_memory.get("id")
                contradiction_found = True

        existing_memories.append(new_memory)
        return existing_memories, contradiction_found
