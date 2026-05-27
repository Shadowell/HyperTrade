# Sprint 03 Contract: Strategy Research And Backtest Workflow

## Goal

Build the first strategy research to backtest loop: create an auditable strategy research record, run a Backtrader-based backtest, persist the report, and surface the latest research/backtest results in `/harness`.

## In Scope

- Add PostgreSQL schema for strategy research records and backtest runs.
- Add a small Strategy SDK with candle DTOs and a built-in `momentum_breakout_v1` template.
- Use Backtrader as the Sprint 03 backtest engine.
- Add API endpoints:
  - `POST /api/strategy/research`
  - `GET /api/strategy/research`
  - `POST /api/backtests`
  - `GET /api/backtests`
- Backtest endpoint supports supplied candles and a deterministic sample dataset fallback.
- Persist Markdown and structured JSON reports.
- Extend `/api/harness/overview` and `/harness` with Strategy Lab state.
- Add tests for research creation, Backtrader run metrics, API endpoints, and frontend rendering.

## Out of Scope

- Parameter optimization sweeps.
- Historical OKX candle backfill.
- Runtime Agent writes to git source files.
- Live/Testnet order generation from backtest results.
- Multi-strategy portfolio simulation.

## Done Means

- `./scripts/check.sh` passes.
- A user can create a strategy research record from free-form text.
- A user can run a backtest from the research record or built-in strategy key.
- Backtest results include start cash, end value, return percentage, max drawdown, trade count, report Markdown, and report JSON.
- `/harness` shows latest strategy research and latest backtest result.
- Deployment to `47.79.36.92` passes health and authenticated backtest smoke checks.

## Verification

```bash
./scripts/check.sh
```

Manual server checks:

```bash
curl -fsS http://127.0.0.1:3334/api/health
```

Authenticated checks:

- `POST /api/strategy/research`
- `POST /api/backtests`
- `GET /api/harness/overview`

## Handoff

Sprint 04 can add OKX historical K-line ingestion or strategy parameter optimization once the research/backtest loop is stable.
