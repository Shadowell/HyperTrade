# Incident Response

## OKX WS Down

Symptoms:

- Market ticker age grows.
- Worker logs show websocket reconnect loops.

Actions:

```bash
cd /opt/hypertrade/current
docker compose logs -f worker
docker compose restart worker
```

## Provider Timeout

Symptoms:

- Agent runs fail during planner step.
- `/harness` provider shows configured but runs fail.

Actions:

- Switch CLI/API provider with `/model deepseek` or `/model openrouter`.
- Confirm server `.env` keys and base URLs.
- Use deterministic fallback by clearing provider key only for local tests.

## Worker Crash

Actions:

```bash
cd /opt/hypertrade/current
docker compose ps
docker compose logs worker --tail=200
docker compose restart worker
```

## Migration Failure

Actions:

- Stop API/worker.
- Inspect Alembic version table.
- Restore PostgreSQL backup if schema is partially changed.
- Re-run deploy only after the migration reason is understood.

