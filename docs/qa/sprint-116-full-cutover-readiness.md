# Sprint 116 QA — Full Cutover, Professional UX & Readiness

## Verdict

**IN PROGRESS — completion audit reopened the Sprint.** The initial Mission workspace, readiness
contract and fail-closed production sandbox wiring passed locally, but the audit found that the
default chat API, local CLI/TUI and worker still use legacy `AgentKernel`/`AgentTask` write paths.
That contradicts the full-cutover contract. The production canary also remains pending because no
reviewed rootless Docker image/digest is available in this environment.

## Evidence

- Focused backend Mission/sandbox/readiness suite: 43 passed.
- `test_professional_agent_readiness.py`: 26 deterministic cases, including recovery, fault, safety
  and cursor coverage.
- Frontend lint passed; Vitest passed with 2 files / 9 tests; TypeScript/Vite production build passed.
- Ruff passed after import/line normalization; strict mypy passed for 169 source files.
- Reopened cutover slice: a provider-backed, catalog-bounded planner now replaces the single-step
  Foundation planner in application composition. API chat canary coverage proves a 100% canary writes
  only a Mission and replays the same idempotency key without an `AgentTask`/`AgentRun` row.

## Scope verified

- React `/harness/missions` workspace uses Mission REST projections for list/detail/events and
  provides create/run/pause/resume/cancel/steer controls.
- Readiness assertions fail if an unsafe dispatch or non-fail-closed write scope is reported.
- Production/staging without `AGENT_STRATEGY_SANDBOX_IMAGE` constructs no host fallback and returns
  503 when the sandbox endpoint is called.
- Configured container adapter has no host Docker socket, uses network `none`, read-only mounts,
  dropped capabilities, non-root UID and bounded resources.

## Blocking scope still open

- Migrate local CLI, Textual task creation and worker execution to the canonical Mission path; leave
  legacy Task/Run endpoints as historical read-only queries only.
- Exercise Mission recovery/lease behavior through the deployed worker, not only synchronous API runs.
- Run the pinned rootless sandbox image canary and record production health/migration evidence.

## Deferred operational gate

Run a deployment canary with a pinned reviewed rootless image. Verify network denial, secret absence,
resource/timeout termination, digest capture and migration/rollback before setting
`AGENT_STRATEGY_SANDBOX_ENABLED=true`. Do not enable paper/live/order/capital actions as part of
this canary.
