# Sprint 105 Portfolio Strategy Lifecycle QA

## Verdict

PASS. Bounded portfolio evidence, explicit unknowns, human-only lifecycle review, migration
reversibility, repository gates and production fail-closed smoke satisfy the Sprint contract.

## Scope Checked

- canonical request/policy/content hashes and idempotency conflict rejection;
- aligned-return correlation, shared symbol/timeframe/factor exposure and bounded storage;
- insufficient, misaligned and zero-variance evidence remaining unknown;
- regime, lifecycle, drawdown, capacity, liquidity, drift and governed Memory projection;
- six fixed research/review recommendations and human accept/reject/hold ledger;
- absence of BitPro/paper/live mutation reachability from the portfolio module;
- administrator API, CLI, TUI and Web projections;
- PostgreSQL upgrade/downgrade/upgrade and existing WorldState/StrategyCard regressions.

## Local Evidence

- Focused backend acceptance: 23 passed.
- Frontend: ESLint, 9 Vitest tests and production Vite build passed.
- Full `./scripts/check.sh`: Ruff; strict mypy over 140 source files; 473 Python tests.
- PostgreSQL `0018_portfolio_lifecycle` upgraded, downgraded to `0017_memory_skills`, and
  re-upgraded; `portfolio_assessments` and `strategy_lifecycle_reviews` existed at head.

## Findings Fixed During QA

- Assessment idempotency now binds the key to a canonical request hash; same key with a
  different strategy set or sampling policy fails instead of returning unrelated data.
- Review idempotency now binds the normalized reason in addition to assessment,
  recommendation and decision.
- Safety regression inspects the portfolio module for forbidden execution adapters/actions.
- Route tests scope queries to the visible metric region, avoiding hidden-page duplicates.

## Boundaries

- No automatic allocation, rebalance, paper pause/start, promotion, live action or order.
- No full equity or return series is copied into long-term portfolio storage.
- Missing evidence never becomes a fabricated correlation, capacity or risk contribution.
- Human approval records a decision fact only; it does not execute the recommendation.

## Production Evidence

- Commit `e80cf0d` deployed successfully in workflow `29365535535`; recorded production SHA
  matched and API/Worker were running with healthy API response.
- Alembic reported `0018_portfolio_lifecycle`; both expected tables and all four portfolio
  OpenAPI paths existed.
- Authenticated assessment list returned HTTP 200; Web `/harness/portfolio` returned the SPA
  bundle through Nginx.
- Idempotent production assessment `pasmt_fbb18fbd79e8499a8c31` returned schema v2,
  `needs_data`, one explicit unknown, zero strategies/pairs/recommendations, false mutation
  flags and no raw series because production had no StrategyCard evidence.
- Exactly one assessment and zero lifecycle reviews existed afterward; API and Worker logs
  contained no error, exception or traceback.
