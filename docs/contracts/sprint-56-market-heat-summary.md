# Sprint 56 Contract: Market Heat Summary

## Sprint Name

`market-heat-summary`

## Goal

Make broad market heat prompts such as `看下目前市场的热度怎么样` return an
operator-readable conclusion instead of only raw ticker tables.

## In Scope

- Route all-market heat/sentiment/breadth prompts to `market_summary`.
- Add deterministic market breadth metrics to `market_summary` payloads.
- Render a market heat conclusion in Markdown, plain CLI, and Rich CLI output.
- Keep detailed ticker/candle tables available through `HYPERTRADE_REPORT_SOURCE=tools`.
- Add regression tests for API, Agent acceptance, and CLI rendering.

## Out of Scope

- External social/news sentiment feeds.
- Multi-source funding/open-interest intelligence beyond the existing roadmap.
- Strategy recommendations or trading advice.

## Deliverables

- `heat_summary` in market summary tool output.
- `## 市场热度总结` in Agent final reports for all-market heat prompts.
- CLI final-summary-first behavior for market detail tool runs.
- Updated README/spec/progress/architecture docs.

## Done Means

- `看下目前市场的热度怎么样` produces a summary with conclusion, sample count,
  advancer/decliner breadth, average change, strongest and weakest symbols.
- The prompt does not degrade into only BTC/ETH/SOL ticker tables.
- Operators can still force raw tool tables with `HYPERTRADE_REPORT_SOURCE=tools`.

## Verification

```bash
uv run pytest tests/test_api.py::test_api_market_heat_prompt_returns_summary \
  tests/test_agent_acceptance.py::test_agent_acceptance_market_heat_uses_summary_not_ticker \
  tests/test_cli.py::test_render_run_prefers_final_market_summary_over_detail_tables \
  tests/test_cli.py::test_render_run_can_force_structured_market_tool_outputs -q
./scripts/check.sh
```

Manual or QA checks:

- Run `hypertrade ask "看下目前市场的热度怎么样"` and confirm the output starts with
  a market heat summary rather than standalone ticker tables.

## Risks / Notes

- Heat is derived from OKX SWAP ticker breadth, not external sentiment.
- When OKX REST is temporarily unavailable, existing DB ticker snapshots are used
  as `db_fallback` if present; otherwise the report states that heat is unavailable.

## Handoff

- Next likely step: combine this breadth summary with the Sprint 48
  multi-source market intelligence layer once that branch is ready to merge.
