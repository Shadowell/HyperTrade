#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="${HYPERTRADE_EVAL_ROOT:-/opt/hypertrade-eval}"
SOURCE_DIR="${HYPERTRADE_SOURCE_ROOT:-/opt/hypertrade}"
ENV_FILE="$ROOT_DIR/.env"
COMPOSE_FILE="$ROOT_DIR/docker-compose.eval.yml"
EVAL_RUNNER_IMAGE="${HYPERTRADE_EVAL_RUNNER_IMAGE:-hypertrade-agent-eval:latest}"

if [ ! -f "$ENV_FILE" ]; then
  echo "[eval-deploy] missing $ENV_FILE"
  exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "[eval-deploy] missing $COMPOSE_FILE"
  exit 1
fi

read_env_value() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key {value = substr($0, length(key) + 2)} END {print value}' "$ENV_FILE"
}

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

codex_auth_source="$(read_env_value CODEX_AUTH_SOURCE_PATH)"
eval_port="$(read_env_value HYPERTRADE_EVAL_PORT)"
eval_image="$(read_env_value HYPERTRADE_EVAL_IMAGE)"

if [ -z "$codex_auth_source" ] || [ ! -s "$codex_auth_source" ]; then
  echo "[eval-deploy] CODEX_AUTH_SOURCE_PATH must point to a non-empty server auth file"
  exit 1
fi

if ! [[ "$eval_port" =~ ^[0-9]{2,5}$ ]]; then
  echo "[eval-deploy] HYPERTRADE_EVAL_PORT must be a valid local TCP port"
  exit 1
fi

if [ -z "$eval_image" ]; then
  eval_image="hypertrade-api:latest"
fi

if ! docker image inspect "$eval_image" >/dev/null 2>&1; then
  echo "[eval-deploy] missing $eval_image; deploy the matching production image first"
  exit 1
fi

if [ ! -f "$SOURCE_DIR/backend/Dockerfile" ]; then
  echo "[eval-deploy] missing source tree at $SOURCE_DIR"
  exit 1
fi

# This target is physically isolated and has no paper/live execution path. The
# flag admits only the two deterministic failure fixtures used by the public
# answer evaluator; production never sets it.
set_env_value HYPERTRADE_OPERATOR_EVAL_FIXTURES_ENABLED true
# The evaluator must exercise the deterministic Mission planner, never make a
# network model call through credentials mounted for unrelated console checks.
set_env_value ACTIVE_CHAT_PROVIDER isolated

chmod 600 "$ENV_FILE"
mkdir -p "$ROOT_DIR/data/postgres" "$ROOT_DIR/eval-artifacts"

compose=(docker compose --project-name hypertrade-eval --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

echo "[eval-deploy] validating isolated Compose configuration"
"${compose[@]}" config -q

echo "[eval-deploy] building reproducible Agent evaluation runner"
docker build \
  --target agent-eval \
  --tag "$EVAL_RUNNER_IMAGE" \
  --file "$SOURCE_DIR/backend/Dockerfile" \
  "$SOURCE_DIR"

echo "[eval-deploy] starting isolated postgres"
"${compose[@]}" up -d postgres

echo "[eval-deploy] running isolated database migrations"
"${compose[@]}" run --rm api alembic upgrade head

echo "[eval-deploy] seeding isolated public-answer fixtures"
eval_db="$(read_env_value POSTGRES_DB)"
eval_user="$(read_env_value POSTGRES_USER)"
eval_password="$(read_env_value POSTGRES_PASSWORD)"
if [ -z "$eval_db" ] || [ -z "$eval_user" ] || [ -z "$eval_password" ]; then
  echo "[eval-deploy] evaluation database credentials are required for fixture seeding"
  exit 1
fi
# The production API image deliberately excludes evaluation scripts. Seed only
# through the isolated runner image on the evaluation network, never via the
# production API container or host Python.
docker run --rm \
  --network hypertrade-eval \
  --env-file "$ENV_FILE" \
  --env HYPERTRADE_EVAL_TARGET=isolated \
  --env "DATABASE_URL=postgresql+psycopg://${eval_user}:${eval_password}@postgres:5432/${eval_db}" \
  "$EVAL_RUNNER_IMAGE" \
  python scripts/seed_operator_answer_eval.py

echo "[eval-deploy] starting isolated API (worker profile remains disabled)"
"${compose[@]}" up -d --force-recreate api

echo "[eval-deploy] waiting for health"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${eval_port}/api/health" >/dev/null; then
    echo "[eval-deploy] health ok"
    exit 0
  fi
  sleep 2
done

echo "[eval-deploy] health failed"
"${compose[@]}" ps
"${compose[@]}" logs --tail=120 api
exit 1
