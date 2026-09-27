# PostgreSQL Backup And Restore

## Manual Backup

持久备份放在 `/var/backups/hypertrade/`。不要写到 `/opt/hypertrade/backups/`：部署同步会 `rsync --delete` 发布树，该目录即使被排除也不作为备份事实来源。

在服务器上执行：

```bash
mkdir -p /var/backups/hypertrade
cd /opt/hypertrade/current
docker compose exec -T postgres pg_dump -U hypertrade hypertrade > /var/backups/hypertrade/hypertrade-$(date +%Y%m%d-%H%M%S).sql
```

## Manual Restore

Stop API/worker first, then restore intentionally:

```bash
cd /opt/hypertrade/current
docker compose stop api worker
cat /var/backups/hypertrade/hypertrade.sql | docker compose exec -T postgres psql -U hypertrade hypertrade
docker compose start api worker
```

## Risk

Sprint 31 does not add automatic backups. Manual backup should be run before migrations, deployment experiments, and destructive data tests.

