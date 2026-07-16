# HyperTrade

**Agent-First Crypto Trading Research & Execution Framework**

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://reactjs.org/)

[📖 Full README](README.md) | [中文版](README.zh-CN.md) | [Documentation Center](docs/documentation-index.md)

---

## What is HyperTrade?

HyperTrade is a self-hosted, governed Agent runtime for crypto-market research. It turns an open-ended
objective into a durable Mission with a versioned plan, bounded steps, evidence, budgets, operator
controls, and an auditable delivery. It provides a unified environment for market research, strategy
development, paper observations, and controlled Testnet intent inspection.

Models can propose work, but they cannot grant permissions, invent evidence, or authorize trades.
HyperTrade is a controlled research loop—not an unattended trading bot—and it does not promise
profitability or provide investment advice.

> **Maturity note:** reviewed trading-research capabilities and selected read-only Mission requests are
> deployed, but HyperTrade is not yet a complete professional general Agent runtime. A real-code audit found
> Run/Task/Mission compatibility paths, surface-specific conversation history, and an event log that cannot
> reconstruct every projection. A fixed 100-task pass is bounded regression evidence, not an overall
> production-grade certification.

**Key Capabilities**:
- 🤖 Natural language interaction with automatic tool selection
- 📊 Real-time OKX market data and technical analysis
- 🧪 Evidence-driven strategy backtesting and experimentation
- 🎮 Paper trading simulation with full lifecycle controls
- ⚡ Approval-gated Testnet execution (V1 blocks mainnet)
- 🔗 BitPro integration via MCP adapter
- 💾 RAG knowledge retrieval and audited Memory system

> Use the [current implementation snapshot](docs/architecture/33-system-architecture.md) for delivered
> boundaries and the [real-code audit and target design](docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md)
> for the canonical Thread/Turn protocol, state machines, permissions, multi-agent model and cutover.

---

## Quick Start

### Install

```bash
git clone git@github.com:Shadowell/HyperTrade.git
cd HyperTrade
cp .env.example .env
# Edit .env with your API keys

export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"
export DEEPSEEK_API_KEY="your-key"
```

### Run

**Backend**:
```bash
uv run uvicorn hypertrade.main:app --app-dir backend/src --port 3334
```

**Frontend**:
```bash
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
```

**CLI**:
```bash
uv run ht --local
```

**Access**:
- Web Console: http://localhost:3333/harness
- API Docs: http://localhost:3334/docs

---

## Usage Examples

### Market Research
```bash
# Natural language
uv run hypertrade --local ask "看下目前市场的热度怎么样"

# Deterministic commands
/price ETH
/candles BTC 1H 120
/compare ETH SOL BTC
```

### Strategy Research
```bash
/research 研究ETH趋势突破策略
/backtest
/experiment 实验ETH动量突破策略的不同参数
/strategy library momentum_breakout_v1
```

### Paper Trading
```bash
/paper              # Check status
/paper pause BTC    # Pause BTC trading
/paper close        # Close all positions
```

### Live Orders (Testnet)
```bash
/live intent ETH buy 0.01 reason="test"
/live approve loi_abc123
/live execute loi_abc123
```

---

## Architecture

```
Client Layer (CLI, Web, API)
    ↓
Agent Runtime (Kernel, Planner, Tool Executor)
    ↓
Governance (ToolRegistry, Risk Policy, Trace)
    ↓
Services (Market, RAG, Memory, Strategy, Backtest)
    ↓
Data Layer (PostgreSQL/SQLite, OKX, BitPro)
```

**Tech Stack**:
- Backend: Python 3.12+, FastAPI, SQLAlchemy, Backtrader
- Frontend: React 18, TypeScript, Vite, TailwindCSS
- Database: PostgreSQL 14+ with pgvector (or SQLite)
- Infrastructure: Docker Compose, Nginx, GitHub Actions

Mission is the intended record for newer research work, but natural-language entry points still include
legacy Run/Task compatibility and the surfaces do not yet share a durable server-side Thread/Turn history.
The reviewed capability catalog and risk policy remain the tool-dispatch authority. Migration starts with
the Remote CLI as a vertical slice and does not use permanent dual writes.

---

## Documentation

| Document | Link |
|----------|------|
| **Complete README** | [README.md](README.md) |
| **Target Architecture** | [docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md](docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md) |
| **Current System Snapshot** | [docs/architecture/33-system-architecture.md](docs/architecture/33-system-architecture.md) |
| **API Reference** | [docs/api-reference.md](docs/api-reference.md) |
| **User Manual** | [docs/user-manual.md](docs/user-manual.md) |
| **Developer Guide** | [docs/developer-guide.md](docs/developer-guide.md) |
| **Documentation Center** | [docs/documentation-index.md](docs/documentation-index.md) |
| **Architecture** | [docs/architecture/](docs/architecture/) |
| **Product Spec** | [docs/spec.md](docs/spec.md) |

Chinese versions available: [中文文档](docs/documentation-index.md)

---

## Testing

```bash
# Full test suite
./scripts/check.sh

# Specific tests
uv run pytest tests/test_api.py -v
npm exec --yes pnpm@10 -- -C frontend test

# Eval status
uv run ht --local /evals
```

---

## Deployment

**Automatic** (via GitHub Actions):
```bash
git push origin main
# Deploys to production automatically
```

**Manual**:
```bash
ssh hypertrade-server
cd /opt/hypertrade
sudo -u hypertrade ./deploy/deploy.sh
```

---

## Contributing

1. Check `docs/contracts/` for active sprint scope
2. Update docs when behavior changes
3. Run `./scripts/check.sh` before committing
4. Commit to `main` branch
5. Push triggers automatic deployment

See [Developer Guide](docs/developer-guide.md) for details.

---

## License

Released under the [MIT License](LICENSE).

Research purposes only. No investment advice.

---

## Contact

- **Documentation**: [docs/documentation-index.md](docs/documentation-index.md)
- **Issues**: Submit via repository issue tracker

---

<div align="center">

**Built for systematic crypto trading research**

[Full README](README.md) • [Documentation](docs/documentation-index.md) • [User Manual](docs/user-manual.md)

</div>
