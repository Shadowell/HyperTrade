# Sprint 61 - CLI Codex Model Picker

## Goal

Make chat provider/model switching list-selectable from the CLI so operators do
not need to type Codex model names manually.

## In Scope

- Add a Codex model allowlist setting through `CODEX_MODEL_OPTIONS`, with
  `CODEX_MODEL` remaining the default.
- Expose provider `model_options` through secret-redacted provider status.
- Let API provider selection accept and validate an optional session model.
- Let local and remote CLI `/model` render numbered provider choices, then a
  numbered Codex model list when Codex is selected.
- Pass the selected session model into `AgentKernel` chat/planner provider
  creation.

## Out of Scope

- Letting arbitrary user-entered model strings bypass configured options.
- Frontend provider/model picker redesign.
- Changing RAG embedding provider selection.
- Letting Codex execute HyperTrade tools, approvals, shell commands, or trading
  actions directly.

## Deliverables

- Provider runtime support for `model_options` and selected model overrides.
- API provider-selection support for validated `model`.
- CLI numbered selection flow for provider and Codex model.
- Tests for provider runtime, API payload validation, and CLI list selection.
- README/spec/architecture/progress documentation updates.

## Done Means

- Interactive `/model` can switch to Codex and choose a Codex model by number.
- `/model <provider>` remains available for scripts and smoke tests.
- Provider status and API responses never expose Codex tokens.
- Invalid model choices are rejected.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_codex_provider.py tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run `printf "/model\n2\n2\n:q\n" | uv run hypertrade --local` in a local
  environment with Codex configured and confirm the selected model is reflected.
- On production, run the host `hypertrade` wrapper with `/model` and confirm the
  numbered provider list appears without requiring typed model names.

## Risks / Notes

- Existing production Codex credentials may be absent; this feature should still
  list configured options and show Codex as disabled/missing without exposing
  auth material.
- The selected model is session/process state and intentionally does not mutate
  `.env` or persist secrets.
