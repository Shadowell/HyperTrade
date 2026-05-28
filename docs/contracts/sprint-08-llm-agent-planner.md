# Sprint 08 Contract: LLM-Driven Agent Planner

## Goal

Replace the hardcoded tool-call sequence in `AgentKernel` with a real LLM-planned multi-turn
tool-calling loop using the DeepSeek OpenAI-compatible API.

## Motivation

Sprint 01–07 established all the scaffolding but the agent never calls an LLM — tool selection is
hardcoded. This sprint wires up DeepSeek function-calling so the agent truly "thinks" before
executing tools.

## In Scope

- `providers/deepseek.py`: thin `DeepSeekClient` wrapper over the `openai` SDK.
- `agent/planner.py`: `AgentPlanner` class with a multi-turn function-calling loop (max 8 turns).
  - Tool schemas for: `market.summary`, `rag.search`, `memory.write`, `memory.search`,
    `strategy.draft`, `backtest.run`.
- `agent/kernel.py`: updated `AgentKernel.run_chat()` uses the planner when `DEEPSEEK_API_KEY` is
  set, falls back to the existing hardcoded sequence otherwise.
- `tests/test_agent_planner.py`: unit tests with a mocked LLM client.
- Progress and spec updates.

## Out of Scope

- Streaming output to the CLI.
- `live.order_intent` and `paper.session` tool execution (approval-gated, excluded from planner).
- Model-switching at runtime.
- Token budget enforcement.

## Done Means

- `AgentPlanner.run()` passes a multi-turn mock LLM test.
- `AgentKernel.run_chat()` calls the planner when an API key is present.
- `./scripts/check.sh` passes.

## Verification

```bash
uv run pytest tests/test_agent_planner.py -q
./scripts/check.sh
```

## Handoff

Next sprint: streaming output or testnet order execution workflow.
