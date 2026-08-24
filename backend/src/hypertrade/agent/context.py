"""Context budget management for the planner loop.

The planner's message history used to be bounded only by MAX_ITERATIONS and
per-tool water-cooling; total history grew unmanaged. This module adds a
deterministic token estimator and a protocol-preserving compaction pass so
long research loops (backtest -> gate -> promotion) can run more iterations
without silently blowing the provider context window.

Compaction keeps the OpenAI message protocol valid: an assistant message with
tool_calls and its tool responses form one group, and compacting a group
replaces it with a single assistant message (no tool_calls) carrying a
structured digest. System and the first user message are never touched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_CJK_RANGES = (
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x3000, 0x303F),  # CJK Symbols and Punctuation
    (0xFF00, 0xFFEF),  # Fullwidth Forms
)


def estimate_tokens(text: str) -> int:
    """Deterministic CJK-aware token estimate.

    CJK characters are roughly one token each; other scripts average ~4
    chars/token. This drives compaction triggers only, never billing.
    """
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        code = ord(char)
        if any(start <= code <= end for start, end in _CJK_RANGES):
            cjk += 1
        else:
            other += 1
    return cjk + (other + 3) // 4


def estimate_message_tokens(message: dict[str, Any]) -> int:
    parts: list[str] = [str(message.get("role", "")), str(message.get("content", "") or "")]
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if isinstance(call, dict):
                function = call.get("function")
                if isinstance(function, dict):
                    parts.append(str(function.get("name", "")))
                    parts.append(str(function.get("arguments", "")))
    if message.get("tool_call_id"):
        parts.append(str(message["tool_call_id"]))
    return estimate_tokens(" ".join(parts))


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
    """Compact old tool-result groups when history exceeds the token budget.

    Returns the original list unchanged (same objects) when under budget.
    Compactable groups are (assistant with tool_calls) + following tool
    responses; each compacted group becomes one assistant message whose
    content records the tool names and bounded result digests. Recent groups
    are preserved verbatim so the model keeps the freshest evidence.
    """

    total = estimate_messages_tokens(messages)
    if total <= max_history_tokens:
        return CompactionResult(messages=messages, compacted_groups=0)

    # Locate groups: (assistant_index_with_tool_calls, [tool_response_indexes]).
    groups: list[tuple[int, list[int]]] = []
    current: tuple[int, list[int]] | None = None
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant" and isinstance(message.get("tool_calls"), list):
            current = (index, [])
            groups.append(current)
        elif role == "tool" and current is not None:
            current[1].append(index)
        elif role in {"user", "system"}:
            current = None
    if len(groups) <= keep_recent_groups:
        return CompactionResult(messages=messages, compacted_groups=0)

    # Never touch system/first user prefix or the most recent groups.
    compactable = groups[:-keep_recent_groups] if keep_recent_groups > 0 else groups
    prefix_end = _prefix_end(messages)
    compactable = [
        (assistant_index, tool_indexes)
        for assistant_index, tool_indexes in compactable
        if assistant_index > prefix_end
    ]
    if not compactable:
        return CompactionResult(messages=messages, compacted_groups=0)

    drop_indexes: set[int] = set()
    replacements: dict[int, dict[str, Any]] = {}
    for assistant_index, tool_indexes in compactable:
        assistant = messages[assistant_index]
        digest_parts: list[str] = []
        for tool_index in tool_indexes:
            tool_message = messages[tool_index]
            name = str(tool_message.get("name", "tool"))
            content = str(tool_message.get("content", "") or "")
            digest_parts.append(f"{name}: {content[:200]}")
            drop_indexes.add(tool_index)
        drop_indexes.add(assistant_index)
        original_content = str(assistant.get("content", "") or "")[:200]
        replacements[assistant_index] = {
            "role": "assistant",
            "content": (
                "[compacted earlier step] "
                f"{original_content} "
                f"tools executed: {'; '.join(digest_parts)}"
            ).strip()[:1200],
        }

    compacted: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if index in drop_indexes:
            if index in replacements:
                compacted.append(replacements[index])
            continue
        compacted.append(message)

    # One aggressive second pass if still over budget: keep fewer recent groups.
    if estimate_messages_tokens(compacted) > max_history_tokens and keep_recent_groups > 1:
        return compact_messages(
            messages,
            max_history_tokens=max_history_tokens,
            keep_recent_groups=max(1, keep_recent_groups // 2),
        )
    return CompactionResult(messages=compacted, compacted_groups=len(compactable))


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
