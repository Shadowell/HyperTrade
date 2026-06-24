# 13 Provider Router

## Purpose

Provider Router decouples Agent planning from a single model vendor. DeepSeek remains the default, while OpenAI-compatible adapters support OpenAI, OpenRouter, and Qwen chat.

## Runtime Contract

```python
class ChatProvider(Protocol):
    name: str
    model: str
    def chat(messages, tools=None) -> ChatResponse: ...
```

`ProviderRuntime` exposes:

- `list_providers(selected=...)`
- `get_chat_provider(selected=...)`

## Supported Slots

| Provider | Runtime support | Notes |
| --- | --- | --- |
| DeepSeek | Enabled | Default provider. |
| OpenAI | Enabled via OpenAI-compatible adapter | Requires `OPENAI_API_KEY`. |
| Codex | Enabled via Responses API adapter | Requires `CODEX_API_KEY` or `CODEX_AUTH_JSON`; `openai-codex` is accepted as an alias. |
| OpenRouter | Enabled via OpenAI-compatible adapter | Requires `OPENROUTER_API_KEY` and model. |
| Qwen chat | Enabled via OpenAI-compatible adapter | Uses Qwen compatible-mode endpoint. |
| Anthropic/Gemini/Ollama | Status placeholders | Kept as extension slots. |

## Selection

- API: `POST /api/harness/provider-selection`
- CLI: `/model` and `/model <provider>`
- Frontend: provider select in `/harness`

Provider selection is process/session state. It does not store secrets or affect embedding provider selection.

## Codex Boundary

Codex follows the same provider-router contract as the other chat providers:
planner messages and function-call schemas go out, and `ToolCallRequest`
records come back. HyperTrade still executes the requested tools through
ToolRegistry, RiskGovernancePolicy, trace, and report rendering. This is
intentionally different from Hermes' optional `codex_app_server` runtime, which
hands an entire turn to a Codex subprocess; HyperTrade does not use that mode
because it would bypass the trading-system audit and approval boundary.
