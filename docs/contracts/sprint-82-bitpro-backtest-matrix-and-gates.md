# Sprint 82 - BitPro Backtest Matrix and Validation Gates

## Goal

Turn one Sprint 81 research job into an evidence-bound BitPro research run. The worker verifies real data coverage, validates a dynamic `BaseStrategy`, runs a bounded chronological backtest matrix, and writes a deterministic validation report. Passing this sprint never starts a simulation.

## In Scope

- Add a `ResearchOrchestrator` worker path that consumes one queued `ResearchJob` and records resumable stage transitions.
- Preflight BitPro through `bitpro_capabilities` and `bitpro_health`; return a structured data gap or upstream failure when unavailable.
- Confirm market coverage with BitPro MCP before generation. If coverage is inadequate, use approved sync diagnostics or reject/shorten the window; never synthesize OHLCV.
- Turn a validated `StrategySpec` into one dynamic DB strategy only through `strategy_validate_code` and `strategy_create` / `strategy_update`.
- Require a single `BaseStrategy` subclass, canonical naming, DB script metadata, and idempotency keys for every external write.
- Run a mandate-bounded baseline plus limited adjacent variants over fixed chronological in-sample, validation, and locked out-of-sample windows using `backtest_start_job`, `backtest_get_job`, and `backtest_get_result`.
- Add a deterministic `ValidationGate` that evaluates declared data completeness, trade count, cost-aware metrics, drawdown, and locked sample availability. Missing metrics fail closed.
- Persist `ExperimentEvidence` with BitPro strategy/job/result ids, data windows, parameters, metrics, gate outcomes, and rejection reasons; write compatible strategy-library evidence.
- Expose a read-only API/CLI report for job outcome and source references.

## Out of Scope

- Large unconstrained sweeps, Bayesian optimizers, or parameter searches beyond the mandate variant cap.
- Paper configuration/start, strategy pause/stop, portfolio allocation changes, or any live action.
- Direct BitPro database access, strategy-file writes, registry changes, or BitPro restart.
- Claiming stable profitability from a passing validation report.

## Deliverables

- `ResearchOrchestrator`, matrix planner, and validation-gate services.
- Persisted experiment-evidence schema and migration additions needed beyond existing strategy memory.
- BitPro MCP adapter integration using only existing lifecycle contracts.
- API/CLI report and Trace links to BitPro job/result ids.
- Focused unit, adapter, worker, policy, API/CLI, and Agent eval coverage.
- Architecture/playbook updates describing fixed temporal windows and failure behavior.

## Done Means

- A valid queued job completes the preflight → code validation → bounded BitPro backtest matrix → validation-report sequence.
- A candidate without real data coverage, code validation, a completed BitPro result, or locked-sample metrics is rejected with a persisted reason.
- The winning candidate is selected only from reported BitPro evidence and remains `evidence_recorded`; it cannot enter simulation.
- BitPro receives only dynamic DB strategy writes with idempotency keys; no direct database or file mutation occurs.
- Reports distinguish sample windows, result ids, unavailable artifacts, and local research notes.

## Verification

```bash
uv run pytest tests/test_research_orchestrator.py tests/test_validation_gate.py -q
uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_strategy_library.py -q
uv run pytest tests/test_agent_planner.py tests/test_agent_acceptance.py tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

Manual or QA checks:

- Run one fixture-backed job with a passing baseline and inspect all saved BitPro/result references.
- Remove one out-of-sample metric and confirm the candidate is rejected rather than described as improved.
- Simulate an unavailable BitPro health or K-line response and confirm the job reaches a structured failure state without a strategy write.

## Risks / Notes

- The matrix budget must remain small and explicit. A high number of tried variants is evidence the report must preserve, not an implementation detail to hide.
- HyperTrade may retain bounded evidence summaries, but BitPro remains source of truth for market data, strategy code, and backtest artifacts.
- Validation is a research gate, not an investment recommendation or a paper-promotion decision.

## Handoff

Sprint 83 accepts only `evidence_recorded` candidates whose validation report passed every required gate and adds an explicit human-approved paper lifecycle.
