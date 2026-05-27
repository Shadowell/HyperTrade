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

## V1 Out of Scope

- Mainnet live order execution.
- Automatic investment advice or unattended real-money trading.
- Milvus/Qdrant production vector clusters.
- Strategy backtest execution and paper trading implementation; these are Sprint 02+.

## Acceptance

- `./scripts/check.sh` passes.
- `GET /api/health` returns OK.
- Admin can log in.
- `/api/harness/tools` shows live order approval gating.
- User can create an Agent market-summary run and inspect trace events.
- PostgreSQL migration creates business tables and pgvector extension.
- Deployment workflow runs only on `main` with SHA gating.

