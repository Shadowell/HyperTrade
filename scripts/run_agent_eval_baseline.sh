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
reference="backend/src/hypertrade/evals/research_os_golden_v1.json"

mkdir -p "$output_dir"
for run_number in 1 2; do
  trajectories="$output_dir/research-os-trajectories-$run_number.json"
  report="$output_dir/research-os-baseline-$run_number.json"
  collector_args=(
    --reference "$reference"
    --output "$trajectories"
    --base-url "$HYPERTRADE_EVAL_BASE_URL"
  )
  case "$HYPERTRADE_EVAL_BASE_URL" in
    http://127.0.0.1*|http://localhost*) ;;
    *) collector_args+=(--allow-remote) ;;
  esac
  uv run --extra agent-evals python scripts/collect_agent_eval_trajectories.py \
    "${collector_args[@]}"
  uv run --extra agent-evals python -m hypertrade.evals.baseline_runner \
    --reference "$reference" \
    --trajectories "$trajectories" \
    --output "$report"
done

comparison="$output_dir/research-os-baseline-comparison.json"
uv run --extra agent-evals python -m hypertrade.evals.comparison \
  --left "$output_dir/research-os-baseline-1.json" \
  --right "$output_dir/research-os-baseline-2.json" \
  --output "$comparison"

echo "Baseline reports and comparison: $output_dir"
