# HyperTrade

HyperTrade is a crypto trading agent for market research and execution. It is independent from BitPro and does not copy BitPro's AI research or autonomous trading logic. BitPro can provide external data, strategy lifecycle, backtest, paper/simulation, and execution-state APIs through stable MCP/API contracts that HyperTrade exposes as auditable tools.

> Research output only. Nothing in this repository is investment advice.

## Current V1 Capabilities

- Observable Agent graph runtime with intent, plan, approval, tool, reflect, and report nodes.
- Provider Router with DeepSeek default and OpenAI/OpenRouter/Qwen chat extension paths.
- Tool calling for market, RAG, Memory, strategy, backtest, paper, live intent, and Testnet execution.
- RAG citations backed by PostgreSQL/pgvector-compatible chunk metadata.
- Memory v2 with dedupe, tags, importance, confidence, and usage audit.
- Trading boundary: Mainnet execution is blocked; OKX Testnet signed execution is allowed only after approval and risk checks.
- Strategy workflow with research, multi-variant backtest evidence, critique, next experiment suggestion, and searchable `strategy_knowledge` memory cards.
- BitPro MCP adapter for health checks, direct K-line reads, strategy generation/create/update, BitPro backtest jobs/results/artifacts, paper lifecycle/monitoring, and live-position read-only diagnostics.
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

## Documentation Map

Start with `docs/README.md` for the documentation index. For hands-on operation,
use `docs/knowledge/tool-usage-guide.md`; it maps Agent graph, tool calling,
providers, RAG, Memory, strategy knowledge, BitPro MCP, risk, Testnet execution,
CLI, frontend, tests, and deployment smoke to commands and source files.

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
