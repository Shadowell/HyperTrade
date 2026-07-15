# Sprint 111 QA - Professional Agent Runtime Foundation

## Verdict

PASS. Gate I is closed for the foundation slice. Production execution remains feature-flagged off
and read-only; no paper, live, order or capital permission changed.

## Contract Review

- PASS: infrastructure-free frozen Mission/Plan/Step/Observation contracts and DAG validation.
- PASS: hard plan/step/attempt/model/tool/token limits cannot be expanded by planner output.
- PASS: adaptive continue/retry/replan/wait/fail/complete loop with safe-point pause/cancel/steer.
- PASS: immutable Plan versions, Step attempts, steering facts and cursor events.
- PASS: async SQLAlchemy store with optimistic version checks and PostgreSQL transactions.
- PASS: successful observations require provenance; structured criteria, not model prose, complete a
  Mission.
- PASS: authenticated REST/SSE Mission projection and execution feature flag defaulting to false.
- PASS: OpenTelemetry mission/step spans contain bounded identifiers and no private reasoning.
- PASS: GitNexus audit found no reverse dependency from the new runtime to AgentKernel.
- PASS: new Mission execution did not write AgentTask or AgentRun.

## Verification

- `tests/test_agent_missions.py` and `tests/test_adaptive_agent_loop.py`: 24 passed, covering
  persistence, API, provenance, completion refusal, retries, replan, steer, optimistic conflicts,
  safe-point controls, invalid DAGs, unknown/write capability denial and hard budgets.
- `./scripts/check.sh`: frontend lint, 9 frontend tests and production build passed; Ruff and strict
  mypy passed; 547 Python tests passed.
- PostgreSQL deployment upgraded to `0023_agent_missions`; `0023 -> 0022 -> 0023` round trip passed.
- Production read-only canary Mission `mis_6d0be4e48e0d4990b0f6` completed with one Plan and one tool
  call. Counts changed from `[AgentTask=4, AgentRun=153, AgentMission=0]` to `[4,153,1]`, proving no
  legacy dual write. Migration round trip then removed the canary and retained `[4,153,0]`.
- Deployment workflow `29425203712` succeeded at SHA `6435110`; API health remained OK and
  `MISSION_RUNTIME_ENABLED=False` was confirmed in production.

## Historical Issues Corrected

- Evidence tests no longer expire against wall-clock dates baked into fixtures.
- World-model scenario tests inject their global-market collector instead of using unstable live
  network state while asserting determinism.

## Not Checked

- Provider-backed dynamic planning, reviewed capability discovery and external tool execution are
  intentionally deferred to Sprint 112.
- Multi-Agent, Context Pack, sandbox and final UI cutover remain outside this contract.

## Next

Activate Sprint 112. It must add a reviewed Capability Catalog and typed ToolObservation runtime
without weakening Sprint 111 budgets, state transitions, provenance or approval boundaries.
