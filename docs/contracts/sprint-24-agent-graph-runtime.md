# Sprint 24 Contract: Agent Graph Runtime

## Goal

Upgrade the Agent runtime from a mostly linear planner/executor flow into an observable graph path while preserving the public `AgentKernel` interface.

## Scope

- Add graph nodes: `intent_classify`, `plan_tools`, `approval_check`, `execute_tool`, `reflect`, `final_report`.
- Persist graph state in `agent_runs.run_state_json`.
- Emit graph trace events and streaming progress events.
- Keep deterministic fallback when no chat provider key is configured.
- Keep business tool traces visible for existing market, RAG, memory, strategy, backtest, and live intent paths.

## Acceptance

- Free-form chat completes through graph path.
- Trace includes graph node events and business tool events.
- API and CLI return `run_state_json.current_node`.
- Existing agent, market, strategy, backtest, and live order tests pass.

## Verification

```bash
uv run pytest tests/test_agent_market_summary.py tests/test_agent_acceptance.py -q
./scripts/check.sh
```

