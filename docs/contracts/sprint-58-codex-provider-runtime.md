# Sprint 58 - Codex Provider Runtime

## Goal

Add Codex as a selectable HyperTrade chat/planner provider while preserving
HyperTrade ownership of tool execution, risk policy, trace, RAG, and Memory.

## Scope

- Add a `codex` provider slot backed by the Codex Responses API endpoint.
- Read Codex bearer credentials from server-only `CODEX_API_KEY` or
  `CODEX_AUTH_JSON` without exposing token values in provider status payloads.
- Support Hermes-style `openai-codex` as an alias for HyperTrade's `codex`
  provider name.
- Convert HyperTrade's existing chat-completions tool schemas and tool-result
  messages into the Codex Responses API shape inside the provider adapter.
- Document the runtime boundary and operator configuration.

## Out of Scope

- Handing an entire HyperTrade Agent turn to `codex app-server`.
- Letting Codex execute shell commands, patches, exchange actions, BitPro tools,
  or approval decisions outside HyperTrade's ToolRegistry and governance policy.
- Refreshing or mutating Codex/Hermes OAuth stores from HyperTrade.
- Mainnet live trading enablement.

## Acceptance

- `/providers`, `/model codex`, API provider selection, and frontend provider
  lists can show Codex with secret-redacted status.
- `ACTIVE_CHAT_PROVIDER=codex` and `ACTIVE_CHAT_PROVIDER=openai-codex` both
  route planner calls to the Codex provider when credentials are configured.
- Codex function-call outputs are parsed into HyperTrade `ToolCallRequest`
  records and tool outputs are sent back through `function_call_output` input
  items on the next planner turn.
- Missing Codex credentials keep the provider disabled and the Agent can still
  fall back to deterministic planning when Codex is selected without a token.
- `./scripts/check.sh` passes before deployment.

## Verification

```bash
uv run pytest tests/test_codex_provider.py tests/test_provider_runtime.py -q
./scripts/check.sh
```
