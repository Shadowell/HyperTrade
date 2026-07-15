# Sprint 106 Agent Research Quality Closure QA

## Verdict

PASS. Fixed-denominator evaluation, bounded planning, two complete isolated provider
baselines, privacy boundaries and production read-only projections satisfy the contract.

## Scope Checked

- 26-case `research_os_golden_v2` cohort and denominator contract;
- structured intent/plan and role/mandate/source/connector/governance candidate intersection;
- one bounded planner repair and fail-closed invalid route/schema behavior;
- source citation, terminal Graph/Task status and six safety denials;
- API, CLI, Textual and Web aggregate-only projections;
- isolated worker/data boundary, artifact privacy and production health.

## Local Evidence

- Focused planner/evaluation/provider regressions passed.
- Full `./scripts/check.sh`: frontend lint, 9 Vitest tests and build; Ruff; mypy over
  142 source files; 489 Python tests.

## Isolated Provider Evidence

- Both runs evaluated all 26 cases with fixed cohorts: chat 2, tool-required 2,
  research-graph 16 and safety 6.
- Both runs passed tool route, required source route, source-bound citation, Graph critical
  sequence, Task terminal status and safety denial at 100%; unsafe dispatch count was zero.
- Run 1 used 141,896 tokens with mean 11.77 seconds and p95 23.05 seconds. Run 2 used
  158,327 tokens with mean 14.87 seconds and p95 46.68 seconds. Cost was not reported.
- The comparison retained two diagnostic Ragas tool-accuracy decreases in Research Graph
  cases. They did not affect the V2 tool-required/source/safety gate and remain visible.
- Artifact scans found no prompt, tool arguments, raw output, report text, credentials or
  private reasoning. The isolated worker count remained zero.

## Findings Fixed During QA

- Authored scenarios and provider route prompts are separate but resolve to one bounded intent.
- Terminal report Graph is captured after `final_report` instead of before it.
- Available OKX candles emit a bounded source citation without candle payload.
- Codex retries one transient 429/5xx/transport failure before tool dispatch, then fails closed.

## Production Evidence

- Commit `43290aa` deployed in workflow `29386037081`; recorded SHA matched.
- API health, deterministic V2 quality/cohort/privacy projection and Web `/harness/quality`
  passed. API, PostgreSQL and Worker were running with zero recent log errors.
- Production research triggers remained disabled and no trading permission changed.

## Not Checked

- Profitability, future market performance and provider dollar cost are intentionally not scored.
- Background research enablement, paper/live execution and capital allocation remain out of scope.

## Next

Activate Sprint 107 for StrategyCard V2 identity, immutable lifecycle projections and the
research funnel. Gate E does not itself enable background research.
