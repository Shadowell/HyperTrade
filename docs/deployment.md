# HyperTrade Deployment

## Summary

HyperTrade deploys to one Linux server with host Nginx, Docker Compose app services, PostgreSQL/pgvector, and a GitHub Actions self-hosted runner labeled `hypertrade-production`.

## Server Layout

- App root: `/opt/hypertrade`
- Frontend static files: `/opt/hypertrade/frontend/dist`
- PostgreSQL data: `/opt/hypertrade/data/postgres`
- Runtime strategy workspace: `/opt/hypertrade/workspace/strategies`
- Deployed SHA marker: `/opt/hypertrade/deploy/last_deployed_sha`

## First Setup

```bash
sudo bash deploy/setup-server.sh
sudo vim /opt/hypertrade/.env
```

Register a GitHub Actions self-hosted runner on the server with label:

```text
hypertrade-production
```

## Deploy Flow

1. Push to `main`.
2. Self-hosted runner checks `/opt/hypertrade/deploy/last_deployed_sha`.
3. If the SHA is new, frontend builds in Actions.
4. Source and frontend dist sync to `/opt/hypertrade`.
5. `deploy/deploy.sh` builds Docker images, starts PostgreSQL, runs Alembic, starts API/worker, reloads Nginx.
6. SHA is recorded only after health check passes.

## PostgreSQL

PostgreSQL runs through Docker Compose with `pgvector/pgvector:pg16`. Port `5432` is not exposed publicly. API and worker connect over the Compose network.

Manual backup command:

```bash
docker exec hypertrade-postgres pg_dump -U hypertrade hypertrade > /opt/hypertrade/hypertrade-$(date +%Y%m%d%H%M%S).sql
```

V1 does not schedule automatic backups.

