# Sprint 63 - CLI Selectable Slash Candidates

## Goal

Make every slash command candidate list selectable by number so operators do not
need to copy or retype displayed alternatives.

## In Scope

- Render slash command candidates and slash argument candidates with stable
  numbers.
- In interactive chat, prompt for a candidate number when incomplete slash
  command or argument candidates are displayed.
- Dispatch the selected candidate through the same deterministic slash-command
  handlers.
- Preserve non-interactive/script behavior: candidates still render without
  prompting when no `input_fn` is available.
- Continue the existing `/model` provider/model picker flow when a model
  provider is selected from an argument candidate such as `/model c`.

## Out of Scope

- Full per-keystroke TUI dropdown navigation.
- Mouse selection inside terminal candidate lists.
- Free-form prompt suggestion/autocomplete.
- Automatic execution of placeholder-heavy examples that require user-specific
  ids or prompts.

## Deliverables

- Shared candidate-selection helpers in the CLI.
- Focused CLI tests for command-candidate selection, argument-candidate
  selection, and blank cancellation.
- README/spec/architecture/progress documentation updates.

## Done Means

- `/st` can show candidates and run `/status` by selecting its number.
- `/model c` can show `codex`, select it by number, and continue into the Codex
  model picker.
- Blank selection cancels cleanly without dispatching an Agent run.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_cli.py -q
./scripts/check.sh
```

Manual or QA checks:

- `printf "/st\n1\n:q\n" | uv run hypertrade --local` prints status output.
- `printf "/model c\n1\n2\n:q\n" | uv run hypertrade --local` switches to Codex
  and the selected Codex model when Codex is configured.

## Risks / Notes

- Candidate selection is a readline-bound interaction, not a full TUI.
- Placeholder commands are normalized to safe slash handlers where possible so
  selecting a help row does not silently invent ids or prompts.
