# Sprint 55 Contract: CLI Slash Command Candidates

## Sprint Name

`cli-slash-command-candidates`

## Goal

Make interactive slash commands feel closer to a professional operator CLI:
short prefixes such as `/st` or `/me` should reveal filtered command candidates
with purpose descriptions instead of falling through to a generic unknown-command
message.

## In Scope

- Reuse the existing slash command help table as the source of truth for
  candidate filtering and descriptions.
- Show filtered candidates when an entered slash prefix is not yet a complete
  command.
- Register a readline completion display hook so Tab completion can render
  described candidates in real TTY sessions.
- Add focused CLI tests for prefix filtering, candidate rendering, and display
  hook registration.

## Out of Scope

- Replacing `input()`/readline with a full-screen TUI framework.
- Live per-keystroke dropdown rendering that requires terminal raw mode.
- Adding or changing trading, monitor, BitPro, or live-order behavior.

## Deliverables

- CLI candidate generation and rendering helpers in `backend/src/hypertrade/cli.py`.
- Focused tests in `tests/test_cli.py`.
- README/spec/architecture/progress documentation updates.

## Done Means

- Entering `/st` in interactive chat shows only matching slash commands such as
  `/status` and `/strategy`.
- Tab completion in readline sessions has a display hook that can show matching
  commands with descriptions.
- Unknown slash prefixes with no matches produce a concise no-match message and
  point operators to `/help`.

## Verification

```bash
uv run pytest tests/test_cli.py::test_configure_interactive_history_reads_and_writes_history \
  tests/test_cli.py::test_slash_command_completion_matches_commands_and_subcommands \
  tests/test_cli.py::test_slash_command_candidates_filter_partial_prefix_with_descriptions \
  tests/test_cli.py::test_slash_command_candidates_render_for_partial_command \
  tests/test_cli.py::test_slash_command_display_hook_renders_filtered_candidates \
  tests/test_cli.py::test_slash_command_root_displays_help_without_unknown_message -q
uv run ruff check backend/src/hypertrade/cli.py tests/test_cli.py
./scripts/check.sh
```

Manual or QA checks:

- In a real terminal, type `/st` and press Enter; confirm a filtered candidate
  list appears and no Agent run starts.
- In a real terminal, type `/me` and press Tab; confirm candidates are displayed
  with descriptions.

## Risks / Notes

- The current CLI still uses readline. True live dropdown rendering on every
  keypress should be a separate TUI sprint if needed.
- Full repository verification can be blocked by unrelated in-progress sprint
  work in the same worktree; do not conflate that with this CLI slice.

## Handoff

- Next likely step: decide whether HyperTrade should adopt a dedicated TUI
  input layer for richer command palettes, fuzzy search, and keyboard navigation.
