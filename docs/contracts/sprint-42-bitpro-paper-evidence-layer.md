# Sprint 42 Contract: BitPro Paper Evidence Layer

## Goal

Strengthen the BitPro paper monitor agent so paper/simulation answers can cite dashboard, event stream, and equity-curve evidence from BitPro MCP instead of relying on the current dashboard view alone.

## In Scope

- Expose read-only Agent tools for BitPro paper events and paper equity curve.
- Keep the mandatory BitPro preflight order: `bitpro_capabilities`, `bitpro_health`, then the smallest read tool needed.
- Normalize bounded paper events and equity-curve samples for deterministic reports.
- Render event/error counts, latest event evidence, and equity/drawdown samples in Agent and CLI output.
- Update planner instructions, architecture docs, progress notes, and tests.

## Out Of Scope

- Starting, pausing, stopping, or modifying paper strategies.
- Live/Testnet order tools.
- Direct BitPro database access or copying BitPro business logic.
- Scheduled paper monitoring jobs or alert notifications.
- Inventing missing per-strategy PnL/drawdown when BitPro does not expose it.

## Done Means

- `bitpro_paper_events` and `bitpro_paper_equity_curve` are available to the planner and registry as read-only tools.
- Adapter outputs include bounded normalized rows, summaries, nested tool call traces, and explicit missing-data behavior.
- Reports keep the `BitPro 模拟盘状态` section source-bound and show event/equity evidence without synthesized metrics.
- CLI structured output renders these tool results without falling back to raw Markdown.

## Verification

```bash
uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_agent_planner.py tests/test_market_candles_tool.py tests/test_agent_acceptance.py tests/test_cli.py tests/test_tool_registry.py -q
./scripts/check.sh
```

## Handoff

After this slice, the next strengthening step is scheduled paper monitor snapshots: persist dashboard/events/equity summaries over time, detect drift, and optionally notify operators.
