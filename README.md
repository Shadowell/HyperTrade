# HyperTrade

**Agent-First Crypto Trading Research & Execution Framework**

[![License](https://img.shields.io/badge/license-Private-red.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://reactjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg)](https://www.typescriptlang.org/)

[中文简版](README.zh-CN.md) | [English Summary](README.en.md) | [📚 Documentation](docs/documentation-index.md)

---

## 🎯 Overview

HyperTrade is a production-grade Agent runtime for crypto trading research and execution. It provides operators, engineers, and external Agents with a unified, governed environment for:

- 📊 **Market Intelligence**: Real-time OKX SWAP data, multi-source analysis, technical indicators
- 🧪 **Strategy Research**: Evidence-driven backtesting, multi-variant experiments, knowledge management
- 🎮 **Paper Trading**: Risk-free simulation environment with full lifecycle controls
- ⚡ **Testnet Execution**: Gated OKX Testnet order execution with approval workflow (V1 blocks mainnet)
- 🔗 **BitPro Integration**: MCP-based adapter for strategy lifecycle, backtest diagnostics, and monitoring
- 🤖 **Intelligent Agent**: Natural language interaction with automatic tool selection and traceability
- 💾 **Knowledge Systems**: RAG document retrieval and audited Memory persistence

> **Research Only**: Nothing in this repository constitutes investment advice. Mainnet live order execution is blocked in V1.

---

## ✨ Key Features

### 🏗️ Production-Ready Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Client Layer                                                │
│  CLI • Web Console • REST/SSE API • External Agents         │
├─────────────────────────────────────────────────────────────┤
│  Agent Runtime                                               │
│  LangGraph-style Kernel • Provider Router • Tool Executor   │
├─────────────────────────────────────────────────────────────┤
│  Governance Layer                                            │
│  ToolRegistry • Risk Policy • Approval Gates • Trace        │
├─────────────────────────────────────────────────────────────┤
│  Service Layer                                               │
│  Market • RAG • Memory • Strategy • Backtest • Monitor      │
├─────────────────────────────────────────────────────────────┤
│  Data Layer                                                  │
│  PostgreSQL/pgvector • OKX API • BitPro MCP                 │
└─────────────────────────────────────────────────────────────┘
```

### 🎨 Operator Surfaces

- **CLI**: `hypertrade` / `ht` - Feature-rich terminal interface with history, colors, and remote mode
- **Web Console**: React + Vite workbench at `/harness` - runs, reports, trace, market snapshot, controls
- **REST API**: FastAPI with streaming SSE, OpenAPI docs at `/docs`

### 🔧 Agent Capabilities

| Capability | Implementation | Status |
|------------|----------------|--------|
| **Natural Language** | Free-form prompts → tool selection via LLM planner | ✅ Production |
| **Tool Calling** | Registry-based with policy enforcement (scope, approval, idempotency) | ✅ Production |
| **Market Intelligence** | OKX SWAP tickers, candles, funding, OI, relative strength | ✅ Production |
| **RAG** | pgvector-backed citation search over `docs/knowledge` | ✅ Production |
| **Memory** | Audited observations and strategy knowledge with tags, confidence, importance | ✅ Production |
| **Strategy Research** | Backtrader backtests, multi-variant experiments, evidence library | ✅ Production |
| **BitPro Integration** | MCP adapter for strategy lifecycle, backtest diagnostics, paper monitoring | ✅ Production |
| **Paper Trading** | Simulated execution with pause/resume/close/reset controls | ✅ Production |
| **Testnet Execution** | Approval-gated OKX Testnet orders with risk checks | ✅ Production |
| **Monitoring & Alerts** | Read-only monitors for paper strategies, connector health, library freshness | ✅ Production |
| **Evaluation Suite** | Deterministic evals for tool choice, RAG, Memory, risk, report quality | ✅ Production |
| **World Model** | Portfolio state tracking and defensive action scheduling | 🧪 Experimental |

### 🛡️ Governance & Safety

- **Risk Engine**: Enforces tool policies (scope, approval, idempotency) before execution
- **Approval Gates**: Human-in-the-loop for Testnet orders, paper resets, defensive actions
- **Idempotency**: Write operations require idempotency keys for audit and replay protection
- **Trace**: Every tool call persisted with payload, timestamp, and provenance
- **BitPro Boundary**: Only accesses BitPro through stable MCP/API contracts, never bypasses risk boundaries
- **Evidence Over Inference**: Reports missing data as unavailable, never smooths over gaps

### 📈 Strategy Development Workflow

1. **Research** → `/research <prompt>` - Create research record with initial analysis
2. **Backtest** → `/backtest` - Run Backtrader backtest with OKX/BitPro/sample data
3. **Experiment** → `/experiment <prompt>` - Compare baseline/fast/conservative variants
4. **Gate** → Automatic winner selection through explicit gate conditions
5. **Memory** → Strategy knowledge card with parameters, metrics, gates, next-experiment guidance
6. **Library** → `/strategy library <name>` - Retrieve aggregated evidence for iteration planning

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- `uv` package manager
- Node.js 18+ and `pnpm`
- Optional: Docker & Docker Compose for PostgreSQL/pgvector
- Chat provider API key (e.g., DeepSeek, OpenAI, Codex)

### Installation

```bash
# Clone repository
git clone git@github.com:Shadowell/HyperTrade.git
cd HyperTrade

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Minimal local setup (SQLite)
mkdir -p .local
export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"
export KNOWLEDGE_DIR="docs/knowledge"
export DEEPSEEK_API_KEY="your-api-key"
```

### Run Locally

**Terminal 1 - Backend**:
```bash
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

**Terminal 2 - Frontend**:
```bash
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
```

**Terminal 3 - CLI**:
```bash
uv run ht --local
```

### Access

- **Web Console**: http://localhost:3333/harness
- **API Docs**: http://localhost:3334/docs
- **Health Check**: http://localhost:3334/api/health

---

## 📖 Documentation

Comprehensive documentation available in English and Chinese:

| Document | English | 中文 |
|----------|---------|------|
| **API Reference** | [api-reference.md](docs/api-reference.md) | [api-reference.zh-CN.md](docs/api-reference.zh-CN.md) |
| **User Manual** | [user-manual.md](docs/user-manual.md) | [user-manual.zh-CN.md](docs/user-manual.zh-CN.md) |
| **Developer Guide** | [developer-guide.md](docs/developer-guide.md) | [developer-guide.zh-CN.md](docs/developer-guide.zh-CN.md) |
| **Documentation Index** | [documentation-index.md](docs/documentation-index.md) | - |

### Additional Resources

- **Product Spec**: [docs/spec.md](docs/spec.md) - Product vision and roadmap
- **Architecture**: [docs/architecture/](docs/architecture/) - System design and module documentation
- **Knowledge Base**: [docs/knowledge/](docs/knowledge/) - Operator guides and best practices
- **Runbooks**: [docs/runbooks/](docs/runbooks/) - Deployment, monitoring, incident response
- **Contracts**: [docs/contracts/](docs/contracts/) - Sprint contracts and delivery scopes
- **Progress Log**: [docs/progress.md](docs/progress.md) - Development history and deployment record

---

## 💡 Usage Examples

### Market Research

```bash
# CLI - Natural language
uv run hypertrade --local ask "看下目前市场的热度怎么样"

# CLI - Deterministic shortcuts
uv run ht --local
> /price ETH
> /candles BTC 1H 120
> /compare ETH SOL BTC

# API - Streaming
curl -N -X POST http://localhost:3334/api/agent/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"prompt":"请做行情归纳"}'
```

### Strategy Research & Backtest

```bash
# Create research record
/research 研究ETH趋势突破策略

# Run backtest with OKX data
/backtest

# Run multi-variant experiment
/experiment 实验ETH动量突破策略的不同参数

# Query strategy library
/strategy library momentum_breakout_v1
```

### BitPro Integration

```bash
# Query BitPro backtests
查看 BitPro 回测收益大于100%的策略有哪些

# Get backtest details
查看 BitPro 回测 result 196 的权益曲线和交易证据

# Monitor paper strategies
监控 BitPro 所有运行中的模拟盘策略，列出异常和数据缺口

# Check live performance
看下实盘收益最高的策略
```

### Paper Trading

```bash
# Check status
/paper

# Control operations
/paper pause BTC
/paper resume
/paper close
/paper reset
```

### Live Order Intents (Testnet)

```bash
# Create intent
/live intent ETH buy 0.01 reason="API smoke test"

# List intents
/live intents

# Approve and execute
/live approve loi_abc123
/live execute loi_abc123
```

### RAG & Memory

```bash
# Search knowledge docs
/rag 风控

# Search memory
/memory search tag:strategy

# Query via API
curl "http://localhost:3334/api/rag/search?query=风控&limit=5"
curl "http://localhost:3334/api/memory?query=市场&limit=10"
```

---

## 🏗️ Architecture Highlights

### Component Layers

| Layer | Responsibility | Key Files |
|-------|----------------|-----------|
| **Client Access** | CLI, `/harness`, REST/SSE API, future external Agents | `backend/src/hypertrade/cli.py`, `frontend/` |
| **Data Inputs** | OKX market data, BitPro MCP/API, knowledge docs, audited Memory | `backend/src/hypertrade/market/`, `backend/src/hypertrade/bitpro/` |
| **Governance Gateway** | Provider runtime, ToolRegistry, risk policy, trace, connector metadata | `backend/src/hypertrade/providers/`, `backend/src/hypertrade/tools/` |
| **Agent Engine** | Planner, graph runtime, tool execution, report rendering, eval guardrails | `backend/src/hypertrade/agent/` |
| **Execution/Output** | Reports, strategy flow, paper/Testnet lifecycle, alerts | `backend/src/hypertrade/strategy/`, `backend/src/hypertrade/monitoring.py` |
| **Infrastructure** | FastAPI, PostgreSQL/pgvector, worker loops, Docker Compose, Nginx | `deploy/`, `.github/workflows/deploy.yml` |

### Technology Stack

**Backend**:
- Python 3.12+ with `uv` package management
- FastAPI for REST/SSE API
- SQLAlchemy + Alembic for database
- PostgreSQL 14+ with pgvector extension (or SQLite for development)
- Backtrader for backtesting
- httpx for external API calls

**Frontend**:
- React 18 + TypeScript 5
- Vite for build tooling
- TanStack Query for data fetching
- Recharts for visualization
- Tailwind CSS for styling

**Infrastructure**:
- Docker Compose for local/production services
- Nginx for reverse proxy and static serving
- GitHub Actions for CI/CD
- Self-hosted runner for production deployment

**Integrations**:
- OKX REST/WebSocket for market data
- BitPro MCP for strategy lifecycle
- DeepSeek/OpenAI/Codex for LLM providers
- Qwen for embeddings

---

## 🧪 Testing & Quality

### Test Coverage

```bash
# Full verification suite
./scripts/check.sh

# Run specific tests
uv run pytest tests/test_api.py -v
uv run pytest tests/test_agent_eval_suite.py -v

# Frontend tests
npm exec --yes pnpm@10 -- -C frontend test
```

### Evaluation Suite

Deterministic evals guard against regressions:

- ✅ Tool choice (market summary, ticker, candles, compare)
- ✅ RAG citations (source paths, missing field disclosure)
- ✅ Memory behavior (tagging, confidence, deduplication)
- ✅ Risk refusal (live write tools blocked in V1)
- ✅ BitPro source-of-truth use (backtest metrics, page parity)
- ✅ Paper monitor read-only boundary
- ✅ Report quality (compact, structured, no noise)
- ✅ Live routing (order history, strategy performance)

Check eval status:
```bash
uv run ht --local /evals
curl http://localhost:3334/api/evals/status
```

---

## 🚢 Deployment

### Production Deployment

HyperTrade deploys automatically via GitHub Actions to a self-hosted runner:

1. Push to `main` branch
2. GitHub Actions triggers `.github/workflows/deploy.yml`
3. Self-hosted runner (`hypertrade-production`) pulls code, builds images, restarts services
4. Deployment SHA recorded in `/opt/hypertrade/deploy/last_deployed_sha`

**Manual Deployment**:
```bash
ssh hypertrade-server
cd /opt/hypertrade
sudo -u hypertrade ./deploy/deploy.sh
```

**Post-Deploy Verification**:
```bash
curl -fsS http://localhost:3334/api/health
curl -fsS http://localhost:3333/api/health  # via Nginx
hypertrade ask "看下ETH行情"
```

### Configuration

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL or SQLite connection string | - |
| `DEEPSEEK_API_KEY` | DeepSeek API key for chat provider | - |
| `OKX_API_KEY` | OKX API credentials for market data | - |
| `BITPRO_MCP_API_BASE` | BitPro MCP base URL | - |
| `BITPRO_MCP_API_TOKEN` | BitPro MCP authentication token | - |
| `KNOWLEDGE_DIR` | Path to knowledge documents | `docs/knowledge` |
| `PAPER_ENABLED` | Enable paper trading | `true` |
| `MONITOR_SCHEDULER_ENABLED` | Enable automatic monitor runs | `false` |

See `.env.example` for full configuration options.

---

## 🔒 Security & Compliance

### Access Control

- **Public Read**: Market data, RAG, Memory search, run history, trace events
- **Admin Auth**: Paper controls, live order approvals, provider selection, monitor triggers
- **Session Cookie**: HttpOnly, SameSite=Lax, secure in production

### Data Protection

- **Secrets**: Never commit API keys, tokens, or production `.env` files
- **BitPro Boundary**: Only access through MCP/API contracts, never bypass
- **Audit Trail**: Every tool execution logged with timestamp, payload, provenance
- **Idempotency**: Write operations require idempotency keys

### Compliance

- **Research Only**: No investment advice, educational purposes only
- **Testnet First**: V1 blocks mainnet live order execution
- **Human Approval**: Testnet orders require explicit approval before execution
- **Risk Gates**: Orders rejected if exceed notional limits or open intent count

---

## 📊 Performance & Scalability

### Current Capacity

- **Agent Runs**: ~5-10 concurrent runs (provider rate limits apply)
- **Market Data**: 100+ OKX SWAP tickers, real-time WebSocket + REST fallback
- **RAG**: 1000+ document chunks, sub-second search with pgvector
- **Memory**: Unlimited items, indexed by type, tags, confidence, importance
- **Trace**: Retention policy TBD (currently unlimited)

### Optimization Strategies

- **Caching**: Market ticker snapshots, provider responses (planned)
- **Pagination**: API endpoints support limit/offset for large result sets
- **Streaming**: SSE for long-running Agent tasks
- **Worker Offload**: Market ingestion, RAG scanning, monitor runs in background
- **Database**: PostgreSQL with indexes on common query patterns

---

## 🤝 Contributing

### Development Workflow

1. **Read Contracts**: Check `docs/contracts/` for active sprint scope
2. **Stay in Scope**: Keep changes within current sprint contract unless explicitly expanded
3. **Update Docs**: Update architecture/knowledge docs when behavior, API, or operational expectations change
4. **Run Tests**: Execute `./scripts/check.sh` before committing
5. **Commit**: Commit to `main` branch (no feature branches in current workflow)
6. **Deploy**: Push triggers automatic deployment via GitHub Actions
7. **Verify**: Smoke test production health after deployment

### Code Style

**Python**:
```bash
uv run ruff format .
uv run ruff check .
uv run mypy backend/src
```

**TypeScript/React**:
```bash
npm exec --yes pnpm@10 -- -C frontend lint
npm exec --yes pnpm@10 -- -C frontend format
```

### Adding New Components

- **Tools**: See [Developer Guide - Adding New Tools](docs/developer-guide.md#adding-new-tools)
- **Providers**: See [Developer Guide - Adding New Providers](docs/developer-guide.md#adding-new-providers)
- **Connectors**: See [Developer Guide - Adding Connectors](docs/developer-guide.md#adding-connectors)

---

## 🐛 Troubleshooting

### Common Issues

| Symptom | Likely Cause | Solution |
|---------|--------------|----------|
| Free-form prompt returns `provider_unavailable` | No chat provider key configured | Check `DEEPSEEK_API_KEY`, run `/model` |
| BitPro tools return 502 | BitPro MCP connection issue | Check `BITPRO_MCP_API_BASE`, `BITPRO_MCP_API_TOKEN` |
| Market data empty | Worker not running or OKX unavailable | Check worker logs, `OKX_REST_URL` |
| RAG search no results | Knowledge dir not scanned | Check `KNOWLEDGE_DIR`, RAG scan logs |
| Testnet order fails | Missing OKX Testnet credentials or risk gate denial | Check `OKX_TESTNET`, API keys, risk payload |
| Web UI slow | Large data volume or SQLite performance | Use PostgreSQL, clean old runs/trace |

See [User Manual - Common Issues](docs/user-manual.md#common-issues) for detailed troubleshooting.

---

## 📜 License

**Private Repository** - All rights reserved.

This is a private research project. Unauthorized copying, distribution, or use is prohibited.

**Security Notice**:
- Keep secrets, provider keys, OKX credentials, BitPro tokens out of version control
- Never commit database files or production `.env` files
- Use environment variables or secure secret management for production

---

## 🙏 Acknowledgments

- **OKX**: Market data provider via public REST/WebSocket API
- **BitPro**: Trading system integration via MCP adapter
- **DeepSeek**: Default LLM provider for Agent planning
- **LangGraph**: Inspiration for graph-style Agent runtime
- **Backtrader**: Python backtesting framework
- **FastAPI**: Modern Python web framework
- **React + Vite**: Frontend stack

---

## 📞 Contact & Support

- **Documentation**: [docs/documentation-index.md](docs/documentation-index.md)
- **Architecture**: [docs/architecture/](docs/architecture/)
- **Runbooks**: [docs/runbooks/](docs/runbooks/)
- **Issues**: Submit via repository issue tracker
- **Email**: Contact repository owner for access requests

---

## 🗺️ Roadmap

### Completed (V1)

- ✅ Agent runtime with LangGraph-style kernel
- ✅ Provider router (DeepSeek, OpenAI, Codex, OpenRouter)
- ✅ Tool registry with policy enforcement
- ✅ Market intelligence (OKX SWAP data, technical indicators)
- ✅ RAG with pgvector citation search
- ✅ Memory with tags, confidence, importance
- ✅ Strategy research and Backtrader backtests
- ✅ Multi-variant experiments with automatic winner selection
- ✅ Strategy library aggregation from memory
- ✅ BitPro MCP adapter for lifecycle operations
- ✅ Paper trading with full lifecycle controls
- ✅ Testnet order execution with approval gates
- ✅ Monitoring & alerts (paper, connector, library)
- ✅ Risk governance policy enforcement
- ✅ Deterministic evaluation suite
- ✅ CLI with history, colors, remote mode
- ✅ Web console at `/harness`
- ✅ REST/SSE API with OpenAPI docs
- ✅ Docker Compose deployment
- ✅ GitHub Actions CI/CD

### In Progress (V2)

- 🚧 World model with portfolio state tracking
- 🚧 Defensive action engine with scheduling
- 🚧 Enhanced connector framework
- 🚧 Advanced monitoring with anomaly detection

### Planned (V3+)

- 📋 Multi-Agent collaboration patterns
- 📋 Custom strategy DSL and code generation
- 📋 Real-time portfolio rebalancing
- 📋 Advanced risk modeling (VaR, CVaR)
- 📋 Multi-exchange support (Binance, Bybit)
- 📋 Options and derivatives support
- 📋 Mobile companion app
- 📋 Mainnet execution (pending governance framework)

---

<div align="center">

**Built with ❤️ for systematic crypto trading research**

[Documentation](docs/documentation-index.md) • [User Manual](docs/user-manual.md) • [Developer Guide](docs/developer-guide.md) • [API Reference](docs/api-reference.md)

</div>
