# Sprint 46 Contract: Strategy Evidence Schema

## Goal

Replace fragile semi-structured strategy-memory parsing with a stable
`StrategyEvidence` JSON schema while keeping existing `strategy_knowledge`
Memory cards readable and backward compatible.

## In Scope

- Define a versioned `StrategyEvidence` schema for local and BitPro-backed
  strategy evidence.
- Store structured evidence in Memory metadata or content payload without
  breaking existing `MemoryService` dedupe/search behavior.
- Update `StrategyExperimentService` to write schema-backed evidence.
- Update `StrategyLibraryService` to prefer structured payloads and fall back to
  legacy text parsing.
- Include gate results, failure reasons, source data, metrics, variant count,
  source ids, and next experiment in the schema.
- Add tests for new cards, old cards, mixed libraries, and missing fields.

## Out of Scope

- New optimization algorithms.
- Automatic paper or live promotion.
- Direct BitPro database reads.
- Frontend strategy-library UI expansion.

## Deliverables

- `StrategyEvidence` model/helper module.
- Schema version documented in architecture docs.
- Updated memory writer and strategy-library parser.
- Tests for backward compatibility and source id preservation.
- Docs in `docs/architecture/06-memory.md` and
  `docs/architecture/16-strategy-agent-workflow.md`.

## Design Notes

Recommended top-level fields:

- `schema_version`
- `strategy_key`
- `experiment_id`
- `research_id`
- `backtest_id`
- `bitpro_result_id`
- `variant_id`
- `variant_count`
- `parameters`
- `metrics`
- `gate_results`
- `failure_reasons`
- `source_data`
- `next_experiment`
- `boundaries`

The schema should use strings for decimal metrics when preserving exact values
from database or BitPro responses.

## Done Means

- New `/experiment` runs create structured `strategy_knowledge` evidence.
- `/api/strategy/library` returns the same public shape as Sprint 44 but reads
  the structured payload first.
- Legacy text cards still appear in the strategy library.
- Missing fields become `n/a` or empty lists, never invented values.

## Verification

```bash
uv run pytest tests/test_strategy_library.py tests/test_strategy_backtest_api.py -q
uv run pytest tests/test_cli.py tests/test_agent_planner.py -q
./scripts/check.sh
```

Manual or QA checks:

- Create one new `/experiment` and inspect `/api/memory?kind=strategy_knowledge`.
- Confirm `/strategy library momentum_breakout_v1` shows source memory ids and
  best/latest evidence.

## Risks / Notes

- Keep exact backward compatibility for older memory cards; production may
  already contain legacy evidence.

## Handoff

- Next likely step: Sprint 47 can use structured evidence to plan next
  experiments.

