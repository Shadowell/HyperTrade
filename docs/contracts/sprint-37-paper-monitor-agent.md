# Sprint 37 Contract: BitPro Paper Monitor Agent

## Goal

Turn the current BitPro paper dashboard read into a deterministic monitoring summary that highlights running strategy coverage, current performance, data gaps, anomalies, and suggested read-only operator actions.

## In Scope

- Extend unfiltered `bitpro_paper_dashboard` results with `monitor_summary`.
- Derive current dashboard equity, total PnL, Sharpe, max drawdown, and running strategy inventory counts from BitPro API data only.
- Add deterministic alert levels for negative PnL, high drawdown, no running strategies, truncated inventory, and missing per-strategy metrics.
- Render a concise `监控结论` block in the Agent report.
- Update spec/progress/architecture/tool guide and tests.

## Out Of Scope

- Starting, pausing, stopping, or modifying paper strategies.
- Live/Testnet order tools.
- Direct BitPro database access.
- Per-strategy performance fan-out unless BitPro exposes a stable read endpoint for it.
- Scheduled daily jobs or notifications.

## Done Means

- Paper dashboard responses include structured `monitor_summary`.
- Reports distinguish current dashboard performance from complete running strategy inventory.
- Missing per-strategy PnL/drawdown is called out as a data gap, not inferred.
- Suggested actions are read-only and source-bound.

## Verification

```bash
uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_market_candles_tool.py tests/test_agent_acceptance.py -q
./scripts/check.sh
```

## Handoff

After this slice, the next strengthening step is scheduled monitoring: persist paper monitor snapshots, detect drift over time, and optionally send operator notifications.
