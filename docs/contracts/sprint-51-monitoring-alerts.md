# Sprint 51 Contract: Monitoring And Alerts

## Goal

Turn one-off paper/live-read inspections into scheduled, read-only monitoring
workflows that detect drift, missing data, errors, and risk threshold breaches,
then produce operator-facing alerts without triggering trading writes.

## In Scope

- Add a monitoring job model for named monitor definitions and runs.
- Support read-only monitor types:
  - BitPro paper dashboard/events/equity/snapshot monitor
  - strategy-library evidence freshness monitor
  - connector health monitor
- Persist monitor results and alert events.
- Add threshold configuration for drawdown, error count, stale data, missing
  artifact, and PnL/equity drift.
- Add CLI/API endpoints to list monitors, run one monitor manually, and inspect
  recent alerts.
- Add notification sink abstraction, initially console/log/webhook-style only.

## Out of Scope

- Auto-pausing, stopping, or starting paper/live strategies.
- Mainnet live trading actions.
- Complex incident management workflow.
- Full frontend monitor dashboard unless Sprint 52 consumes the API.

## Deliverables

- Monitor definitions and run persistence.
- Monitor service using existing read-only BitPro adapter paths.
- Alert event schema.
- API/CLI surfaces.
- Tests for threshold detection, missing data, and no-write enforcement.
- Runbook in `docs/runbooks/monitoring-alerts.md`.

## Design Notes

Monitor outputs should include:

- monitor id
- scope
- source tools called
- metric snapshot
- drift vs previous run
- alerts
- data gaps
- recommended read-only action

Scheduling can start simple. If a durable worker loop already exists, reuse it;
otherwise expose manual monitor run first and document scheduler follow-up.

## Done Means

- Operator can run one monitor manually from CLI/API.
- Monitor result persists and can be compared with the previous result.
- Alerts include source ids and thresholds.
- No paper/live write tools are called.

## Verification

```bash
uv run pytest tests/test_monitoring_alerts.py tests/test_bitpro_paper_monitor_service.py -q
uv run pytest tests/test_cli.py tests/test_api.py -q
uv run pytest tests/test_agent_acceptance.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run a monitor against BitPro paper data and inspect alert/data-gap output.
- Confirm trace includes read-only tools only.

## Risks / Notes

- If BitPro lacks per-strategy metrics, report that as a data gap rather than
  inferring per-strategy performance.

## Handoff

- Next likely step: Sprint 52 can render monitors and alerts in `/harness`.
