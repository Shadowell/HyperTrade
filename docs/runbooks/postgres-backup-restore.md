# PostgreSQL Backup And Restore

## Manual Backup

Run on the server:

```bash
cd /opt/hypertrade/current
docker compose exec -T postgres pg_dump -U hypertrade hypertrade > /opt/hypertrade/backups/hypertrade-$(date +%Y%m%d-%H%M%S).sql
```

## Manual Restore

Stop API/worker first, then restore intentionally:

```bash
cd /opt/hypertrade/current
docker compose stop api worker
cat /opt/hypertrade/backups/hypertrade.sql | docker compose exec -T postgres psql -U hypertrade hypertrade
docker compose start api worker
```

## Risk

Sprint 31 does not add automatic backups. Manual backup should be run before migrations, deployment experiments, and destructive data tests.

