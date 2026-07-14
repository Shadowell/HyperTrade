# Sprint 94 - Isolated Evaluation Deployment

## Goal

Provision a repeatable server-side Agent evaluation target that follows the
production runtime shape without sharing production service components, data,
or deployment configuration.

## In scope

- Add a dedicated `hypertrade-eval` Docker Compose deployment with its own API,
  PostgreSQL container, network, container names, data path, database
  credentials, and loopback-only API port.
- Keep the evaluation runtime at `/opt/hypertrade-eval`, separate from the
  production source and `/opt/hypertrade/data/postgres` volume.
- Reuse the already-built production API image as an immutable runtime artifact
  rather than building a second image on the constrained server.
- Mount the server's Codex auth file only into the evaluation API as a
  read-only Compose secret; do not copy the token into any repository file or
  evaluation environment file.
- Make the Codex Responses adapter compatible with the ChatGPT Codex
  stream-only endpoint by sending `stream=true`, placing trusted system
  guidance in `instructions`, and rebuilding completed output items from SSE.
- Disable paper trading, monitor scheduling, BitPro host access, private
  exchange credentials, Feishu, and Langfuse in the evaluation environment.
- Keep the background worker as an opt-in Compose profile; the default
  evaluation target is API plus an isolated throwaway PostgreSQL database.
- Provide an idempotent deployment script and server-only environment template.

## Out of scope

- Provisioning another physical server, VM, Docker daemon, or a separate Codex
  workspace access token.
- Reusing production PostgreSQL, BitPro MCP, exchange credentials, data mounts,
  Nginx routes, or production `.env` values.
- Running a provider-backed golden baseline or enabling CI score thresholds.
- Deploying Langfuse or any external evaluator service.

## Done means

- `hypertrade-eval-api` and `hypertrade-eval-postgres` run independently of
  their production counterparts, on the `hypertrade-eval` Docker network.
- The API binds only to `127.0.0.1:4334`; it is not added to production Nginx.
- Its database files are under `/opt/hypertrade-eval/data/postgres`, and its
  credentials differ from production.
- The default deployment does not start an evaluation worker or expose the
  BitPro host gateway/data mount.
- The isolated API reports healthy and lists Codex as configured without
  revealing credentials.
- A minimal `evaluation_mode=true` Codex request completes through the
  stream-only transport without targeting a production service.

## Verification

- `docker compose --env-file deploy/hypertrade-eval.env.example -f docker-compose.eval.yml config -q`
- `uv run pytest tests/test_eval_deployment_config.py tests/test_deployment_config.py -q`
- `./scripts/check.sh`
- On the server: `/opt/hypertrade-eval/deploy/deploy-eval.sh`, then
  `curl -fsS http://127.0.0.1:4334/api/health` and inspect the
  `hypertrade-eval` Compose project only.

## Handoff

- This is logical isolation on the existing host. A requirement for physical
  isolation must be fulfilled with a separate VM/server and provider identity.
- Start the golden baseline only with `HYPERTRADE_EVAL_TARGET=isolated` against
  `http://127.0.0.1:4334`; keep generated artifacts in
  `/opt/hypertrade-eval/eval-artifacts` or another reviewed non-repository path.
- Rotate or replace the shared Codex OAuth mount with a dedicated Codex access
  token before granting the evaluation environment broader automation access.
