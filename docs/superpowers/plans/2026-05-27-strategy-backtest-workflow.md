# Strategy Backtest Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an auditable strategy research and Backtrader backtest workflow.

**Architecture:** Add a focused `hypertrade.strategy` package for research and SDK DTOs, plus `hypertrade.backtest` for Backtrader execution and persistence. FastAPI exposes research/backtest endpoints and `/harness` displays latest results.

**Tech Stack:** Python 3.12, Backtrader, FastAPI, SQLAlchemy 2, Alembic, React/Vite/TypeScript/Tailwind, pytest, Vitest.

---

## Tasks

- [x] Add strategy/backtest DB models and Alembic migration.
- [x] Add Strategy SDK DTOs and built-in `momentum_breakout_v1`.
- [x] Add Backtrader engine tests and implementation.
- [x] Add research/backtest services and API endpoints.
- [x] Extend `/api/harness/overview`.
- [x] Add `/harness` Strategy Lab panel.
- [ ] Run `./scripts/check.sh`, deploy, and verify server smoke.

## Scope Notes

- Sprint 03 uses deterministic sample candles when no candle payload is supplied.
- Runtime strategy files are still not written to git source.
- Results are research artifacts only and remain labeled as non-investment advice.
