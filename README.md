# HyperTrade

<p align="center">
  <strong>Governed Agent Runtime for Evidence-Driven Crypto Trading Research</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/FastAPI-0.104+-009688.svg" alt="FastAPI" /></a>
  <a href="#"><img src="https://img.shields.io/badge/React-18+-61DAFB.svg" alt="React" /></a>
  <a href="#"><img src="https://img.shields.io/badge/TypeScript-5.0+-3178C6.svg" alt="TypeScript" /></a>
  <a href="#"><img src="https://img.shields.io/badge/PostgreSQL-14+-4169E1.svg" alt="PostgreSQL" /></a>
  <a href="docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md"><img src="https://img.shields.io/badge/status-canonical_protocol_hardening-orange.svg" alt="Status" /></a>
</p>

<p align="center">
  <a href="README.zh-CN.md">中文文档</a> ·
  <a href="README.en.md">English Summary</a> ·
  <a href="docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md">Target Architecture</a> ·
  <a href="docs/documentation-index.md">Documentation</a> ·
  <a href="docs/api-reference.md">API</a> ·
  <a href="docs/user-manual.md">User Manual</a> ·
  <a href="docs/developer-guide.md">Developer Guide</a>
</p>

---

## Overview

HyperTrade is a self-hosted, governed Agent runtime for crypto-market research. It turns an open-ended
research objective into a durable **Mission** with a versioned plan, bounded steps, evidence, budgets,
operator controls, and an auditable delivery. Models can propose work; they cannot expand permissions,
invent evidence, or authorize trades.

It connects LLM reasoning to governed market data, strategy/backtest facts, paper-state observations and
risk-gated Testnet intent summaries. The result is a controlled research loop—from a natural-language
question to evidence-backed strategy iteration—not an unattended trading bot.

![HyperTrade Architecture](docs/assets/hypertrade-architecture.svg)

> 📖 Start with the [System Architecture](docs/architecture/33-system-architecture.md), then use the
> [real-code audit and target design](docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md)
> to distinguish the current implementation from the canonical Thread/Turn architecture being built.

> **Maturity note:** reviewed trading-research capabilities and selected read-only Mission requests are
> deployed, but HyperTrade is not yet a complete professional general Agent runtime. The current system still
> contains Run/Task/Mission compatibility paths, surface-specific conversation history and an event log that
> cannot reconstruct every projection. The fixed 100-task suite is useful regression evidence, not an overall
> production-grade certification.

### What HyperTrade Owns—and What It Does Not

| HyperTrade owns | It deliberately does not do |
| --- | --- |
| Mission lifecycle, tool governance, evidence/Artifact references, research orchestration, audit and operator delivery | Promise profitability, give investment advice, or enable unattended real-money trading |
| A reviewed capability catalog over market, knowledge, strategy/backtest, paper and Testnet-read surfaces | Treat model text as evidence or let a planner grant itself a tool/permission |
| Stable MCP/API integration with BitPro | Read BitPro's database directly or copy BitPro trading business logic |
| Human-reviewed research and isolated strategy-code validation | Enable mainnet execution; current Mission capabilities are governed reads |

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

## Architecture at a Glance

~~~mermaid
flowchart LR
  U["Operator / External Agent"] --> S["Web · CLI · TUI · Desktop<br/>REST / SSE"]
  S --> C["Mission Control API"]
  C --> M["Mission Runtime<br/>Plan · Context · Validate · Deliver"]
  W["SQL-leased Worker"] --> M
  M --> G["Reviewed Capability Catalog<br/>Governed Tool Executor"]
  M --> D[("PostgreSQL + pgvector<br/>events · projections · audit")]
  G --> X["OKX · RAG · Memory<br/>BitPro MCP/API"]
  C --> B["Isolated strategy sandbox<br/>digest-bound UDS"]
~~~

Mission is the intended research-workflow record, but the current natural-language surfaces still include
legacy Run/Task compatibility and do not yet share a durable Thread/Turn history. Reviewed capabilities,
bounded observations, SQL leases and SSE Mission events are implemented; complete event reduction,
cross-surface context, Approval and Supervisor integration are target work rather than finished claims.

