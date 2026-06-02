# Sprint 16 Contract: Structured CLI Report Renderer

## Goal

Improve HyperTrade CLI readability by rendering structured Agent outputs instead of showing raw Markdown whenever `report_json` or trace tool outputs contain enough data.

## Scope

- Keep `report_json` and trace events as the primary machine-readable report source.
- Render market-summary reports as structured CLI sections.
- Render planner market tool outputs from trace events:
  - `market_ticker`
  - `market_candles`
  - `market_compare`
- Preserve Markdown as a fallback when a run has no recognized structured payload.
- Add tests proving structured payloads do not display raw Markdown headings.

## Out Of Scope

- Web report component redesign.
- Adding a new terminal dependency such as `rich`.
- Changing provider prompts or LLM planner behavior.
- Changing report persistence schema.

## Acceptance

- CLI `render_run()` prefers structured market summary output over `report_markdown`.
- CLI `render_run()` prefers structured planner tool output over `report_markdown`.
- Existing Markdown fallback still works for unknown report shapes.
- `uv run pytest tests/test_cli.py -q` passes.
- Full `./scripts/check.sh` passes.
- Server smoke verifies a free-form market prompt prints structured CLI sections.
