# Sprint 38 Contract: CLI Command History

## Goal

Make interactive `hypertrade` chat behave like a normal operator terminal: up/down arrow history should recall prior prompts instead of printing escape sequences.

## In Scope

- Enable readline-backed input history for real TTY chat sessions.
- Persist command history under the local HyperTrade config directory.
- Add focused CLI tests for history setup and de-duplication.
- Update CLI architecture/progress docs.

## Out Of Scope

- A full-screen terminal UI.
- Prompt autosuggest or fuzzy search.
- Shell-level history outside the HyperTrade CLI process.

## Done Means

- Interactive chat loads and writes `~/.hypertrade/history`.
- Non-TTY/script output remains unchanged.
- Empty prompts and consecutive duplicates are not added to history.

## Verification

```bash
uv run pytest tests/test_cli.py::test_configure_interactive_history_reads_and_writes_history -q
./scripts/check.sh
```
