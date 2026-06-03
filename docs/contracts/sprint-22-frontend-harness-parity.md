# Sprint 22 Contract: Frontend Harness Parity

## Goal

Bring the `/harness` frontend closer to the current CLI/API capability set so the operator can use the browser for core monitoring and approval workflows instead of relying only on terminal slash commands.

## Scope

- Show Agent streaming progress while a run is executing.
- Add deterministic market tool shortcuts for ticker, candles, and relative-strength compare.
- Add paper lifecycle controls for close-all and reset.
- Add Live Approval panel for creating, approving, and rejecting order intents.
- Add `live_orders` overview typing and rendering.
- Extend frontend test coverage for Live Approval and market tool surface.

## Out Of Scope

- Mainnet order execution.
- Full report detail pages.
- Markdown-rich report renderer.
- Full memory item management.
- Strategy source-code editor.

## Acceptance

- `/harness` can trigger Agent streaming runs and show progress events.
- `/harness` can call market ticker, candle, and compare APIs.
- `/harness` can pause, resume, close all, and reset the paper session.
- `/harness` can create, approve, and reject live/testnet order intents.
- Frontend lint, test, and production build pass.
- Full `./scripts/check.sh` passes.
