# Sprint 67 LLM Planner Routing

## Sprint Name

`llm-planner-routing`

## Goal

Make free-form Agent prompts use the configured chat provider and `AgentPlanner`
as the semantic source of truth for intent and tool choice. HyperTrade should
execute, audit, and govern tool calls, but it should not map natural-language
business questions to tools through keyword branches or hidden market fallbacks.

## In Scope

- Route free-form natural-language Agent runs through the configured LLM
  planner whenever a chat provider is available.
- Return a clear provider-unavailable result when no chat provider is
  configured, without guessing a market, BitPro, RAG, or Memory tool path.
- Keep explicit CLI slash commands, API tool listing, and risk-governance
  enforcement deterministic because they are not natural-language intent
  recognition.
- Update tests and documentation to describe the planner-owned routing
  contract.

## Out of Scope

- Mainnet live order execution.
- Replacing the provider runtime or adding a new model provider.
- Rewriting every tool implementation or report renderer.
- Copying BitPro business logic into HyperTrade.

## Deliverables

- Agent kernel routing change for free-form prompts.
- Regression tests that fail if natural-language prompts take keyword tool
  shortcuts or silently fall back to market summary without a provider.
- Spec/progress updates that record the new routing boundary.

## Done Means

- With a provider, free-form prompts reach `AgentPlanner` for tool selection,
  including live order, live strategy, and market heat prompts.
- Without a provider, free-form prompts produce an auditable
  provider-unavailable report and no business tool calls.
- Tool approval, idempotency, and safety gates still run after planner tool
  selection.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_agent_market_summary.py tests/test_agent_acceptance.py -q
uv run pytest tests/test_agent_eval_suite.py tests/test_api.py -q
./scripts/check.sh
```

Manual or QA checks:

- Ask a provider-backed Agent prompt and confirm the trace records the provider
  planner instead of a deterministic natural-language router.
- Ask the same prompt with no provider configured and confirm no market or
  BitPro tool is guessed.

## Risks / Notes

- Existing deterministic natural-language market fallback tests need to become
  planner-backed tests or provider-unavailable boundary tests.
- Sprint 67 removes the natural-language market fallback from
  `run_chat_with_events`; future explicit shortcuts must stay outside free-form
  Agent intent recognition.

## Handoff

- Sprint 68 promotes the recent live BitPro misrouting regressions into
  deterministic `/evals` guardrails, so production operators can see if live
  order or live strategy prompts regress back to market summaries.
