# Sprint 23 Contract: Report, Memory, and Backtest UX

## Goal

Improve the `/harness` operator experience for reading reports, auditing memory, and running strategy backtests with explicit data-source parameters.

## Scope

- Add a styled Markdown report reader with a raw Markdown toggle.
- Add a lightweight, safe Markdown renderer for headings, lists, paragraphs, and bold text.
- Add Memory Manager:
  - fetch active memory items from `/api/memory`
  - select and inspect memory details
  - show source run/tool
  - disable memory through `DELETE /api/memory/{id}`
- Add full backtest form controls:
  - strategy key
  - candle source: `sample`, `okx`, `bitpro`
  - initial cash
  - symbol
  - bar
  - candle limit
- Extend frontend test coverage for report reader, Memory Manager, and full backtest controls.

## Out Of Scope

- Rich Markdown tables.
- Server-side report pages.
- Memory hard delete from UI.
- Strategy code editor.
- Chart visualization of backtest equity curve.

## Acceptance

- Frontend lint, test, and production build pass.
- Full `./scripts/check.sh` passes.
- `/harness` provides readable report rendering while retaining raw Markdown access.
- `/harness` can inspect and disable Memory items.
- `/harness` can run backtests using explicit source/symbol/bar/limit/cash/strategy parameters.
