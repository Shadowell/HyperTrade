# Sprint 91 - Strategy Card Hierarchy

## Goal

Finish the strategy-library card system by making summary, evidence metrics, source references, and next-experiment content use the same operator-card hierarchy as the parent evidence card.

## In scope

- Apply the shared card treatment to strategy summary metrics and evidence-detail blocks.
- Use semantic rails to distinguish source metadata, performance metrics, audit references, and next experiment guidance.
- Preserve strategy search, evidence selection, source ids, keyboard interaction, and responsive layout.
- Validate with existing real strategy evidence at desktop and 390px widths.

## Out of scope

- Backend/API/data changes, new aggregation, polling, or persistence.
- Changes to strategy validation, backtests, risk gates, paper, or live behavior.
- Changing the strategy information architecture or card contents.

## Done means

- The strategy page contains no legacy mixed card styles for its evidence summary or detail blocks.
- Nested cards remain visually quiet, source-bound, and readable without competing with the selected strategy card.
- Existing checks pass and no narrow-screen overflow is introduced.

## Verification

- Frontend test checks the shared classes for strategy summary and evidence metrics.
- Browser-inspect strategy page with real data at desktop and 390px widths.

## Handoff

- New strategy evidence sub-blocks should use the compact operator-card variant and a semantic tone.
