# Sprint 77 - CLI Flight Recorder

## Goal

Make the HyperTrade terminal CLI a professional operator surface: a completed
run must remain concise by default, while an explicit audit view exposes the
same provider, Token, latency, tool, Memory, and trace evidence already
available in the Flight Recorder API and web console.

## In Scope

- Route `HYPERTRADE_RENDERER=enhanced` through the production Rich run
  renderer (`report_markdown`, `report_json`, `run_state_json`, and
  `trace_events`) so it never drops a standard Agent answer because it expects
  demo-only fields.
- Extend `HYPERTRADE_TRACE=summary|full` with a redacted terminal Flight
  Recorder that shows run status, provider/model, duration, reported Token
  ledger, model-call count, tool aggregate, Memory read/write totals, and a
  folded or full trace.
- Add `/run <run_id>` so an operator can open a historical local or remote run
  from the `/runs` list and render it through the same formatter.
- Preserve compact default output, Rich/plain renderer behavior, remote/local
  parity, script-friendly non-TTY output, and existing report-source switches.
- Add focused CLI tests for reported/unreported usage, Memory/trace redaction,
  enhanced standard-run output, and local/remote historical-run retrieval.

## Out of Scope

- A full-screen TUI, mouse navigation, charts, or live token streaming.
- Persisting or showing prompts, credentials, raw tool payloads, or private
  model reasoning.
- Changes to Agent planning, tool selection, provider credentials, database
  schema, web UI, or live-trading permissions.

## Done Means

- `HYPERTRADE_RENDERER=enhanced` renders a standard completed run and its
  Markdown answer instead of an empty demo-only result section.
- `HYPERTRADE_TRACE=summary` prints one concise Flight Recorder summary with
  exact provider-reported usage when available and `unavailable` otherwise.
- `HYPERTRADE_TRACE=full` adds an ordered graph/model/tool/Memory trace without
  exposing prompts, secrets, or private reasoning.
- `/run run_*` loads and renders the same persisted run in local and remote
  mode; a missing argument returns actionable usage text.
- Focused CLI tests and `./scripts/check.sh` pass.

## Verification

```bash
uv run pytest tests/test_cli.py -q
./scripts/check.sh
```

Manual smoke:

```bash
HYPERTRADE_TRACE=summary uv run ht --remote http://47.79.36.92:3333 ask "检查 Agent 可观测链路"
HYPERTRADE_TRACE=full uv run ht --remote http://47.79.36.92:3333
# then: /run <a run id from /runs>
```

## Handoff

- A later terminal UX sprint can introduce a full-screen TUI with keyboard
  navigation and live event lanes, using this redacted run projection as its
  stable data contract.
- Cost estimates, external telemetry export, and pricing dashboards remain
  separate observability work because providers do not consistently report
  cost.

## Completion Evidence

- Focused CLI regression suite passed with `72 passed`.
- `./scripts/check.sh` passed with frontend lint/test/build, Ruff, Mypy, and
  `pytest` (`298 passed`).
- Deployment run `29066526591` succeeded for SHA `fedfe22`.
- Production CLI smoke run `run_7ad26af4667d41559afc` completed through
  DeepSeek with 30,408 reported Tokens over two model calls. Its
  `HYPERTRADE_TRACE=summary` ledger and `/run <run_id>` full trace replay both
  showed the same redacted runtime, Token, tool, and Memory evidence.
