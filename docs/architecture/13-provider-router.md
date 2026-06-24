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

- `list_providers(selected=..., selected_models=...)`
- `get_chat_provider(selected=..., selected_model=...)`

## Supported Slots

| Provider | Runtime support | Notes |
| --- | --- | --- |
| DeepSeek | Enabled | Default provider. |
| OpenAI | Enabled via OpenAI-compatible adapter | Requires `OPENAI_API_KEY`. |
| Codex | Enabled via Responses API adapter | Requires `CODEX_API_KEY` or `CODEX_AUTH_JSON`; `openai-codex` is accepted as an alias, and selectable models come from `CODEX_MODEL_OPTIONS`. |
| OpenRouter | Enabled via OpenAI-compatible adapter | Requires `OPENROUTER_API_KEY` and model. |
| Qwen chat | Enabled via OpenAI-compatible adapter | Uses Qwen compatible-mode endpoint. |
| Anthropic/Gemini/Ollama | Status placeholders | Kept as extension slots. |

## Selection

- API: `POST /api/harness/provider-selection`
- CLI: interactive `/model` numbered selection and scripted `/model <provider>`
- Frontend: provider select in `/harness`

Provider and model selection are process/session state. They do not store
secrets or affect embedding provider selection. API model overrides are
validated against the selected provider's `model_options`; Codex options are
configured through `CODEX_MODEL_OPTIONS`, with `CODEX_MODEL` remaining the
default when no session override is selected.

## Codex Boundary

Codex follows the same provider-router contract as the other chat providers:
planner messages and function-call schemas go out, and `ToolCallRequest`
records come back. HyperTrade still executes the requested tools through
ToolRegistry, RiskGovernancePolicy, trace, and report rendering. This is
intentionally different from Hermes' optional `codex_app_server` runtime, which
hands an entire turn to a Codex subprocess; HyperTrade does not use that mode
because it would bypass the trading-system audit and approval boundary.
