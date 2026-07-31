"""
Advanced Context Management 2.0 Core Subsystem

Provides Dynamic Token Budget Manager, Schema-Aware Semantic Context Pruner,
and Multi-Turn Sliding Window Summarizer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "deepseek-chat": 128000,
    "deepseek-reasoner": 128000,
    "claude-3-5-sonnet": 200000,
    "claude-3-opus": 200000,
    "qwen-2.5-72b": 32000,
    "gpt-4o": 128000,
    "default": 64000,
}


class DynamicTokenBudgetManager:
    """
    Dynamically manages token budgets across context categories based on model capacity.
    Allocates 20% System, 40% Tool History, 30% Memory/RAG, 10% Output Reserve.
    """

    def __init__(self, model_name: str = "default") -> None:
        self.model_name = model_name
        self.max_tokens = MODEL_CONTEXT_LIMITS.get(
            model_name.lower(), MODEL_CONTEXT_LIMITS["default"]
        )
        self.output_reserve = int(self.max_tokens * 0.10)
        self.available_tokens = self.max_tokens - self.output_reserve

        self.budgets: dict[str, int] = {
            "system": int(self.available_tokens * 0.20),
            "tool_history": int(self.available_tokens * 0.40),
            "memory_rag": int(self.available_tokens * 0.30),
            "output_reserve": self.output_reserve,
        }

    def get_budget(self, category: str) -> int:
        return self.budgets.get(category, int(self.available_tokens * 0.20))

    def is_within_budget(self, category: str, estimated_tokens: int) -> bool:
        budget = self.get_budget(category)
        return estimated_tokens <= budget


class SemanticContextPruner:
    """
    AST & Schema-aware payload pruner preserving dictionary key structures
    while folding large nested lists and long text strings.
    """

    def __init__(self, max_payload_chars: int = 1500) -> None:
        self.max_payload_chars = max_payload_chars

    def prune(self, payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload

        raw_str = json.dumps(payload, ensure_ascii=False)
        if len(raw_str) <= self.max_payload_chars:
            return payload

        pruned = dict(payload)
        pruned["_semantic_pruned"] = True

        for key, val in list(pruned.items()):
            if isinstance(val, list) and len(val) > 5:
                # Keep first 2 and last 3 items, fold the middle
                pruned[key] = (
                    val[:2]
                    + [f"... [Folded {len(val) - 5} items for schema preservation] ..."]
                    + val[-3:]
                )
            elif isinstance(val, str) and len(val) > 400:
                pruned[key] = val[:200] + "... [Folded text] ..." + val[-100:]
            elif isinstance(val, dict):
                pruned[key] = self.prune(val)

        return pruned


class TurnSlidingWindowSummarizer:
    """
    Multi-Turn Sliding Window Summarizer compressing historical conversation turns
    when turn count exceeds max_turns.
    """

    def __init__(self, max_turns: int = 12) -> None:
        self.max_turns = max_turns

    def compress_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(messages) <= self.max_turns:
            return messages

        # Preserve System message (index 0) and user intent (index 1)
        head = messages[:2]
        tail = messages[-4:]  # Preserve last 4 active messages
        middle = messages[2:-4]

        # Compress middle messages
        tools_called: set[str] = set()
        for msg in middle:
            if msg.get("role") == "tool" and "tool_call_id" in msg:
                tools_called.add(str(msg.get("tool_name", "tool")))

        tools_str = ", ".join(sorted(tools_called)) if tools_called else "None"
        summary_content = (
            f"[Historical Executive Summary]: Compressed {len(middle)} intermediate turns. "
            f"Tools invoked in history: {tools_str}."
        )

        summary_msg = {
            "role": "user",
            "content": summary_content,
        }

        return head + [summary_msg] + tail
