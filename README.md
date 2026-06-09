# HyperTrade

[中文](README.zh-CN.md) | [English](README.en.md)

HyperTrade is a production-oriented agent-first crypto trading research and execution harness. Current V1 covers observable Agent graph runs, provider routing, tool calling, RAG citations, audited Memory, OKX market research, paper trading, strategy experiments, risk-gated live intents, OKX Testnet signed execution, and a BitPro MCP adapter for external data access plus non-live strategy lifecycle workflows.

> Research output only. Nothing in this repository is investment advice.

## Quick Start

```bash
cp .env.example .env
uv run pytest -q
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

## Verification

```bash
./scripts/check.sh
```

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
HYPERTRADE_USERNAME=admin \
HYPERTRADE_PASSWORD='***' \
uv run hypertrade --remote http://47.79.36.92:3333 ask "请做行情归纳"
```

Force local mode even when `HYPERTRADE_API_URL` is set:

```bash
uv run hypertrade --local
```

In interactive chat, slash commands inspect harness state without starting a new Agent run:

```text
/help
/status
/tools
/runs
/memory
/strategy
/research 研究BTC趋势突破
/backtest
/backtest latest
/rag risk
/memory search risk
/model deepseek
/experiment 研究ETH趋势突破
/live execute loi_...
/evals
```

## Operations Guide

For an operational map of Agent graph, tool calls, provider routing, RAG, Memory,
risk, Testnet execution, CLI, frontend, tests, and deployment smoke, read
`docs/knowledge/tool-usage-guide.md`.
