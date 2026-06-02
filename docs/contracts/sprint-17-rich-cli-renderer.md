# Sprint 17 Contract: Rich CLI Renderer

## Goal

Upgrade HyperTrade CLI structured reports from plain text blocks to Rich terminal tables and panels when terminal output supports it, while preserving plain text fallback for pipes, logs, and tests that opt out.

## Scope

- Add `rich` as a runtime dependency.
- Add renderer selection:
  - `HYPERTRADE_RENDERER=rich` forces Rich output.
  - `HYPERTRADE_RENDERER=plain` forces plain text output.
  - default `auto` uses Rich only for TTY output.
- Render structured market runs with Rich panels/tables:
  - run header
  - tool trace
  - market summary
  - ticker
  - trend
  - relative strength
  - disclaimer
- Keep Markdown fallback for unknown report shapes.

## Out Of Scope

- Frontend report redesign.
- LLM prompt changes.
- Changing report database schema.
- Adding charts or sparklines.

## Acceptance

- `uv run pytest tests/test_cli.py -q` passes.
- Full `./scripts/check.sh` passes.
- Server smoke verifies `HYPERTRADE_RENDERER=rich hypertrade ask "看下ETH行情"` outputs Rich-style tables/panels.
- Plain text fallback remains available.
