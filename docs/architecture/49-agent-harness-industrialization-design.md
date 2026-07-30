# 49. Agent Harness Industrialization & Self-Healing Scaffolding Architecture

## 1. Executive Summary

This specification defines the **Industrial-Grade Agent Harness & Tool-Calling Scaffolding Upgrade**.

Prior to this upgrade, tool execution failures, malformed JSON parameters, and simple keyword RAG searches resulted in unhandled exceptions or poor retrieval quality. This architecture introduces three industrial-grade scaffolding components:

1. **`ModelCallHarnessNormalizer`**: Normalizes, cleans, and sanitizes tool-calling payloads across heterogeneous LLM providers (DeepSeek-V3/R1, OpenAI, Claude, Qwen), handling raw JSON strings, code blocks, and function call schema variations.
2. **`ToolExecutionSelfHealer`**: Intercepts tool execution errors and feeds exact error stacktraces back into an LLM self-correction loop, automatically repairing parameters or attempting fallback tool execution before failing.
3. **`HybridRRFSearchEngine`**: Replaces mock embedding search in `RagService` with BM25 lexical token matching fused with Cosine Vector similarity via Reciprocal Rank Fusion (RRF, $k=60$).

```
+---------------------------------------------------------------------------------------+
|                             Agent Runtime Harness Architecture                         |
+---------------------------------------------------------------------------------------+
|  1. Model Call Normalizer    |  2. Tool Execution Self-Healer |  3. Hybrid BM25+RRF RAG   |
|  - Normalizes heterogeneous  |  - Intercepts tool exceptions  |  - Lexical BM25 + Vector  |
|    tool-calling schemas      |  - Auto-repairs malformed JSON |  - Reciprocal Rank Fusion |
|  - Cleans codeblock/text     |  - Fallback tool execution     |  - Dynamic RRF Scoring    |
+---------------------------------------------------------------------------------------+
```

---

## 2. Component Design

### 2.1 `ModelCallHarnessNormalizer`
Located in `backend/src/hypertrade/agent/planner.py`:
* **`normalize_tool_call(raw_call: dict[str, Any]) -> dict[str, Any]`**: Ensures `name` is a valid string, parses stringified `arguments` if necessary, strips invalid markdown fencing, and fills required default parameters.

### 2.2 `ToolExecutionSelfHealer`
Located in `backend/src/hypertrade/agent/planner.py`:
* **`execute_with_self_healing(tool_name, tool_args, executor_fn, llm_provider)`**:
  - Executes tool. If successful, returns result.
  - On error, constructs a self-repair context: `Tool '{name}' failed with error: {err_msg}`.
  - Queries LLM for a corrected tool call and retries execution.

### 2.3 `HybridRRFSearchEngine`
Located in `backend/src/hypertrade/rag/service.py`:
* **`search_hybrid(query, limit=5, rrf_k=60)`**: Computes lexical BM25 ranks $R_{lexical}$ and vector ranks $R_{vector}$, scoring each chunk by:
  $$\text{RRF\_Score}(d) = \frac{1}{k + R_{lexical}(d)} + \frac{1}{k + R_{vector}(d)}$$

---

## 3. Verification Plan

1. **Unit Tests (`tests/test_agent_harness_industrialization.py`)**:
   * Test malformed JSON tool call parsing & normalization.
   * Test tool execution error self-correction & fallback retry.
   * Test Hybrid BM25 + RRF RAG retrieval scoring.
2. **Integration Verification**:
   * Run full `./scripts/check.sh` suite ensuring 100% green tests.
