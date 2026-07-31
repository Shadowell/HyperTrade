"""
Unit Tests for Advanced Context Management 2.0 (context_v2.py)
"""

from hypertrade.agent.context_v2 import (
    DynamicTokenBudgetManager,
    SemanticContextPruner,
    TurnSlidingWindowSummarizer,
)


def test_dynamic_token_budget_manager():
    mgr_deepseek = DynamicTokenBudgetManager("deepseek-chat")
    assert mgr_deepseek.max_tokens == 128000
    assert mgr_deepseek.get_budget("tool_history") > 0
    assert mgr_deepseek.is_within_budget("system", 1000) is True

    mgr_qwen = DynamicTokenBudgetManager("qwen-2.5-72b")
    assert mgr_qwen.max_tokens == 32000
    assert mgr_qwen.get_budget("tool_history") < mgr_deepseek.get_budget("tool_history")


def test_semantic_context_pruner():
    pruner = SemanticContextPruner(max_payload_chars=200)

    small_dict = {"status": "ok", "symbol": "BTC-USDT"}
    assert pruner.prune(small_dict) == small_dict

    large_dict = {
        "status": "ok",
        "items": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "description": "X" * 500,
    }
    pruned = pruner.prune(large_dict)
    assert pruned["_semantic_pruned"] is True
    assert len(pruned["items"]) == 6  # 2 head + 1 message string + 3 tail
    assert "... [Folded text] ..." in pruned["description"]


def test_turn_sliding_window_summarizer():
    summarizer = TurnSlidingWindowSummarizer(max_turns=6)

    messages = [
        {"role": "system", "content": "You are a quant assistant."},
        {"role": "user", "content": "Goal: Optimize WTI strategy."},
    ] + [
        {
            "role": "assistant" if i % 2 == 0 else "tool",
            "content": f"Step {i}",
            "tool_name": f"tool_{i}",
            "tool_call_id": f"call_{i}",
        }
        for i in range(10)
    ]

    compressed = summarizer.compress_messages(messages)
    assert len(compressed) < len(messages)
    assert compressed[0]["role"] == "system"
    assert compressed[1]["role"] == "user"
    assert "[Historical Executive Summary]" in compressed[2]["content"]
