# Sprint 100 Robustness Validation QA

## Verdict

PASS. Deterministic planning, bounded BitPro execution, fail-closed gates, persistence,
paper-promotion integration, deployment and a real rejected production candidate passed.

## Scope Checked

- Locked OOS freeze, non-overlapping walk-forward and budget reservation.
- Parameter-neighborhood, cost/slippage and optional regime scenarios.
- Missing metrics/results, terminal BitPro failures and deterministic replay.
- Validation API/CLI/StrategyCard projections and paper-promotion hard gate.
- BitPro Streamable HTTP lifecycle, schema and runtime BaseStrategy compatibility.

## Evidence

- Migration 0015 passed upgrade/downgrade/upgrade in isolation.
- Final `./scripts/check.sh`: frontend lint, 8 frontend tests, TypeScript/Vite build,
  Ruff, mypy over 129 source files, and 403 Python tests.
- BitPro PRs `#570` and `#571` deployed in workflows `29351668545` and `29353194135`;
  production generated-code smoke returned `valid=true, smoke=true`.
- HyperTrade commits `bf627d4`, `119bd24`, and `f7b1bea`; final deployment workflow
  `29353572908` succeeded.
- Production ResearchJob `rjob_5dcc95b103394cffb130`, strategy `309`, experiment
  `exex_c64e1699533c48b0a0b3`, and validation `rvld_5f43ed2c628847ada2a5` completed.
  Usage was 13 backtests and 219 audited tool calls, with 3 evidence rows, 7 scenarios
  and 16 artifact refs. Data integrity passed; locked OOS, walk-forward, parameter
  sensitivity and cost stress failed, so the candidate was correctly rejected.

## Incidents Found And Fixed

- HyperTrade previously treated BitPro's validator as local-only; it now uses official
  MCP Streamable HTTP transport.
- BitPro's mounted MCP app omitted its session-manager lifespan; PR `#570` composes it
  into the parent FastAPI lifespan and tests a real JSON-RPC initialize request.
- The validator schema accepts `code`, and runtime safety requires `smoke=true`; the
  adapter now sends exact symbol/market/timeframe context.
- The historical generated class used an incompatible constructor and nonexistent
  history/position APIs. It was replaced by the native async BaseStrategy contract.
- BitPro's smoke helper nested `asyncio.run()` inside FastMCP's event loop; PR `#571`
  added an awaitable entrypoint while preserving the synchronous client interface.

## Boundaries

- Rejection is a successful research outcome, not a profitability failure of the system.
- BitPro remains the raw data/backtest source of truth; HyperTrade stores bounded refs.
- No automatic paper/live action, capital allocation, unbounded search or profit claim.

## Next

Activate Sprint 101 Agent Research Evaluation.
