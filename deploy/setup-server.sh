#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="/opt/hypertrade"

apt-get update
apt-get install -y nginx git curl rsync ca-certificates

mkdir -p "$ROOT_DIR" \
  "$ROOT_DIR/data/postgres" \
  "$ROOT_DIR/logs" \
  "$ROOT_DIR/frontend/dist" \
  "$ROOT_DIR/workspace/strategies" \
  "$ROOT_DIR/deploy"

if [ ! -f "$ROOT_DIR/.env" ]; then
  cat > "$ROOT_DIR/.env" <<'ENV'
APP_ENV=production
POSTGRES_DB=hypertrade
POSTGRES_USER=hypertrade
POSTGRES_PASSWORD=change-me
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me
SESSION_SECRET=change-me
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
QWEN_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_EMBEDDING_MODEL=text-embedding-v4
QWEN_EMBEDDING_DIMENSIONS=1024
OKX_TESTNET=true
ENV
  chmod 600 "$ROOT_DIR/.env"
fi

echo "[setup] install GitHub runner separately with label hypertrade-production"
echo "[setup] edit $ROOT_DIR/.env before first deployment"

