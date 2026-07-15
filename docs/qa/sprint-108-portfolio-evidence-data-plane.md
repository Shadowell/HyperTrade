# Sprint 108 Portfolio Evidence Data Plane QA

## Verdict

PASS. Bounded BitPro reads, immutable summary windows, explicit data quality, PortfolioAssessment
integration and zero execution-side mutation satisfy the evidence half of Gate G.

## Scope Checked

- strict capture/window/data-quality contracts and fixed Card denominator;
- health, paper snapshot and bounded equity-curve read-only adapter surface;
- UTC horizon/bucket normalization and Decimal return/volatility/drawdown/correlation summaries;
- missing identity, unhealthy source, stale, insufficient, misaligned and zero-variance handling;
- source/content/idempotency hashes and immutable summary-only persistence;
- PortfolioAssessment window refs and API, CLI, Textual, Web shared projections;
- PostgreSQL migration reversibility and forbidden mutation/import boundaries.

## Local Evidence

- Nine focused window tests cover available, no-window, stale, zero variance, unhealthy source,
  separated snapshot/curve failures, idempotency, REST and CLI rendering.
- Combined observation, assessment, StrategyCard, CLI and TUI regressions passed 104 tests before
  the production finding; the final focused regression was added afterward.
- Temporary PostgreSQL passed the full chain, `0020 -> 0019 -> 0020`, and the summary table existed.
- Final `./scripts/check.sh` passed frontend lint, 9 Vitest tests and build; Ruff; mypy over
  145 source files; and 506 Python tests.

## Findings Fixed During QA

- Initial production capture showed that a per-strategy read failure was correctly recorded on the
  strategy but the aggregate quality status was `insufficient`. Aggregate precedence now reports
  `source_unhealthy` when no strategy is available and any curve source failed.
- Snapshot and curve calls are now isolated: a missing snapshot remains an unknown but does not
  block a usable curve; a curve failure fails the strategy window closed.
- Capture time was removed from content identity. Unchanged request/source/quality projections reuse
  the existing row instead of creating timer-driven snapshots.

## Production Evidence

- Main implementation commit `c7dc2a0` deployed in workflow `29388870334`; classification fix
  `57b67bd` deployed in workflow `29389087323`. Recorded SHA matched both deployments.
- Alembic reported `0020_portfolio_windows (head)` and health/Web `/harness/portfolio` returned 200.
- Final capture `pwin_c23b2d48cfab40eeb3f9` used a denominator of three V2 Cards: one source-bound
  strategy was available and two Manifest-only Cards remained `no_window`. Replay returned the same
  id with `idempotent=true`.
- Recursive persisted-key audit found no `equity_curve`, `returns`, `return_series`, `positions`,
  `trades` or `orders` key in strategy/pairwise JSON. The response invariants were
  `raw_series_persisted=false` and `execution_authorized=false`.
- PaperPromotion remained 0; existing paper orders and live intents remained 10 and 1. No lifecycle
  review was created.
- Assessment `pasmt_eb4f3e0be84d494ba1ef` referenced the final window id/status, projected three
  strategies and three pairs, and returned `needs_data` with 14 explicit unknowns. Its three
  recommendations all retained `allocation_change_allowed=false` and
  `trading_mutation_allowed=false`.

## Not Checked

- A complete 30/60/90-day production paper cohort is unavailable and was not fabricated.
- Champion/Challenger labels, decay comparisons and shadow capital proposals remain Sprints 109–110.
- These statistics do not establish profitability, future returns or capital suitability.

## Next

Activate Sprint 109 and admit only comparable, source-healthy windows into human-reviewed paper
cohorts. Gate G remains open until incubation acceptance; no automatic paper lifecycle action is
enabled.
