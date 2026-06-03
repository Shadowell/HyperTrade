# Progress Log

## Current Baseline

- Branch: `main`
- Harness status: active
- Last verified state: Sprint 22 frontend harness parity deployed to `47.79.36.92` at SHA `a35e374`.

## Active Contract

- `docs/contracts/sprint-22-frontend-harness-parity.md` (completed locally)

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
- Added Sprint 10 market candles research path locally: OKX candle parsing, REST candle fetcher, deterministic trend feature extraction, `market_candles` planner tool, `market.candles` registry entry, AgentKernel execution, and stable K-line trend report block.
- Added Sprint 11 market relative-strength compare locally: `market_compare` planner tool, `market.compare` registry entry, deterministic strength scoring, ranking payload, and stable multi-symbol comparison report block.
- Added Sprint 12 CLI/API streaming locally: AgentKernel progress event emission, `POST /api/agent/runs/stream` SSE endpoint, remote SSE parsing, local streaming rendering, and CLI progress lines for run/tool events.
- Added Sprint 13 live candle backtest path locally: BacktestService can fetch OKX candles, convert them into Strategy SDK candles, accept API live-candle options, and pass `/backtest --live --symbol ETH --bar 1H --limit 100` from CLI.
- Added Sprint 14 Agent acceptance tests locally: deterministic replay tests now cover exact-symbol ticker output, K-line trend plus relative-strength comparison, RAG + Memory auditability, strategy research + backtest chaining, and report quality guardrails.
- Added `docs/testing/agent-acceptance-test-plan.md` with automated cases, server smoke commands, expected output checks, and forbidden advice phrases.
- Added Sprint 15 CLI market shortcuts locally: `/price`, `/candles`, and `/compare` call deterministic market payloads without waiting for LLM planning.
- Improved CLI Agent streaming status text so free-form runs show run creation, planning, tool execution, tool completion, and final report generation.
- Added Sprint 16 structured CLI report rendering locally: market-summary `report_json` and market tool trace outputs now render as structured CLI sections before falling back to Markdown.
- Added Sprint 17 Rich CLI rendering locally: structured market reports can render as terminal panels/tables when `HYPERTRADE_RENDERER=rich` or when running on a TTY, while `HYPERTRADE_RENDERER=plain` keeps script-friendly output.
- Updated the host CLI wrapper to pass safe display environment variables (`HYPERTRADE_RENDERER`, `NO_COLOR`) into the API container.
- Added Sprint 18 paper CLI controls locally: `/paper status`, `/paper pause`, and `/paper resume` call the existing paper runtime without starting an Agent run.
- Added Sprint 19 BitPro archived K-line backtest source locally: `BITPRO_SQLITE_PATH` can point to a BitPro SQLite DB, `/backtest --source bitpro --symbol ETH --bar 1H --limit 500` routes archived K-lines into Backtrader, and Compose mounts `${BITPRO_HOST_DATA_DIR:-/opt/bitpro/data}` read-only at `/bitpro-data`.
- Added Sprint 20 paper lifecycle controls locally: API and CLI now support `/paper close [symbol]` and `/paper reset`, close positions with realized PnL/events/fills, and reset by creating a new auditable running session.
- Added Sprint 21 live/testnet order approval gate locally: `live_order_intents` schema/service/API/CLI, Agent planner `live_order_intent` tool, and approve/reject status transitions without exchange execution.
- Added Sprint 22 frontend harness parity locally: `/harness` now includes Agent streaming status, market ticker/candle/compare shortcuts, paper close/reset controls, and Live Approval intent create/approve/reject UI.
- `npm exec --yes pnpm@10 -- -C frontend lint`, `test`, and `build` -> passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `a35e374`; server-local `GET 127.0.0.1:3334/api/health` and Nginx `GET 127.0.0.1:3333/api/health` returned OK.
- Server authenticated `/api/harness/overview` smoke returned `359` tickers, `0` pending live order intents, `1` recent live order intent, and paper session `running`.
- `uv run pytest tests/test_paper_service.py tests/test_api.py tests/test_cli.py -q` -> 27 passed.
- `uv run pytest tests/test_live_order_intents.py tests/test_api.py tests/test_cli.py -q` -> 23 passed.
- `uv run ruff check backend tests`, `uv run mypy backend/src` -> clean.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `9f02367`; Alembic migrated `0003_strategy_backtest -> 0004_live_order_intents`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server host CLI smoke passed: `/paper status` rendered the running paper session, `/live intent ETH buy 0.01 --reason deploy smoke` created pending testnet intent `loi_10c5e2b8e34f469cb5e7`, and `/live reject loi_10c5e2b8e34f469cb5e7 --reason deploy smoke cleanup` moved it to `rejected`.

