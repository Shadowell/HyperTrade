# Sprint 62 - Live Order History Routing

## Goal

Stop live-account order-history questions from falling back to all-market
reports. A prompt such as `我的实盘最近的一笔订单是什么` must route to a
read-only BitPro live order-history diagnostic tool and render order evidence.

## Scope

- Add a HyperTrade Agent tool schema for BitPro live order history.
- Wire the trusted runtime to BitPro's read-only `/trading/orders/history`
  API path through the existing adapter preflight.
- Classify the tool as `live_diagnostic_read`, not market data and not a live
  write tool.
- Render a compact `BitPro 实盘订单` report section focused on the latest
  order.
- Cover the routing surface with focused regression tests.

## Out of Scope

- Live order placement, cancellation, transfer, or any exchange write.
- Changing BitPro business logic or direct BitPro database access.
- Full live-account UI redesign.

## Acceptance

- Planner schemas include `bitpro_live_order_history` with recent/latest order
  guidance.
- Planner prompt explicitly tells the model not to answer live order-history
  questions with `market_summary`.
- Adapter calls `bitpro_capabilities`, `bitpro_health`, then
  `trading_order_history`.
- The final Agent report includes `BitPro 实盘订单` and a latest-order line.
- `./scripts/check.sh` passes before deployment.

## Verification

```bash
uv run pytest \
  tests/test_agent_market_summary.py::test_agent_routes_live_order_history_prompt_away_from_market_fallback \
  tests/test_agent_planner.py::test_bitpro_live_order_history_schema_targets_recent_order_queries \
  tests/test_agent_planner.py::test_planner_prompt_does_not_treat_bitpro_live_gate_as_runtime_status \
  tests/test_bitpro_mcp_adapter.py::test_bitpro_adapter_reads_live_order_history_after_preflight \
  tests/test_market_candles_tool.py::test_planner_report_renders_bitpro_live_order_history_latest_order \
  tests/test_tool_registry.py::test_tool_registry_exposes_sprint_one_tools_and_live_gate \
  tests/test_tool_registry.py::test_tool_registry_attaches_policy_metadata_to_every_tool -q
./scripts/check.sh
```
