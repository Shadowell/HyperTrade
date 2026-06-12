# HyperTrade Product Spec

## Product Summary

HyperTrade is a crypto trading agent for market research and execution. V1 focuses on stable agent capabilities: provider configuration, tool calls, RAG, memory, trace, market ingestion, risk gates, testnet execution, BitPro strategy lifecycle orchestration, and operator-facing harnesses.

HyperTrade 是一个面向行情研究与执行的加密交易 Agent。V1 重点是稳定 Agent 能力：Provider 配置、Tool Call、RAG、Memory、Trace、行情采集、风控门禁、Testnet 执行、BitPro 策略生命周期编排和面向操作员的 Harness。

BitPro is treated as the base trading-system platform: it owns market/reference data, strategy storage, backtest execution, metrics, paper/simulation runtime, and future live execution. HyperTrade is the Agent control and research layer: it discovers BitPro capabilities, reads/writes through MCP tools only, generates and validates `BaseStrategy` code, starts BitPro-owned backtests, inspects real evidence, and promotes only passing candidates into paper simulation. HyperTrade must not copy BitPro business logic or bypass BitPro risk boundaries.

BitPro 作为基础交易系统平台：负责行情/基础数据、策略存储、回测执行、指标、模拟盘运行和未来实盘执行。HyperTrade 作为 Agent 控制与研发层：通过 MCP 发现 BitPro 能力，只经由 MCP 工具读写，生成并校验 `BaseStrategy` 策略，启动 BitPro 负责的回测，基于真实证据迭代，并且只把通过门禁的候选策略推进到模拟盘。HyperTrade 不复制 BitPro 业务逻辑，也不绕过 BitPro 风险边界。

## Users

- Operator running audited agent research and execution workflows.
- Quant trader researching OKX perpetual swap market structure.
- Engineer integrating stable external data and execution-state providers.

## Core User Journeys

1. Operator opens `/harness` and reviews the core workbench: Agent run creation, report reading, recent runs, trace, RAG, Memory, and OKX market snapshot without a login wall.
2. Worker continuously ingests OKX SWAP ticker snapshots.
3. User asks for a market summary in free-form chat.
4. Agent calls market, RAG, and memory tools, then stores trace and report.
5. User reviews the report from `/harness`; privileged sharing or mutation actions stay outside the primary workbench and require admin-authenticated API/CLI paths.
6. User creates auditable strategy research records and Backtrader backtests through API/CLI workflows.
7. Developer runs `hypertrade` for a standalone terminal Agent, or `hypertrade --remote <url>` to connect to a deployed API.

## V1 In Scope

