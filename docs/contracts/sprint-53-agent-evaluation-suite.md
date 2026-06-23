# Sprint 53 Contract: Agent Evaluation Suite

## Goal

Strengthen automated evaluation so HyperTrade catches hallucinated trading
claims, wrong source-of-truth usage, missing tool calls, and noisy report
regressions before deployment.

## In Scope

- Add eval cases for:
  - strategy-library/history prompts
  - BitPro page-parity result prompts
  - missing artifact prompts
  - paper monitor prompts
  - multi-source market intelligence prompts when Sprint 48 lands
  - compact/default report rendering
- Add assertions for required tool calls and forbidden unsupported claims.
- Add fixture helpers for tool outputs and memory evidence.
- Expose eval status in existing `/evals` surface.
- Document how parallel Agents add evals for new tools.

## Out of Scope

- Paid model evaluation service.
- Human preference ranking.
- Benchmarking trading profitability.
- Full LLM fine-tuning.

## Deliverables

- Expanded deterministic eval suite.
- New tests under existing eval/acceptance structure.
- Report-quality guardrail helpers.
- Updated `docs/testing/agent-acceptance-test-plan.md` and
  `docs/testing/agent-eval-suite.md`.

## Design Notes

Each eval case should define:

- prompt
- required tools
- forbidden tools
- required report fragments
- forbidden report fragments
- source ids expected
- missing-data expectations

The eval should check behavior, not exact prose.

## Done Means

- Eval suite fails if an Agent answers strategy-history prompts without
  `strategy_library_search`.
- Eval suite fails if BitPro result-ranking prompts use memory or descriptions
  instead of BitPro result tools.
- Eval suite fails if missing data disappears from reports.

## Verification

```bash
uv run pytest tests/test_agent_acceptance.py -q
uv run pytest tests/test_agent_eval_suite.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run `/evals` locally and through the production wrapper after deployment.
- Confirm new cases are visible in the eval status payload.

## Risks / Notes

- Avoid brittle string snapshots. Prefer stable tool/report invariants.

## Handoff

- Next likely step: every future sprint should add or update at least one eval
  case for its new Agent-visible behavior.

