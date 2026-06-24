# Sprint 59 - CLI Argument Candidate Display

## Goal

Fix slash-command candidate display so partial command arguments such as
`/model c` show available completions instead of being treated as an unknown
command or dispatched as a bad argument.

## Scope

- Keep the existing readline completion source of truth.
- Render argument candidates for commands listed in `SLASH_ARGUMENT_COMPLETIONS`.
- Intercept incomplete known arguments before command dispatch.
- Cover the bug with focused CLI tests.

## Out of Scope

- Replacing readline with a full-screen TUI.
- Live per-keystroke dropdown rendering.
- Changing Agent tools, provider runtime, trading, BitPro, paper, or live-order
  behavior.

## Acceptance

- `/model c` renders `codex` as an argument candidate and does not switch to a
  fake provider named `c`.
- The readline display hook renders argument candidates such as `codex` for
  `/model c`.
- Existing command-prefix candidates such as `/st` and `/me` still work.
- `./scripts/check.sh` passes before deployment.

## Verification

```bash
uv run pytest tests/test_cli.py::test_slash_command_display_hook_renders_argument_candidates \
  tests/test_cli.py::test_slash_partial_argument_renders_candidates_without_dispatch \
  tests/test_cli.py::test_slash_command_display_hook_renders_filtered_candidates \
  tests/test_cli.py::test_slash_command_candidates_render_for_partial_command -q
./scripts/check.sh
```
