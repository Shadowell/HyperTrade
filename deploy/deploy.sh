#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="/opt/hypertrade"
cd "$ROOT_DIR"

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "[deploy] missing $ROOT_DIR/.env"
  exit 1
fi

mkdir -p "$ROOT_DIR/data/postgres" "$ROOT_DIR/logs" "$ROOT_DIR/workspace/strategies" "$ROOT_DIR/deploy"

echo "[deploy] building api and worker images"
docker compose build api worker

echo "[deploy] starting postgres"
docker compose up -d postgres

echo "[deploy] running database migrations"
docker compose run --rm api alembic upgrade head

echo "[deploy] starting app services"
docker compose up -d api worker

echo "[deploy] installing host cli wrapper"
cat > /usr/local/bin/hypertrade <<'WRAPPER'
#!/usr/bin/env bash

set -euo pipefail

cd /opt/hypertrade

env_args=()
for name in HYPERTRADE_RENDERER HYPERTRADE_THINKING_ANIMATION NO_COLOR; do
  if [ "${!name+x}" = "x" ]; then
    env_args+=("-e" "$name=${!name}")
  fi
done

if [ -t 0 ] && [ -t 1 ]; then
  exec docker compose exec "${env_args[@]}" api hypertrade "$@"
fi

exec docker compose exec -T "${env_args[@]}" api hypertrade "$@"
WRAPPER
chmod 755 /usr/local/bin/hypertrade
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
