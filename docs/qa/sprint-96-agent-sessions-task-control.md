# Sprint 96 Agent Sessions and Task Control QA

## Verdict

Local verdict: **PASS**. Production deployment: **PENDING** until the implementation
commit is deployed and PostgreSQL migration/API/CLI smokes complete.

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

### Not Checked Yet

- Production PostgreSQL migration and `FOR UPDATE SKIP LOCKED` behavior, pending
  deployment of the implementation commit.
- Production remote CLI/API smoke, pending deployment.

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

## Next

1. Run the final full repository gate after all Sprint 96 code/docs changes.
2. Push the implementation commit and verify the production deployment/migration.
3. Run health, Session/Task API, cursor Event, worker, and remote CLI smokes.
4. Change this verdict to final PASS, close Sprint 96, and activate Sprint 97.
