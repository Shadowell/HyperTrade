# Sprint 50 Contract: Report Provenance System

## Goal

Create a reusable report-block and provenance system so Agent outputs stay
readable by default while preserving exact source evidence, missing fields, and
tool paths for audit.

## In Scope

- Define a report block schema for:
  summary, metric table, evidence list, missing data, risk boundary, next
  actions, and audit references.
- Add helpers for building report blocks from tool outputs.
- Update at least two existing report paths to use the block schema:
  suggested starting points are strategy library and BitPro paper monitoring.
- Support compact default rendering and expanded audit rendering in CLI/API.
- Preserve report JSON for frontend consumption.
- Add tests for missing-data rendering and source id visibility.

## Out of Scope

- Full frontend redesign.
- PDF/export pipeline.
- Model-specific prompt tuning unrelated to structured reporting.
- New external data connectors.

## Deliverables

- Report block schema/helpers.
- Updated AgentKernel report rendering for selected paths.
- CLI rendering tests for compact and audit modes.
- Docs in `docs/architecture/04-tool-calling.md`,
  `docs/architecture/11-cli-conversation-harness.md`, and
  `docs/knowledge/tool-usage-guide.md`.

## Design Notes

Each block should support:

- `block_type`
- `title`
- `source_refs`
- `metrics`
- `rows`
- `missing`
- `notes`
- `severity`

Reports should not include raw tool JSON unless explicitly requested.

## Done Means

- Default reports are concise and source-backed.
- Audit mode can show source ids and tool paths.
- Missing fields appear as missing data, not silence.
- Existing CLI report readability does not regress.

## Verification

```bash
uv run pytest tests/test_market_candles_tool.py tests/test_cli.py -q
uv run pytest tests/test_agent_acceptance.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run a BitPro paper prompt and confirm the default report is compact.
- Re-run with debug/audit configuration and confirm source details are visible.

## Risks / Notes

- Avoid a broad renderer rewrite. Start with two paths and keep compatibility
  with existing Markdown reports.

## Handoff

- Next likely step: Sprint 52 can render report blocks in `/harness`.

