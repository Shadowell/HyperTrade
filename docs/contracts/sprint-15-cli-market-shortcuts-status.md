# Sprint 15 Contract: CLI Market Shortcuts And Agent Status

## Goal

Make the CLI more usable for day-to-day trading research by adding deterministic market shortcut commands and clearer Agent progress status while a free-form prompt is running.

## Scope

- Add CLI slash commands:
  - `/price <symbol>`
  - `/candles <symbol> --bar <bar> --limit <n>`
  - `/compare <symbol> <symbol> [more...] --bar <bar> --limit <n>`
- Add authenticated API endpoints for the same deterministic market payloads.
- Keep free-form chat on the existing Agent streaming path.
- Improve CLI streaming status labels so users can see run creation, planning, tool execution, tool completion, and final report generation.
- Add tests for CLI shortcuts, remote API paths, and status text.

## Out Of Scope

- Live order execution.
- Changing LLM planner behavior.
- Historical K-line persistence.
- Frontend UI changes.

## Acceptance

- `hypertrade` interactive chat can run `/price`, `/candles`, and `/compare`.
- `hypertrade ask "<prompt>"` prints readable Agent status while the run is in progress.
- Remote CLI can call deterministic market endpoints through the deployed API.
- `uv run pytest tests/test_cli.py tests/test_api.py -q` passes.
- Full `./scripts/check.sh` passes.
- Server smoke verifies `/price ETH`, `/candles ETH --bar 1H --limit 50`, and `/compare ETH SOL --bar 4H --limit 100`.
