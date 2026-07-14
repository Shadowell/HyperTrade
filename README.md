# HyperTrade

<p align="center">
  <strong>Production-Grade Agent Runtime for Crypto Trading Research & Execution</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Private-red.svg" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/FastAPI-0.104+-009688.svg" alt="FastAPI" /></a>
  <a href="#"><img src="https://img.shields.io/badge/React-18+-61DAFB.svg" alt="React" /></a>
  <a href="#"><img src="https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg" alt="TypeScript" /></a>
  <a href="#"><img src="https://img.shields.io/badge/PostgreSQL-14+-4169E1.svg" alt="PostgreSQL" /></a>
  <a href="#"><img src="https://img.shields.io/badge/status-active-success.svg" alt="Status" /></a>
</p>

<p align="center">
  <a href="README.zh-CN.md">中文文档</a> ·
  <a href="README.en.md">English Summary</a> ·
  <a href="docs/documentation-index.md">Documentation</a> ·
  <a href="docs/api-reference.md">API</a> ·
  <a href="docs/user-manual.md">User Manual</a> ·
  <a href="docs/developer-guide.md">Developer Guide</a>
</p>

---

## Overview

HyperTrade is a self-hosted Agent runtime that connects LLM-powered reasoning with governed access to crypto market data, strategy backtesting, paper trading, and risk-gated Testnet execution. It provides a unified environment for systematic trading research — from natural language exploration to evidence-backed strategy iteration.

![HyperTrade Architecture](docs/assets/hypertrade-architecture.svg)

> 📖 [Detailed Architecture Documentation](docs/architecture/19-hypertrade-architecture-diagram.md)

### Core Capabilities

| Domain | Capability |
|--------|-----------|
| **Market Intelligence** | Real-time OKX SWAP data, multi-source indicators, global market regime classification |
| **Strategy Research** | Backtrader backtests, multi-variant experiments, evidence library with automatic gating |
| **Paper Trading** | Full lifecycle simulation with pause/resume/close/reset controls |
| **Testnet Execution** | Approval-gated OKX Testnet orders with risk checks (mainnet blocked in V1) |
| **BitPro Integration** | MCP adapter for strategy lifecycle, backtest diagnostics, and paper monitoring |
| **Knowledge Systems** | RAG retrieval over `docs/knowledge` with pgvector, audited Memory persistence |
| **Governance** | Policy-enforced tool registry, approval gates, idempotency, deterministic evals |

> **Disclaimer**: Nothing in this repository constitutes investment advice. Mainnet live order execution is blocked in V1.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Client Layer                                                        │
│  CLI (ht) · Web Console (/harness) · REST/SSE API · External Agents │
├─────────────────────────────────────────────────────────────────────┤
│  Agent Runtime                                                       │
│  Graph Kernel · Provider Router · Tool Executor                      │
├─────────────────────────────────────────────────────────────────────┤
│  Governance Layer                                                    │
│  ToolRegistry · Risk Policy · Approval Gates · Audit Trace          │
├─────────────────────────────────────────────────────────────────────┤
│  Service Layer                                                       │
│  Market · RAG · Memory · Strategy · Backtest · World Model          │
├─────────────────────────────────────────────────────────────────────┤
│  Data Layer                                                          │
│  PostgreSQL/pgvector · OKX API · BitPro MCP · Alpha Vantage         │
└─────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Runtime** | Python 3.12+, FastAPI, SQLAlchemy, Alembic |
| **Agent Engine** | Graph-based kernel, provider routing, policy-enforced tool execution |
| **Frontend** | React 18, TypeScript 5, Vite, TanStack Query, Recharts |
| **Database** | PostgreSQL 14+ with pgvector (or SQLite for development) |
| **LLM Providers** | Vide Coding (opus-4.6), DeepSeek, OpenAI, Codex, OpenRouter, Qwen |
| **Backtesting** | Backtrader |
| **Infrastructure** | Docker Compose, Nginx, GitHub Actions CI/CD |

### Agent Capabilities

| Capability | Description | Status |
|-----------|-------------|--------|
| Natural Language | Free-form prompts routed to LLM planner with automatic tool selection | Production |
| Tool Calling | Registry-based execution with scope, approval, and idempotency enforcement | Production |
| Market Intelligence | OKX SWAP tickers, candles, funding, OI, relative strength indicators | Production |
| Global Market | Cross-asset regime classification (equities, volatility, FX, rates) | Production |
| RAG | pgvector-backed citation search over knowledge documents | Production |
| Memory | Audited observations with tags, confidence scoring, and importance weighting | Production |
| Strategy Research | Backtrader backtests, multi-variant experiments, evidence library | Production |
| BitPro Integration | MCP adapter for strategy lifecycle, backtest diagnostics, paper monitoring | Production |
| Paper Trading | Simulated execution with full lifecycle controls | Production |
| Testnet Execution | Approval-gated OKX Testnet orders with risk validation | Production |
| Monitoring & Alerts | Read-only monitors for paper strategies, connector health, library freshness | Production |
| Evaluation Suite | Deterministic evals for tool choice, RAG, Memory, risk, report quality | Production |
| Agent Task OS | Durable sessions, tasks, checkpoints, cursor events, controls, leases, and recovery | Production |
| World Model | Portfolio state tracking and defensive action scheduling | Experimental |

