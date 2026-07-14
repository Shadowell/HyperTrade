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

export PROMPTFOO_DISABLE_REMOTE_GENERATION=true
export PROMPTFOO_DISABLE_REDTEAM_REMOTE_GENERATION=true
export PROMPTFOO_DISABLE_TELEMETRY=1
export PROMPTFOO_DISABLE_UPDATE=1
export PROMPTFOO_DISABLE_SHARING=1
export PROMPTFOO_SELF_HOSTED=1

npx --yes promptfoo@0.121.19 eval --config evals/promptfoo/promptfooconfig.yaml --no-cache
