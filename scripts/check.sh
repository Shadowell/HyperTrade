#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[check] repository root: $ROOT_DIR"

if [ -f "$ROOT_DIR/frontend/package.json" ]; then
  echo "[check] frontend install"
  (cd "$ROOT_DIR/frontend" && npm exec --yes pnpm@10 -- install --frozen-lockfile)
  echo "[check] frontend lint"
  (cd "$ROOT_DIR/frontend" && npm exec --yes pnpm@10 -- lint)
  echo "[check] frontend test"
  (cd "$ROOT_DIR/frontend" && npm exec --yes pnpm@10 -- test)
  echo "[check] frontend build"
  (cd "$ROOT_DIR/frontend" && npm exec --yes pnpm@10 -- build)
fi

if [ -f "$ROOT_DIR/pyproject.toml" ]; then
  echo "[check] python ruff"
  (cd "$ROOT_DIR" && uv run ruff check backend tests)
  echo "[check] python mypy"
  (cd "$ROOT_DIR" && uv run mypy backend/src)
  echo "[check] python pytest"
  (cd "$ROOT_DIR" && uv run pytest -q)
elif [ -d "$ROOT_DIR/backend" ]; then
  echo "[check] compiling backend python sources"
  python3 -m compileall "$ROOT_DIR/backend"
fi

if [ -f "$ROOT_DIR/voice_gen.py" ]; then
  echo "[check] compiling standalone python entrypoints"
  python3 -m compileall "$ROOT_DIR/voice_gen.py"
fi

echo "[check] done"
