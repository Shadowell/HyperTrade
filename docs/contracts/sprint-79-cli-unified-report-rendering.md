# Sprint 79 - CLI Unified Report Rendering

## Goal

Make every completed Agent run use a concise, user-facing answer as the default
CLI output. Tool, monitor, risk, and evidence blocks remain auditable, but are
visible by default only when no usable final answer exists or when the operator
explicitly asks for tool/audit output.

## In Scope

- Trace the BitPro paper-monitor render path that appends raw monitor blocks
  after a completed Agent answer.
- Apply one default-output precedence rule to normal, structured, and Rich CLI
  renderers: final answer first; internal report blocks only as fallback.
- Preserve `HYPERTRADE_REPORT_SOURCE=tools|audit` for operators who require
  raw structured evidence.
- Add regression tests for a simulated paper-strategy comparison answer and
  its accompanying monitor, alert, missing-data, next-action, and risk blocks.

## Out of Scope

- Changing BitPro paper strategy metrics, source payloads, or read-only
  permissions.
- Building a full-screen terminal UI or hiding evidence from Trace/audit modes.

## Done Means

- `hypertrade ask "我的哪个模拟盘策略收益比较好，分析下"` presents the Agent's
  formatted comparison as the default completed output without raw monitor
  block dumps.
- Structured/audit output remains available when explicitly requested.
- Plain and Rich renderers have matching output-precedence behavior.

## Verification

```bash
uv run pytest tests/test_cli.py tests/test_market_candles_tool.py \
  tests/test_agent_planner.py tests/test_agent_acceptance.py \
  tests/test_report_blocks.py -q
./scripts/check.sh
```

Production smoke:

```bash
hypertrade ask "我的哪个模拟盘策略收益比较好，分析下"
```

Confirm the conclusion, ranking, caveats, and next step are formatted as one
report, and raw BitPro monitor blocks are absent from default output.

## Handoff

- A future terminal-TUI sprint can add interactive drill-down panes for the
  same structured evidence without changing the concise default.

## Completion Evidence

- Focused renderer, planner, paper-report, acceptance, and report-block tests
  passed (`141 passed`).
- `./scripts/check.sh` passed with frontend lint/test/build, Ruff, Mypy, and
  Python tests.
- Initial production smoke `run_ef3acad3a6a447d6af75` confirmed the Planner can
  request multiple paper curves and backtest results for a comparison; the
  follow-up renderer compacts that compound evidence into one paper comparison
  summary and suppresses unrelated historical-backtest rows. Deployment and
  final production smoke are pending.
