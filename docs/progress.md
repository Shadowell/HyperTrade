# Progress Log

## Current Baseline

- Branch: `main`
- Harness status: active
- Last verified state: Sprint 03 strategy/backtest workflow verified locally; deployment pending.

## Active Contract

- `docs/contracts/sprint-03-strategy-backtest-workflow.md`

## Latest Completed Work

- Applied `codex-project-template` development harness.
- Added FastAPI backend, AgentKernel, ToolRegistry, RAG, Memory, OKX market parser, worker loops, Alembic migration.
- Added React/Vite `/harness` and market summary frontend surface.
- Added Docker Compose, Nginx config, self-hosted GitHub Actions deployment.
- Added `/api/harness/overview` and wired `/harness` to live Provider, Tool, market, Agent run, RAG, Memory, and trace state.
- Added configurable `COOKIE_SECURE` so the current HTTP `3333` deployment can keep admin sessions, while HTTPS deployments can opt in to secure cookies.
- Added Sprint 02 automatic paper trading runtime with paper sessions, deterministic signals, simulated fills/positions, pause/resume API, worker loop, and `/harness` Paper Runtime panel.
- Added Sprint 03 strategy research and Backtrader backtest workflow with persisted research records, backtest runs, Markdown/JSON reports, API endpoints, and `/harness` Strategy Lab panel.

## Verification Evidence

- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 17 tests.
- `uv run pytest -q` -> 15 passed.
- `npm exec --yes pnpm@10 -- -C frontend test` -> 1 passed.
- `npm exec --yes pnpm@10 -- -C frontend build` -> production build passed.
- Playwright opened `http://127.0.0.1:3333`, logged in, and triggered an Agent market summary.
- Server deployment verified `http://47.79.36.92:3333/api/health`.
- Server authenticated `/api/harness/overview` through Nginx verified with 344 OKX SWAP tickers, 3 Agent runs, DeepSeek configured, 1 RAG document, 3 active Memory items, and 9 trace events.
- Server authenticated `/api/paper/status` through Nginx verified paper session `running`, equity `100000`, 10 positions, and 10 recent fills.
- Worker logs verified `paper_trading tick status=running fills=10`.

## Known Gaps

- OKX live WebSocket ingestion is implemented but not exercised against the remote server in this local run.
- V1 does not include automatic PostgreSQL backup.
- Sprint 03 uses deterministic sample candles unless the caller supplies candle payloads; no historical OKX candle backfill yet.
- Testnet order execution remains documented as a later sprint.

## Recommended Next Steps

1. Deploy Sprint 03 to `47.79.36.92` and run authenticated strategy/backtest smoke checks.
2. Add OKX historical K-line ingestion for research-grade backtests.
3. Add HTTPS before setting `COOKIE_SECURE=true`.
