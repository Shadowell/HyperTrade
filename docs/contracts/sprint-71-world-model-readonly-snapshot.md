# Sprint 71 - World Model Read-Only Snapshot

## Goal

Implement the first read-only world-model slice for HyperTrade: a global
operator `WorldState` snapshot that aggregates global market sense, crypto
market evidence, strategy evidence, execution state, tool health, deployment
state, source references, missing data, and bounded candidate actions without
executing any trading or lifecycle mutation.

## In Scope

- Define `WorldState` schema v1 for global operator state.
- Add a `world_model` backend module with collectors, evaluators, and service
  orchestration.
- Represent global market sense as cross-asset state, not only crypto market
  state.
- Reuse existing HyperTrade evidence where available:
  - `MarketRepository` and `MarketIntelligenceService`
  - `StrategyLibraryService`
  - `PaperTradingService`
  - `BitProPaperMonitorService` or latest monitor snapshots
  - `ConnectorRegistry`
  - `MonitorService` alerts and monitor definitions
  - recent `AgentRun` and `TraceEvent` rows
  - API/database health checks
- Add read-only API endpoint `GET /api/world-model/snapshot`.
- Add Agent tool schema and ToolRegistry row for `world_model_snapshot`.
- Teach `AgentKernel` to execute `world_model_snapshot` without calling write
  tools.
- Render a compact world-model report section with source references and
  missing-data notes.
- Add deterministic eval coverage requiring `world_model_snapshot` for global
  operator prompts.
- Update docs and progress.

## Out of Scope

- Automatic paper, BitPro, Testnet, or live mutations.
- Offensive actions such as open position, add risk, increase leverage, or
  switch to high-risk strategy parameters.
- Real-time global market data feeds if provider credentials or contracts are
  unavailable. Missing cross-asset sources must be reported as missing data.
- Training a neural world model.
- Replacing existing market, strategy, risk, Memory, RAG, or connector modules.

## Deliverables

- `backend/src/hypertrade/world_model/` with:
  - `schemas.py`
  - `collectors.py`
  - `evaluators.py`
  - `actions.py`
  - `service.py`
- `GET /api/world-model/snapshot` endpoint.
- Agent planner schema, kernel executor branch, and ToolRegistry entry for
  `world_model_snapshot`.
- Report block rendering for world-model summary, candidate actions, missing
  data, and audit references.
- Tests for schema shape, source references, missing-data behavior, API output,
  tool execution, and Agent eval routing.

## Done Means

- A global operator prompt such as `现在全局状态怎么样` calls
  `world_model_snapshot`.
- The snapshot includes at least these sections:
  - `global_market`
  - `crypto_market`
  - `strategy`
  - `execution`
  - `tool_health`
  - `deployment`
  - `missing_data`
  - `candidate_actions`
  - `source_refs`
- `global_market` can report unavailable global cross-asset inputs without
  inventing data from model memory.
- Candidate actions are limited to L0/L1, for example:
  - `observe_more`
  - `run_monitor`
  - `inspect_trace`
  - `request_human_confirmation`
  - `pause_strategy_request`
  - `reduce_risk_request`
- No paper, BitPro lifecycle, Testnet, or live write tool is called by the
  snapshot path.
- Report output explains the current state, key risks, missing data, and next
  review action with source references.

## Verification

```bash
uv run pytest tests/test_world_model_snapshot.py tests/test_agent_planner.py tests/test_agent_eval_suite.py -q
./scripts/check.sh
```

Manual or QA checks:

- Ask the Agent `现在全局状态怎么样` and confirm the trace includes
  `world_model_snapshot`.
- Confirm the report does not substitute `market_summary` for the global
  world-model snapshot.
- Confirm missing global market sources are visible as `missing_data`.

## Risks / Notes

- Global market data providers may need a later connector contract. This sprint
  should expose source gaps instead of blocking the entire snapshot.
- Deployment health should distinguish public-network health failures from
  server-local health, GitHub Actions status, and host-wrapper smoke signals.
- The world model must keep the HyperTrade/BitPro boundary explicit: BitPro is
  accessed only through stable MCP/API contracts.

## Handoff

- Next likely step: Sprint 72 adds action scenario simulation and scoring on top
  of this read-only `WorldState`.
