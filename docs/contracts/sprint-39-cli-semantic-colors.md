# Sprint 39 Contract: CLI Semantic Colors

## Goal

Make interactive CLI output easier to scan by coloring different output types with stable semantic colors.

## In Scope

- Add a shared CLI color helper for semantic output roles.
- Color slash-command help, tool catalog rows, Agent streaming status, and remote/API error text in real TTY output.
- Keep non-TTY output and `NO_COLOR=1` output plain for scripts and logs.
- Add focused CLI tests for colored TTY output and plain fallback.
- Update CLI architecture/spec/progress docs.

## Out Of Scope

- Full theme customization.
- Frontend color changes.
- Replacing Rich table/panel rendering.

## Done Means

- Command names, tools, categories, approvals, status, success, warning, and error text can use different ANSI colors in TTY sessions.
- Script-friendly output remains stable without ANSI escape sequences.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_cli.py::test_slash_help_uses_semantic_colors_for_tty tests/test_cli.py::test_render_tools_uses_distinct_tty_colors tests/test_cli.py::test_run_stream_uses_status_colors_for_tty -q
./scripts/check.sh
```
