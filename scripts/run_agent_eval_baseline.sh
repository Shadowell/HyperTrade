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
  *)
    if [ "${HYPERTRADE_EVAL_ALLOW_REMOTE:-}" != "true" ]; then
      echo "Non-loopback targets require HYPERTRADE_EVAL_ALLOW_REMOTE=true." >&2
      exit 2
    fi
    ;;
esac

output_dir="${HYPERTRADE_EVAL_OUTPUT_DIR:-/tmp/hypertrade-agent-evals}"
reference="evals/ragas/agent_golden_reference.json"
trajectories="$output_dir/agent-golden-trajectories.json"
report="$output_dir/agent-golden-baseline.json"
collector_args=(
  --reference "$reference"
  --output "$trajectories"
  --base-url "$HYPERTRADE_EVAL_BASE_URL"
)

case "$HYPERTRADE_EVAL_BASE_URL" in
  http://127.0.0.1*|http://localhost*) ;;
  *) collector_args+=(--allow-remote) ;;
esac

mkdir -p "$output_dir"
uv run python scripts/collect_agent_eval_trajectories.py \
  "${collector_args[@]}"
uv run python -m hypertrade.evals.baseline_runner \
  --reference "$reference" \
  --trajectories "$trajectories" \
  --output "$report"

echo "Baseline report: $report"
