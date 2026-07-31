# Tool Result Cache & Prompt Cache Prefix Aligner Architecture Specification

## 1. Executive Summary

This document specifies the **Tool Result Cache & Prompt Cache Prefix Aligner** for HyperTrade (Harness 3.0). It optimizes API latency, token consumption, and network overhead by introducing MD5-keyed LRU result caching and KV prompt prefix alignment.

---

## 2. Architecture & Components

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                               Tool Result Cache & Prompt Cache Prefix Alignment                                               |
+-------------------------------------------------------+-----------------------------------------------------------------------+
| 1. Tool Result LRU Cache (ToolResultLRUCache)         | 2. KV Prompt Cache Prefix Aligner (PromptCachePrefixAligner)           |
| - Key: MD5(tool_name + sorted_json_args)              | - Static Prefix: System Prompt -> Rules -> Tools                      |
| - TTL: 15s for market read tools                      | - Dynamic Suffix: Conversational turns & memory                       |
| - Invalidation: Clears on state-modifying write tools | - Hit Rate: 50%~90% KV cache hit rate on DeepSeek V3 / Claude 3.5     |
+-------------------------------------------------------+-----------------------------------------------------------------------+
```

### 2.1 Tool Result LRU Cache (`ToolResultLRUCache`)
- **MD5 Hash Keying**: Computes deterministic hash keys from tool names and canonicalized JSON arguments.
- **TTL Expiration**: Serves cached responses for read-only tools within TTL (default 15s).
- **Write Invalidation**: Automatically clears cached entries when write operations execute.

### 2.2 KV Prompt Cache Prefix Aligner (`PromptCachePrefixAligner`)
- **Prefix Isolation**: Reorders System Prompts, System Directives, and Tool Schemas to the exact start of the message payload.
- **KV Cache Optimization**: Guarantees identical prefix bytes across API calls, maximizing provider-level KV cache hits (DeepSeek, Claude, Qwen, Gemini).

---

## 3. Verification Plan

1. **Unit Tests**: `tests/test_harness_cache.py`
2. **Integration Verification**: Run `./scripts/check.sh` ensuring all tests pass.
