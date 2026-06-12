# Sprint 36 Contract: BitPro Backtest Artifacts

## Goal

Add a read-only BitPro backtest detail evidence path so Agent answers can inspect a specific BitPro-owned backtest result beyond ranking rows.

## In Scope

- Add an Agent tool for `bitpro_backtest_get_result`.
- Keep the flow behind `bitpro_capabilities` and `bitpro_health` preflight.
- Normalize result metrics plus bounded artifact samples for equity curve, trades, orders, fills, and drawdown series.
- Render a concise Agent report section that names the source tool, result id, strategy id/name, metrics, artifact availability, and sample counts.
- Update docs and tests for the new evidence path.

## Out Of Scope

- Starting new BitPro backtests.
- Paper/simulation promotion.
- Live or Testnet order tools.
- Direct BitPro database reads.
- Full charting or frontend artifact visualization.

## Done Means

- `bitpro_backtest_get_result(backtest_id=...)` returns normalized metrics and artifact summaries from BitPro API data only.
- Missing artifacts are reported as unavailable instead of being synthesized.
- Agent reports can cite the detail evidence for a specific backtest id.
- Existing BitPro result ranking behavior remains unchanged.

## Verification

```bash
uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_agent_planner.py tests/test_market_candles_tool.py tests/test_agent_acceptance.py -q
./scripts/check.sh
```

## Handoff

After this slice, the next strengthening step is to improve BitPro paper/simulation monitoring across multiple running strategies and expose drift/anomaly summaries.
