# Sprint 115 QA - Sandboxed Strategy Development

## Verdict

PASS for the local/CI contract; production activation remains deliberately fail-closed until the
rootless container canary in Sprint 116.

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

- `uv run pytest tests/test_strategy_sandbox.py tests/test_sandbox_isolation.py -q` -> **20 passed**.
- `uv run ruff check backend tests` -> passed.
- `uv run mypy backend/src` -> passed.
- `git diff --check` -> passed.
- `./scripts/check.sh` -> frontend lint/test/build, Ruff, strict mypy and **605 Python tests passed**
  in 131.98s.

## Production status

No production sandbox run or BitPro import was performed. The feature flag remains disabled by
default. A production rollout must first provide a rootless Docker/OCI adapter with network-none,
read-only filesystem, non-root UID, cgroup/pids limits, no host Docker socket and a canary escape
suite. Until then, the API fails closed rather than claiming isolation.

## Next

Sprint 116 should implement the container deployment adapter and the professional Mission operator
workspace (REST/SSE replay, plan/step/artifact ledger, pause/resume/steer/review) before deleting old
runtime write paths.
