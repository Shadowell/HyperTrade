# Sprint 07 Contract: CLI Strategy Workflow Shortcuts

## Goal

Add slash commands that trigger strategy research and Backtrader backtest workflows from interactive CLI chat without starting a full Agent run.

## In Scope

- `/research <prompt>` creates a strategy research record and prints the report summary.
- `/backtest` runs a backtest against the latest research record.
- `/backtest <research_id>` runs a backtest for a specific `srch_*` record.
- `/backtest <strategy_key>` runs a backtest when the argument is not a research id.
- Local and remote CLI client implementations.
- Tests and documentation updates.

## Out of Scope

- Agent workflow planning over tools.
- Custom candle upload from CLI.
- Live/Testnet trading commands.

## Done Means

- `uv run hypertrade` chat accepts `/research` and `/backtest` shortcuts.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_cli.py -q
./scripts/check.sh
```

## Handoff

Next sprint should add Agent workflow planning that chains strategy research and backtest tools automatically.
