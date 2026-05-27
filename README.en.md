# HyperTrade

HyperTrade is an independent agent-first crypto trading research and execution system. It is not developed inside BitPro and does not copy BitPro's AI research or autonomous trading logic. BitPro is only a deployment and OKX environment reference.

> Research and learning project only. Nothing in this repository is investment advice.

## Sprint 01

The first sprint implements one usable loop:

- OKX perpetual swap market ingestion.
- WebSocket tickers first, REST as snapshot, supplement, and fallback.
- User-triggered market summary through free-form chat.
- Tool-call trace, RAG hits, audited memory writes, and run history.
- `/harness` and market summary frontend surfaces.

## Stack

- Agent: LangGraph-style AgentKernel with explicit ToolRegistry, Trace, Memory, and RAG.
- Backend: FastAPI, SQLAlchemy 2, Alembic, uv, pytest, ruff, mypy.
- Storage: PostgreSQL + pgvector.
- RAG: Qwen `text-embedding-v4` config path; deterministic embedding fallback for local tests.
- LLM: DeepSeek official API, default `deepseek-v4-flash`.
- Frontend: React, Vite, TypeScript, Tailwind, shadcn-style UI, lucide-react.
- Deploy: Docker Compose, host Nginx, GitHub Actions self-hosted runner.

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

