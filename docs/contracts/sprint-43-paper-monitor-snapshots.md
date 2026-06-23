# Sprint 43 Contract: BitPro Paper Monitor Snapshots

## Goal

Turn BitPro paper monitoring from a single current read into a durable, source-bound snapshot trail that can compare the latest dashboard/events/equity evidence against the previous snapshot and report drift.

## In Scope

- Persist BitPro paper monitor snapshots in HyperTrade's database.
- Capture dashboard, event summary, equity summary, normalized metrics, nested BitPro tool calls, and drift metadata.
- Add a read-only Agent tool for manual snapshot capture and drift reporting.
- Render previous-vs-current drift in Agent/CLI reports.
- Update docs, tests, and migration.

## Out of Scope

- Scheduled jobs or background monitors.
- Notifications, webhooks, Feishu pushes, or email alerts.
- Automatic paper pause/resume/stop actions.
- Any live trading mutation tool.
- Direct BitPro database access or copied BitPro business logic.

## Deliverables

- `bitpro_paper_monitor_snapshot` Agent tool and registry entry.
- `bitpro_paper_monitor_snapshots` table and Alembic migration.
- Snapshot/drift service with deterministic alerts for PnL drop, equity drop, drawdown expansion, and new event errors.
- Report rendering for baseline and compared snapshots.
- Spec/progress/architecture/tool-guide updates.

## Done Means

- First capture is marked as a baseline snapshot.
- Later captures for the same strategy scope include `previous_snapshot_id` and drift deltas.
- Missing metrics are reported as data gaps, not inferred.
- Every BitPro read remains MCP/API-only and read-only.

## Verification

```bash
uv run pytest tests/test_bitpro_paper_monitor_service.py tests/test_agent_planner.py tests/test_market_candles_tool.py tests/test_agent_acceptance.py tests/test_cli.py tests/test_tool_registry.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run a production read-only Agent prompt asking for a BitPro paper monitor snapshot and confirm no live write tools appear in trace.

## Risks / Notes

- Drift quality depends on BitPro exposing comparable paper metrics. Missing event/equity fields must remain explicit data gaps.

## Handoff

- Next likely step: add scheduled snapshot capture and optional operator notifications.