- FastAPI backend with public workbench observability/read endpoints and admin session auth for privileged mutations.
- LangGraph-style AgentKernel with explicit traceable tool calls.
- DeepSeek default provider configuration.
- Qwen embedding configuration path and pgvector schema.
- PostgreSQL job table and worker process.
- OKX SWAP market ingestion: WS tickers + REST fallback/supplements.
- RAG scanner over `docs/knowledge`.
- Audited memory writes with disable/delete support.
- React `/harness` and market summary UI.
- Docker Compose and host Nginx deployment on ports `3333/3334`.
- Sprint 03 strategy research and Backtrader backtest workflow with persisted Markdown/JSON reports.
- Sprint 05 standalone hybrid CLI runtime with local AgentKernel mode and remote API mode.
- Sprint 06 CLI slash commands for status, tools, runs, memory, strategy research, and backtests.
- Sprint 07 CLI shortcuts `/research` and `/backtest` for strategy workflow triggers.
- Sprint 08 LLM-driven `AgentPlanner` using DeepSeek function calling; hardcoded fallback when no key.
- Sprint 09 exact `market_ticker` tool for any listed OKX USDT SWAP symbol or instrument id.
- Sprint 10 `market_candles` tool for recent OKX candles and deterministic trend features.
- Sprint 11 `market_compare` tool for multi-symbol relative strength ranking.
- Sprint 12 CLI/API run streaming with run and tool progress events.
- Sprint 13 live OKX candle input for Backtrader backtests.
- Sprint 14 Agent acceptance tests for tool selection, traceability, RAG, Memory, strategy research, backtesting, and output quality.
- Sprint 15 deterministic CLI market shortcuts and clearer Agent run status display.
- Sprint 16 structured CLI report rendering that prefers JSON/trace payloads over raw Markdown when possible.
- Sprint 17 Rich CLI renderer for terminal panels/tables with plain text fallback.
- Sprint 18 paper-trading CLI controls for status, pause, and resume.
- Sprint 19 BitPro archived SQLite K-line source for Backtrader backtests.
- Sprint 20 paper close/reset lifecycle controls.
- Sprint 21 live/testnet order intent approval gate.
- Sprint 22 frontend harness parity for market tools, paper controls, and live approval.
- Sprint 23 Markdown report, Memory details, and complete backtest form UX.
- Sprint 24 graph-style Agent runtime with observable graph nodes and run state.
- Sprint 25 provider router and session model switching.
- Sprint 26 RAG v2 citation-ready search through pgvector-compatible storage.
- Sprint 27 Memory v2 with policy fields, dedupe, search, tags, and audit metadata.
- Sprint 28 RiskEngine for live/testnet order intents.
- Sprint 29 OKX Testnet signed order execution after approval and risk check.
- Sprint 30 multi-step strategy experiment workflow.
- Sprint 31 deterministic Agent eval suite and operations runbooks.
- Sprint 32 production-oriented project positioning and BitPro API tool-surface contract.
- Sprint 33 initial BitPro MCP adapter: capability/health preflight, K-line data direct access, paper dashboard reads, live-position diagnostics, API endpoints, Agent tool schemas, and `bitpro_mcp` backtest candle source.
- Sprint 34 BitPro strategy lifecycle Agent tools: strategy search/generation/creation/update, BitPro-owned backtest job start/status reads, and paper/simulation configure/start/pause/resume/stop with live-write tools still blocked.
- BitPro backtest result reads through `bitpro_backtest_list_results`, including total-return threshold filters and page-parity reporting based on BitPro-owned result records.
- BitPro external API adapter contract for backtest data, base market data, paper/simulation state, and live trading state without copying BitPro business logic.

## V1 Out of Scope

- Mainnet live order execution. Mainnet intent creation may be audited, but execution is blocked.
- Automatic investment advice or unattended real-money trading.
- Milvus/Qdrant production vector clusters.
- Parameter optimization sweeps and live/Testnet order generation from backtest results.
- Direct BitPro database access or copied BitPro trading logic; HyperTrade consumes BitPro capabilities only through explicit API contracts.

## Acceptance

- `./scripts/check.sh` passes.
- `GET /api/health` returns OK.
- `/harness` loads a simplified core workbench without rendering a login form: Agent run creation, report reading, recent runs, trace events, RAG search, Memory search/detail, OKX top movers, and core telemetry.
- Advanced provider switching, paper lifecycle controls, live approval/execution, strategy lab/backtest forms, eval panels, Feishu send, and Memory disable are not first-class `/harness` UI controls.
- Privileged mutations such as provider selection, paper lifecycle control, live order approval/execution, Memory disable, and Feishu send still require admin session auth.
- `/api/harness/tools` shows live order approval gating.
- User can create an Agent market-summary run and inspect trace events.
- User can ask for a specific listed OKX SWAP symbol, such as ETH/SOL/DOGE/PEPE, and the Agent can
  call the exact ticker tool instead of returning only the all-market movers list.
- User can ask for a specific symbol's recent trend and the Agent can call the candle research tool
  to return OHLCV-derived features.
- User can compare multiple listed OKX SWAP symbols and the Agent can return relative strength
  rankings.
