# Sprint 52 Contract: Frontend Operator Console

## Goal

Expand `/harness` from a compact workbench into a production operator console
for strategy library evidence, monitoring alerts, report reading, and
approval/risk status while preserving the simplified, Chinese-first style.

## In Scope

- Add a Strategy Library view backed by `/api/strategy/library`.
- Add monitor/alert panels when Sprint 51 APIs are available, or a clearly
  stubbed empty state if implemented in parallel.
- Add report reader support for structured report blocks when Sprint 50 lands,
  while preserving Markdown fallback.
- Add source-evidence drilldowns for memory id, experiment id, backtest id,
  BitPro result id, and tool trace.
- Keep current `/harness` observability-first public read behavior.
- Add frontend tests for navigation, rendering, empty states, and no-overlap
  responsive layout.

## Out of Scope

- Marketing landing page.
- Full admin console for every privileged mutation.
- Live trading execution UI expansion.
- Decorative analytics without source ids.

## Deliverables

- Frontend components/views for:
  strategy library, monitor alerts, report blocks, evidence drilldown.
- API client additions.
- CSS/layout updates consistent with current design direction.
- Frontend tests and at least one browser/screenshot verification.
- Docs in `docs/architecture/09-frontend-harness.md`.

## Design Notes

Operator UI priorities:

- show the actual evidence first
- make status and missing data scannable
- preserve source ids
- avoid raw JSON as the primary display
- keep Chinese operational labels with tool/protocol names preserved

Cards should represent repeated items only. Avoid nested cards and decorative
hero layouts.

## Done Means

- `/harness` can inspect strategy-library summaries without using CLI.
- Empty strategy library and empty alerts have clear states.
- A strategy item shows best evidence, failure reasons, next experiment, and
  source memory ids.
- Frontend tests and browser verification pass.

## Verification

```bash
npm exec --yes pnpm@10 -- -C frontend lint
npm exec --yes pnpm@10 -- -C frontend test
npm exec --yes pnpm@10 -- -C frontend build
./scripts/check.sh
```

Manual or QA checks:

- Open `/harness`, view Strategy Library, resize to mobile/desktop, and confirm
  text does not overlap.
- Click evidence rows and confirm source ids remain visible.

## Risks / Notes

- Do not reintroduce a login wall for observability-first views.
- Privileged mutations must remain admin-authenticated.

## Handoff

- Next likely step: connect monitor alert actions after Sprint 51 stabilizes.

