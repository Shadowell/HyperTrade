# Sprint 12 Contract: CLI Streaming

## Goal

Make `hypertrade ask` and interactive chat show Agent progress while a run is executing, instead of
waiting for the full DeepSeek/tool-call cycle to complete before printing anything.

## Motivation

After Sprint 09-11, market runs often call several tools and can take 10+ seconds. A modern Agent
CLI should reveal run start, tool start, tool result, and final report events as they happen.

## In Scope

- Add AgentKernel event emission for:
  - run started
  - tool started
  - tool completed
  - run completed
  - run failed
- Add FastAPI SSE endpoint `POST /api/agent/runs/stream`.
- Add remote API client SSE parsing.
- Add local CLI streaming support using the same event shape.
- Make `hypertrade ask` and interactive chat prefer streaming, with existing full-run rendering as
  fallback.
- Add tests for CLI event rendering and API SSE output.

## Out of Scope

- Token-by-token model streaming.
- Browser `/harness` live event panels.
- WebSocket replacement.
- Changes to Agent tool behavior or report content.

## Done Means

- `hypertrade ask <prompt>` prints progress lines before the final report.
- Remote CLI can consume `/api/agent/runs/stream`.
- Existing non-stream run endpoint still works.
- `./scripts/check.sh` passes.
- Server CLI smoke verifies tool-call progress lines are visible.

## Verification

```bash
uv run pytest tests/test_cli.py tests/test_api.py -q
./scripts/check.sh
ssh root@47.79.36.92 'hypertrade ask "比较 ETH 和 SOL 哪个更强"'
```
