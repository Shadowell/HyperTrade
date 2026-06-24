# HyperTrade

[中文](README.zh-CN.md) | [English](README.en.md)

HyperTrade is an agent-first crypto trading research and execution system. It
lets an operator or external Agent ask market questions, call auditable tools,
inspect evidence, iterate on strategy ideas, and move only risk-approved work
toward paper or Testnet execution.

HyperTrade is independent from BitPro. BitPro can provide market/reference
data, strategy storage, backtest execution, paper/simulation state, and live
diagnostics through stable MCP/API contracts; HyperTrade consumes those
contracts as auditable Agent tools and does not copy BitPro business logic.

> Research output only. Nothing in this repository is investment advice.

## Architecture

![HyperTrade architecture](docs/assets/hypertrade-architecture.svg)

The poster follows the same layered operating-system pattern as AI-native
trading-agent maps: clients enter through the Agent/API surface, data and
BitPro capabilities pass through a governed gateway, the HyperTrade engine owns
planning/tool execution/reporting, and safety boundaries remain visible all the
way down to infrastructure. The layer-by-layer notes live in
`docs/architecture/19-hypertrade-architecture-diagram.md`.

## What HyperTrade Owns

- Agent planning, provider routing, tool selection, trace, report rendering,
  Memory, RAG citations, and eval guardrails.
- OKX market research tools for tickers, candles, breadth/heat, relative
  strength, funding, open interest, and deterministic market context.
- Strategy research loops that create evidence, compare variants, preserve
  missing data, and store source-backed `strategy_knowledge` Memory cards.
- Risk governance for tool scope, approval gates, idempotency, live-write
  boundaries, and operator-readable refusal reasons.
- Operator surfaces: CLI, REST/SSE API, `/harness`, runbooks, and deployment
  smoke checks.

## BitPro Boundary

BitPro is treated as the base trading-system platform. HyperTrade reaches it
only through stable MCP/API tools:

- Read paths: capability/health checks, K-line reads, backtest result/artifact
  reads, paper dashboard/events/equity snapshots, and live diagnostics.
- Research/paper mutation paths: strategy generation/create/update, BitPro-owned
  backtest jobs, and paper lifecycle calls when explicitly requested.
- Live write paths: blocked in V1 unless a future contract adds separate scopes,
  idempotency keys, approval, and risk checks.

HyperTrade must not query BitPro databases directly, infer missing BitPro
metrics, or bypass BitPro's own risk boundaries.

## Current V1 Capabilities

- Observable Agent graph runtime with intent, plan, approval, tool, reflect,
  and report nodes.
- Provider Router with DeepSeek default plus OpenAI-compatible, Codex,
  OpenRouter, and Qwen extension paths.
- CLI `/model` picker with numbered provider choices; Codex models come from
  `CODEX_MODEL_OPTIONS` and currently include `gpt-5.4`, `gpt-5.5`, and
  `gpt-5.4-mini` by default.
- Tool calling for market research, RAG, Memory, strategy research, backtests,
  paper monitoring, live diagnostics, live intents, and OKX Testnet execution.
- RAG citations backed by PostgreSQL/pgvector-compatible chunk metadata.
- Memory v2 with dedupe, tags, importance, confidence, usage audit, and a
  strategy-library read model over strategy evidence.
- BitPro MCP adapter for health checks, direct K-line reads, strategy
  generation/create/update, BitPro backtest jobs/results/artifacts, paper
  lifecycle, paper monitoring snapshots, live order history, and live strategy
  performance diagnostics.
- Monitoring and alerts for connector health, strategy-library freshness, and
  BitPro paper state.
- Deterministic eval suite covering tool choice, source-of-truth usage,
  unsupported-claim guardrails, missing-data preservation, and compact report
  rendering.

## Core Workflows

| Workflow | Entry points | Output |
| --- | --- | --- |
| Market research | Free-form Agent prompt, `market_*` tools, `/harness` | Source-backed market report with traceable tool evidence |
| Strategy experiment | `/research`, `/backtest`, `/experiment` | Research record, backtest evidence, critique, next experiment |
| BitPro evidence read | BitPro MCP Agent tools | Page-parity backtest, paper, live-order, or live-strategy evidence |
| Paper and monitoring loop | `/monitors`, `/monitor run`, `/alerts` | Persisted monitor runs, alerts, data gaps, recommended read-only actions |
| Risk-gated execution | `/live intent`, `/live approve`, `/live execute` | Audited OKX Testnet execution after approval and risk checks |

## Quick Start

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

This runs frontend install/lint/test/build, Python ruff, mypy, and pytest.

## CLI

