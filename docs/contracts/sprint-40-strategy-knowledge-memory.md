# Sprint 40 Contract: Strategy Knowledge Memory

## Goal

Turn completed strategy experiments into audited, searchable strategy knowledge so future Agent research can reuse prior evidence instead of treating every prompt as a blank slate.

## In Scope

- Write one compact `strategy_knowledge` memory item after each completed local strategy experiment.
- Include source experiment/research/backtest ids, winning variant, parameters, return, drawdown, trade count, evidence gates, data selection, and next-experiment suggestion.
- Tag the memory item for strategy, experiment, evidence, strategy key, and winning variant searches.
- Keep the storage path inside the existing audited Memory service and API.
- Add API-level tests proving the knowledge item is persisted and searchable through `/api/memory`.
- Update strategy workflow, memory, spec, and progress docs.

## Out Of Scope

- New database tables for a full strategy library.
- LLM-generated summaries.
- BitPro business-logic copies or direct BitPro database reads.
- Automatic BitPro paper/live promotion from local experiment memory.
- Frontend redesign for a dedicated strategy library page.

## Done Means

- `POST /api/strategy/experiments` persists the normal experiment plus one searchable `strategy_knowledge` memory item.
- Operators can query strategy experience through the existing Memory API/CLI/search surfaces.
- The knowledge item is source-bound and does not hide evidence gaps or research-only boundaries.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_strategy_backtest_api.py::test_strategy_experiment_workflow_api -q
./scripts/check.sh
```
