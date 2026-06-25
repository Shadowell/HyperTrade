# Sprint 74 - World Model Portfolio Scheduler

## Goal

Extend world-model reasoning from single strategy or single symbol decisions to
portfolio-level strategy scheduling. The Agent should understand regime fit,
strategy evidence, correlation risk, drawdown, tool health, and operator limits
before recommending allocation or scheduling changes.

## In Scope

- Define portfolio state schema:
  - strategy group
  - allocation or risk budget
  - evidence freshness
  - recent performance
  - drawdown
  - regime fit
  - correlation or shared exposure proxy
  - active paper/live status labels
- Aggregate strategy-library evidence, BitPro paper evidence, monitor alerts,
  and global market regime into a portfolio view.
- Add scheduler recommendation types:
  - keep allocation
  - reduce strategy risk budget request
  - pause strategy request
  - increase observation frequency
  - run targeted backtest or experiment
  - request human review before allocation change
- Add portfolio-level scenario scoring.
- Add report blocks for portfolio risk, strategy fit, concentration, and
  recommended review actions.
- Add evals for portfolio-level prompts.

## Out of Scope

- Automatic live allocation changes.
- Automatic offensive strategy promotion.
- Large parameter sweeps.
- Direct BitPro database reads or copied BitPro business logic.
- Full quantitative optimizer. The first scheduler is rule-based and
  evidence-bound.

## Deliverables

- `world_model/portfolio.py` or equivalent service.
- Portfolio schema and report blocks.
- API payload fields under world-model snapshot or a dedicated
  `/api/world-model/portfolio` endpoint.
- Agent planner guidance for portfolio prompts.
- Tests for regime fit, stale evidence handling, concentration warnings, and
  no-live-write behavior.

## Done Means

- A prompt such as `当前应该提高还是降低哪些策略权重` returns a portfolio
  recommendation based on strategy evidence, global market state, execution
  state, and source references.
- The scheduler can explain missing evidence and refuse allocation advice when
  required data is unavailable.
- The report distinguishes local research, paper simulation, live diagnostics,
  and any future live-write gate.
- No live allocation mutation occurs in this sprint.

## Verification

```bash
uv run pytest tests/test_world_model_portfolio.py tests/test_agent_eval_suite.py -q
./scripts/check.sh
```

Current focused verification:

- `uv run pytest tests/test_world_model_portfolio.py tests/test_agent_eval_suite.py -q`
  passed with 13 tests after adding the portfolio scheduler view.
- `uv run pytest tests/test_world_model_portfolio.py tests/test_world_model_snapshot.py tests/test_world_model_scenarios.py tests/test_world_model_defensive_actions.py tests/test_agent_eval_suite.py tests/test_api.py::test_api_exposes_health_harness_and_agent_run -q`
  passed with 24 tests.
- `./scripts/check.sh` passed with frontend lint/test/build, ruff, mypy, and
  full Python pytest (`254 passed`).

Manual or QA checks:

- Ask for a portfolio allocation review and confirm source references include
  strategy memory or BitPro paper evidence.
- Confirm stale strategy evidence produces a review/backtest recommendation
  rather than an allocation increase.
- Confirm live-write tools are absent from trace.

## Risks / Notes

- Correlation and regime-fit proxies should start simple and auditable. If data
  is insufficient, surface that limitation instead of inventing portfolio math.
- The scheduler depends on Phase 1 and Phase 2 state quality and should not be
  built before those snapshots and decision records are stable.

## Handoff

- Sprint 74 implementation entrypoints:
  - `backend/src/hypertrade/world_model/portfolio.py`
  - `GET /api/world-model/portfolio`
  - `portfolio` field on `world_model_snapshot`
  - deterministic eval case `world_model_portfolio_review`
- Later work can add richer optimizer logic, external portfolio risk data, or
  live allocation workflows under a separate explicit live-risk contract.