Start the standalone terminal Agent:

```bash
uv run hypertrade
# short alias
uv run ht
```

Run one prompt locally:

```bash
uv run hypertrade ask "请做行情归纳"
```

Use the terminal harness against a running API:

```bash
uv run ht /login
uv run ht ask "请做行情归纳"
```

`/login` saves the remote API URL, username, and password to
`~/.hypertrade/client.env` with local-only file permissions. After that,
`uv run ht` defaults to the saved remote API unless `--local` is passed.

Force local mode even when `HYPERTRADE_API_URL` is set:

```bash
uv run hypertrade --local
```

In interactive chat, slash commands inspect harness state without starting a new Agent run.
`/help` explains every command, and `/tools` shows each Agent tool with its category,
approval gate, and purpose:
Enter `/` to display the command list, or press Tab after `/` or a partial command such
as `/m` to complete available slash commands and common subcommands.
Short incomplete prefixes such as `/st` or `/me` render a filtered candidate list with
descriptions instead of starting an Agent run or dumping the full help page.
In interactive chat, slash command and argument candidate lists are numbered;
enter a number to select the displayed alternative directly.
Run `/model` in interactive chat to choose the active provider from a numbered
list; when Codex is selected, its model is chosen from the configured
`CODEX_MODEL_OPTIONS` list. Scripted switches such as `/model codex` still work.
Free-form Agent prompts show a live `Thought` / `Thinking` status block in interactive
terminals while the planner or tools are still running.
Interactive terminals also render Markdown reports into readable headings, lists, and tables;
set `HYPERTRADE_RENDERER=plain` when raw Markdown is needed for scripts.
Rich terminal output hides run metadata and trace tables by default so routine answers show
only the core report; set `HYPERTRADE_TRACE=summary` for a compact trace or
`HYPERTRADE_TRACE=full` when a full audit trace is needed.
Streaming progress is compact by default (`Agent: running/completed`). Set
`HYPERTRADE_PROGRESS=full` to see every tool start/completion line. BitPro paper
monitor/equity/event reports prefer concise conclusions and core metrics; set
`HYPERTRADE_REPORT_SOURCE=tools` only when raw tool evidence tables are needed.
With a chat provider configured, broad prompts such as `看下目前市场的热度怎么样`
let the planner choose `market_summary` and return a market heat summary with
advancer/decliner breadth, average change, strongest/weakest symbols, and the
top movers; set `HYPERTRADE_REPORT_SOURCE=tools` to inspect raw ticker/candle
tables instead. Without a chat provider, free-form prompts return a
provider-unavailable report and do not guess a tool route from keywords.

```text
/help
/status
/tools
/runs
/memory
/strategy
/strategy library momentum_breakout_v1
/research 研究BTC趋势突破
/backtest
/backtest latest
/rag risk
/memory search risk
/model deepseek
/model codex
/experiment 研究ETH趋势突破
/monitors
/monitor run mon_bitpro_paper_all
/alerts
/live execute loi_...
/evals
```

## Safety Boundaries

- Mainnet live order execution is blocked in V1.
- Live diagnostics are read-only unless a future sprint explicitly adds a
  write-gated tool path.
- Testnet execution requires an approved live order intent and RiskEngine pass.
- Server-only secrets stay in environment/configuration and must never be
  committed.
- Reports should preserve source paths, timestamps, missing fields, and
  research-only framing instead of turning evidence into investment advice.

## Documentation Map

- `docs/README.md`: documentation index and current capability map.
- `docs/spec.md`: product scope, acceptance criteria, and boundaries.
- `docs/progress.md`: latest implementation/deployment state.
- `docs/architecture/19-hypertrade-architecture-diagram.md`: layered HyperTrade architecture diagram.
- `docs/architecture/`: module-level architecture notes.
- `docs/knowledge/tool-usage-guide.md`: operator guide for Agent tools and validation.
- `docs/runbooks/`: deployment, BitPro MCP, monitoring, smoke, backup, and incident procedures.

## Repository Layout

- `backend/`: FastAPI, Agent runtime, providers, ToolRegistry, RAG, Memory,
  market ingestion, BitPro MCP adapter, risk, monitors, and APIs.
- `frontend/`: React/Vite `/harness` operator workbench.
- `docs/architecture/`: module-level architecture notes and the layered system
  map.
- `docs/contracts/`: focused sprint contracts that define implementation scope.
- `docs/knowledge/`: operator guides and reusable validation procedures.
- `docs/runbooks/`: deployment, smoke, backup, monitoring, and BitPro MCP
  operations.
- `deploy/`: production Nginx and host deployment assets.
