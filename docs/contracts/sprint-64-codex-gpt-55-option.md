# Sprint 64 - Codex GPT-5.5 Model Option

## Goal

Add `gpt-5.5` to the default Codex model allowlist so it appears in the
numbered CLI model picker without requiring operators to edit configuration
first.

## In Scope

- Add `gpt-5.5` to the default `CODEX_MODEL_OPTIONS` setting.
- Keep `CODEX_MODEL=gpt-5.4` as the default selected Codex model.
- Update `.env.example` so new deployments show the same default model list.
- Add a provider-runtime regression test for the default Codex option order.
- Update project progress/spec documentation.

## Out of Scope

- Auto-discovering model names from the Codex backend.
- Persisting model choices into `.env`.
- Changing provider authentication or token handling.

## Done Means

- The default Codex model options are `gpt-5.4`, `gpt-5.5`, and
  `gpt-5.4-mini`.
- Explicit `CODEX_MODEL_OPTIONS` environment values still override the default
  allowlist.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_codex_provider.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run `/model` or `/model c` in the CLI and confirm `gpt-5.5` appears in the
  Codex model list when production does not override `CODEX_MODEL_OPTIONS`.

## Risks / Notes

- This only adds `gpt-5.5` to the local allowlist. Actual request success still
  depends on the connected Codex backend accepting that model name for the
  configured token.
