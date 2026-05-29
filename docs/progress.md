# Progress Log

## Current Baseline

- Branch: `main`
- Harness status: active
- Last verified state: Sprint 09 specific market ticker tool deployed to `47.79.36.92` at SHA `16b4ac6`; stable ticker report block pending deploy.

## Active Contract

- `docs/contracts/sprint-09-specific-market-ticker-tool.md` (completed and deployed)

## Latest Completed Work

- Applied `codex-project-template` development harness.
- Added FastAPI backend, AgentKernel, ToolRegistry, RAG, Memory, OKX market parser, worker loops, Alembic migration.
- Added React/Vite `/harness` and market summary frontend surface.
- Added Docker Compose, Nginx config, self-hosted GitHub Actions deployment.
- Added `/api/harness/overview` and wired `/harness` to live Provider, Tool, market, Agent run, RAG, Memory, and trace state.
- Added configurable `COOKIE_SECURE` so the current HTTP `3333` deployment can keep admin sessions, while HTTPS deployments can opt in to secure cookies.
- Added Sprint 02 automatic paper trading runtime with paper sessions, deterministic signals, simulated fills/positions, pause/resume API, worker loop, and `/harness` Paper Runtime panel.
- Added Sprint 03 strategy research and Backtrader backtest workflow with persisted research records, backtest runs, Markdown/JSON reports, API endpoints, and `/harness` Strategy Lab panel.
- Added Sprint 04 CLI conversation harness with `hypertrade ask` and `hypertrade chat` over the same FastAPI Agent runtime.
- Added Sprint 05 standalone hybrid CLI runtime so bare `hypertrade` starts an Agent terminal, `--local` forces local AgentKernel mode, and `--remote` connects to a deployed API.
- Added Sprint 06 CLI slash commands for `/help`, `/status`, `/model`, `/providers`, `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in local and remote interactive chat.
- Added Sprint 07 CLI workflow shortcuts `/research <prompt>` and `/backtest` to trigger strategy research and Backtrader backtests without a full Agent run.

- Added Sprint 08 LLM-driven agent planner: `DeepSeekClient`, `AgentPlanner` multi-turn tool-calling loop, and updated `AgentKernel` to use real DeepSeek function calling when `DEEPSEEK_API_KEY` is configured, with hardcoded fallback when not.
- Fixed DeepSeek thinking-mode compatibility by preserving `reasoning_content` across tool-call turns.
- Added Sprint 09 exact market ticker path: `market_ticker` planner tool, `market.ticker` registry entry, exact `MarketRepository.get_ticker()`, and symbol normalization for any listed OKX USDT SWAP symbol such as ETH, SOL, DOGE, or PEPE.
- Added stable planner report rendering for successful `market_ticker` calls so CLI/API answers always include exact price, UTC0 change, 24h volume, source, and timestamp.

- `uv run pytest -q` -> 33 passed (5 new planner tests).
- `uv run ruff check` and `uv run mypy` -> clean.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 34 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 10 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 38 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 39 tests.
- Server deployed SHA `16b4ac6`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.ticker [market]`.
- Server non-BTC CLI smoke `hypertrade ask "看下ETH行情"` produced run `run_d745abf2ec4246a38315` with `market_ticker`, `market_summary`, and `memory_write` tool calls.
- Server trace query verified `market_ticker` output `inst_id=ETH-USDT-SWAP`, `found=true`, `data_source=okx_rest`.
- Server deployed SHA `8d91748`; external `GET /api/health` returned OK.
- Server `/status` slash command smoke passed through host `hypertrade`.
- Server DeepSeek planner smoke passed with `hypertrade ask "看下比特币行情"`, producing run `run_363a592c965141a8b914` with `market_summary`, `rag_search`, `memory_search`, and `memory_write` tool calls.

## Verification Evidence (previous sprints)

- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 17 tests.
- `uv run pytest -q` -> 15 passed.
- `npm exec --yes pnpm@10 -- -C frontend test` -> 1 passed.
- `npm exec --yes pnpm@10 -- -C frontend build` -> production build passed.
- Playwright opened `http://127.0.0.1:3333`, logged in, and triggered an Agent market summary.
- Server deployment verified `http://47.79.36.92:3333/api/health`.
- Server authenticated `/api/harness/overview` through Nginx verified with 344 OKX SWAP tickers, 3 Agent runs, DeepSeek configured, 1 RAG document, 3 active Memory items, and 9 trace events.
- Server authenticated `/api/paper/status` through Nginx verified paper session `running`, equity `100000`, 10 positions, and 10 recent fills.
- Worker logs verified `paper_trading tick status=running fills=10`.
- Server deployment ran Alembic `0003_strategy_backtest`, rebuilt API/worker images, and deployed SHA `e38f3e3`.
- Server authenticated strategy/backtest smoke created research `srch_12196a7d8aff4fbda649`, backtest `bt_9fc24eda9bff4e02bde0`, strategy `momentum_breakout_v1`, return `0.019000`, trade count `1`, and confirmed `/api/harness/overview.strategy_lab`.
- `uv run pytest tests/test_cli.py -q` -> 3 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 20 tests.
- Server deployed SHA `8528171`; external `GET /api/health` returned OK.
- Server container CLI smoke passed with `docker compose exec -T -e HYPERTRADE_API_URL=http://127.0.0.1:3334 api hypertrade ask "请做行情归纳"`, producing run `run_24d3927e3e324496bac3` with `market.summary`, `rag.search`, and `memory.write` tool calls.
- `uv run pytest tests/test_cli.py -q` -> 6 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 23 tests.
- Server deployed SHA `d125406`; external `GET /api/health` returned OK.
- Server local standalone CLI smoke passed with `docker compose exec -T api hypertrade ask "请做行情归纳"`, producing run `run_77da091e850346fa9da7` with `market.summary`, `rag.search`, and `memory.write`.
- Server remote CLI smoke passed with `docker compose exec -T api hypertrade --remote http://127.0.0.1:3334 ask "请做行情归纳"`, producing run `run_d5b161b8d5a54f659328`.
- Server bare interactive CLI smoke passed with `printf ":q\n" | docker compose exec -T api hypertrade`.
- Server host CLI wrapper installed at `/usr/local/bin/hypertrade` via `deploy/deploy.sh`; root shell `hypertrade` enters chat and `hypertrade ask "请做行情归纳"` produced run `run_83db62b8e9184eadaab7`.
- `uv run pytest tests/test_cli.py -q` -> 9 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 25 tests.
- `uv run pytest tests/test_cli.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 28 tests.

## Known Gaps

- OKX live WebSocket ingestion is implemented but not exercised against the remote server in this local run.
- V1 does not include automatic PostgreSQL backup.
- Sprint 03 uses deterministic sample candles unless the caller supplies candle payloads; no historical OKX candle backfill yet.
- Testnet order execution remains documented as a later sprint.

## Recommended Next Steps

1. Run full `./scripts/check.sh` for stable ticker report rendering and deploy to `47.79.36.92`.
2. Add historical K-line lookup for richer single-symbol reports.
3. Add multi-symbol comparison support, such as `比较 ETH 和 SOL`.
