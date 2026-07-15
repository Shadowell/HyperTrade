# Sprint 107 StrategyCard Lifecycle & Research Funnel QA

## Verdict

PASS. Manifest-bound identity, immutable Card V2 snapshots, fixed-denominator funnel,
human-only lifecycle decisions and production backfill satisfy Gate F without creating a
paper, live, order or capital mutation path.

## Scope Checked

- mandate-scoped lineage and stable Manifest-bound version allocation;
- incomplete Card creation at Manifest registration and deterministic historical reconcile;
- content-hashed snapshot immutability, explicit unknown/missing fields and source refs;
- fact-driven lifecycle and idempotent human decision audit facts;
- Manifest-denominated funnel through Task, Spec, Evidence, Validation and Paper;
- REST, CLI, Textual, Web and PortfolioAssessment server-projection reuse;
- PostgreSQL migration reversibility and forbidden execution-adapter boundaries.

## Local Evidence

- Focused StrategyCard V2 suite passed 8 tests, including cross-mandate PaperPromotion
  isolation and zero PaperPromotion creation from a Manifest-only candidate.
- Combined API, CLI, TUI, strategy and portfolio regressions passed.
- Temporary PostgreSQL passed the full migration chain, `0019 -> 0018 -> 0019`, and all four
  Sprint 107 tables were present at head.
- Full `./scripts/check.sh` passed frontend lint, 9 Vitest tests and build; Ruff; mypy over
  143 source files; and 497 Python tests.

## Findings Fixed During QA

- PaperPromotion fallback association now requires the same mandate as the Manifest; an equal
  `strategy_key` in another mandate cannot supply paper status or BitPro strategy identity.
- Promotion-only historical records remain `strategy_card.v1_compat` with an explicit missing
  Manifest and do not enter the V2 funnel denominator.

## Production Evidence

- Commit `14d686e` deployed successfully in workflow `29387796135`; recorded SHA matched.
- Alembic reported `0019_strategy_card_v2 (head)` and API health returned 200.
- Three historical Manifests reconciled to one lineage, three versions and three snapshots.
  Two consecutive reconciles and subsequent list/funnel reads left the snapshot count at three.
- The V2 card count and funnel denominator both remained three; stage counts were Task 3,
  Spec 3, Manifest 3, Evidence 1, Validation 1, Paper 0 and Card 3.
- PaperPromotion remained 0. Existing paper order and live-order-intent counts remained 10 and
  1 before and after the backfill, demonstrating no execution-side mutation.
- Nginx Web `/harness/strategy` returned 200; API and worker remained running without new
  application errors during acceptance.

## Not Checked

- Strategy profitability and future market performance are not implied by completeness or
  lifecycle status.
- Portfolio return windows, cohort comparison and hypothetical capital proposals remain in
  Sprints 108–110.

## Next

Activate Sprint 108 for bounded PortfolioObservationWindow and data-quality evidence. Gate F
does not enable automatic paper promotion, live trading or capital allocation.
