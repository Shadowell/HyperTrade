# Sprint 06 Contract: CLI Slash Commands

## Goal

Add terminal slash commands so developers can inspect harness state, recent runs, memory, strategy research, and backtests without leaving the interactive CLI loop.

## In Scope

- Slash commands in interactive chat: `/help`, `/status`, `/model`, `/providers`, `/tools`, `/runs`, `/memory`, `/strategy`, `/backtests`.
- Local `LocalAgentClient` implementations backed by database/services.
- Remote `AgentApiClient` implementations backed by existing FastAPI endpoints.
- Tests for slash command rendering and API resource listing.
- CLI architecture and progress documentation updates.

## Out of Scope

- Streaming token output.
- `/model <name>` provider switching.
- Creating strategy research or backtests from slash commands.
- Live/Testnet trading commands.

## Done Means

- `uv run hypertrade` chat accepts slash commands without starting an Agent run.
- Local mode lists tools, runs, memory, strategy research, and backtests from the configured database.
- Remote mode lists the same resources from `/api/harness/*`, `/api/agent/runs`, `/api/memory`, `/api/strategy/research`, and `/api/backtests`.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_cli.py -q
./scripts/check.sh
```

## Handoff

Next sprint should add Agent workflow planning over strategy research/backtest tools and optional slash shortcuts to trigger those workflows.