See the [current implementation snapshot](docs/architecture/33-system-architecture.md) and the
[evidence-driven target architecture](docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md).

### Technology Stack

| Layer | Technologies |
|-------|-------------|
| **Runtime** | Python 3.12+, FastAPI, SQLAlchemy, Alembic |
| **Agent Engine** | Mission Runtime, provider-backed bounded planner, reviewed capability catalog, policy-enforced tool execution |
| **Frontend** | React 18, TypeScript 5, Vite, TanStack Query, Recharts |
| **Database** | PostgreSQL 14+ with pgvector (or SQLite for development) |
| **LLM Providers** | Vide Coding (opus-4.6), DeepSeek, OpenAI, Codex, OpenRouter, Qwen |
| **Backtesting** | Backtrader |
| **Infrastructure** | Docker Compose, Nginx, PostgreSQL leases, GitHub Actions CI/CD |

### Agent Capabilities

| Capability | Description | Status |
|-----------|-------------|--------|
| Natural Language | Free-form prompts with bounded planning and tool selection | Bounded coverage; canonical Thread/Turn pending |
| Tool Calling | Reviewed registry, scope, schema and idempotency enforcement | Read catalog deployed; Mission approval loop incomplete |
| Market Intelligence | OKX SWAP tickers, candles, funding, OI, relative strength indicators | Delivered read capability |
| Global Market | Cross-asset regime classification (equities, volatility, FX, rates) | Delivered read capability |
| RAG | pgvector-backed citation search over knowledge documents | Delivered |
| Memory | Audited observations with tags, confidence scoring, and importance weighting | Delivered; reviewed learning target pending |
| Strategy Research | Backtrader backtests, multi-variant experiments, evidence library | Delivered research workflows |
| BitPro Integration | MCP adapter for strategy lifecycle, backtest diagnostics, paper monitoring | Delivered governed contracts |
| Paper Trading | Simulated execution with lifecycle controls | Existing operator paths; not canonical Mission write |
| Testnet Execution | Approval-gated OKX Testnet orders with risk validation | Existing gated path; mainnet blocked |
| Monitoring & Alerts | Read-only monitors for paper strategies, connector health, library freshness | Delivered |
| Evaluation Suite | Fixed cohorts for tools, sources, safety and response quality | 100-task regression passes; fault/cross-surface gaps remain |
| Agent Task OS | Sessions/tasks/checkpoints plus newer Mission lifecycle | Legacy-compatible; canonical replacement planned |
| Professional Mission Runtime | Mission/Plan/Step/Attempt, budgets, read capabilities, SQL worker and sandbox | Selected read-only paths deployed; not end-to-end canonical |
| Research Triggers | Durable schedule/regime/drift/data/eval triggers with quotas, dedupe, and kill switch | Disabled by default |
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
# Same-host Docker deployments normally use the BitPro MCP endpoint below:
# BITPRO_REMOTE_MCP_URL=http://host.docker.internal:8889/api/v2/mcp/
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
/validations list                 # List robustness decisions
/validations show rvld_xxx        # Inspect scenarios and hard gates
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

### Reproducible Experiment Ledger

ResearchOrchestrator creates a canonical `ExperimentManifestV1` before any BitPro
strategy or backtest write. Semantic inputs and version hashes produce a stable
SHA-256 fingerprint; Task/Job IDs and timestamps do not. Identical queued, running,
or completed work reuses one execution, while failed or forced reruns append an
audited attempt.

HyperTrade retains bounded BitPro references, metrics, artifact hashes, usage and
Evidence IDs—not raw data, credentials, full prompts or private reasoning:

```text
/ledger list
/ledger show <fingerprint>
/ledger diff <left_fingerprint> <right_fingerprint>
```

Sprint 99 is production-verified. The ledger establishes reproducibility and audit,
not profitability, automatic optimization, paper promotion or live authority.

---

## Documentation

| Document | Description |
|----------|-------------|
| [System Architecture](docs/architecture/33-system-architecture.md) | Canonical system context, runtime layers, trust boundaries, data flow, deployment model, and contribution rules |
| [API Reference](docs/api-reference.md) | Complete REST/SSE API documentation |
| [User Manual](docs/user-manual.md) | Operator guide for all surfaces (CLI, Web, API) |
| [Developer Guide](docs/developer-guide.md) | Extending HyperTrade with tools, providers, connectors |
| [Documentation Index](docs/documentation-index.md) | Full documentation map |
| [Architecture Docs](docs/architecture/) | System design, runtime contracts, integration boundaries, and implementation decisions |
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

