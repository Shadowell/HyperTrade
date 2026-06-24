# HyperTrade

[中文简版](README.zh-CN.md) | [English summary](README.en.md)

HyperTrade is an agent-first crypto trading research and execution framework.
It gives an operator, engineer, or external Agent one governed runtime for
market research, tool calling, evidence-backed strategy iteration, paper/Testnet
execution, BitPro diagnostics, trace, Memory, RAG, and deployment operations.

HyperTrade is independent from BitPro. BitPro can provide market/reference
data, strategy storage, backtest execution, paper/simulation state, and live
diagnostics through stable MCP/API contracts. HyperTrade consumes those
contracts as auditable tools; it does not copy BitPro business logic, query
BitPro databases directly, or bypass BitPro risk boundaries.

> Research output only. Nothing in this repository is investment advice.
> Mainnet live order execution is blocked in V1.

## Contents

- [What HyperTrade Is](#what-hypertrade-is)
- [Architecture](#architecture)
- [Component Guide](#component-guide)
- [How a Prompt Runs](#how-a-prompt-runs)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Using The Framework](#using-the-framework)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [Testing And Evals](#testing-and-evals)
- [Troubleshooting](#troubleshooting)
- [Repository Layout](#repository-layout)
- [Development Workflow](#development-workflow)

## What HyperTrade Is

HyperTrade is the Agent control plane for crypto trading research workflows.
It is designed to be used in three ways:

| User | What they do | Primary surfaces |
| --- | --- | --- |
| Operator | Ask market/live/paper questions, inspect reports, review trace, approve guarded Testnet actions. | CLI `hypertrade`/`ht`, `/harness`, REST API |
| Engineer | Add tools, providers, connectors, evals, runbooks, and deployment checks. | `backend/src/hypertrade`, `docs/contracts`, `scripts/check.sh` |
| External Agent | Call a stable API/tool surface without direct access to secrets or BitPro internals. | REST/SSE API, ToolRegistry metadata, connector capability APIs |

The framework owns:

- provider selection and `AgentPlanner` tool choice
- ToolRegistry schema, policy, approval, idempotency, and trace
- market intelligence over OKX SWAP data
- RAG over `docs/knowledge`
- audited Memory and strategy evidence cards
- local strategy research/backtest workflows
- BitPro MCP/API adapters with explicit preflight and source-of-truth rules
- paper monitoring, alerts, and read-only live diagnostics
- OKX Testnet execution after approval and risk checks
- deterministic evals that catch routing, source, and report regressions

The framework does not own:

- BitPro database schema or internal trading logic
- unattended real-money trading
- hidden model-only investment advice
- production secrets
- mainnet live order execution in V1

## Architecture

![HyperTrade architecture](docs/assets/hypertrade-architecture.svg)

HyperTrade is layered like a production Agent system:

| Layer | Responsibility | Main files |
| --- | --- | --- |
| Client access | CLI, `/harness`, REST/SSE API, future external Agents. | `backend/src/hypertrade/cli.py`, `backend/src/hypertrade/main.py`, `frontend/` |
| Data inputs | OKX market data, BitPro MCP/API, knowledge docs, audited Memory. | `backend/src/hypertrade/market/`, `backend/src/hypertrade/bitpro/`, `docs/knowledge/` |
| Governance gateway | Provider runtime, ToolRegistry, risk policy, trace, connector metadata. | `backend/src/hypertrade/providers/`, `backend/src/hypertrade/tools/`, `backend/src/hypertrade/risk/` |
| Agent engine | Planner, graph runtime, tool execution, report rendering, eval guardrails. | `backend/src/hypertrade/agent/`, `backend/src/hypertrade/evals/` |
| Execution/output | Reports, strategy flow, paper/Testnet lifecycle, alerts. | `backend/src/hypertrade/strategy/`, `backend/src/hypertrade/backtest/`, `backend/src/hypertrade/monitoring.py` |
| Infrastructure | FastAPI, PostgreSQL/pgvector, worker loops, Docker Compose, Nginx, GitHub Actions. | `deploy/`, `.github/workflows/deploy.yml`, `backend/src/hypertrade/worker.py` |

Detailed architecture notes:

- [System architecture diagram](docs/architecture/19-hypertrade-architecture-diagram.md)
- [Agent graph runtime](docs/architecture/12-agent-graph-langgraph-runtime.md)
- [Tool calling and governance](docs/architecture/04-tool-calling.md)
- [BitPro adapter boundary](docs/architecture/17-bitpro-tool-adapter.md)
- [Deployment topology](docs/architecture/10-deployment.md)

## Component Guide

This section is the practical map of the framework. Each component has a
runtime purpose, entry points, source path, and deeper docs.

| Component | What it does | How to use it | Source / docs |
| --- | --- | --- | --- |
| Agent runtime | Turns a free-form prompt into a graph run: classify metadata, plan, approve, execute tools, reflect, render final Markdown/JSON. | `POST /api/agent/runs`, `POST /api/agent/runs/stream`, `uv run hypertrade ask "..."` | `backend/src/hypertrade/agent/`, [Agent graph](docs/architecture/12-agent-graph-langgraph-runtime.md) |
| Provider runtime | Selects the configured chat provider for `AgentPlanner`. Supports DeepSeek by default plus OpenAI-compatible, Codex, OpenRouter, Qwen extension paths. | CLI `/model`, API `/api/harness/provider-selection`, env `ACTIVE_CHAT_PROVIDER` | `backend/src/hypertrade/providers/`, [Provider router](docs/architecture/13-provider-router.md) |
| ToolRegistry | Single catalog for Agent-callable tools, schemas, scopes, approvals, idempotency, source-of-truth metadata, and safe sample limits. | CLI `/tools`, API `/api/harness/tools`, planner tool calls | `backend/src/hypertrade/tools/registry.py`, [Tool calling](docs/architecture/04-tool-calling.md) |
| Risk governance | Evaluates tool policy before execution; denies write-like tools without approval/idempotency and records policy decisions in trace. | Live/Testnet order intent flow, report governance blocks | `backend/src/hypertrade/risk/`, [Risk engine](docs/architecture/14-risk-engine.md) |
| Market intelligence | Reads OKX SWAP tickers, candles, market breadth/heat, relative strength, funding, open interest, and curated market context. | Prompts like `看下目前市场的热度怎么样`, `/price ETH`, `/candles ETH`, `/compare ETH SOL` | `backend/src/hypertrade/market/`, `backend/src/hypertrade/agent/kernel.py` |
| RAG | Scans `docs/knowledge`, stores citation-ready chunks, returns source paths and bounded snippets. | CLI `/rag risk`, API `/api/rag/search?query=risk` | `backend/src/hypertrade/rag/`, [RAG architecture](docs/architecture/05-rag-pgvector.md) |
| Memory | Stores audited observations, strategy knowledge, tags, confidence, importance, usage count, and disabled state. | CLI `/memory search risk`, API `/api/memory?query=risk` | `backend/src/hypertrade/memory/`, [Memory architecture](docs/architecture/06-memory.md) |
| Strategy research | Creates research records, Backtrader backtests, multi-variant experiments, strategy evidence cards, and next-experiment plans. | `/research`, `/backtest`, `/experiment`, `/strategy library` | `backend/src/hypertrade/strategy/`, `backend/src/hypertrade/backtest/`, [Strategy workflow](docs/architecture/16-strategy-agent-workflow.md) |
| BitPro adapter | Calls BitPro only through stable MCP/API tools. Every flow preflights `bitpro_capabilities` then `bitpro_health`. | Prompts for BitPro backtests, paper state, live order history, live strategy performance | `backend/src/hypertrade/bitpro/mcp.py`, [BitPro adapter](docs/architecture/17-bitpro-tool-adapter.md) |
| Paper runtime | Simulates paper sessions, positions, fills, close/reset/pause actions, and status snapshots. | CLI `/paper`, API `/api/paper/status`, `/api/paper/control` | `backend/src/hypertrade/paper/` |
| Monitoring and alerts | Runs read-only monitors for connector health, strategy-library freshness, and BitPro paper state. Persists monitor runs and alert events. | CLI `/monitors`, `/monitor run mon_bitpro_paper_all`, `/alerts` | `backend/src/hypertrade/monitoring.py`, [Monitoring runbook](docs/runbooks/monitoring-alerts.md) |
| Live/Testnet intents | Creates auditable live order intents, requires approval, then executes only through OKX Testnet after risk checks. | `/live intent`, `/live approve`, `/live execute` | `backend/src/hypertrade/live/`, [OKX Testnet execution](docs/architecture/15-okx-testnet-execution.md) |
| Connectors | Exposes redacted capability/auth/tool metadata for trusted external surfaces such as BitPro. | CLI `/connectors`, API `/api/connectors/capabilities` | `backend/src/hypertrade/connectors/`, [Connector framework](docs/architecture/20-connector-framework.md) |
| Evals | Deterministic guardrails for tool choice, RAG citations, Memory behavior, risk refusal, BitPro source-of-truth use, compact reports, and live routing. | CLI `/evals`, API `/api/evals/status` | `backend/src/hypertrade/evals/`, [Eval suite](docs/testing/agent-eval-suite.md) |
| Frontend workbench | Core operator console for runs, reports, trace, Memory/RAG search, market snapshot, and telemetry. | `http://localhost:3333/harness` or production `:3333/harness` | `frontend/`, [Frontend harness](docs/architecture/09-frontend-harness.md) |
| Worker | Runs market ingestion, RAG scans, paper loop, and scheduled monitors when enabled. | Docker Compose `worker` service or direct module execution | `backend/src/hypertrade/worker.py` |

## How a Prompt Runs

Free-form natural-language prompts use the configured chat provider and
`AgentPlanner` as the semantic source of truth for tool choice.

```text
User / external Agent
  -> API or CLI
  -> AgentKernel graph run
  -> ProviderRuntime selects chat provider
  -> AgentPlanner chooses tool calls
  -> ToolRegistry validates schema and policy
  -> RiskGovernancePolicy checks approval/idempotency/scope
  -> tool executor calls market/RAG/Memory/BitPro/strategy/live service
  -> trace event and graph event are persisted
  -> report renderer produces Markdown plus structured JSON
  -> Memory/evals/monitoring can consume the evidence
```

If no chat provider is configured, HyperTrade returns an auditable
`provider_unavailable` result and does not guess a market, BitPro, RAG, or
Memory route from keywords. Deterministic slash commands such as `/price`,
`/candles`, `/compare`, `/rag`, `/memory`, and `/evals` remain available as
explicit commands.

## Installation

### Prerequisites

- Python 3.12+
- `uv`
- Node.js and `pnpm` through `npm exec --yes pnpm@10`
- Docker and Docker Compose for production-style deployment
- A chat provider key for free-form Agent prompts, for example `DEEPSEEK_API_KEY`
- Optional OKX Testnet credentials for signed Testnet execution
- Optional BitPro MCP base URL and token for BitPro-backed tools

### Clone

```bash
git clone git@github.com:Shadowell/HyperTrade.git
cd HyperTrade
```

### Configure

```bash
cp .env.example .env
```

For the fastest local start, use SQLite so you do not need PostgreSQL:

```bash
mkdir -p .local
export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"
export KNOWLEDGE_DIR="docs/knowledge"
export DEEPSEEK_API_KEY="your-provider-key"
```

If `DEEPSEEK_API_KEY` is empty, API/CLI still start, but free-form Agent prompts
return `provider_unavailable` instead of guessing a tool route.

## Quick Start

Run the backend:

```bash
DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db" \
KNOWLEDGE_DIR="docs/knowledge" \
DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

Run the frontend in another terminal:

```bash
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
```

Open:

- Frontend workbench: `http://localhost:3333/harness`
- Backend health: `http://localhost:3334/api/health`
- API docs: `http://localhost:3334/docs`

Run one CLI prompt:

```bash
DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db" \
DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
uv run hypertrade --local ask "看下目前市场的热度怎么样"
```

Start the interactive CLI:

```bash
DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db" \
DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
uv run ht --local
```

Useful first commands:

```text
/help
/status
/tools
/evals
/price ETH
/candles ETH
/compare ETH SOL
/rag 风控
/memory search 风控
```

## Using The Framework

### 1. Market Research

Ask broad market questions through the Agent:

```bash
uv run hypertrade --local ask "看下目前市场的热度怎么样"
```

Expected behavior:

- planner chooses `market_summary`
- report includes breadth, advancers/decliners, average UTC0 change, strongest
  and weakest symbols, and top movers
- trace stores the business tool calls and graph nodes

Use deterministic market commands when you want an explicit shortcut:

```text
/price ETH
/candles ETH 1H 120
/compare ETH SOL BTC
```

### 2. RAG And Memory

Scan/search knowledge docs:

```text
/rag risk
/memory search market
```

API equivalents:

```bash
curl -sS "http://127.0.0.1:3334/api/rag/search?query=risk&limit=3"
curl -sS "http://127.0.0.1:3334/api/memory?query=market"
```

RAG is for source-grounded documentation context. Memory is for audited runtime
observations and strategy evidence. Reports should keep source ids, missing
fields, and data gaps visible instead of smoothing over them.

### 3. Strategy Research And Backtests

Create research and backtest records from the CLI:

```text
/research 研究ETH趋势突破
/backtest
/experiment 研究ETH趋势突破
/strategy library momentum_breakout_v1
```

The strategy loop is evidence-first:

1. create a research record
2. run a bounded Backtrader backtest
3. compare variants and gate the winner
4. write a `strategy_knowledge` Memory card
5. retrieve prior evidence through `/strategy library`
6. propose the next adjacent experiment

Related docs:

- [Strategy workflow](docs/architecture/16-strategy-agent-workflow.md)
- [Strategy research playbook](docs/knowledge/strategy-research-playbook.md)

### 4. BitPro MCP/API Evidence

BitPro-backed reads and lifecycle tools always keep the source boundary visible.
Every BitPro flow starts with:

```text
bitpro_capabilities -> bitpro_health -> smallest required BitPro tool
```

Examples:

```bash
uv run hypertrade --local ask "查看 BitPro 回测收益大于100%的策略有哪些"
uv run hypertrade --local ask "查看 BitPro 回测 result 196 的权益曲线和交易证据"
uv run hypertrade --local ask "监控 BitPro 所有运行中的模拟盘策略，列出异常和数据缺口"
uv run hypertrade --local ask "我的实盘最近的一笔订单是什么"
uv run hypertrade --local ask "看下实盘收益最高的策略"
```

Important BitPro rules:

- HyperTrade never reads BitPro databases directly.
- HyperTrade never copies BitPro trading logic.
- Backtest ranking uses BitPro `total_return_pct`, not inferred or annualized
  substitutions.
- Live order history and live strategy performance are read-only diagnostics.
- Live write tools are blocked in V1.

### 5. Paper Monitoring And Alerts

Inspect monitor definitions:

```text
/monitors
/monitor run mon_bitpro_paper_all
/alerts
```

API:

```bash
curl -sS http://127.0.0.1:3334/api/monitors
curl -sS -X POST http://127.0.0.1:3334/api/monitors/mon_bitpro_paper_all/run
curl -sS http://127.0.0.1:3334/api/alerts
```

Monitors are read-only. Missing paper metrics become data gaps; HyperTrade must
not infer PnL, drawdown, or running strategy state when BitPro does not provide
those fields.

### 6. Testnet Order Intents

Testnet execution is guarded:

```text
/live intent ETH buy 0.01 reason="api smoke"
/live intents
/live approve loi_...
/live execute loi_...
```

Execution requires:

- an order intent
- approval
- RiskEngine pass
- OKX Testnet credentials
- idempotent/audited trace

Mainnet execution remains blocked in V1.

### 7. REST And Streaming API

Health:

```bash
curl -sS http://127.0.0.1:3334/api/health
```

Create an Agent run:

```bash
curl -sS \
  -H "Content-Type: application/json" \
  -d '{"prompt":"看下目前市场的热度怎么样"}' \
  http://127.0.0.1:3334/api/agent/runs
```

Stream run events:

```bash
curl -N \
  -H "Content-Type: application/json" \
  -d '{"prompt":"请做行情归纳"}' \
  http://127.0.0.1:3334/api/agent/runs/stream
```

Inspect recent runs and trace:

```bash
curl -sS http://127.0.0.1:3334/api/agent/runs
curl -sS http://127.0.0.1:3334/api/agent/runs/run_...
```

Useful API groups:

| Area | Endpoints |
| --- | --- |
| Harness | `/api/harness/overview`, `/api/harness/tools`, `/api/harness/providers` |
| Agent | `/api/agent/runs`, `/api/agent/runs/stream`, `/api/agent/runs/{run_id}` |
| Market | `/api/market/tickers/latest`, `/api/market/ticker/{symbol}`, `/api/market/candles/{symbol}`, `/api/market/compare` |
| RAG/Memory | `/api/rag/search`, `/api/memory` |
| Strategy/backtest | `/api/strategy/research`, `/api/strategy/experiments`, `/api/strategy/library`, `/api/backtests` |
| BitPro | `/api/bitpro/health`, `/api/bitpro/market/klines/{symbol}`, `/api/bitpro/paper/dashboard`, `/api/bitpro/live/positions` |
| Monitoring | `/api/monitors`, `/api/monitors/{monitor_id}/run`, `/api/alerts` |
| Evals | `/api/evals/status` |

### 8. Remote CLI

Save a remote API login once:

```bash
uv run ht /login
uv run ht ask "请做行情归纳"
```

`/login` writes `~/.hypertrade/client.env` with local-only permissions. Later
`uv run ht` defaults to the saved remote API unless `--local` is passed.

On the production host, `/usr/local/bin/hypertrade` and `/usr/local/bin/ht`
start a short-lived remote client container. Deployments can replace the API
container without killing the operator's terminal session.

## Configuration

Configuration is loaded from `.env` through `Settings` in
`backend/src/hypertrade/config.py`.

| Area | Key variables |
| --- | --- |
| App/API | `APP_ENV`, `API_HOST`, `API_PORT`, `FRONTEND_ORIGIN`, `SESSION_SECRET`, `COOKIE_SECURE` |
| Database | `DATABASE_URL` |
| Chat providers | `ACTIVE_CHAT_PROVIDER`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `CODEX_AUTH_JSON`, `OPENROUTER_API_KEY` |
| Codex models | `CODEX_MODEL`, `CODEX_MODEL_OPTIONS`, `CODEX_TIMEOUT_SECONDS` |
| Embeddings/RAG | `QWEN_API_KEY`, `QWEN_EMBEDDING_MODEL`, `KNOWLEDGE_DIR`, `RAG_SCAN_INTERVAL_SECONDS` |
| OKX | `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_PASSPHRASE`, `OKX_TESTNET`, `OKX_REST_URL`, `OKX_PUBLIC_WS_URL` |
| Paper/Risk | `PAPER_ENABLED`, `PAPER_STARTING_EQUITY_USDT`, `RISK_MAX_ORDER_NOTIONAL_USDT`, `RISK_MAX_OPEN_INTENTS` |
| BitPro | `BITPRO_MCP_API_BASE`, `BITPRO_MCP_API_TOKEN`, `BITPRO_MCP_AUTH_HEADER`, `BITPRO_MCP_TIMEOUT_SECONDS` |
| Monitoring | `MONITOR_SCHEDULER_ENABLED`, `MONITOR_LOOP_INTERVAL_SECONDS` |

Secrets must stay in local `.env` files or `/opt/hypertrade/.env` on the
server. Do not commit provider keys, OKX credentials, BitPro tokens, database
files, or production `.env` files.

## Deployment

Production deployment uses one server:

- host Nginx listens on public port `3333`
- API container binds to `127.0.0.1:3334`
- PostgreSQL/pgvector runs in Docker Compose
- GitHub Actions deploys `main` through the self-hosted runner label
  `hypertrade-production`
- deployment records `/opt/hypertrade/deploy/last_deployed_sha`
- server-local CLI wrapper `hypertrade`/`ht` talks to `http://api:3334` inside
  the Compose network

Server bootstrap:

```bash
sudo ./deploy/setup-server.sh
sudo install -m 600 .env.example /opt/hypertrade/.env
sudo editor /opt/hypertrade/.env
```

Normal deployment path:

```bash
git push origin main
gh run watch <deploy-run-id> --exit-status
curl -fsS http://47.79.36.92:3333/api/health
```

Manual server deployment, when explicitly needed:

```bash
cd /opt/hypertrade
./deploy/deploy.sh
curl -fsS http://127.0.0.1:3334/api/health
curl -fsS http://127.0.0.1:3333/api/health
```

Post-deploy smoke:

```bash
hypertrade ask "看下ETH行情"
printf "/status\n/model\n/evals\n:q\n" | hypertrade --remote http://127.0.0.1:3334
```

See [deployment architecture](docs/architecture/10-deployment.md) and
[deployment smoke runbook](docs/runbooks/deployment-smoke.md).

## Testing And Evals

Run the full verification entrypoint:

```bash
./scripts/check.sh
```

It runs:

- frontend install
- frontend lint
- frontend tests
- frontend production build
- Python ruff
- Python mypy
- Python pytest

Run focused checks:

```bash
uv run pytest tests/test_agent_eval_suite.py -q
uv run pytest tests/test_agent_market_summary.py tests/test_api.py -q
npm exec --yes pnpm@10 -- -C frontend test
```

Run eval status:

```bash
uv run ht --local /evals
curl -sS http://127.0.0.1:3334/api/evals/status
```

The eval suite guards against:

- wrong tool choice
- missing RAG citations
- Memory behavior regressions
- risk-refusal regressions
- BitPro backtest/page-parity source mistakes
- missing artifact smoothing
- paper-monitor read/write boundary mistakes
- noisy report regressions
- live order and live strategy prompts falling back to generic market reports

## Troubleshooting

| Symptom | Likely cause | What to check |
| --- | --- | --- |
| Free-form prompt returns `provider_unavailable` | No configured chat provider key. | `DEEPSEEK_API_KEY`, `ACTIVE_CHAT_PROVIDER`, CLI `/model`, API `/api/harness/providers` |
| `/harness` loads but Agent runs fail | Backend or provider config issue. | `curl /api/health`, server logs, provider status |
| BitPro tools return unavailable/502 | BitPro MCP base URL/token/health problem. | `BITPRO_MCP_API_BASE`, `BITPRO_MCP_API_TOKEN`, `/api/bitpro/health` |
| Market data is empty | Worker has not ingested data or OKX REST/WS is unavailable. | `/api/market/tickers/latest`, worker logs, `OKX_REST_URL` |
| RAG search has no hits | Knowledge directory not scanned or empty query corpus. | `KNOWLEDGE_DIR`, `/rag <query>`, `docs/knowledge/` |
| Testnet order execution fails | Missing OKX Testnet credentials or risk gate denial. | order intent status, risk payload, `OKX_TESTNET`, OKX keys |
| Deployment succeeds but public UI fails | Nginx/frontend/API mismatch. | `curl :3333/api/health`, `docker compose ps`, Nginx config |

Incident procedures live in [incident response](docs/runbooks/incident-response.md).

## Repository Layout

```text
backend/src/hypertrade/
  agent/          AgentKernel, planner integration, report rendering
  backtest/       Backtrader service and persisted backtest records
  bitpro/         BitPro MCP/API client and adapter
  connectors/     Trusted connector registry and redacted capabilities
  live/           Live order intent service and approval lifecycle
  market/         OKX market repository, parsers, and research helpers
  memory/         Audited Memory service
  paper/          Paper trading runtime and state
  providers/      Chat provider runtime and model selection
  rag/            Knowledge scanning and citation search
  risk/           Risk governance and order checks
  strategy/       Strategy research, experiment, and library services
  tools/          ToolRegistry and policy metadata
frontend/         React/Vite operator workbench
docs/
  architecture/   Module-level architecture notes
  contracts/      Sprint contracts and delivery scopes
  knowledge/      Operator guides and source material for RAG
  runbooks/       Deployment, smoke, backup, monitoring, incident procedures
deploy/           Docker/Nginx/server deployment assets
scripts/check.sh  Single local verification entrypoint
```

## Development Workflow

HyperTrade keeps durable project state in files, not chat history.

1. Read `README.md`, `docs/spec.md`, `docs/progress.md`, the active contract in
   `docs/contracts/`, and relevant architecture docs.
2. Keep changes inside the current sprint contract unless scope is explicitly
   expanded.
3. Update docs when behavior, API, architecture, or operational expectations
   change.
4. Run targeted tests first when useful, then `./scripts/check.sh`.
5. Commit and push to `origin/main` after verification passes so GitHub Actions
   deploys production.
6. Watch deployment and smoke production health before reporting completion.

Current project state:

- Product scope: [docs/spec.md](docs/spec.md)
- Latest progress/deployments: [docs/progress.md](docs/progress.md)
- Documentation index: [docs/README.md](docs/README.md)
- Tool usage guide: [docs/knowledge/tool-usage-guide.md](docs/knowledge/tool-usage-guide.md)
- Active contracts: [docs/contracts/](docs/contracts/)

## License

Private repository. Keep secrets, provider keys, OKX credentials, BitPro tokens,
database files, and production `.env` files out of version control.
