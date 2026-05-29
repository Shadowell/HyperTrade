# HyperTrade Product Spec

## Product Summary

HyperTrade is an independent agent-first crypto trading system for learning modern agent development and building a public portfolio project. V1 focuses on the complete agent ecosystem: provider configuration, tool calls, RAG, memory, trace, market ingestion, and a harness UI.

HyperTrade 是一个独立的 Agent 交易系统，用于学习现代 Agent 开发流程并沉淀公开作品。V1 重点不是高频交易，而是完整 Agent 生态：Provider 配置、Tool Call、RAG、Memory、Trace、行情采集和可观测 Harness。

## Users

- Individual developer learning agent engineering.
- Quant trader researching OKX perpetual swap market structure.
- Portfolio reviewer evaluating practical AI-agent system design.

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

## V1 Out of Scope

- Mainnet live order execution.
- Automatic investment advice or unattended real-money trading.
- Milvus/Qdrant production vector clusters.
- Historical K-line backfill, parameter optimization sweeps, and live/Testnet order generation from backtest results.

## Acceptance

- `./scripts/check.sh` passes.
- `GET /api/health` returns OK.
- Admin can log in.
- `/api/harness/tools` shows live order approval gating.
- User can create an Agent market-summary run and inspect trace events.
- User can ask for a specific listed OKX SWAP symbol, such as ETH/SOL/DOGE/PEPE, and the Agent can
  call the exact ticker tool instead of returning only the all-market movers list.
- User can create a strategy research record and run a deterministic Backtrader backtest.
- Developer can run `hypertrade` as a standalone CLI Agent and see run id, tool calls, and report output.
- Developer can use CLI slash commands such as `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in interactive chat.
- Developer can run `/research <prompt>` and `/backtest` from interactive CLI chat to create research and backtest records.
- PostgreSQL migration creates business tables and pgvector extension.
- Deployment workflow runs only on `main` with SHA gating.