The required gate currently covers 40 deterministic cases: 14 legacy Agent
contracts plus 26 versioned Research OS cases for fixed quality cohorts, task recovery, role/node order,
Evidence, reproducibility, budgets, faults, cursor replay, privacy, and tool safety.
Server-side provider baselines run only through the separate
`hypertrade-agent-eval:latest` image against the loopback isolated API on `4334`.

Optional evaluation tooling is documented in
[`docs/architecture/26-agent-evaluation-foundation.md`](docs/architecture/26-agent-evaluation-foundation.md).
It keeps the deterministic suite as the CI gate, uses metadata-only opt-in
self-hosted Langfuse tracing, and limits the six-case Promptfoo suite and two-run
Ragas Research OS baseline to isolated, read-only evaluation runs. The V2 runner
requires two fixed-denominator runs to meet route/source/graph/task/safety thresholds;
its result never authorizes paper or live trading.

Sprint 106 production acceptance passed two isolated 26-case runs with 100% V2
route/source/citation/Graph/Task/safety gates and zero unsafe dispatch. Aggregate artifacts
remain prompt-, argument-, raw-output-, credential- and reasoning-free; provider variability
and latency remain diagnostic evidence, not a trading authorization.

The optional Textual research workbench runs over the same durable
Session/Task/Event APIs:

```bash
uv sync --extra tui
uv run ht --remote http://127.0.0.1:3334 tui
# On the deployed host, the wrapper selects the short-lived TUI image:
hypertrade tui
```

Use `--session ses_*` for an initial session filter. `Ctrl+N` focuses the multiline
task input; `Ctrl+P`, `Ctrl+R`, and `Ctrl+C` request pause, resume/retry, and cancel
through reason-required modals. The TUI is an operator surface only; server-side auth,
idempotency, state machines, budgets and risk gates remain authoritative.

Sprint 103 provides disabled-by-default background research triggers. They create only
bounded, auditable Tasks from committed schedule/market/data/eval facts; they have no
direct BitPro, paper, testnet, live, approval or capital path. Operators can inspect and
control them through the API, `/triggers` CLI command, or the TUI Triggers tab:

```bash
hypertrade --remote http://127.0.0.1:3334 chat
# /triggers list
# /triggers fires [rtrg_*]
# /triggers enable|disable rtrg_* <reason>
# /triggers run rtrg_* <reason>
# /triggers kill on|off <reason>
```

Production stays inert until `RESEARCH_TRIGGERS_ENABLED=true` is deliberately set.
Every fire still revalidates the active mandate and bounded zero-backtest budget.

Sprint 104 implements governed Memory assertions and a code-free Skill lifecycle.
Assertions require active Evidence V2 and human review; conflicts and expired sources
fail closed during normal Memory search. Skills require static policy, an HMAC-verified
isolated evaluation and separate administrator approval before an immutable release can
enter a matching role prompt. They cannot add tools, execute code or widen paper/live
permissions. Operators review the same state through Web Memory governance, the TUI
Governance tab, or `/assertions` and `/skills` in the CLI. Production acceptance passed;
an empty `SKILL_EVAL_ATTESTATION_SECRET` intentionally blocks eval imports until the
server operator configures the shared isolated-evaluation secret.

Sprint 105 implements portfolio-level strategy lifecycle review. It preserves explicit
unknown data, bounded aligned-return correlation/shared-exposure summaries and immutable
human accept/reject/hold records. Operators use Web `/harness/portfolio`, the Textual
Portfolio tab, REST `/api/portfolio/assessments*`, or CLI `/portfolio-v2` (`/pv2`). Every
recommendation is limited to observation, targeted research or a named human review;
automatic capital, rebalance, pause/start, promotion and order actions are prohibited.
Production acceptance passed on Alembic `0018`; the empty-card smoke remained
`needs_data` with an explicit unknown and performed no lifecycle or trading action.

