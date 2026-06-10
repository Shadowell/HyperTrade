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

For the current port-only HTTP deployment on `3333`, keep `COOKIE_SECURE=false`.
Set it to `true` only after Nginx serves the site through HTTPS; otherwise
admin-authenticated privileged API requests will not send the session cookie.
The `/harness` workbench itself is readable without login, but privileged
mutations still use the admin session.

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

## CLI Access

The server installs `/usr/local/bin/hypertrade` and `/usr/local/bin/ht`.
The host wrapper runs a short-lived CLI client container and connects to the
running API over the Compose network at `http://api:3334` by default. It no
longer execs into the long-running `hypertrade-api` service container, so a
deployment can replace the API container without killing the operator's terminal
process. An in-flight request can still fail while the API is restarting; the
CLI prints a retryable remote API message and the interactive loop remains open.

From the server host:

```bash
hypertrade
hypertrade ask "看下ETH行情"
```

From a developer machine, use the CLI as a remote client for the deployed API.
This runs only the terminal client locally; Agent runs, database reads, Memory,
RAG, paper state, and BitPro adapter calls all happen on the server:

```bash
HYPERTRADE_USERNAME=admin \
HYPERTRADE_PASSWORD='***' \
uv run hypertrade --remote http://47.79.36.92:3333
```

Other operators can open the web harness at `http://47.79.36.92:3333/harness`
to review live runs, trace, RAG, Memory, and market state without a login wall.
For privileged actions, use the same remote CLI pattern with their own
credentials. Do not share production `.env` files or server-only provider keys.

## PostgreSQL

PostgreSQL runs through Docker Compose with `pgvector/pgvector:pg16`. Port `5432` is not exposed publicly. API and worker connect over the Compose network.

Manual backup command:

```bash
docker exec hypertrade-postgres pg_dump -U hypertrade hypertrade > /opt/hypertrade/hypertrade-$(date +%Y%m%d%H%M%S).sql
```

V1 does not schedule automatic backups.
