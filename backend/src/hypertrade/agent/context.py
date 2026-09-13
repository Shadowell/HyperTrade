"""Compatibility entrypoint for the shared, evidence-safe request compactor.

Production callers pass complete requests to agent.compaction.compact_request.
This message-only wrapper remains for consumers that have no tool schemas.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def estimate_tokens(text: str) -> int:
    """UTF-8 byte upper allowance for CJK/English; not provider billing."""
    return len(text.encode("utf-8"))


def estimate_message_tokens(message: dict[str, Any]) -> int:
    from hypertrade.agent.compaction import canonical

    return estimate_tokens(canonical(message)) + 64


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


@dataclass(frozen=True)
class CompactionResult:
    messages: list[dict[str, Any]]
    compacted_groups: int


def compact_messages(
    messages: list[dict[str, Any]],
    *,
    max_history_tokens: int = 24_000,
    keep_recent_groups: int = 4,
) -> CompactionResult:
    """Build a bounded view or raise ContextBlocked without deleting originals."""

    from hypertrade.agent.compaction import compact_request

    result = compact_request(
        messages,
        tools=[],
        max_tokens=max_history_tokens,
        keep_recent_groups=keep_recent_groups,
    )
    return CompactionResult(
        messages=messages if result.messages == messages else result.messages,
        compacted_groups=result.compacted_groups,
    )


def _prefix_end(messages: list[dict[str, Any]]) -> int:
    """Index boundary after system + first user message (always preserved)."""

    end = 0
    seen_user = False
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "system":
            end = index
        elif role == "user" and not seen_user:
            end = index
            seen_user = True
            break
    return end


def json_digest(value: Any, *, max_chars: int = 200) -> str:
    """Bounded JSON digest used inside compaction summaries."""

    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return text[:max_chars]
