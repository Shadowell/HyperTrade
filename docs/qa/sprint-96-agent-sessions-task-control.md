# Sprint 96 Agent Sessions and Task Control QA

## Verdict

Final verdict: **PASS**. Local gates, production deployment, PostgreSQL-backed
Task persistence, cursor reads, and remote CLI smokes all completed successfully.

## Contract Review

### Passed

- Durable Session, Task, Node Run, Checkpoint, and Event models exist with an
  Alembic migration.
- Task creation and its first Event commit in one transaction; database unique
  constraints and race handling enforce idempotency.
- pause/resume/cancel/retry/branch use one deterministic transition service and
  persist operator, reason, idempotency key, status history, and cursor events.
- Running Task pause is honored at an Agent event safe point and creates a
  checkpoint before becoming paused.
- PostgreSQL workers use skip-locked claims, lease ownership, heartbeat, and
  fail-closed expired-lease recovery.
- Task events use monotonic per-Task sequence numbers, recursive redaction, REST
  cursor reads, `Last-Event-ID`, and SSE ids.
- AgentKernel one-shot runs are Task-backed in local CLI and API modes; legacy
  AgentRun endpoints and renderers remain compatible.
- `httpx.TimeoutException` becomes a retryable `provider_timeout` Task error in
  `retry_wait`, with a checkpoint and structured API/SSE error boundary.
- CLI exposes `/sessions`, `/tasks`, and `/task <id> [control] [reason]` in local
  and remote modes.
- Worker execution runs outside the main asyncio loop and renews its lease while
  a synchronous provider/tool attempt is in flight.

### Failed

- None in the Sprint 96 implementation or focused regression suite.

### Not Checked

- A forced production worker crash during a non-idempotent external write was not
  induced because doing so would cross the safe smoke-test boundary. The fail-closed
  reconciliation path is covered by deterministic service tests.
- Multi-worker claim contention was not artificially generated on production. The
  PostgreSQL `FOR UPDATE SKIP LOCKED` query and lease ownership behavior are covered
  by focused tests and the deployed worker uses that path.

## Verification Evidence

- Focused Task/Session/Event/CLI/worker/API regression: `101 passed`.
- Full `./scripts/check.sh`: frontend lint/test/build, Ruff, Mypy, and Python
  tests passed (`350 passed`).
- `0012_agent_sessions_tasks` on a temporary SQLite database stamped at `0011`:
  upgrade, downgrade, and upgrade passed.
- A fresh full SQLite Alembic chain is not a supported validation path because
  historical `0001_initial` contains PostgreSQL-only `CREATE EXTENSION vector`.
  The applied migration was not rewritten; local SQLite development continues
  to use `Database.create_all()`.
- Implementation commit `65c8a41` deployed successfully in GitHub Actions run
  `29338187375`; the deployment applied the PostgreSQL migration and restarted the
  production API/worker.
- Production Agent run `run_e2c36d58611f4c49ba5f` completed as durable Session
  `ses_dd5306ed19374f1b94b2` and Task `task_dd509a0e4b924187bafa`, with checkpoint
  `tcp_0698fd674ca0437fb36b` and 25 monotonic events.
- Cursor requests after sequence 0 and 3 returned `1..3` and `4..6`; remote CLI
  `/sessions`, `/tasks`, and `/task task_dd509a0e4b924187bafa` returned the same
  completed Task projection.
- Production `GET /api/health` returned
  `{"status":"ok","service":"hypertrade-api"}` after deployment and smokes.

## Next

Activate Sprint 97 and implement the structured Research Evidence contract on top
of the completed Session/Task control plane.
