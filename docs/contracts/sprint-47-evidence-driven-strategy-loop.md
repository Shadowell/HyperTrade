# Sprint 47 Contract: Evidence-Driven Strategy Loop

## Goal

Make strategy research iterative: before proposing or running a new strategy
experiment, the Agent should inspect strategy-library evidence, identify prior
success/failure patterns, propose adjacent variants, run bounded backtests, and
write a source-backed next-experiment summary.

## In Scope

- Add a strategy-loop planner service that consumes `StrategyLibraryService`
  output and produces an experiment plan.
- Generate bounded candidate variants from prior evidence and explicit user
  prompt constraints.
- Run local backtests or BitPro MCP backtests only through existing safe tools.
- Compare new results against prior evidence.
- Write structured strategy evidence and a concise report with:
  prior evidence used, variant plan, results, failure reasons, and next action.
- Add Agent planner guidance to call `strategy_library_search` before strategy
  iteration prompts.

## Out of Scope

- Large parameter sweeps or optimizer infrastructure.
- Direct BitPro DB access.
- Unattended paper or live promotion.
- New frontend UI beyond existing report display.

## Deliverables

- Strategy iteration service or workflow module.
- Agent tool schema for `strategy_experiment_plan` or equivalent.
- CLI/API entrypoint such as `/experiment iterate <prompt>` or an extension of
  `/experiment`.
- Tests for prior-evidence retrieval, variant planning, result comparison, and
  missing evidence behavior.
- Docs in `docs/knowledge/strategy-research-playbook.md`.

## Design Notes

- If no prior evidence exists, the workflow should clearly say it is creating a
  first baseline.
- If prior failures exist, they should constrain new variants.
- Variant count should be bounded by configuration, with deterministic defaults
  for tests.
- Every generated variant should include the reason it exists.

## Done Means

- A prompt like `继续优化 momentum_breakout_v1` first reads strategy-library
  evidence.
- The report names source memory ids and prior experiment/backtest ids.
- The new experiment writes evidence that appears in `/strategy library`.
- The workflow refuses to claim improvement if metrics are missing or worse.

## Verification

```bash
uv run pytest tests/test_strategy_library.py tests/test_strategy_backtest_api.py -q
uv run pytest tests/test_agent_planner.py tests/test_agent_acceptance.py -q
./scripts/check.sh
```

Manual or QA checks:

- Seed one passed and one failed strategy evidence card.
- Run the iteration prompt and confirm the planned variants are explained from
  that evidence.

## Risks / Notes

- The Agent must not optimize from one tiny sample as if it were robust.
- Reports should distinguish local sample backtests from BitPro-owned backtests.

## Handoff

- Next likely step: Sprint 51 can monitor strategies that passed paper gates.

