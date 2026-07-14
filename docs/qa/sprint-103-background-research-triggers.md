# Sprint 103 Background Research Triggers QA

## Verdict

PASS. Durable trigger persistence, bounded committed-event adapters, transactional
Task-only dispatch, lease/restart behavior, operator controls, default-off deployment
and production PostgreSQL migration passed.

## Scope Checked

- schedule/regime/drift/data-quality/evaluation trigger schemas and condition bounds;
- fingerprint/time-bucket dedupe, cooldown, per-trigger/global quota and kill switch;
- active-mandate and persisted TaskBudget revalidation before every Task;
- PostgreSQL lease/`SKIP LOCKED` worker claim and restart-safe next-run state;
- authenticated API, `/triggers` CLI and TUI Triggers management/history surfaces;
- direct BitPro/paper/testnet/live/approval adapter reachability and eval isolation.

## Evidence

- Focused Sprint suite: 26 passed, including a 100-event storm and concurrent fire race.
- Final `./scripts/check.sh`: frontend lint, 8 tests and build; Ruff; strict mypy over
  135 source files; 449 Python tests.
- Commit `afbed93` deployed in workflow `29361442025`.
- Production API and worker containers were healthy; authenticated trigger projection
  returned HTTP 200 with no rules or fires.
- Production Alembic version was `0016_research_triggers`; settings and worker probe
  both reported the feature disabled.

## Findings Fixed During QA

- Fire IDs are assigned before Task creation so resource/control references are never
  empty before flush.
- The unique fire decision is flushed before Session/Task rows; a concurrent unique-key
  race rolls back and returns the committed fire instead of duplicating a Task.
- Fire-time validation now rechecks the persisted zero-backtest Task budget, not only
  the create request.
- Cooldown uses decision time while fingerprint buckets use committed observation time,
  preventing future-dated source timestamps from poisoning runtime cooldown state.
- Trigger event maps, string fields and operator reasons are bounded to prevent oversized
  prompts/audit records; duplicate trigger names return a controlled conflict.
- Triggered Tasks include the bounded committed projection and run with the kernel's
  write-denying evaluation boundary.

## Boundaries

- Production remains disabled by default and no production Trigger, Fire or Task was
  created during acceptance.
- A trigger creates only a normal bounded Task; it cannot promote, start paper, place an
  order, allocate capital or modify BitPro.
- TUI and CLI do not implement scheduling or state transitions; service/API facts remain
  authoritative.

## Next

Activate Sprint 104 Governed Memory and Skill Lifecycle before allowing long-running
agents to propose reusable institutional knowledge or procedures.
