# Sprint 78 - CLI Market Answer Quality

## Goal

Make a generic market question produce a concise, readable, evidence-backed
answer in the production terminal. Operational WorldState and governance detail
must support the answer, not replace it.

## In Scope

- Register `global_market_snapshot` against its read-only registry policy so a
  planner-selected global market read is not denied as an unknown tool.
- Strengthen planner guidance: generic market heat/current-market prompts use
  `market_summary`; WorldState and cross-asset global-market tools are reserved
  for their explicit operator or macro scopes.
- Prefer an Agent's final user-facing Markdown answer over verbose WorldState
  report blocks in default CLI output. Keep structured blocks available in
  explicit tool/audit modes.
- Ensure the production host wrapper enables Rich rendering for an interactive
  terminal unless the operator explicitly chooses another renderer.
- Add focused tests for global-market policy mapping, generic-market planner
  guidance, final-answer precedence, and interactive wrapper behavior.

## Out of Scope

- Changes to live-trading permissions, portfolio allocation, or tool payload
  storage.
- Hiding trace/WorldState evidence in `HYPERTRADE_TRACE` or audit modes.
- Full terminal TUI work, charts, or token-by-token model streaming.

## Done Means

- A generic prompt such as `现在市场是什么情况` produces a market conclusion
  before optional evidence, not a raw WorldState dump.
- `global_market_snapshot` has a known read-only policy and is not denied for a
  missing runtime mapping.
- Interactive production `hypertrade` uses Rich tables/Markdown by default;
  `HYPERTRADE_RENDERER=plain` remains respected for scripts.
- Focused tests and `./scripts/check.sh` pass.

## Verification

```bash
uv run pytest tests/test_cli.py tests/test_agent_planner.py \
  tests/test_report_blocks.py tests/test_tool_registry.py -q
./scripts/check.sh
```

Production smoke:

```bash
hypertrade ask "现在市场是什么情况"
```

Confirm the final conclusion is visible first, market metrics render as a
table/panel, no tool denial is reported, and audit detail is absent unless
explicitly requested.

## Handoff

- A future TUI sprint can add collapsible WorldState and tool-detail panes on
  top of this concise-answer/default-audit-detail separation.

## Completion Evidence

- Focused CLI, planner, registry, governance, WorldState, and wrapper tests
  passed (`114 passed`), with shell syntax validation for the host wrapper.
- `./scripts/check.sh` passed with frontend lint/test/build, Ruff, Mypy, and
  `pytest` (`305 passed`).
- Production deployment and generic-market CLI smoke are pending.
