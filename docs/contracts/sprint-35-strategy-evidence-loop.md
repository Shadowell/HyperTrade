# Sprint 35 Contract: Strategy Evidence Loop

## Goal

Upgrade the current single-pass strategy experiment into an auditable evidence loop that compares multiple strategy variants before recommending the next experiment.

## In Scope

- Extend the deterministic `StrategyExperimentService` workflow to run a small candidate matrix.
- Persist each candidate as a normal `BacktestRun` so operators can audit the evidence.
- Store structured `variants`, `winner`, `evidence_gates`, and `next_experiment` fields in `strategy_experiments.report_json`.
- Render the experiment report with a comparison table and explicit winning rationale.
- Keep the workflow research-only and separate from BitPro live mutation tools.
- Update product/spec/progress/architecture docs for the new evidence loop.

## Out Of Scope

- Large parameter optimization sweeps.
- Live or mainnet order generation from backtest results.
- Direct BitPro database access or copied BitPro trading logic.
- UI redesign for strategy comparison.
- Automatic paper promotion from local Backtrader results.

## Done Means

- A single experiment prompt runs at least three candidate variants.
- The experiment selects a winner from real backtest metrics, not model text.
- The winning variant's `backtest_id` is stored on the experiment row.
- The report explains data source, candidate metrics, pass/fail gates, and next experiment.
- Existing API and CLI experiment entrypoints continue to work.

## Verification

```bash
uv run pytest tests/test_strategy_backtest_api.py tests/test_cli.py -q
./scripts/check.sh
```

## Handoff

After this slice, the next strengthening step is to add richer BitPro backtest artifacts: equity curve, trades, orders, fills, and drawdown series.
