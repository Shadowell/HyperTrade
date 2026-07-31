# MCP Circuit Breaker & Tool Risk Governance Scaffolding Architecture Specification

## 1. Executive Summary

This document specifies the **MCP Circuit Breaker & Tool Risk Governance Scaffolding 2.5** for HyperTrade. It isolates external MCP server failures, prevents agent hangs on unresponsive endpoints, normalizes complex MCP schemas, and enforces 3-tier risk permissions.

---

## 2. Architecture & Components

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                                      HyperTrade Industrial MCP & Tool Governance                                              |
+------------------------------------+------------------------------------+-----------------------------------------------------+
| 1. MCP Dynamic Schema Translator   | 2. MCP Connection Circuit Breaker  | 3. Tool Risk Governance Sandbox Guard               |
| - Flattens complex MCP $ref/allOf  | - Closed / Open / Half-Open states | - L1 Read-Only: Auto-pass                           |
|   into LLM-optimal JSON Schemas    | - Prevents agent hang on dead MCPs | - L2 Paper-Write: Sandbox check                     |
|                                    | - Gracefully degrades tool search  | - L3 Live-Order: Requires ApprovalToken             |
+------------------------------------+------------------------------------+-----------------------------------------------------+
```

### 2.1 MCP Dynamic Schema Translator (`MCPToolSchemaTranslator`)
Flattens `$ref`, `allOf`, and deeply nested properties into standard flat JSON schemas optimal for LLMs (DeepSeek, Claude, Qwen).

### 2.2 MCP Connection Circuit Breaker (`MCPConnectionCircuitBreaker`)
Implements standard 3-state circuit breaker logic:
- **Closed**: Requests flow normally. Failure counter resets on success.
- **Open**: After 3 consecutive timeouts/502 errors, requests are blocked for 30s. Returns structured degradation payload: `{"status": "degraded", "reason": "MCP Circuit Opened"}`.
- **Half-Open**: Allows 1 probe request after cooldown to test endpoint health.

### 2.3 Tool Risk Governance Sandbox Guard (`ToolCallPermissionSandboxGuard`)
Categorizes tools into 3 security tiers:
- `L1_READ_ONLY`: Market queries, RAG, memory reads (Auto-approved).
- `L2_SIMULATED_WRITE`: Paper trading config updates (Sandbox validated).
- `L3_CRITICAL_LIVE_WRITE`: Live order submission/cancellation (Requires valid `approval_token`).

---

## 3. Verification Plan

1. **Unit Tests**: `tests/test_mcp_harness.py`
2. **Integration Verification**: Run `./scripts/check.sh` ensuring all tests pass.
