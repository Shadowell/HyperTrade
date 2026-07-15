#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="/opt/hypertrade"
cd "$ROOT_DIR"

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "[deploy] missing $ROOT_DIR/.env"
  exit 1
fi

mkdir -p \
  "$ROOT_DIR/data/postgres" \
  "$ROOT_DIR/logs" \
  "$ROOT_DIR/workspace/strategies" \
  "$ROOT_DIR/workspace/sandbox-ipc" \
  "$ROOT_DIR/deploy"
chown 65532:65532 "$ROOT_DIR/workspace/sandbox-ipc"
chmod 0750 "$ROOT_DIR/workspace/sandbox-ipc"

echo "[deploy] building api, worker, sandbox, and optional TUI client images"
docker compose build api worker sandbox cli

# The service image is built from this reviewed release. Persist its immutable
# local content digest so the API and sandbox reject mismatched IPC requests.
sandbox_image_id="$(docker image inspect hypertrade-sandbox:latest --format '{{.Id}}')"
sandbox_digest="local@${sandbox_image_id}"
python3 - "$ROOT_DIR/.env" "$sandbox_digest" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
digest = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
updated = False
result: list[str] = []
for line in lines:
    if line.startswith("AGENT_STRATEGY_SANDBOX_IMAGE="):
        result.append(f"AGENT_STRATEGY_SANDBOX_IMAGE={digest}")
        updated = True
    else:
        result.append(line)
if not updated:
    result.append(f"AGENT_STRATEGY_SANDBOX_IMAGE={digest}")
path.write_text("\n".join(result) + "\n", encoding="utf-8")
PY

echo "[deploy] starting postgres"
docker compose up -d postgres

echo "[deploy] running database migrations"
docker compose run --rm api alembic upgrade head

echo "[deploy] starting app services"
docker compose up -d sandbox api worker

echo "[deploy] installing host cli wrapper"
install -m 755 "$ROOT_DIR/deploy/hypertrade-host-cli" /usr/local/bin/hypertrade
ln -sfn /usr/local/bin/hypertrade /usr/local/bin/ht

echo "[deploy] installing nginx config"
cp "$ROOT_DIR/deploy/hypertrade.nginx" /etc/nginx/sites-available/hypertrade
ln -sfn /etc/nginx/sites-available/hypertrade /etc/nginx/sites-enabled/hypertrade
nginx -t
systemctl reload nginx

echo "[deploy] waiting for health"
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3334/api/health >/dev/null; then
    echo "[deploy] health ok"
    exit 0
  fi
  sleep 2
done

echo "[deploy] health failed"
docker compose ps
docker compose logs --tail=120 api
exit 1
