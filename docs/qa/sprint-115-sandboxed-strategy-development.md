# Sprint 115 QA - Sandboxed Strategy Development

## Verdict

PASS. The local/CI contract and the rootless production canary are closed. Source defaults remain
fail-closed; the production feature was enabled only after the Sprint 116 boundary checks passed.

## Contract review

- PASS: only `strategies/` and `tests/` Python/JSON/YAML files are accepted; traversal, symlink-like
  paths, binary content, forbidden imports, dynamic execution and unsafe command arguments are denied.
- PASS: lint, pytest and the deterministic limited-backtest contract must all pass before a run is
  `validated`; failed and timed-out runs never become validated.
- PASS: command output is bounded through a temporary file, `output_bytes` is recorded, and timeout
  cleanup kills the complete process group. CPU, file-size, file-descriptor and process-count
  limits are applied where supported by the host kernel.
- PASS: source-file, patch, command-output and manifest metadata are content-addressed in the
  `SandboxArtifactV1` ledger; ephemeral workspace contents are discarded.
- PASS: SQL projection/migration `0027_agent_sandbox` persists runs, artifacts and append-only review
  facts. API source artifact refs must resolve to current Mission artifact stable refs.
- PASS: review accept/reject is hash-bound and idempotency keys reject canonical-content mismatch;
  accept records a proposal only and never calls BitPro or an execution tool.
- PASS: `APP_ENV=production|staging` rejects the host subprocess fallback with HTTP 503 when no
  rootless container adapter is configured.

## Verification

- `uv run pytest tests/test_strategy_sandbox.py tests/test_sandbox_isolation.py -q` -> **21 passed**.
- `uv run ruff check backend tests` -> passed.
- `uv run mypy backend/src` -> passed.
- `git diff --check` -> passed.
- `./scripts/check.sh` -> frontend lint/test/build, Ruff, strict mypy and **605 Python tests passed**
  in 131.98s.

## Production status

Sprint 116 verified the rootless service with `network=none`, read-only root, UID/GID `65532`, no
Docker socket or provider/BitPro credentials, bounded PID/memory/CPU/tmpfs resources and an immutable
image digest. A valid lint/test/limited-backtest run passed; network imports were rejected before
execution; CPU and wall-time limits terminated adversarial candidates; and sandbox review recorded
`external_write_performed=false`. No BitPro import, paper, live, order or capital action occurred.

## Follow-up

Keep the source defaults fail-closed and require the same canary evidence for any new deployment.
Future work may add an explicit, separately governed BitPro import workflow; sandbox acceptance itself
must remain a no-import proposal fact.
