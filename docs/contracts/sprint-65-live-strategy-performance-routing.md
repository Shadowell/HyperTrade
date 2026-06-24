# Sprint 65 - Live Strategy Performance Routing

## Goal

Route live strategy performance questions such as `看下实盘收益最高的策略`
to BitPro read-only live strategy evidence instead of the generic OKX market
summary fallback.

## In Scope

- Add a read-only Agent tool, `bitpro_live_strategy_performance`, backed by
  BitPro `/live/strategies`.
- Rank returned live strategies by BitPro's `return_pct` page metric and show
  `total_pnl` beside it.
- Add deterministic routing for live/real-account strategy performance prompts.
- Render a compact `BitPro 实盘策略收益` report section.
- Register the tool as `live_diagnostic_read` with no idempotency requirement.
- Update tool-calling, BitPro adapter, runbook, and operator guide docs.

## Out of Scope

- Live order placement, cancellation, transfer, or promotion.
- Direct BitPro database reads.
- Inferring missing strategy PnL/return metrics when BitPro does not return them.
- Changing the existing Sprint 64 Codex model picker work.

## Done Means

- `看下实盘收益最高的策略` does not call `market_summary`.
- Trace includes `bitpro.live_strategy_performance`.
- The report includes the highest strategy id/name, `return_pct`, `total_pnl`,
  account, status, and symbols when BitPro provides them.
- BitPro calls still preflight through `bitpro_capabilities` and `bitpro_health`.

## Verification

```bash
uv run pytest tests/test_agent_market_summary.py::test_agent_routes_live_strategy_performance_prompt_away_from_market_fallback tests/test_agent_planner.py::test_bitpro_live_strategy_performance_schema_targets_highest_return_queries tests/test_bitpro_mcp_adapter.py::test_bitpro_adapter_reads_live_strategy_performance_after_preflight tests/test_market_candles_tool.py::test_planner_report_renders_bitpro_live_strategy_performance_top_strategy tests/test_tool_registry.py -q
./scripts/check.sh
```

## Risks / Notes

- BitPro `/live/strategies` exposes page-level runtime metrics from
  `strategy_engine.get_strategy_status`. If `return_pct` or `total_pnl` is
  missing, HyperTrade must report that absence rather than inventing a value.
