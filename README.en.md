# HyperTrade

HyperTrade is an independent agent-first crypto trading research and execution system. It is not developed inside BitPro and does not copy BitPro's AI research or autonomous trading logic. BitPro can provide external data and execution-state APIs through stable contracts that HyperTrade exposes as auditable tools.

> Research output only. Nothing in this repository is investment advice.

## Current V1 Capabilities

- Observable Agent graph runtime with intent, plan, approval, tool, reflect, and report nodes.
- Provider Router with DeepSeek default and OpenAI/OpenRouter/Qwen chat extension paths.
- Tool calling for market, RAG, Memory, strategy, backtest, paper, live intent, and Testnet execution.
- RAG citations backed by PostgreSQL/pgvector-compatible chunk metadata.
- Memory v2 with dedupe, tags, importance, confidence, and usage audit.
- Trading boundary: Mainnet execution is blocked; OKX Testnet signed execution is allowed only after approval and risk checks.
- Strategy workflow with research, backtest, critique, and next experiment suggestion.
- BitPro MCP read adapter for health checks, direct K-line reads, paper dashboard, and live-position diagnostics.
- Observability through `/harness`, CLI slash commands, and deterministic eval suite.

## Stack

- Agent: LangGraph-style AgentGraph/AgentKernel with explicit ToolRegistry, Trace, Memory, and RAG.
- Backend: FastAPI, SQLAlchemy 2, Alembic, uv, pytest, ruff, mypy.
- Storage: PostgreSQL + pgvector.
- RAG: Qwen `text-embedding-v4` config path; deterministic embedding fallback for local tests.
- LLM: DeepSeek official API, default `deepseek-v4-flash`.
- Frontend: React, Vite, TypeScript, Tailwind, shadcn-style UI, lucide-react.
- Deploy: Docker Compose, host Nginx, GitHub Actions self-hosted runner.

## Useful CLI Commands

```text
/status
/model deepseek
/rag risk
/memory search risk
/experiment research ETH breakout
/live intents
/live execute loi_...
/evals
```

## Operations Guide

Start with `docs/knowledge/tool-usage-guide.md` when operating or validating Agent capabilities. It maps Agent graph, tool calling, providers, RAG, Memory,
risk, Testnet execution, CLI, frontend, tests, and deployment smoke to the
relevant commands and source files.

## Local Start

```bash
cp .env.example .env
uv run pytest -q
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

Frontend: `http://localhost:3333`. Backend: `http://localhost:3334`.

## Verification

```bash
./scripts/check.sh
```