- User can create a strategy research record and run a deterministic Backtrader backtest.
- Developer can run `hypertrade` as a standalone CLI Agent and see run id, tool calls, and report output.
- Developer can use the production host `hypertrade` wrapper as a remote client without attaching to the long-running API service container, so deploy-time API replacement does not terminate the terminal session.
- Developer can run `hypertrade /login` or `ht /login` once on a local machine to save remote API URL, username, and password to `~/.hypertrade/client.env` with local-only permissions; later `ht` commands default to the saved remote API unless `--local` is passed.
- Developer can see run/tool progress while `hypertrade ask` or interactive chat is still running.
- Developer can see a live `Thought` / `Thinking` animation in interactive terminals while an Agent prompt is waiting for planning or tool results.
- Developer can use CLI slash commands such as `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in interactive chat.
- Developer can read a purpose description beside every `/help` slash command and every `/tools` Agent tool row.
- Developer can run `/research <prompt>` and `/backtest` from interactive CLI chat to create research and backtest records.
- Developer can run Backtrader backtests with recent OKX candles through API or CLI options.
- Developer can run Agent acceptance tests and review a documented test plan for expected tool calls, trace output, and report quality.
- Developer can run deterministic CLI market commands such as `/price`, `/candles`, and `/compare` without waiting for LLM planning.
- Developer can see readable Agent progress statuses while free-form prompts are running.
- Developer can read structured CLI report sections for market runs, and unknown Markdown reports render as terminal headings, lists, and tables in interactive/Rich mode.
- Developer can read Rich CLI run output without low-signal trace noise: graph/preflight/nested rows are folded into a compact summary by default, while `HYPERTRADE_TRACE=full` shows the full trace for audits.
- Routine market/RAG/Memory CLI outputs do not repeat a fixed investment-advice disclaimer; strategy, backtest, Testnet, live-order, or recommendation-like prompts still surface the research/risk boundary.
- Developer can enable Rich terminal rendering for structured CLI reports while keeping plain output for scripts.
- Developer can inspect and control the simulated paper runtime from CLI slash commands.
- Developer can run backtests from archived BitPro K-line data without copying BitPro business logic.
- Developer can inspect Agent graph state and graph trace nodes for each run.
- Developer can switch chat providers from CLI/API/frontend without exposing provider keys.
- Developer can search RAG citations and Memory from CLI/API/frontend.
- Developer can create, approve, and execute OKX Testnet order intents after risk checks.
- Developer can run `/experiment <prompt>` to create strategy research, backtest, critique, and next experiment report.
- Developer can run `/evals` and inspect deterministic Agent eval status.
- Operator can use `docs/knowledge/tool-usage-guide.md` to validate each Agent tool surface and follow related operational source-code comments.
- Operator can review the BitPro tool-surface requirements before wiring external data, backtest, paper/simulation, or live-state APIs into Agent tools.
- Operator can call BitPro read tools through HyperTrade API/Agent paths while every flow starts with `bitpro_capabilities` and `bitpro_health`.
- Developer can run backtests with `candle_source=bitpro_mcp` or `/backtest --source bitpro_mcp` to use BitPro `market_klines` data without direct database access.
- Agent can use BitPro strategy lifecycle tools to generate/create/update strategy drafts, start/query BitPro-owned backtest jobs, and configure/control paper validation while real-account write tools remain blocked.
- Agent can complete the BitPro strategy R&D loop through MCP only: `bitpro_capabilities` -> `bitpro_health` -> real K-line coverage confirmation -> `strategy_validate_code` -> `strategy_create` with DB-backed `script_content` -> optional `strategy_update` for canonical metadata/renaming -> `backtest_start_job`/result inspection -> gated `paper_configure`/`paper_start`.
- Agent can answer BitPro backtest ranking or threshold questions, such as `回测收益大于100%`, by calling `bitpro_backtest_list_results` and reporting `total_return_pct` from actual BitPro result rows instead of annualized return, strategy descriptions, memory, or inferred data.
- Agent can answer BitPro paper/simulation inventory questions without mistaking the current `paper_dashboard` view for the full universe: unfiltered dashboard reads include `strategy_search(status=running)` inventory and reports distinguish current dashboard instance from all running strategies.
- PostgreSQL migration creates business tables and pgvector extension.
- Deployment workflow runs only on `main` with SHA gating.
