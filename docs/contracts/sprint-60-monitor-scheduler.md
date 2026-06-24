# Sprint 60 - Monitor Scheduler Worker

## Goal

Turn the existing manual monitor system into a scheduled, read-only worker loop
so HyperTrade can persist monitor runs and alert events without an operator
manually invoking `/monitor run`.

## In Scope

- Add schedule metadata for default monitors using the existing
  `MonitorDefinition.schedule_json` field.
- Add a `MonitorService.run_due_monitors()` path that selects enabled monitors
  with interval schedules and skips monitors that are not due.
- Wire a monitor scheduler loop into `hypertrade.worker`, gated by settings.
- Keep monitor collection read-only and preserve the existing
  `monitor_write_tool_blocked` guardrail.
- Update the monitoring runbook and progress log.

## Out of Scope

- Auto-pausing, stopping, starting, or promoting paper/live strategies.
- Mainnet or Testnet order execution.
- External incident-management integrations.
- Automatic PostgreSQL backups; this should be a separate follow-up sprint.
- Full frontend alert-action workflows.

## Deliverables

- Scheduler helpers in `hypertrade.monitoring`.
- Worker loop and settings for monitor scheduling.
- Focused tests for due/not-due selection, disabled/manual skip behavior, and
  worker-loop wiring.
- Documentation updates for the scheduled monitor path.

## Done Means

- Default monitors have interval schedule metadata.
- The worker can run due monitors automatically without calling paper/live write
  tools.
- Manual CLI/API monitor runs still work.
- Operators can disable scheduled monitor execution through configuration.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_monitoring_alerts.py tests/test_bitpro_paper_monitor_service.py -q
uv run pytest tests/test_cli.py tests/test_api.py -q
./scripts/check.sh
```

Manual or QA checks:

- Start the worker with monitor scheduling enabled and confirm a due monitor
  produces a persisted monitor run and alert rows when thresholds/data gaps are
  present.
- Confirm monitor output includes read-only source tools only.

## Risks / Notes

- BitPro may be unavailable or unconfigured on some deployments. Scheduler
  output must treat that as a monitor data gap rather than a worker crash.
- Default intervals should be conservative enough to avoid noisy BitPro calls.

## Handoff

- Next likely step: add a PostgreSQL backup smoke/automation sprint and include
  backup freshness in monitor output.
