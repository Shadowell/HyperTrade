# Sprint 44 Contract: Strategy Library Memory

## Goal

Upgrade strategy memory from individual `strategy_knowledge` cards into a durable strategy-library view that operators and the Agent can search before proposing the next experiment.

## In Scope

- Aggregate existing audited Memory items of kind `strategy_knowledge` into strategy-level library summaries.
- Keep Memory as the source of truth; do not introduce a separate strategy-library table.
- Enrich newly written strategy knowledge cards with gate results, failure reasons, and variant counts.
- Expose strategy-library search through API, CLI, ToolRegistry, Agent planner, and Agent reports.
- Update docs, tests, and progress.

## Out of Scope

- Direct BitPro database access or copying BitPro strategy logic.
- Auto-promoting library entries to paper, Testnet, or live trading.
- Scheduled curation jobs, notifications, or external publishing.
- Large optimization sweeps or parameter search infrastructure.

## Deliverables

- `StrategyLibraryService` that parses `strategy_knowledge` memory cards and returns grouped strategy evidence.
- `GET /api/strategy/library` endpoint with `query`, `strategy_key`, and `limit`.
- CLI `/strategy library [query]` rendering.
- Agent planner tool `strategy_library_search` and ToolRegistry entry `strategy.library_search`.
- Planner report section for strategy-library evidence.
- Updated memory card format for future experiments.

## Done Means

- Strategy library summaries include evidence counts, pass/fail counts, best evidence, latest evidence, variant summaries, failure reasons, next experiments, and source memory ids.
- Queries never synthesize missing metrics; absent fields are reported as `n/a` or empty lists.
- The Agent can answer strategy-library/history questions from `strategy_library_search` instead of free-form memory guesses.
- Existing `strategy_knowledge` Memory search remains compatible.

## Verification

```bash
uv run pytest tests/test_strategy_library.py tests/test_strategy_backtest_api.py tests/test_agent_planner.py tests/test_market_candles_tool.py tests/test_cli.py tests/test_tool_registry.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run `/strategy library` in CLI after at least one experiment and confirm it shows source memory ids and next-experiment guidance.
- Run an Agent prompt asking for prior strategy experience and confirm trace includes `strategy_library_search`.

## Risks / Notes

- Existing strategy memory cards are semi-structured text. The parser must be tolerant and treat missing fields as unavailable rather than inventing them.
