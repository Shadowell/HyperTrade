"""
Unit Tests for Tool Result LRU Cache & Prompt Cache Prefix Aligner (harness_cache.py)
"""

import time

from hypertrade.agent.harness_cache import PromptCachePrefixAligner, ToolResultLRUCache


def test_tool_result_lru_cache():
    cache = ToolResultLRUCache(max_size=10, default_ttl_sec=0.1)

    read_tool = "market_ticker"
    args = {"symbol": "BTC-USDT"}
    result = {"price": 95000}

    # Miss
    assert cache.get(read_tool, args) is None

    # Put
    cache.put(read_tool, args, result)

    # Hit
    hit = cache.get(read_tool, args)
    assert hit is not None
    assert hit["price"] == 95000

    # Non-read tool should never cache
    cache.put("submit_live_order", args, result)
    assert cache.get("submit_live_order", args) is None

    # TTL Expiration
    time.sleep(0.12)
    assert cache.get(read_tool, args) is None

    # Invalidation on write
    cache.put(read_tool, args, result)
    assert cache.get(read_tool, args) is not None
    cache.invalidate_on_write("update_paper_config")
    assert cache.get(read_tool, args) is None


def test_prompt_cache_prefix_aligner():
    system_prompt = "You are a quantitative trader."
    rules = ["Do not commit secrets", "Pass check.sh"]
    tools_schema = [{"name": "market_ticker", "description": "Fetch ticker"}]
    dynamic_messages = [{"role": "user", "content": "Analyze BTC"}]

    aligned = PromptCachePrefixAligner.align_prompt_prefix(
        system_prompt, rules, tools_schema, dynamic_messages
    )

    assert len(aligned) == 2
    assert aligned[0]["role"] == "system"
    assert "You are a quantitative trader." in aligned[0]["content"]
    assert "### SYSTEM RULES" in aligned[0]["content"]
    assert "### AVAILABLE TOOL SCHEMAS" in aligned[0]["content"]
    assert aligned[1]["content"] == "Analyze BTC"
