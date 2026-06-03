# Sprint 25 Contract: Provider Router

## Goal

Turn provider configuration from display-only metadata into an actual chat-provider routing surface.

## Scope

- Add a `ChatProvider` protocol and OpenAI-compatible adapter.
- Keep DeepSeek as default provider.
- Expose OpenAI, OpenRouter, Qwen chat, Anthropic, Gemini, and Ollama status slots.
- Add API provider selection for the current API process.
- Add CLI `/model` and `/model <provider>`.
- Do not persist or return API keys.

## Acceptance

- DeepSeek remains the default configured provider.
- Missing provider keys are shown as `missing` without crashing the system.
- CLI and API can switch the active session provider.
- Provider switching affects chat/planner only, not embedding provider.

## Verification

```bash
uv run pytest tests/test_api.py::test_api_can_switch_active_provider_without_exposing_keys tests/test_cli.py -q
./scripts/check.sh
```

