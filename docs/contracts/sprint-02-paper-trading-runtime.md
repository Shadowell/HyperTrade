# Sprint 02 Contract: Automatic Paper Trading Runtime

## Goal

Build the first automatic paper-trading loop on top of Sprint 01 market data: the worker creates and maintains a paper session, generates deterministic rule signals from OKX SWAP tickers, simulates orders/fills/positions, and exposes runtime state in `/harness`.

## In Scope

- Add PostgreSQL schema for paper sessions, positions, orders, fills, and runtime events.
- Add a deterministic V1 signal engine using existing `market_tickers` snapshots.
- Add a paper execution engine with:
  - starting equity `100000 USDT`
  - max 10 open positions
  - max 20% notional per symbol
  - max 5x simulated leverage
  - taker fee 5 bps
  - slippage 2 bps
  - next available ticker snapshot as the fill reference
- Add worker autorun loop, enabled by default, with pause/resume control.
- Add API endpoints for paper status, fills, events, and pause/resume.
- Extend `/api/harness/overview` with paper runtime summary.
- Extend `/harness` with paper session status, positions, recent fills, PnL, and pause/resume.
- Add tests covering signal generation, order sizing, fill math, pause/resume, API status, and frontend rendering.

## Out of Scope

- Backtrader historical backtesting.
- Runtime strategy SDK files under `/opt/hypertrade/workspace/strategies`.
- Testnet or live OKX order placement.
- Agent-authored strategy mutation.
- Portfolio optimization beyond deterministic V1 rules.
- Mainnet account reads.

## Done Means

- `./scripts/check.sh` passes.
- A fresh deployment starts a default paper session automatically.
- `/api/paper/status` returns session, equity, positions, fills, and paused/running state.
- `/api/paper/control` can pause and resume the worker loop.
- `/harness` shows paper runtime state without requiring a manual Agent run.
- The paper engine never creates more than 10 open positions and never sizes a symbol above 20% notional or 5x simulated leverage.
- Fills persist enough data to audit fee, slippage, side, quantity, price, and source ticker.

## Verification

```bash
./scripts/check.sh
```

Manual server checks:

```bash
curl -fsS http://127.0.0.1:3334/api/health
curl -fsS http://127.0.0.1:3334/api/paper/status
```

UI checks:

- Log in to `/harness`.
- Confirm paper session is running by default.
- Pause paper trading and confirm status changes to paused.
- Resume paper trading and confirm status changes to running.
- Confirm positions/fills update after worker ticks when market data exists.

## Risks / Notes

- This Sprint intentionally uses deterministic rules so the trading loop is auditable before adding Agent strategy research or optimization.
- The signal engine is deterministic and must be labeled as simulated research, not investment advice.
- The worker may run on sparse ticker updates; the fill model should use latest available snapshots and record the snapshot time.

## Handoff

- Sprint 03 should add strategy research/backtest workflow or a safer Testnet order-intent approval path, depending on which production capability is higher priority after reviewing Sprint 02.
