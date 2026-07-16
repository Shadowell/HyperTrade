#!/usr/bin/env bash

set -euo pipefail

if [ "${HYPERTRADE_EVAL_TARGET:-}" != "isolated" ]; then
  echo "Set HYPERTRADE_EVAL_TARGET=isolated; this runner must not target production." >&2
  exit 2
fi

if [ -z "${HYPERTRADE_EVAL_BASE_URL:-}" ]; then
  echo "Set HYPERTRADE_EVAL_BASE_URL to the isolated HyperTrade API." >&2
  exit 2
fi

case "$HYPERTRADE_EVAL_BASE_URL" in
  http://127.0.0.1*|http://localhost*) ;;
  *) echo "The task-completion suite requires a loopback isolated target." >&2; exit 2 ;;
esac

output_dir="${HYPERTRADE_EVAL_OUTPUT_DIR:-/tmp/hypertrade-agent-evals}"
runner_image="${HYPERTRADE_EVAL_RUNNER_IMAGE:-hypertrade-agent-eval:latest}"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"

if ! docker image inspect "$runner_image" >/dev/null 2>&1; then
  echo "Missing $runner_image; run deploy/deploy-eval.sh first." >&2
  exit 2
fi

docker run --rm \
  --network host \
  --env HYPERTRADE_EVAL_TARGET=isolated \
  --volume "$output_dir:/eval-output" \
  "$runner_image" \
  python scripts/run_operator_task_completion_eval.py \
    --output /eval-output/operator-task-completion.json \
    --base-url "$HYPERTRADE_EVAL_BASE_URL" \
    "$@"
