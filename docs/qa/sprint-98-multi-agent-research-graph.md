# Sprint 98 Multi-Agent Research Graph QA

## Verdict

Final verdict: **PASS**. Local contract, full repository gates, deployment, public
topology, authenticated Task creation/control, worker dispatch, role-policy denial,
schema fail-closed behavior, and production Evidence V2 projections were checked.

## Scope Checked

- Fixed 13-role topology, required/optional selection, prompt/catalog hashes, and
  bounded LangGraph branch concurrency.
- Role/operator/ToolRegistry policy intersection, secret-argument rejection, and
  zero dispatch for paper/live or unknown tools.
- Atomic provider/tool budget reservations, calibrated per-role token limits,
  provider/read/BitPro semaphores, and no evidence persistence after usage failure.
- Strict role planning/output schemas, one repair, explicit data-gap fallback,
  source/evidence ownership validation, and StrategySpec validation.
- Durable node attempts/checkpoints/events, pause/cancel/retry safe points,
  completed-node replay, worker dispatch, API projection, and CLI queries.
- Idempotent StrategySpec handoff to the existing ResearchProgram/ResearchOrchestrator
  queue without a role-level BitPro mutation capability.

## Evidence

- Focused Sprint 98/Task/CLI/worker tests passed (`97 passed`) before production
  feedback; added production regressions then passed in their focused suites.
- Final `./scripts/check.sh`: frontend lint, 8 frontend tests, TypeScript/Vite build,
  Ruff, mypy over 125 source files, and `378 passed` Python tests.
- Implementation commit `1a78a2a` deployed in workflow `29343469600`.
- Production-derived fixes deployed in workflows `29344164485`, `29344632886`,
  `29345133897`, `29345747196`, and `29346380441` for tool-plan, schema,
  retry-projection, semantic-evidence, and globally bounded budget calibration.
- Public production topology reported `research_graph_topology.v1`, 13 roles,
  `fixed=true`, and `dynamic_agents_allowed=false`.
- Production Task `task_264b280a368e444ab77e` proved worker claim, pre-dispatch
  unknown-tool denial, one read-tool dispatch, structured schema failure/data gaps,
  retry error clearing, and safe-point cancellation while retaining prior attempts.
- Task `task_493c0570b4744b859ae2` completed 10 business roles and proved completed-node
  replay before exposing a too-tight validation-role budget; the final calibration
  was deployed without reusing its older catalog hash.
- Final clean-catalog production Task `task_337586947e7348a39523` is the acceptance
  run: catalog hash matched, 13/13 nodes completed, zero nodes failed, final
  checkpoint listed all roles, and production health remained OK.
- The final run emitted 21 Evidence V2 data gaps under the deliberately narrowed
  operator allowlist. It used 72,533 tokens, 29 model calls, zero tool calls, and
  zero backtests; 103 Task events contained zero tool-policy denials because no
  unapproved dispatch was attempted.

## Findings Resolved During QA

- The tool-plan example contained the literal placeholder `allowed.tool`; DeepSeek
  selected it and policy correctly denied it before dispatch. The prompt contract now
  exposes exact allowed names and an empty-call template.
- A second invalid evidence response terminated the graph. It now becomes a bounded,
  zero-confidence data gap after exactly one repair; invalid raw text is not persisted.
- Retry retained a stale live error projection. Retry now clears the projection while
  immutable Task events retain failure history.
- Initial token budgets were below observed DeepSeek V4 Flash structured-output usage.
  Role limits were calibrated under the unchanged 300k global cap, and usage checks now
  happen before evidence writes.

## Known Boundaries

- Production acceptance validates orchestration, safety, recovery, and evidence
  behavior; it does not validate profitability or authorize paper/live trading.
- Role-catalog changes intentionally require a new acceptance Task rather than silently
  treating an old configuration as reproducible. Sprint 99 will make this invariant an
  immutable experiment fingerprint.

## Production Acceptance Result

```text
task_id: task_337586947e7348a39523
status: completed
catalog_match: true
node_attempts: 13
completed_nodes: 13
failed_nodes: 0
evidence_v2: 21 data_gap
usage: 72,533 tokens / 29 model calls / 0 tool calls / 0 backtests
events: 103
final_checkpoint: risk_committee + all 13 completed role keys
```

This result is intentionally an orchestration and safety acceptance, not a strategy
performance result. The narrow allowlist forced unknowns to remain visible instead of
letting the model infer unsupported market or validation claims.

## Next

Activate Sprint 99 and bind graph-produced StrategySpec, provider/prompt/tool/catalog
versions, BitPro refs, costs, windows, and Evidence V2 IDs into immutable experiment
manifests and execution records.