Sprint 107 moves StrategyCard creation to the immutable ExperimentManifest boundary. Use CLI
`/cards` or the Web/TUI strategy and portfolio surfaces to inspect stable versions, completeness,
missing sources and the fixed research funnel. Card snapshots and review decisions are audit
projections only; they cannot create paper sessions, place orders or allocate capital.
Production acceptance passed on Alembic `0019`: three historical Manifests produced one lineage,
three versions and three immutable snapshots, repeated reconcile was idempotent, and no paper or
execution-side count changed. Gate F is closed; Sprint 108 is the next active slice.

Sprint 108 builds bounded PortfolioObservationWindow and data-quality summaries from approved
BitPro MCP read contracts. HyperTrade stores source refs and statistics only—not complete equity,
return, position, trade, or order series—and missing/stale inputs remain explicit unknowns. The
data plane cannot start paper, place live orders, or change capital.
Operators inspect or capture the same server projection through Web Portfolio, Textual, REST
`/api/portfolio/observation-windows*`, or CLI `/windows list|capture|show|diff`. PortfolioAssessment
now references an immutable window id/content hash instead of independently interpreting monitor
snapshots.
Production acceptance passed on Alembic `0020`: the fixed three-Card denominator produced one
available and two explicit no-window strategies, replay was idempotent, and persisted summaries
contained no raw-series keys. Sprint 109 is the next active slice.

Sprint 109 groups committed paper evidence only when market, symbols, timeframes, cost model,
horizon and bucket are identical. Champion/Challenger/Watch outputs are expiring review proposals,
not return rankings or execution instructions. Production acceptance retained all three Cards but
correctly returned `needs_data`, 0 comparable members and 0 proposals because no complete comparable
paper cohort exists; rebuild was idempotent and paper/live counts did not change. Gate G is closed,
providing the governed input boundary used by Sprint 110.

Sprint 110 turns accepted, unexpired cohort labels into immutable hypothetical portfolio scenarios.
Only equal-weight, evidence-complete inverse-volatility and capped risk-budget proxy templates exist;
weights are Decimal, capped and sum to one, while costs, stress tests and order impacts remain
explicitly hypothetical. Human review records research intent only and cannot allocate capital or
create orders. Production acceptance retained the three-Card denominator and correctly returned
`needs_data`, 0 eligible members and 0 scenarios; idempotency, payload isolation and unchanged
paper/live counts closed Gate H and the Sprint 106–110 roadmap.

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

### Current implementation state

| Initiative | Status |
|-----------|--------|
| World Model — portfolio state and defensive actions | In Progress |
| Global Market — cross-asset regime classification | Production |
| Vide Coding (opus-4.6) provider | Production |
| Enhanced output formatting | Complete |
| Agent Session and Task OS | Legacy-compatible; canonical Thread/Turn replacement proposed |
| Research Evidence V2 contract | Production |
| Multi-Agent research graph V1 | Contracts/tests delivered; not in default Mission loop |
| Reproducible experiment ledger | Production |
| Robustness validation suite | Production |
| Agent Research Evaluation Foundation | Production |
| Agent Research Quality Closure | Production (Sprint 106) |
| StrategyCard V2 and Research Funnel | Production (Sprint 107) |
| Portfolio Evidence Data Plane | Production (Sprint 108) |
| Champion–Challenger Paper Incubation | Production (Sprint 109) |
| Shadow Portfolio Governance | Production (Sprint 110) |
| Professional Agent Runtime V2 | Read-only Mission paths deployed; real audit found remaining legacy writes/protocol gaps |

### Planned (V3+)

- [Next-Generation Agent Runtime audit and target design](docs/architecture/34-next-generation-agent-runtime-audit-and-target-design.md)
- [Sprint 121 canonical Thread/Turn vertical cutover](docs/contracts/sprint-121-canonical-thread-turn-protocol.md)
- [Research Operations and Shadow Portfolio roadmap](docs/architecture/29-research-operations-shadow-portfolio-roadmap.md)
- [Professional Agent Runtime V2 roadmap](docs/architecture/30-professional-agent-runtime-v2-roadmap.md)
- [Professional Agent Runtime V2 technical design](docs/architecture/31-professional-agent-runtime-v2-technical-design.md)
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
