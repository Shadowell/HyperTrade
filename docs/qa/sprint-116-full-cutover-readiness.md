# Sprint 116 QA — Full Cutover, Professional UX & Readiness

## Verdict

**IN PROGRESS — implementation cutover is locally verified; operational Gate M remains open.** The
completion audit found legacy default paths and reopened the Sprint. The current local slice routes
the API/CLI/TUI/worker Mission surfaces through the canonical ledger and archives legacy write APIs
when the canary reaches 100%. Production canaries remain pending until the digest-bound isolated
sandbox service and deployed worker recovery have been exercised.

## Evidence

- Focused backend Mission/sandbox/readiness suite: 43 passed.
- `test_professional_agent_readiness.py`: 26 deterministic cases, including recovery, fault, safety
  and cursor coverage.
- Frontend lint passed; Vitest passed with 2 files / 9 tests; TypeScript/Vite production build passed.
- Ruff passed after import/line normalization; strict mypy passed for 169 source files.
- Reopened cutover slice: a provider-backed, catalog-bounded planner now replaces the single-step
  Foundation planner in application composition. API chat canary coverage proves a 100% canary writes
  only a Mission and replays the same idempotency key without an `AgentTask`/`AgentRun` row.
- Mission projections now build a public `OperatorResponseV1` solely from validated Mission facts.
  Its answer-first shape carries bounded provenance, explicit unknowns and safe next actions; a
  24-case public-answer catalog verifies contract shape and rejects runtime/tool-payload noise.
- Local TUI acceptance covers Mission list/detail/plan/evidence/cursor/control projection; a full
  canary rejects new `AgentTask` writes with HTTP 410. Public default-chat streaming emits bounded
  `answer_delta`, `evidence_ready`, `warning` and `final` event types.

## Scope verified

- React `/harness/missions` workspace uses Mission REST projections for list/detail/events and
  provides create/run/pause/resume/cancel/steer controls.
- Local CLI/TUI Mission clients use stable Mission ids and `Last-Event-ID` cursor replay; a separate
  disabled-by-default Mission worker owns SQL lease/heartbeat/release. At full canary, legacy task
  worker and trigger loops are suppressed and legacy APIs stay readable but reject writes.
- With the Mission worker flag enabled, API run requests enqueue into the Mission ledger and the
  authenticated Mission SSE endpoint tails cursor events until terminal state; the API process does
  not inline-dispatch that Mission.
- Readiness assertions fail if an unsafe dispatch or non-fail-closed write scope is reported.
- Production/staging without an immutable `AGENT_STRATEGY_SANDBOX_IMAGE` digest and UDS sandbox service
  constructs no host/API fallback and returns 503 when the sandbox endpoint is called; mutable image
  tags are rejected.
- Configured sandbox service has no Docker socket, uses network `none`, a read-only root filesystem,
  dropped capabilities, non-root UID, bounded tmpfs and bounded resources.
- Chat ingress is deterministic and Plan-free for a direct mainnet order request, approval-gated
  Testnet execution and excessive leverage; isolated-only evaluator fixtures are denied by default
  and terminalize without a provider or connector when explicitly enabled.

## Blocking scope still open

- Exercise Mission recovery/lease behavior through the deployed worker, not only synchronous API runs.
- Subscribe public mission progress to worker-owned event delivery for long runs. The current stream
  emits a prompt acceptance event immediately, then follows the worker-owned Mission before it
  projects evidence and conclusion; it is not yet a production worker-stream proof.
- Run the digest-bound isolated sandbox-service canary and record production health/migration evidence.

## Deferred operational gate

Run a deployment canary with the digest-bound isolated sandbox service. Verify network denial, secret
absence, resource/timeout termination, digest capture and migration/rollback before setting
`AGENT_STRATEGY_SANDBOX_ENABLED=true`. Do not enable paper/live/order/capital actions as part of
this canary.
