# Monitoring And Alerts Runbook

HyperTrade monitoring turns read-only evidence into persisted monitor runs and
alert events. Monitors may inspect BitPro paper state, strategy-library
freshness, or connector health, but they must never pause, resume, start, stop,
or otherwise mutate paper/live trading state.

## Operator Commands

List configured monitors:

```bash
uv run ht /monitors
```

Run one monitor manually:

```bash
uv run ht /monitor run mon_bitpro_paper_all
```

Inspect recent alert events:

```bash
uv run ht /alerts
```

The same surfaces are available over HTTP:

```bash
curl -s http://127.0.0.1:3334/api/monitors
curl -s -X POST http://127.0.0.1:3334/api/monitors/mon_bitpro_paper_all/run
curl -s http://127.0.0.1:3334/api/alerts
```

## Scheduled Worker

The worker checks monitor schedules every `MONITOR_LOOP_INTERVAL_SECONDS`
seconds. The default is `60`, which is only the scheduler tick; each monitor has
its own interval schedule.

Configuration:

```bash
MONITOR_SCHEDULER_ENABLED=true
MONITOR_LOOP_INTERVAL_SECONDS=60
```

Set `MONITOR_SCHEDULER_ENABLED=false` to stop automatic monitor runs while
keeping manual CLI/API monitor runs available.

## Default Monitors

- `mon_bitpro_paper_all`: reads BitPro paper dashboard, events, equity curve, and
  HyperTrade paper-monitor snapshots every 300 seconds; thresholds cover
  drawdown, error count, equity/PnL drift, and missing data.
- `mon_strategy_library_freshness`: reads audited `strategy_knowledge` Memory
  through `StrategyLibraryService` every 3600 seconds; thresholds cover stale or
  missing evidence.
- `mon_connector_health`: reads connector health, initially BitPro MCP health,
  every 600 seconds.

## Read-Only Boundary

Allowed evidence calls are read-only calls such as `bitpro_capabilities`,
`bitpro_health`, `paper_dashboard`, `paper_events`, `paper_equity_curve`,
`strategy_library_search`, and connector health checks.

Forbidden calls include paper/live mutation tools such as `paper_start`,
`paper_pause`, `paper_resume`, `paper_stop`, and live trading mutation tools.
If a monitor ever observes a write tool in its source calls, it records a
critical `monitor_write_tool_blocked` alert.

## Alert Review

Each persisted alert includes:

- `monitor_id`
- `run_id`
- `source_id`
- alert `level` and `code`
- threshold payload
- metric payload

Treat missing BitPro per-strategy metrics as data gaps. Do not infer
per-strategy PnL, drawdown, or equity when BitPro has not returned those fields.

## Verification

Focused checks:

```bash
uv run pytest tests/test_monitoring_alerts.py tests/test_bitpro_paper_monitor_service.py -q
uv run pytest tests/test_cli.py tests/test_api.py -q
```

Full gate:

```bash
./scripts/check.sh
```

Manual smoke after deployment:

```bash
hypertrade /monitors
hypertrade /monitor run mon_bitpro_paper_all
hypertrade /alerts
curl -s http://127.0.0.1:3334/api/health
```

Confirm default monitor schedules use `mode=interval`, monitor output includes
read-only source tools only, and alert events include source ids, thresholds,
data gaps, and recommended read-only actions.
