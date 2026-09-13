"""Sprint-141: planner context engineering — token estimation and compaction.

Compaction must keep the OpenAI message protocol valid (assistant tool_calls
paired with their tool responses), preserve the system+first-user prefix and
the most recent groups verbatim, and never touch small histories.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypertrade.agent.compaction import ContextBlocked
from hypertrade.agent.context import (
    compact_messages,
    estimate_messages_tokens,
    estimate_tokens,
)
from hypertrade.agent.planner import AgentPlanner
from hypertrade.providers.chat import ChatResponse, ToolCallRequest


def test_token_estimator_is_cjk_aware() -> None:
    ascii_tokens = estimate_tokens("abcdefgh")
    cjk_tokens = estimate_tokens("研究BTC趋势策略")  # 6 CJK + 3 ascii

    assert ascii_tokens == 8
    assert cjk_tokens == 6 * 3 + 3  # UTF-8 bytes, not average tokenization


def test_small_history_passes_through_unchanged() -> None:
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hello"},
    ]

    result = compact_messages(messages, max_history_tokens=24_000)

    assert result.compacted_groups == 0
    assert result.messages is messages  # same objects, zero copies


def _tool_group(index: int, result_chars: int = 3_000) -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": "market_candles",
                        "arguments": json.dumps({"symbol": "BTC", "limit": 100}),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": f"call_{index}",
            "name": "market_candles",
            "content": json.dumps({"candles": [12345] * result_chars}),
        },
    ]


def _large_history(groups: int = 10) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "研究 BTC 走势"},
    ]
    for index in range(groups):
        messages.extend(_tool_group(index))
    return messages


def test_compaction_preserves_protocol_and_recent_groups() -> None:
    messages = _large_history(10)
    before_tokens = estimate_messages_tokens(messages)

    result = compact_messages(messages, max_history_tokens=100_000, keep_recent_groups=4)

    assert result.compacted_groups >= 1
    assert estimate_messages_tokens(result.messages) < before_tokens

    # Protocol validity: every tool message is directly preceded by the
    # assistant that called it; compacted groups appear as plain assistants.
    for index, message in enumerate(result.messages):
        if message.get("role") == "tool":
            previous = result.messages[index - 1]
            assert previous.get("role") == "assistant"
            calls = previous.get("tool_calls")
            assert isinstance(calls, list) and calls
            assert any(call["id"] == message["tool_call_id"] for call in calls), (
                "tool response must follow its own assistant call"
            )

    # Prefix (system + first user) untouched.
    assert result.messages[0]["content"] == "system prompt"
    assert result.messages[1]["content"] == "研究 BTC 走势"

    # Calls and results stay together; only old numeric arrays become digests.
    payloads = [json.loads(m["content"]) for m in result.messages if m["role"] == "tool"]
    assert any(isinstance(p["candles"], dict) for p in payloads)
    assert all(isinstance(p["candles"], list) for p in payloads[-4:])


def test_compaction_second_pass_reaches_budget() -> None:
    messages = _large_history(16)

    result = compact_messages(messages, max_history_tokens=100_000, keep_recent_groups=4)

    assert estimate_messages_tokens(result.messages) <= 100_000
    assert result.compacted_groups >= 1


class _ReplayProvider:
    """Replays N tool-call rounds then a final answer; records history sizes."""

    def __init__(self, tool_rounds: int, *, result_chars: int = 6_000) -> None:
        self._responses: list[ChatResponse] = []
        for index in range(tool_rounds):
            self._responses.append(
                ChatResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{index}",
                            name="market_candles",
                            arguments={"symbol": "BTC", "limit": 100},
                        )
                    ],
                )
            )
        self._responses.append(ChatResponse(content="## 结论\n研究完成。"))
        self.calls: list[int] = []
        self.seen: list[list[dict[str, Any]]] = []
        self.name = "replay"
        self.model = "context-test"
        self._result_chars = result_chars

    def chat(self, messages: list[dict[str, Any]], tools=None) -> ChatResponse:
        self.calls.append(estimate_messages_tokens(messages))
        self.seen.append(json.loads(json.dumps(messages)))
        return self._responses.pop(0)

    def _tool_result(self) -> dict[str, Any]:
        return {"candles": ["x" * self._result_chars]}


def test_planner_compacts_history_and_completes_long_loop() -> None:
    provider = _ReplayProvider(tool_rounds=9)
    records = []
    planner = AgentPlanner(provider, max_history_tokens=120_000, context_sink=records.append)

    def executor(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"candles": [12345] * 6_000}

    result = planner.run("研究 BTC 走势", executor)

    assert result.final_message.startswith("## 结论")
    assert result.context_compactions >= 1
    assert result.history_tokens_last <= 120_000
    assert max(provider.calls) <= 120_000
    assert all(r["manifest"]["final_tokens_upper_bound"] <= 120_000 for r in records)
    # Full executed results remain in PlannerResult while the recovery record
    # contains exactly the bounded request sent to the provider.
    assert all(len(call.output_json["candles"]) == 6000 for call in result.tool_calls)
    assert records[-1]["request_messages"] == provider.seen[-1]


def test_planner_small_history_never_compacts() -> None:
    provider = _ReplayProvider(tool_rounds=2, result_chars=200)
    planner = AgentPlanner(provider, max_history_tokens=64_000)

    result = planner.run("看下 BTC", lambda name, args: {"ok": True})

    assert result.context_compactions == 0
    assert result.history_tokens_last > 0


def test_oversized_opaque_evidence_is_blocked():
    with pytest.raises(ContextBlocked):
        compact_messages(_large_history(), max_history_tokens=200)
