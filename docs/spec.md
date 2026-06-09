# HyperTrade Product Spec

## Product Summary

HyperTrade is an independent production-oriented agent-first crypto trading system. V1 focuses on a stable agent capability platform: provider configuration, tool calls, RAG, memory, trace, market ingestion, risk gates, testnet execution, and operator-facing harnesses.

HyperTrade 是一个独立的生产级 Agent 交易系统。V1 重点是稳定 Agent 能力平台：Provider 配置、Tool Call、RAG、Memory、Trace、行情采集、风控门禁、Testnet 执行和面向操作员的 Harness。

## Users

- Operator running audited agent research and execution workflows.
- Quant trader researching OKX perpetual swap market structure.
- Engineer integrating stable external data and execution-state providers.

## Core User Journeys

1. Admin logs in and reviews `/harness` provider/tool/runtime state.
2. Worker continuously ingests OKX SWAP ticker snapshots.
3. User asks for a market summary in free-form chat.
4. Agent calls market, RAG, and memory tools, then stores trace and report.
5. User reviews the report and can manually forward it to Feishu.
6. User creates an auditable strategy research record and runs a Backtrader backtest from `/harness`.
7. Developer runs `hypertrade` for a standalone terminal Agent, or `hypertrade --remote <url>` to connect to a deployed API.

## V1 In Scope

- FastAPI backend with admin session auth.
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
- BitPro external API adapter contract for backtest data, base market data, paper/simulation state, and live trading state without copying BitPro business logic.

## V1 Out of Scope

- Mainnet live order execution. Mainnet intent creation may be audited, but execution is blocked.
- Automatic investment advice or unattended real-money trading.
- Milvus/Qdrant production vector clusters.
- Historical K-line backfill, parameter optimization sweeps, and live/Testnet order generation from backtest results.
- Direct BitPro database access or copied BitPro trading logic; HyperTrade consumes BitPro capabilities only through explicit API contracts.

## Acceptance

- `./scripts/check.sh` passes.
- `GET /api/health` returns OK.
- Admin can log in.
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
- Developer can see run/tool progress while `hypertrade ask` or interactive chat is still running.
- Developer can use CLI slash commands such as `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in interactive chat.
- Developer can run `/research <prompt>` and `/backtest` from interactive CLI chat to create research and backtest records.
- Developer can run Backtrader backtests with recent OKX candles through API or CLI options.
- Developer can run Agent acceptance tests and review a documented test plan for expected tool calls, trace output, and report quality.
- Developer can run deterministic CLI market commands such as `/price`, `/candles`, and `/compare` without waiting for LLM planning.
- Developer can see readable Agent progress statuses while free-form prompts are running.
- Developer can read structured CLI report sections for market runs, with Markdown kept as fallback.
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
- PostgreSQL migration creates business tables and pgvector extension.
- Deployment workflow runs only on `main` with SHA gating.