- `uv run pytest -q` -> 33 passed (5 new planner tests).
- `uv run ruff check` and `uv run mypy` -> clean.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 34 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 10 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 38 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 39 tests.
- `uv run pytest tests/test_market_candles_tool.py tests/test_agent_planner.py -q` -> 12 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 44 tests.
- `uv run pytest tests/test_market_compare_tool.py tests/test_agent_planner.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 47 tests.
- `uv run pytest tests/test_cli.py tests/test_api.py -q` -> 15 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 49 tests.
- `uv run pytest tests/test_live_candle_backtest.py tests/test_strategy_backtest_api.py tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 52 tests.
- `uv run pytest tests/test_agent_acceptance.py -q` -> 4 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 56 tests.
- `uv run pytest tests/test_cli.py tests/test_api.py -q` -> 17 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 57 tests.
- `uv run pytest tests/test_cli.py -q` -> 15 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 59 tests.
- `uv run pytest tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 60 tests.
- `uv run pytest tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 60 tests.
- `uv run pytest tests/test_bitpro_archive_backtest.py tests/test_cli.py -q` -> 19 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 63 tests.
- Server deployed SHA `bd58dd7`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server BitPro archive backtest smoke passed through host `hypertrade`: `/research 研究BTC趋势突破` created research `srch_c51a2aabfa4a448194c8`; `/backtest --source bitpro --symbol BTC --bar 1H --limit 200` created `bt_26ee2b9416b24f5db66c` using `bitpro_sqlite_candles`, `BTC-USDT-SWAP`, `1H`, and 200 candles.
- Server deployed SHA `9f3fa0c`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server paper CLI smoke passed through host `hypertrade`: `/paper status` printed session, positions, fills, and events; `/paper pause` reported paused; `/paper resume` reported running.
- Server deployed SHA `cb02da6`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server Rich CLI smoke passed with `HYPERTRADE_RENDERER=rich hypertrade ask "看下ETH行情"`: output showed Rich panels and tables for run header, tool trace, `Agent Report`, and `Ticker`.
- Server deployed SHA `fee6be7`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server structured CLI smoke passed with `hypertrade ask "看下ETH行情"`: output showed `Agent Report`, `Ticker`, and multiple `Trend` sections rendered from structured trace outputs instead of raw Markdown.
- Server deployed SHA `e975d00`; server-local `GET 127.0.0.1:3334/api/health` and `GET 127.0.0.1:3333/api/health` returned OK.
- Server CLI shortcut smoke passed through host `hypertrade`: `/price ETH`, `/candles ETH --bar 1H --limit 50`, and `/compare ETH SOL --bar 4H --limit 100` returned exact ticker, K-line trend, and relative-strength output with `okx_rest` data source.
- Server CLI Agent status smoke passed with `hypertrade ask "看下ETH行情"`: output showed run creation, planning, tool execution, tool completion, final report generation, and completed report.
- Server deployed SHA `0afb197`; external `GET /api/health` returned OK.
- Server deployed SHA `48859cb`; external `GET /api/health` returned OK.
- Server live-candle backtest smoke passed with host `hypertrade`: `/research 研究ETH趋势突破` created `srch_987a780e0715494a99a3`, then `/backtest --live --symbol ETH --bar 1H --limit 100` created `bt_480d647199dd4d16b960` using `okx_rest_candles`, `ETH-USDT-SWAP`, `1H`, and 100 candles.
- Server deployed SHA `4ce55f8`; external `GET /api/health` returned OK.
- Server streaming smoke `hypertrade ask "比较 ETH 和 SOL 哪个更强"` produced run `run_c6909801a50243649c32` and printed progress lines before the final report: `Run started`, `Tool call`, `Tool result`, and `Run completed`.
- Server deployed SHA `4de0a4b`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.compare [market]`.
- Server comparison smoke `hypertrade ask "比较 ETH 和 SOL 哪个更强"` produced run `run_7b35c4bfa1e34c899425` with `market_compare` calls, and the final answer included stable relative-strength ranking blocks for ETH/SOL across 1H, 4H, and 1D.
- Server deployed SHA `a258e05`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.candles [market]`.
- Server non-BTC trend smoke `hypertrade ask "看下ETH这两天走势"` produced run `run_f6d262efb67147eca905` with `market_ticker` and two `market_candles` calls, and the final answer included stable K-line trend blocks for `ETH-USDT-SWAP` 1H and 1D.
- Server deployed SHA `16b4ac6`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.ticker [market]`.
- Server non-BTC CLI smoke `hypertrade ask "看下ETH行情"` produced run `run_d745abf2ec4246a38315` with `market_ticker`, `market_summary`, and `memory_write` tool calls.
- Server trace query verified `market_ticker` output `inst_id=ETH-USDT-SWAP`, `found=true`, `data_source=okx_rest`.
- Server deployed SHA `38f484f`; external `GET /api/health` returned OK.
- Server non-BTC CLI smoke `hypertrade ask "看下ETH行情"` produced run `run_674ab692117a443cb969` with `market_ticker` and `rag_search`, and the final answer included the stable exact ticker block for `ETH-USDT-SWAP`.
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
- Sprint 13 adds live OKX candle input, but does not persist historical candles to PostgreSQL.
- Testnet order execution remains documented as a later sprint.
- Public `http://47.79.36.92:3333/api/health` timed out from the current local environment after Sprint 15 deploy, while server-local Nginx/API health checks passed; likely requires cloud security group or caller IP whitelist review.

## Recommended Next Steps

1. Check cloud security group / caller IP whitelist for public port `3333`.
2. Add an archived candle source reader for BitPro file-store data if server data expands beyond SQLite.
3. Start the next execution sprint: paper trading close/reset controls, position risk rules, or Testnet approval-gated order path.