---

## Quick Start

### Prerequisites

- **Python 3.12+** with [`uv`](https://github.com/astral-sh/uv) package manager
- **Node.js 18+** with `pnpm`
- **API key** for at least one chat provider (Vide Coding, DeepSeek, OpenAI, etc.)
- **PostgreSQL 14+** with pgvector (recommended) or SQLite for development

### Setup

```bash
git clone git@github.com:Shadowell/HyperTrade.git
cd HyperTrade
cp .env.example .env
# Edit .env with your API keys
```

### Launch

**Backend** (API server):
```bash
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

**Frontend** (Web console):
```bash
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
```

**CLI** (command-line interface):
```bash
uv run ht --local
```

### Access Points

| Service | URL |
|---------|-----|
| Web Console | http://localhost:3333/harness |
| API Docs (Swagger) | http://localhost:3334/docs |
| Health Check | http://localhost:3334/api/health |

### Docker (PostgreSQL + pgvector)

```bash
docker compose up -d postgres
export DATABASE_URL="postgresql://hypertrade:hypertrade@localhost:5432/hypertrade"
uv run alembic upgrade head
```

---

## Usage

### Market Research

```bash
# Natural language queries
uv run hypertrade --local ask "看下目前市场的热度怎么样"

# Structured commands
/price ETH
/candles BTC 1H 120
/compare ETH SOL BTC
/global-market          # Cross-asset regime snapshot
```

### Strategy Research

```bash
/research 研究ETH趋势突破策略     # Create research record
/backtest                         # Run Backtrader backtest
/experiment 不同参数动量策略       # Multi-variant experiment
/strategy library momentum_v1     # Query aggregated evidence
```

### BitPro Integration

```bash
# Query backtest performance
查看 BitPro 回测收益大于100%的策略有哪些

# Inspect backtest details
查看 BitPro 回测 result 196 的权益曲线和交易证据

# Monitor live paper strategies
监控 BitPro 所有运行中的模拟盘策略，列出异常和数据缺口
```

### Paper Trading

```bash
/paper                   # Status overview
/paper pause BTC         # Pause a strategy
/paper resume            # Resume all
/paper close             # Close positions
/paper reset             # Reset simulation
```

### Testnet Execution (Approval-Gated)

```bash
/live intent ETH buy 0.01 reason="API smoke test"
/live intents            # List pending intents
/live approve loi_abc123 # Approve for execution
/live execute loi_abc123 # Submit to OKX Testnet
```

### RAG & Memory

```bash
/rag 风控                # Semantic search over knowledge base
/memory search tag:strategy  # Query audited memory
```

### API Access

```bash
# Streaming agent run
curl -N -X POST http://localhost:3334/api/agent/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt":"请做行情归纳"}'

# RAG search
curl "http://localhost:3334/api/rag/search?query=风控&limit=5"

# Memory query
curl "http://localhost:3334/api/memory?query=市场&limit=10"

# Market snapshot
curl http://localhost:3334/api/global-market/snapshot
```

### Durable Agent Sessions and Tasks

Every new local or API Agent run is backed by a durable Session and Task. `AgentRun`
remains the immutable execution attempt, while Task owns pause, resume, cancel,
retry, branch, budget, checkpoint, lease, and recovery state.

```bash
/sessions
/tasks
/task task_abc123
/task task_abc123 pause "operator review"
/task task_abc123 resume "review completed"
```

Task events are cursor-addressable through
`GET /api/agent/tasks/{task_id}/events?after=<sequence>` or SSE at
`GET /api/agent/tasks/{task_id}/stream`. Control APIs require an authenticated
administrator, a reason, and an idempotency key. Provider timeouts become
structured retryable Task errors instead of uncaught HTTP 500 responses.
Sprint 96 is production-verified: the PostgreSQL migration, durable Agent run,
checkpoint, monotonic event cursor, and remote CLI inspection all passed after
deployment.

### Structured Research Evidence

Research Evidence V2 is an append-only, source-bound ledger for `fact`,
`inference`, `counter_evidence`, and `data_gap` records. Canonical UTC/Decimal
JSON produces a stable SHA-256 identity; facts require an available non-Memory
source, inferences require active supporting evidence, and counter-evidence must
name the challenged record. Expiry, rejection, conflict, and supersession remain
visible lifecycle or graph state instead of rewriting historical claims.

Read APIs expose evidence, filters, and relation graphs. Append and lifecycle
mutations require an administrator session; no Agent tool has direct evidence
mutation authority. Legacy experiment and Memory evidence remains read-only and
is explicitly labelled as legacy context rather than promoted to a V2 fact.

---

## Documentation

| Document | Description |
|----------|-------------|
| [API Reference](docs/api-reference.md) | Complete REST/SSE API documentation |
| [User Manual](docs/user-manual.md) | Operator guide for all surfaces (CLI, Web, API) |
| [Developer Guide](docs/developer-guide.md) | Extending HyperTrade with tools, providers, connectors |
| [Documentation Index](docs/documentation-index.md) | Full documentation map |
| [Architecture Docs](docs/architecture/) | System design and module documentation (20+ docs) |
| [Product Spec](docs/spec.md) | Vision, scope, and roadmap |
| [Knowledge Base](docs/knowledge/) | Operator guides and best practices |
| [Runbooks](docs/runbooks/) | Deployment, monitoring, incident response |

Chinese translations available for all primary documents.

---

## Development

### Quality Gates

```bash
./scripts/check.sh       # Full suite: tests, lint, type-check
uv run pytest tests/ -v  # Run specific tests
```

### Code Standards

**Python**:
```bash
uv run ruff format .     # Auto-format
uv run ruff check .      # Lint
uv run mypy backend/src  # Type-check
```

**Frontend**:
```bash
npm exec --yes pnpm@10 -- -C frontend lint
npm exec --yes pnpm@10 -- -C frontend format
```

### Evaluation Suite

Deterministic evals guard against regressions across tool choice, RAG citations, Memory behavior, risk refusal, BitPro source-of-truth usage, and report quality.

```bash
uv run ht --local /evals
curl http://localhost:3334/api/evals/status
```

Optional evaluation tooling is documented in
[`docs/architecture/26-agent-evaluation-foundation.md`](docs/architecture/26-agent-evaluation-foundation.md).
It keeps the deterministic suite as the CI gate, uses metadata-only opt-in
self-hosted Langfuse tracing, and limits Promptfoo/Ragas to isolated,
read-only evaluation runs.

---

## Deployment

Automated deployment via GitHub Actions to a self-hosted runner on push to `main`.

```bash
# Manual deployment
ssh hypertrade-server
sudo -u hypertrade /opt/hypertrade/deploy/deploy.sh

# Post-deploy verification
curl -fsS http://localhost:3334/api/health
hypertrade ask "看下ETH行情"
```

See [Runbooks](docs/runbooks/) for detailed deployment and monitoring procedures.

---

## Security

- **Secrets**: API keys, tokens, and credentials managed via environment variables; never committed
- **BitPro Boundary**: All BitPro access through stable MCP/API contracts only
- **Audit Trail**: Every tool execution logged with timestamp, payload, and provenance
- **Idempotency**: Write operations require idempotency keys
- **Approval Gates**: Human-in-the-loop for Testnet orders and destructive operations
- **Testnet First**: Mainnet live execution blocked in V1

---

## Roadmap

### Current (V2)

| Initiative | Status |
|-----------|--------|
| World Model — portfolio state and defensive actions | In Progress |
| Global Market — cross-asset regime classification | Production |
| Vide Coding (opus-4.6) provider | Production |
| Enhanced output formatting | Complete |
| Agent Session and Task OS | Production |
| Research Evidence V2 contract | Production |
| Multi-Agent research graph V1 | Production |
| Reproducible experiment ledger | In Progress |

### Planned (V3+)

- Custom strategy DSL
- Multi-exchange support (Binance, Bybit)
- Advanced risk modeling (VaR, CVaR)
- Mainnet execution framework (pending governance)

---

## Contributing

1. Review active sprint scope in `docs/contracts/`
2. Keep changes within contract scope
3. Run `./scripts/check.sh` before committing
4. Commit to `main` (no feature branches in current workflow)
5. Push triggers automatic CI/CD deployment

See [Developer Guide](docs/developer-guide.md) for detailed contribution guidelines.

---

## Acknowledgments

Built with these excellent projects and services:

[OKX API](https://www.okx.com/docs-v5/) · [Backtrader](https://www.backtrader.com/) · [FastAPI](https://fastapi.tiangolo.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [React](https://reactjs.org/) · [Vite](https://vitejs.dev/) · [pgvector](https://github.com/pgvector/pgvector) · [Alembic](https://alembic.sqlalchemy.org/)

---

<div align="center">

**[Documentation](docs/documentation-index.md)** · **[User Manual](docs/user-manual.md)** · **[Developer Guide](docs/developer-guide.md)** · **[API Reference](docs/api-reference.md)**

</div>
