# Sprint 80 - Paper Strategy Performance Matrix

## Goal

Provide one read-only, provenance-aware Agent tool for comparing currently
running BitPro paper strategies without mistaking the current dashboard view,
duplicate responses, or historical backtests for per-strategy performance.

## In Scope

- Add a bounded `bitpro_paper_strategy_performance` tool that inventories
  running strategies and requests strategy-scoped dashboard evidence.
- Reject dashboard evidence whose returned strategy id does not match the
  requested strategy id.
- Normalize comparable return, PnL, drawdown, equity, and strategy identity
  fields; rank only rows with a reported paper return metric.
- Return explicit coverage, rejected-evidence, and missing-data summaries.
- Route simulated-strategy ranking questions to this tool and render a concise
  professional comparison in Agent/CLI output.
- Add adapter, planner, registry, report, and acceptance regressions.

## Out of Scope

- Copying or changing BitPro business logic or database access.
- Treating backtest results as current paper performance.
- Starting, stopping, pausing, or modifying paper or live strategies.
- Building the interactive web comparison workbench; it remains the next UI
  slice after the evidence contract is stable.

## Done Means

- A single Agent tool call can return the running inventory, validated
  per-strategy performance rows, deterministic return ranking, and coverage.
- A dashboard response for the wrong strategy is rejected and cannot enter the
  ranking.
- Full-ranking claims require complete comparable coverage; partial evidence is
  labeled partial and names the missing strategy ids.
- The default answer contains conclusion, comparison, risk/data gaps, and next
  step without raw tool dumps.

## Verification

```bash
uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_agent_planner.py \
  tests/test_tool_registry.py tests/test_market_candles_tool.py \
  tests/test_agent_acceptance.py tests/test_cli.py -q
./scripts/check.sh
```

Production smoke:

```bash
hypertrade ask "我的哪个模拟盘策略收益比较好，分析下"
```

Confirm that only strategy-id-matched paper evidence is ranked and incomplete
coverage is stated explicitly.

## Completion Evidence

- Focused adapter, planner, registry, report, acceptance, and CLI regression
  suite passed (`161 passed`).
- `./scripts/check.sh` passed: frontend lint/test/build, Ruff, Mypy, and Python
  tests (`312 passed`).
- Production deployment and smoke evidence are pending the pushed commit.
