# Sprint 30 Contract: Strategy Workflow v2

## Goal

Wrap strategy research and backtesting into a multi-step Agent-style experiment workflow.

## Scope

- Add `strategy_experiments` persistence.
- Add workflow stages: hypothesis, data selection, backtest, critique, revision suggestion, report.
- Add `POST /api/strategy/experiments` and list endpoint.
- Add CLI `/experiment <prompt>`.
- Show latest experiment in `/harness`.

## Acceptance

- One prompt creates research, backtest, critique, and final experiment report.
- Report includes a research disclaimer.
- Backtest id, data source, metrics, and next experiment are auditable.
- API, CLI, and frontend expose the workflow.

## Verification

```bash
uv run pytest tests/test_strategy_backtest_api.py tests/test_cli.py -q
./scripts/check.sh
```

