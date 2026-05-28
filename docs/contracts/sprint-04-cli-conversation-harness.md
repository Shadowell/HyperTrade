# Sprint 04 Contract: CLI Conversation Harness

## Goal

Add a developer-friendly CLI conversation harness so HyperTrade can be used from terminal while reusing the same server-side Agent, Tool Call, RAG, Memory, and Trace runtime.

## In Scope

- Add a `hypertrade` console script.
- Add `hypertrade ask <prompt>` for one-shot Agent runs.
- Add `hypertrade chat` for an interactive terminal loop.
- Default CLI mode calls the deployed FastAPI API instead of starting local services.
- Configure connection through environment variables:
  - `HYPERTRADE_API_URL`
  - `HYPERTRADE_USERNAME`
  - `HYPERTRADE_PASSWORD`
  - `HYPERTRADE_TIMEOUT_SECONDS`
- Print run id, status, tool calls, and Markdown report.
- Add tests for command behavior and API client requests.
- Document local/server usage.

## Out of Scope

- A separate local-only Agent runtime.
- Streaming token output.
- Rich terminal UI.
- Live/Testnet trading commands.
- Strategy optimization or historical K-line ingestion.

## Done Means

- `uv run hypertrade ask "请做行情归纳"` can call a running HyperTrade API.
- `uv run hypertrade chat` starts a REPL and exits on `exit`, `quit`, or `:q`.
- CLI output includes traceable tool calls and the report body.
- `./scripts/check.sh` passes.
- Server smoke verifies CLI can call `http://127.0.0.1:3334` with server `.env` credentials.

## Verification

```bash
uv run pytest tests/test_cli.py -q
./scripts/check.sh
```

Server smoke:

```bash
cd /opt/hypertrade
set -a && . /opt/hypertrade/.env && set +a
HYPERTRADE_API_URL=http://127.0.0.1:3334 \
HYPERTRADE_USERNAME="$ADMIN_USERNAME" \
HYPERTRADE_PASSWORD="$ADMIN_PASSWORD" \
uv run hypertrade ask "请做行情归纳"
```

## Handoff

After this, Sprint 05 should make the Agent workflow itself more autonomous: planning, strategy research tool calls, backtest tool calls, review, memory write, and trace inspection from CLI and `/harness`.
