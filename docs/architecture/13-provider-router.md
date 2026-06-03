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
| OpenRouter | Enabled via OpenAI-compatible adapter | Requires `OPENROUTER_API_KEY` and model. |
| Qwen chat | Enabled via OpenAI-compatible adapter | Uses Qwen compatible-mode endpoint. |
| Anthropic/Gemini/Ollama | Status placeholders | Kept as extension slots. |

## Selection

- API: `POST /api/harness/provider-selection`
- CLI: `/model` and `/model <provider>`
- Frontend: provider select in `/harness`

Provider selection is process/session state. It does not store secrets or affect embedding provider selection.

