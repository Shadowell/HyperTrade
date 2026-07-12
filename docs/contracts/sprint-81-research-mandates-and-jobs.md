# Sprint 81 - Research Mandates and Durable Jobs

## Goal

Create the operator-controlled root of the autonomous strategy research flow: a versioned research mandate and durable research job records. A mandate defines what the Agent may research, how much work it may start, and which validation/paper boundaries apply. This sprint does not create BitPro strategies or start backtests.

## In Scope

- Add a versioned `ResearchMandate` persistence model and service with:
  - allowed symbols, market type, timeframes, and strategy categories;
  - candidate/variant/concurrency budgets;
  - data coverage, cost, sample-size and drawdown gate configuration;
  - chronological validation-window configuration;
  - `paper_promotion_mode=manual_approval` and `live_mode=disabled` invariants.
- Add a durable `ResearchJob` model and state transitions for `queued`, `planning`, `failed`, `rejected`, `completed`, and `canceled`.
- Enforce that a job references one active mandate and receives an idempotency key before it is queued.
- Expose admin-protected API and CLI surfaces to create, list, inspect, pause, and resume mandates and to list/cancel jobs.
- Add a bounded Agent tool that can read a mandate and propose a schema-valid `StrategySpec`; its output remains a draft and cannot create a BitPro strategy.
- Persist an auditable decision/trace reference for mandate validation and every job transition.

## Out of Scope

- BitPro MCP strategy creation, data sync, backtest, paper configuration, or paper start.
- Automatic scheduling of research jobs.
- A frontend redesign beyond the API/CLI paths needed to inspect the records.
- Automatic paper or live promotion.
- Portfolio allocation changes.

## Deliverables

- Database migration and models for research mandates and research jobs.
- Pydantic schemas and service/state-transition helpers.
- API/CLI endpoints with policy and idempotency enforcement.
- A schema-valid `StrategySpec` draft path with no external mutation.
- Focused persistence, policy, API, CLI, and Agent planner tests.
- Documentation updates to the research-institution architecture design and strategy research playbook.

## Done Means

- An operator can define a mandate such as a BTC/ETH, 1h/4h, bounded-variant research program and inspect the normalized persisted result.
- A job without a valid active mandate or idempotency key is rejected before it reaches a worker.
- A paused mandate cannot create new jobs; existing job transitions remain traceable.
- The Agent can produce a `StrategySpec` draft only within the mandate allowlist.
- No BitPro write tool is present in the Sprint 81 job executor trace.

## Verification

```bash
uv run pytest tests/test_research_mandates.py tests/test_research_jobs.py -q
uv run pytest tests/test_agent_planner.py tests/test_tool_registry.py tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

Manual or QA checks:

- Create, pause, and resume one mandate; verify job creation is blocked while paused.
- Queue one idempotent research job and inspect its trace, mandate id, and transition history.
- Ask the Agent for a strategy draft and confirm the trace contains no BitPro mutation tool.

## Risks / Notes

- Treat the mandate as a policy object, not an LLM preference. Python validates it before a job is persisted.
- Research-job metadata belongs to HyperTrade; it must not duplicate BitPro strategy, market-data, or backtest tables.
- Keep validation thresholds configurable rather than hard-coding a profitability claim.

## Handoff

Sprint 82 consumes a queued job and validated `StrategySpec` to run the first bounded BitPro backtest matrix through MCP only.
