# HyperTrade

[中文](README.zh-CN.md) | [English](README.en.md)

HyperTrade is an agent-first crypto trading research and execution harness. Sprint 01 focuses on OKX perpetual swap market ingestion, user-triggered market summaries, tool-call tracing, RAG, audited memory, and a `/harness` frontend workbench.

> Research and learning project only. Nothing in this repository is investment advice.

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

Use the terminal harness against a running API:

```bash
HYPERTRADE_API_URL=http://47.79.36.92:3333 \
HYPERTRADE_USERNAME=admin \
HYPERTRADE_PASSWORD='***' \
uv run hypertrade ask "请做行情归纳"
```

Interactive mode:

```bash
uv run hypertrade chat
```
