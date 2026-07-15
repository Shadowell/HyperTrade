# Progress Log

## Current Baseline

- Branch: `main`
- Harness status: active
- Sprint 113 implementation state: completed and production-verified on 2026-07-15. Deterministic
  per-step Context Packs retain objective,
  constraints, permission, Plan and Step blocks, apply a hard token ledger, stable tier ordering,
  bounded extractive compaction and explicit stale/budget/duplicate/unsafe drop decisions. The
  Mission Artifact Index adds content-bound dedupe, versions, stable refs, derived-from/supersede
  relations and forged-ref completion refusal. SQL persistence, authenticated APIs and migration
  `0025_agent_context_artifacts` are implemented. Full checks passed 574 Python and 9 frontend tests.
  Workflow `29428834737` deployed SHA `3277d46`; PostgreSQL `0025 -> 0024 -> 0025`, health and
  flag-off checks passed. Production counts remained unchanged and a repeated read-only compiler
  canary produced the same manifest hash. Gate J2 is closed; Sprint 114 is active.
- Sprint 112 implementation state: completed and production-verified on 2026-07-15. A
  reviewed/versioned Capability Catalog, contract/policy hashes,
  pending-only discovery proposals, idempotent administrator reviews, JSON-Schema preflight/output
  validation, deterministic error taxonomy, timeout/circuit handling and bounded/redacted SQL tool
  observations now govern the Mission path. Four built-in read capabilities are active; no discovery,
  paper, live, order or capital permission is auto-enabled. Focused acceptance passed 40 tests. The
  full suite exposed and corrected an unrelated StrategyCard snapshot reconciliation race; the race
  test passed ten consecutive runs. SHA `e364ee9` deployed in workflow `29427572167`; PostgreSQL
  `0024 -> 0023 -> 0024`, health and flag-off checks passed. Production exposed exactly four reviewed
  read capabilities and zero proposals/observations; AgentTask/AgentRun/Mission counts were unchanged.
  Gate J1 is closed and Sprint 113 Context and Artifact Engine is active.
- Sprint 111 implementation state: completed and production-verified on 2026-07-15. A clean `hypertrade.runtime` modular core,
  frozen Mission/Plan/Observation contracts, bounded adaptive loop, optimistic event store,
  async SQLAlchemy adapter, migration `0023_agent_missions`, OpenTelemetry spans and authenticated
  Mission REST/SSE projection are implemented. The foundation runtime is read-only and disabled by
  default; successful observations require provenance and completion is derived from structured
  criteria. New Missions do not write AgentTask/AgentRun. GitNexus mapped the old AgentKernel
  cutover surface, and the shipped technical design records keep/rewrite/delete decisions. Full
  `./scripts/check.sh` passed 547 Python and 9 frontend tests. SHA `6435110` deployed in workflow
  `29425203712`; PostgreSQL `0023 -> 0022 -> 0023`, flag-off health and a direct read-only canary
  passed. AgentTask/AgentRun counts remained 4/153 while only AgentMission changed, proving zero
  legacy dual write. Gate I is closed; Sprint 112 Capability and Tool Runtime V2 is next.
- Sprint 110 implementation state: completed and production-verified on 2026-07-15. Immutable
  Shadow Portfolio proposals bind exact cohort/window/Card/label decision facts, retain a fixed
  denominator and allow only equal-weight, evidence-complete inverse-volatility and capped risk-
  budget proxy templates. Decimal cap normalization, fixed cost/stress assumptions, hypothetical
  impacts and expiring research-only reviews are implemented across API, `/shadow`, Textual and Web.
  PostgreSQL `head -> 0021 -> head` passed; full `./scripts/check.sh` passed frontend lint/9 tests/
  build, Ruff, mypy over 149 source files and 523 Python tests. Commit `a855a8e` deployed through
  workflow `29391103674`. Production proposal `shpf_5bfd4d97d12646d8a303` retained all three Cards
  but correctly returned `needs_data`, 0 eligible and 0 scenarios; replay was idempotent and no
  execution payload keys were persisted. Shadow review and paper lifecycle counts stayed 0, paper
  orders stayed 10 and live intents stayed 1. Gate H and the Sprint 106–110 route are closed.
- Sprint 109 implementation state: completed and production-verified on 2026-07-15. Immutable,
  versioned paper cohorts consume only committed Card/Manifest/Observation facts; exact comparison
  keys, a fixed Card denominator, multi-dimensional gates and expiring human labels prevent return-
  only ranking and lifecycle dispatch. Migration `0021`, API, `/cohorts`, Textual and Web projections
  are implemented. PostgreSQL `head -> 0020 -> head` passed; full `./scripts/check.sh` passed frontend
  lint/9 tests/build, Ruff, mypy over 147 source files and 514 Python tests. Commit `22dbc3c` deployed
  through workflow `29390025815`. Production cohort `pcoh_cbf6b383e7b448d7a36f` retained all three
  Cards but correctly returned `needs_data` with 0 comparable members and 0 proposals; replay was
  idempotent. Paper promotion/review/decision counts stayed 0, paper orders stayed 10 and live
  intents stayed 1. Gate G is closed; Sprint 110 activation is next.
- Sprint 108 implementation state: completed and production-verified on 2026-07-15. The contract
  adds bounded, source-bound PortfolioObservationWindow/DataQuality summaries over BitPro MCP
  read contracts, integrates them into PortfolioAssessment, and exposes shared API/CLI/TUI/Web
  projections. Raw equity/return/position/trade/order series remain BitPro-owned; missing identity,
  unhealthy/stale sources, insufficient alignment and zero variance fail closed. No paper/live/
  order/capital mutation is permitted. Migration `0020`, strict capture/quality schemas, immutable
  summary persistence, Decimal/UTC statistics, source/quality idempotency, PortfolioAssessment
  window references and shared API/CLI/Textual/Web projections are implemented. PostgreSQL full
  chain and `0020 -> 0019 -> 0020` pass. Full `./scripts/check.sh` passes frontend lint/9 tests/build,
  Ruff, mypy over 145 source files and 506 Python tests. Initial production capture correctly
  preserved raw-series/execution boundaries but exposed an overall quality-classification issue;
  snapshot/curve failures are now isolated and curve failure wins as `source_unhealthy` instead of
  `insufficient`. Fix `57b67bd` deployed through workflow `29389087323`; final production capture
  projected 1 available and 2 no-window strategies over a fixed 3-Card denominator, replayed
  idempotently, and persisted no raw-series keys. Assessment consumption, Web route and logs passed;
  PaperPromotion/paper-order/live-intent counts were unchanged. Sprint 109 activation is next.
- Sprint 107 implementation state: completed and production-verified on 2026-07-15. The focused
  contract introduces stable mandate-scoped lineage, Manifest-bound versions, immutable Card
  snapshots, fact-driven lifecycle decisions and a fixed-denominator research funnel. It must
  make Manifest-only candidates visible without inventing Evidence/Paper facts and cannot add
  BitPro, paper, live, order or capital mutation paths. Migration `0019` and the V2 projection
  service are implemented: Experiment registration creates identity/version, reconcile/backfill
  appends content-hashed snapshots, legacy promotion-only cards remain explicitly marked compat,
  and human decisions write a separate idempotent audit fact. API, `/cards` CLI, Textual Portfolio
  and Web strategy metrics share the service projection. PostgreSQL `0018 -> 0019 -> 0018 ->
  0019` passes. Full `./scripts/check.sh` passes with frontend lint/9 tests/build, Ruff, mypy
  over 143 source files and 497 Python tests. Commit `14d686e` deployed through workflow
  `29387796135`; Alembic reached `0019`. Three production Manifests reconciled to one lineage,
  three stable versions and three snapshots; repeated reconcile was idempotent and the V2 Card
  count matched the funnel denominator. PaperPromotion, paper-order and live-order-intent counts
  were unchanged. Gate F is closed; Sprint 108 activation is next.
- Sprint 106 implementation state: completed and production-verified on 2026-07-15.
  `research_os_golden_v2` fixes 26 cases into 2 `chat_answer`, 2 `tool_required`, 16
  `research_graph` and 6 `safety` cases. Structured intent/plan, bounded candidate
  intersection, one repair and fail-closed V2 scoring are implemented. Two isolated provider
  runs completed 26/26 cases and both passed route/source/citation/Graph/Task/safety at 1.0
  with zero unsafe dispatch. Artifacts retained no prompt, arguments, raw output, credentials
  or reasoning; two non-gating Ragas tool-accuracy decreases remain visible as model variability.
  Full `./scripts/check.sh` passed with frontend lint/9 tests/build, Ruff, mypy over 142 source
  files and 489 Python tests. Commit `43290aa` deployed in workflow `29386037081`; production
  SHA, health, quality/Web projections, containers and logs passed. Gate E is closed; Sprint
  107 activation is next. Triggers remain disabled and no paper/live/capital permission changed.
- Sprint 105 implementation state: completed and production-verified on 2026-07-15.
  Persisted `portfolio_assessment.v2` binds idempotency keys to canonical
  requests, consumes bounded StrategyCard/WorldState/paper/monitor/Evidence/governed
  Memory projections, stores correlation summaries rather than return histories and
  preserves unknown for insufficient, misaligned or zero-variance samples. Six fixed
  recommendation types are research/review only; accept/reject/hold writes an immutable
  human review fact and cannot reach BitPro, paper or live mutation adapters. API,
  `/portfolio-v2`, Textual and Web `/harness/portfolio` use the same service. PostgreSQL
  `0018 -> 0017 -> 0018`, focused 23-test backend acceptance, frontend lint/9 tests/build,
  Ruff, mypy over 140 source files and all 473 Python tests pass. Commit `e80cf0d`
  deployed in workflow `29365535535`; recorded SHA, health, Alembic `0018`, 2/2 tables,
  four OpenAPI paths, authenticated list API, Web route and API/worker logs passed.
  Production assessment `pasmt_fbb18fbd79e8499a8c31` found no StrategyCards and therefore
  returned `needs_data`, one explicit unknown and no recommendations instead of fabricating
  evidence; no lifecycle review was written. Gate D and the Sprint 96–105 roadmap are closed.
- Sprint 104 implementation state: completed and production-verified on 2026-07-15.
  Eight `0017_memory_skills` tables, source-bound `MemoryAssertionV1`,
  explicit conflict/supersede/expiry, ordinary-search fail-closed compatibility Memory,
  code-free Skill proposal/static-check/evaluation/approval/release/rollback, immutable
  versions and role-scoped approved loading are implemented. Isolated evaluation
  attestations are HMAC-bound to proposal/suite/baseline/counters/artifact and production
  fails closed when the shared server secret is absent or mismatched; administrator
  approval remains a separate gate. API, `/assertions` and `/skills`, TUI Governance and
  Web Memory review surfaces all delegate to the same server state machine. PostgreSQL
  `0017 -> 0016 -> 0017` migration passed; full `./scripts/check.sh` passed with frontend
  lint/8 tests/build, Ruff, mypy over 138 source files and 464 Python tests. No Skill or
  Assertion was activated in production. Commit `d4d43bb` deployed in workflow
  `29363666735`; SHA/health/log/API/8-table checks passed. The production attestation
  secret remains absent, so forged import returned 409 and releases remain fail closed.
  Sprint 105 Portfolio Strategy Lifecycle subsequently completed production acceptance.
- Sprint 103 implementation state: completed and production-verified on 2026-07-15.
  The bounded slice adds
  disabled-by-default durable research triggers,
  fire audit, lease/cooldown/quota/dedupe/kill-switch enforcement and Task-only
  dispatch. Trigger code may read committed Monitor/World/Paper/Eval facts but cannot
  import or call BitPro, paper, testnet, live or approval adapters. Trigger-created
  Tasks remain visible and controllable through the existing API/TUI contracts.
  Migration `0016`, UTC interval/daily schedules, PostgreSQL lease/skip-locked claims,
  immutable fingerprinted fire decisions, bounded committed-event adapters, API/CLI/TUI
  controls and read-only `triggered_research` dispatch are implemented. Concurrency,
  restart, trigger-storm, quota, cooldown, kill-switch, budget-revalidation, API auth,
  TUI and deployment-boundary tests pass; full `./scripts/check.sh` passes with 449
  Python tests. Commit `afbed93` deployed successfully in workflow `29361442025`;
  PostgreSQL migrated to `0016_research_triggers`, authenticated trigger projection
  returned no rules/fires, worker probe returned `disabled`, and API/worker health
  remained normal. Production remains disabled until explicit operator configuration.
  Sprint 104 Governed Memory and Skill Lifecycle is completed.
- Sprint 102 implementation state: completed and production-verified on 2026-07-15
  after Sprint 101 isolated
  acceptance. The bounded slice adds an optional Textual terminal workbench over
  existing REST/SSE contracts for Sessions, Tasks, graph/timeline, Evidence,
  experiments, validations and approvals. It may request task controls only through
  authenticated API reason/idempotency contracts; it cannot access the database,
  ToolRegistry, BitPro or trading services directly. Existing chat/plain/Web surfaces
  and all paper/live boundaries remain unchanged. Textual `8.2.8` is pinned in the
  optional `tui` extra; UI-independent store/cursor models, remote/local client
  methods, responsive workbench panels, multiline task creation, reason-required
  control modals, cursor SSE reconciliation and a separate short-lived TUI Docker
  target are implemented. Focused TUI/CLI/API/deploy regressions pass (`91 passed`);
  full gate passed with 435 Python tests. Deployment workflow `29359569036`
  succeeded; `hypertrade-tui:latest` contains Textual 8.2.8 while the API image has
  no Textual package. A real production SSH TTY at 80 columns rendered compact mode,
  loaded the production Research Graph/checkpoint/metrics, and exited cleanly.
  Sprint 103 Background Research Triggers is next.
- Sprint 101 implementation state: completed and isolated-production-verified on
  2026-07-15 after Sprint 100 production
  acceptance. The bounded slice adds versioned Research OS golden cases, deterministic
  Task/Graph/Evidence/Experiment/Validation evaluations, property/state-machine tests,
  provider/BitPro/worker/SSE fault injection, privacy-safe trajectory artifacts and
  isolated Promptfoo/Ragas extensions. Provider-backed runs remain isolated; evals
  cannot dispatch write tools, score profitability, promote candidates or allocate
  capital. `research_os_golden_v1` now contains 24 authored cases (4 normal, 4 data
  integrity, 4 recovery, 4 fault, 6 safety, 2 cursor); Hypothesis verifies Task/Node/
  cursor invariants, the required `/evals` gate includes Research OS status, Promptfoo
  has six pinned adversarial checks with zero write dispatch, Ragas scores role/node/tool
  sequence, and Langfuse exports metadata-only node spans. The first server baseline
  attempt exposed an invalid host-`uv` dependency. Evaluation dependencies now live in
  a dedicated `agent-eval` Docker target built by the isolated deploy; the production
  image remains dependency-minimal and the runner executes only in that pinned image.
  Focused tests and full `./scripts/check.sh` pass with 425 Python tests. Promptfoo
  isolated safety acceptance passed 6/6 with zero tool/write dispatch; reproducible
  runner deployment succeeded and two 24-case provider-backed baselines completed.
  They showed zero unsafe dispatches but also exposed weak generic-Agent alignment
  (tool accuracy 0.0833, mean Research OS node sequence 0.0, task-status match
  0.5833). A post-run privacy scan found that the trajectory still retained
  allowlisted `args`, contradicting the declared no-argument boundary; that field is
  now removed entirely. The comparison now detects F1, citation and task-status
  regressions instead of reporting a false stable result. Full `./scripts/check.sh`
  passes with 426 Python tests. The corrected final rerun completed twice with 24/24
  trajectories, no unsafe dispatch, and an argument-free privacy scan. Both runs
  reported tool accuracy 0.0833, node sequence 0 and task-status match 0.5833;
  comparison was `stable_or_improved` with one F1 improvement. Final deployment
  workflow `29357931595` succeeded. Sprint 102 TUI Research Workbench is next.
- Sprint 100 implementation state: completed and production-verified on 2026-07-15.
  The bounded slice adds versioned robustness policies/results, locked OOS
  freeze, non-overlapping walk-forward windows, budgeted parameter neighborhoods,
  cost/slippage and regime stress scenarios, fail-closed data/trade/result gates,
  persisted validation runs, and API/CLI/report projections. It reuses BitPro as the
  backtest/artifact source and the Sprint 99 immutable experiment ledger. Bayesian or
  genetic optimization, unbounded grids, raw-result storage, automatic ranking,
  automatic paper/live promotion and capital decisions remain out of scope.
  The first production run exposed two pre-existing BitPro boundary defects before
  any strategy/backtest write: HyperTrade rejected the MCP-only validator, while the
  BitPro mounted Streamable HTTP app had no running session-manager lifespan. BitPro
  PR `#570` fixed and deployed the authenticated transport in workflow `29351668545`;
  production MCP initialize and a generated-candidate sandbox validation now pass.
  HyperTrade now uses the official MCP Python client for local-only tools, maps the
  validator's real `code` schema, and emits a BitPro-native asynchronous dynamic
  BaseStrategy instead of the historical incompatible constructor/history API.
  Validation is fail-closed with `smoke=true`, exact symbol/market/timeframe context,
  and terminal backtest status diagnostics before downstream evidence handling.
  This exposed BitPro's nested `asyncio.run()` defect; BitPro PR `#571` split sync and
  async validation entrypoints, deployed in workflow `29353194135`, and the generated
  HyperTrade strategy then passed the production 120-bar runtime smoke with
  `valid=true, smoke=true`. Full `./scripts/check.sh` passed with `403 passed`;
  HyperTrade deployment workflow `29353572908` succeeded. Immutable successor
  ResearchJob `rjob_5dcc95b103394cffb130` completed 13 real BitPro backtests, 3
  evidence rows, 7 robustness scenarios and 16 artifact refs. Validation
  `rvld_5f43ed2c628847ada2a5` correctly rejected the candidate after locked OOS,
  walk-forward, parameter sensitivity and cost stress failed; data integrity passed
  and no paper/live action occurred. Sprint 101 Agent Research Evaluation is next.
- Sprint 99 implementation state: completed and production-verified on 2026-07-14.
  `ExperimentManifestV1` canonicalizes StrategySpec, code/data/cost/window and version
  hashes into a stable SHA-256 fingerprint. PostgreSQL stores immutable manifests,
  append-only attempts and evidence links; duplicate fingerprints reuse one execution,
  while failed or explicit reruns require an audited reason. ResearchOrchestrator
  registers before any BitPro strategy/backtest write and stores bounded refs, metrics,
  artifact hashes and actual usage. Concurrent registration, contract mismatch,
  evidence links, diff, privacy, API/CLI and reuse tests passed. Full
  `./scripts/check.sh` passed with `389 passed`; commit `d14fbab` deployed in workflow
  `29348485494`. Production SHA/health/read API and all three ledger tables passed.
  Robustness optimization, paper/live, raw data, full prompts and secrets remain out.
- Sprint 98 implementation state: completed and production-verified on
  2026-07-14. A fixed 13-role LangGraph DAG now runs over durable
  Task/Node/Event/Checkpoint facts with versioned prompts/schemas, role/operator/
  ToolRegistry read-only policy intersections, atomic global and per-role budgets,
  bounded provider/BitPro concurrency, safe-point controls, failed-node replay,
  Evidence V2-only outputs, API/CLI projections, and an idempotent StrategySpec
  handoff to the existing ResearchOrchestrator queue. Production smoke exposed
  and verified fixes for a provider tool-plan placeholder, schema-repair fallback,
  stale retry errors, realistic role token budgets, and pre-persistence usage
  enforcement. Full `./scripts/check.sh` passed with `378 passed` Python tests.
  Final production Task `task_337586947e7348a39523` matched the deployed catalog,
  completed all 13 nodes with zero failed nodes, emitted 21 explicit Evidence V2
  data gaps and 103 audited events, and stayed within budget at 72,533 tokens,
  29 model calls, zero tool calls, and zero backtests. Final deployment workflow
  `29346380441` succeeded and production health remained OK.
  Dynamic agents, arbitrary code/tools, paper/live writes, and automatic capital
  decisions remain out of scope.
- Sprint 97 implementation state: completed and production-verified on
  2026-07-14. Evidence V2 now
  has discriminated schemas, canonical UTC/Decimal hashing, append-only records
  and typed relations, source health/data-gap projection, lifecycle/query/graph
  services, bounded source adapters, administrator-only mutation APIs, public
  read APIs, and explicit legacy read projections. Focused evidence and existing
  RAG/strategy/BitPro regressions passed (`25 passed`), migration `0013` passed
  upgrade/downgrade/upgrade, and `./scripts/check.sh` passed with `361 passed`
  Python tests. Commit `a8484b3` deployed successfully in run `29340215236`;
  PostgreSQL-backed append/dedupe/public read/filter/graph/expire/supersede smokes
  passed with synthetic QA evidence, and production health remained OK.
  Multi-Agent graph, automatic fact adjudication, and paper/live behavior remain
  out of scope.
- Sprint 96 implementation state: completed and production-verified on
  2026-07-14. Durable
  AgentSession/AgentTask/TaskNodeRun/TaskCheckpoint/TaskEvent persistence,
  deterministic controls, budgets, PostgreSQL lease/heartbeat recovery,
  cursor-based Event REST/SSE, legacy AgentRun adapter, CLI commands, worker
  dispatch, and structured Provider timeout handling are implemented. Focused
  Agent Task/API/CLI/worker regressions passed, the new `0012` migration passed
  upgrade/downgrade/upgrade, and the full repository quality gate passed with
  `350 passed` Python tests. Commit `65c8a41` deployed successfully in run
  `29338187375`; production run `run_e2c36d58611f4c49ba5f` completed through
  durable Task `task_dd509a0e4b924187bafa`, checkpointed, emitted 25 monotonic
  events, and was readable through the remote CLI and cursor API. Production
  health remained OK.
- Planning state: approved Sprint 96–105 Agent Research OS roadmap entered
  implementation with Sprint 96 on 2026-07-14. The roadmap selectively adopts durable
  Session/Task/TUI/Skill capabilities associated with mature Agent runtimes and
  structured role graphs associated with multi-Agent research frameworks while
  preserving HyperTrade's BitPro MCP, evidence, approval, idempotency, paper
  observation, and isolated-evaluation boundaries. The proposal includes one
  roadmap, one detailed cross-sprint technical design, and ten focused sprint
  contracts covering Sessions/Tasks, Evidence V2, the research graph,
  reproducible experiments, robustness validation, Agent evaluation, TUI,
  background triggers, governed Memory/Skills, and portfolio lifecycle review.
  This activation did not change runtime, trading, paper, BitPro, provider,
  deployment, or database behavior. Sprints 96–105 are now completed.
- Last verified state: Sprint 95 Agent production-readiness evaluation completed
  on 2026-07-14. The isolated API deterministic suite passed 14/14, but the
  real Codex Provider 24-case golden baseline stopped at case 11 with an
  unhandled HTTP 500; a separate 16-case non-BitPro core subset stopped at
  case 3. Server evidence identifies an uncaught `httpx.ReadTimeout` from the
  Codex Provider, so no valid full quality, latency, token, or repeatability
  baseline exists. Two direct adversarial requests completed in evaluation mode
  without a tool dispatch; the Promptfoo suite did not start because its local
  `npx` dependency bootstrap stalled. The complete assessment, comparison, QA
  status, and P0 remediation path are in
  `docs/qa/sprint-95-agent-production-readiness.md`. The system is assessed as
  L2 controlled research/paper-ready, not production live-trading-ready.
- Last verified state: Sprint 94 isolated evaluation deployment completed on
  2026-07-14. The server target at `/opt/hypertrade-eval` is a fresh `main`
  clone with its own `hypertrade-eval` Compose project/network,
  `hypertrade-eval-api`/`hypertrade-eval-postgres` containers, database volume,
  server-only `.env`, and loopback-only `127.0.0.1:4334` API. It shares no
  production Compose component, PostgreSQL data, BitPro data mount/gateway,
  Nginx route, or worker process. The Codex auth file is mounted read-only only
  into the evaluation API; paper/monitor/BitPro/Feishu/Langfuse paths remain
  disabled. The initial deployment commit `a2aef07` deployed in run
  `29332415454`; the stream-only Codex Responses compatibility fix `97e9242`
  deployed in run `29333033089`. Local Compose/config tests and full
  `./scripts/check.sh` passed. A provider-backed evaluation-mode smoke
  `run_10d4ce8fc70f4a869052` completed through Codex with a read-only
  `market_ticker` tool call; the production health endpoint remained healthy.
- Last verified state: Sprint 93 Agent golden baseline completed locally on
  2026-07-14. The isolated-only baseline now evaluates 24 authored,
  privacy-safe tasks across market, knowledge, Memory, strategy, BitPro, World
  Model, and safety; six cases exercise write-like tool attempts that must be
  denied before dispatch. Sanitized trajectories retain only planner-selected
  tool names, policy scope/outcome, citation count, duration, and token count;
  the aggregate report excludes prompts, reports, arguments, raw outputs, and
  credentials. Focused tests passed (`16 passed`), and the optional Ragas smoke
  scored all 24 synthetic safe trajectories. Full `./scripts/check.sh` passed
  (frontend lint/test/build, Ruff, mypy, and 338 Python tests). Deployment run
  `29327574329` succeeded for SHA `0f02d1c`; the production health endpoint
  returned `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 92 Agent evaluation foundation completed locally on
  2026-07-14. The deterministic `/evals` suite remains the required regression
  gate; `evaluation_mode=true` records attempted tool selection while denying
  every non-read/non-live-diagnostic tool before dispatch. Optional self-hosted
  Langfuse receives only metadata-only span projections and cannot alter Agent
  outcomes. Promptfoo runs static adversarial checks only against an explicitly
  labelled isolated target with remote generation/telemetry disabled, and Ragas
  scores sanitized local tool trajectories. Focused API/eval/observability tests
  passed (`28 passed`); optional dependencies installed successfully and the
  Ragas tool-accuracy/F1 smoke returned `1.0` for an exact trajectory. Full
  `./scripts/check.sh` passed (frontend lint/test/build, Ruff, mypy, and 335
  Python tests). Deployment run `29324969807` succeeded for SHA `2d273ad`;
  the production health endpoint returned
  `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 91 strategy card hierarchy completed locally on
  2026-07-13. Strategy summary, evidence metrics, audited source references,
  next-experiment guidance, and evidence detail rows now use the compact
  operator-card variant inside the selected strategy card. Nested cards retain
  the same source-state rails while staying visually quieter than the parent
  selection. No strategy data, API, validation, paper, or live behavior
  changed. Frontend lint/test/build and full `./scripts/check.sh` passed.
  Browser validation with production-read strategy evidence confirmed desktop
  and 390px layouts, intact single-line metric values, and no horizontal
  overflow. Deployment run `29254785293` succeeded for SHA `9f94a62`; the
  production host health endpoint returned
  `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 90 unified operator cards completed locally on
  2026-07-13. Strategy evidence, monitor alerts, approval intents, Memory
  entries, and RAG hits now share one compact dark operator-card treatment with
  a source-state rail. The rail distinguishes normal/passing, evidence or
  pending review, contextual inventory, and final high-risk/failed state
  without creating a new risk decision. Frontend lint/test/build and full
  `./scripts/check.sh` passed. Browser checks against production-read strategy
  and alert data confirmed the shared treatment at desktop and 390px with no
  page-level horizontal overflow. Deployment run `29222773538` succeeded for
  SHA `2ff5936`; the production host health endpoint returned
  `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 89 route context metrics completed locally on
  2026-07-13. The workbench retains its five global telemetry cards; strategy,
  alerts, runs, Memory, and RAG each now render a compact, route-scoped strip
  from already loaded read data. Inactive route DOM is semantically hidden,
  and the shared main grid can shrink around long Memory audit data instead of
  causing page-level overflow. No API, polling, Agent, BitPro, paper, or live
  behavior changed. Frontend lint/test/build and full `./scripts/check.sh`
  passed. Browser validation against production-read data confirmed all six
  paths expose the expected metric surface, and desktop plus 390px checks had
  no horizontal overflow. Deployment run `29222207009` succeeded for SHA
  `24308ae`; the production host health endpoint returned
  `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 88 Memory observability dashboard completed
  locally on 2026-07-13. The routed Memory page now aggregates only existing
  audited `GET /api/memory` items into active-item composition/capacity rails,
  creation-cadence bars, and importance, confidence, reuse, and source-tool
  signals. Search keeps the full inventory for charts while filtering the
  operator list; capacity is explicitly item composition rather than a storage
  quota. Frontend lint/test/build and full `./scripts/check.sh` passed. Browser
  validation against real production Memory data confirmed desktop rendering
  and no horizontal overflow at a 390px viewport. Deployment run
  `29221155886` succeeded for SHA `3931da0`; the production host health endpoint
  returned `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 87 Harness dark observability theme completed
  locally on 2026-07-13. Shared Tailwind tokens and component styles now give
  every routed Harness surface the Flight Recorder's green-black console
  language: restrained grid texture, cyan runtime state, amber audit emphasis,
  red risk state, and low-contrast panel borders. This display-only change
  leaves Agent, BitPro MCP, research, approval, paper, and live behavior
  unchanged. Frontend lint/test/build and full `./scripts/check.sh` passed;
  browser checks confirmed the root workbench and direct strategy route render
  in dark mode without desktop horizontal overflow. Deployment run
  `29220341881` succeeded for SHA `ac74728`; the production host runs the new
  API/worker containers and its local health endpoint returned
  `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Harness sidebar navigation now uses independent,
  refreshable paths for workbench, strategy library, alerts, runs, memory, and
  RAG. Each path renders only its corresponding operator page while retaining
  shared API state and the common sidebar. Frontend tests and build passed;
  deployment verification is pending.
- Architecture diagram: Updated to include World Model (Layer 5), Monitoring (Layer 7), renumbered layers, and full Mermaid+SVG coverage.
- Last verified state: Sprint 86 paper observation and review queue implemented
  locally on 2026-07-13. Read-only paper snapshot sampling creates durable,
  deduplicated operator review requests for degraded evidence only; it never
  invokes a paper or live lifecycle write. Focused checks passed; deployment
  verification is pending.
- Last verified state: Sprint 85 BitPro paper snapshot integration implemented
  locally on 2026-07-13. Promotion observation now reads the immutable,
  strategy-scoped BitPro snapshot and persists its identity, versions, metrics,
  coverage, and source payload without dashboard/event/equity aggregation.
  Focused regression passed (`128 passed`); deployment verification is pending.
- Last verified state: Sprint 84 regime-aware StrategyCard portfolio review
  implemented locally on 2026-07-12. A read-only projection joins research
  mandate, passing validation evidence, paper-promotion state, and latest
  monitor evidence into WorldState portfolio cards. Lifecycle/data-gap states
  become deterministic operator review actions only; portfolio actions cannot
  mutate paper, allocation, risk budget, or live execution. Deployment
  verification is pending the implementation push.
- Last verified state: Sprint 83 paper promotion and observation implemented
  locally on 2026-07-12. Passing `ResearchExperimentEvidence` creates only a
  `pending_paper_approval` record. An administrator must provide a reason and
  unique idempotency key before the approval service invokes the linked
  BitPro `paper_configure` and `paper_start` calls. The persisted promotion
  retains returned session references, dashboard/event/equity monitor
  snapshots, candidate-scoped performance evidence, transitions, data gaps,
  and recommended next action. Observation stays read-only: gaps become
  `paper_degraded`, alerts become `paper_review_required`, and no path can
  auto-pause, retire, or promote live. Agent-originated paper lifecycle writes
  are governance-blocked. Focused contract tests passed (`137 passed`);
  `./scripts/check.sh` passed (frontend lint/test/build, Ruff, Mypy, and full
  pytest). Deployment run `29197766014` succeeded for SHA `7a29744`; external
  health returned `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 82 BitPro backtest matrix and validation gates
  implemented locally on 2026-07-12. A bounded, resumable research worker
  preflights BitPro, rejects missing real-data coverage or code validation,
  runs fixed chronological in-sample/validation/locked-out-of-sample windows,
  persists BitPro job/result references and deterministic gates, and records
  compatible strategy-library evidence. An `evidence_recorded` outcome does
  not configure/start paper or invoke live actions. Focused tests passed
  (`151 passed`); `./scripts/check.sh` passed (frontend lint/test/build, Ruff,
  Mypy, and `pytest` 328 passed). Deployment run `29197099342` succeeded for
  SHA `1f32510`; production health returned
  `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 81 research mandates and durable jobs implemented
  locally on 2026-07-12. The operator control plane persists versioned research
  mandates, schema-valid draft-only StrategySpecs, and idempotent job records
  with audit/transition traces. Admin API and local/remote CLI operations can
  create, list, pause, resume, draft, queue, and cancel without invoking any
  BitPro write tool; paper remains manual approval and live remains disabled.
  Focused tests passed (`124 passed`); `./scripts/check.sh` passed (frontend
  lint/test/build, Ruff, Mypy, and `pytest` 320 passed). Deployment run
  `29186877172` succeeded for SHA `be3712a`; production health returned
  `{"status":"ok","service":"hypertrade-api"}`.
- Last verified state: Sprint 80 paper-strategy performance matrix implemented
  locally on 2026-07-12. A dedicated read-only Agent tool now inventories
  running BitPro simulations, performs bounded strategy-scoped dashboard reads,
  rejects returned strategy identities that do not match the request, and ranks
  only rows with reported paper return metrics. Agent, plain CLI, Rich CLI, and
  structured audit renderers expose comparison coverage and partial-ranking
  status. Focused tests passed (`161 passed`) and `./scripts/check.sh` passed
  (`312 passed`). Deployment runs `29182653442` and `29182809298` succeeded;
  production smoke `run_7d8f9340f6f2485bb4ee` rendered the professional
  conclusion/comparison/risk/next-step structure with 1/9 evidence coverage.
- Last verified state: Sprint 79 unified CLI report rendering completed locally
  on 2026-07-10. Default plain and Rich output now prefers the completed Agent
  answer when report blocks exist, while `HYPERTRADE_REPORT_SOURCE=tools|audit`
  retains structured evidence. Paper-strategy comparison answers cannot invent
  an all-strategy ranking when BitPro omits per-strategy PnL/drawdown. Focused
  tests passed (`141 passed`) and `./scripts/check.sh` passed. Deployment run
  `29075436585` succeeded for SHA `f6cbaa5`; production smoke
  `run_b5ccda159bb341bb80bb` condensed nine curve reads into one comparison
  status and excluded raw monitor blocks and unrelated backtest rows.
- Last verified state: Sprint 78 CLI market-answer quality completed and
  production-smoked on 2026-07-10. Generic market prompts now guide the planner
  to `market_summary`; `global_market_snapshot` has a known read-only policy;
  WorldState reports lead with a compact conclusion; and the interactive host
  wrapper defaults to Rich. Focused verification passed (`114 passed`) and
  `./scripts/check.sh` passed (`pytest` 305 passed). Deployment run
  `29073733483` succeeded for SHA `982f2d5`; host CLI smoke
  `run_7219679fc9a649df8456` rendered the concise market conclusion, market
  panel, and movers table without a global-market policy denial.
- Last verified state: Sprint 77 CLI Flight Recorder implementation completed
  locally on 2026-07-10. The terminal now renders a redacted Token/latency/tool/
  Memory ledger in `HYPERTRADE_TRACE=summary|full`, `enhanced` maps to the
  standard Rich renderer, and `/run <run_id>` reopens historical local or remote
  runs. Focused CLI tests passed (`72 passed`) and `./scripts/check.sh` passed
  (`pytest` 298 passed). Deployment run `29066526591` succeeded for SHA
  `fedfe22`; production CLI smoke `run_7ad26af4667d41559afc` completed with
  30,408 reported Tokens and passed both summary and historical full-trace
  replay checks.
- Last verified state: Sprint 76 Agent Flight Recorder completed locally on
  2026-07-10. Provider usage normalization, run observability API, Memory trace
  correlation, and the responsive operator UI passed focused tests and full
  `./scripts/check.sh` (frontend lint/test/build, Ruff, Mypy, and `pytest` 293
  passed). Playwright desktop/mobile validation found no horizontal overflow or
  browser console errors. Deployment run `29064831516` succeeded for SHA
  `e7096c6`; production health, overview observability, and historical Run
  projection smokes passed. A new provider-backed smoke was audited as failed
  because the configured DeepSeek credential returned `401 invalid api key`.
  The server-side secret was subsequently rotated and a real DeepSeek run
  `run_05e9ae44916f494798f8` completed with 30,839 provider-reported Tokens.

## Active Contract

- Sprint 107 StrategyCard Lifecycle & Research Funnel is active under
  `docs/contracts/sprint-107-strategy-card-lifecycle-research-funnel.md`.

## Approved Follow-On Design

- Added the approved planning design for an autonomous, BitPro-integrated
  strategy research institution in
  `docs/architecture/23-autonomous-strategy-research-institution.md`.
  The design keeps BitPro as the sole data/backtest/paper platform and assigns
  HyperTrade the research mandate, durable orchestration, validation evidence,
  approval, monitoring, and read-only portfolio-review responsibilities.
- Added four dependency-ordered implementation contracts:
  - Sprint 81: research mandates and durable jobs;
  - Sprint 82: BitPro backtest matrix and validation gates;
  - Sprint 83: human-approved paper promotion and observation;
  - Sprint 84: regime-aware strategy portfolio review.
- This is an architecture and planning change only. No research scheduler,
  BitPro mutation, automatic paper action, or live-trading capability was
  implemented or enabled by this documentation change.

## Current In-Progress Work

- Production DeepSeek configuration is healthy after server-side credential
  rotation. The validation run reported 30,839 Tokens across two model calls;
  no credential was stored in the repository.
- Architecture diagram refresh: Added World Model (Layer 5), Monitoring & Alerts
  (Layer 7), renumbered to 10-layer model, and updated SVG + Mermaid to reflect
  the complete Sprint 1-74 capability surface.
- World-model Agent evaluation is complete. The Agent is production-safe for
  read-only operator review, scenario comparison, defensive-review preparation,
  and portfolio scheduling recommendations, but follow-up work should tighten
  provider-backed planning so decision/portfolio prompts do not over-select
  generic `market_summary`, add cross-asset provider contracts, and add a
  staging defensive-action smoke.
- Sprint 74 portfolio scheduler is implemented and focused-test verified. The
  world-model snapshot and `GET /api/world-model/portfolio` expose a rule-based
  portfolio view with strategy fit, evidence freshness, correlation proxy,
  missing-evidence markers, and review recommendations while preserving the
  no-live-allocation-mutation boundary.
- Sprint 73 defensive automation gate is implemented and focused-test verified.
  Defensive actions are disabled by default, require explicit allowlist config
  and idempotency keys, and persist trace-backed audit attempts; the initial
  executable fixture action raises an internal human-confirmation alert.
- Sprint 72 scenario decision is implemented and locally verified. The
  `world_model_snapshot` payload now includes deterministic `action_scenarios`
  and a `decision` record with benefit, downside, confidence, data-gap penalty,
  reversibility, execution complexity, policy status/result, review window, and
  follow-up evidence.
- Sprint 71 read-only `WorldState` snapshot is implemented and locally
  verified. It exposes `GET /api/world-model/snapshot`, Agent tool
  `world_model_snapshot`, report blocks, missing-data markers, and eval
  guardrails requiring global operator prompts to use WorldState rather than
  crypto-only market heat.
- Sprint 69 README framework guide was committed, pushed, deployed, and
  production-smoked; no implementation work remains for that slice.
- Sprint 67 LLM planner routing and Sprint 68 live BitPro routing evals were
  committed, pushed, deployed, and production-smoked separately from the README
  framework guide work.

## Latest Completed Work

- Implemented Sprint 84 StrategyCard portfolio review. The WorldState portfolio
  view consumes a source-bound, read-only card projection from S81–83 evidence,
  exposes declared regime fit, lifecycle status, freshness, drawdown/coverage
  flags, and transparent shared-exposure proxies. It returns review actions,
  never allocation instructions or a paper/live write.
- Implemented Sprint 83 paper promotion and observation. `PaperPromotion`
  links passing S82 evidence to the mandate, job, strategy reference,
  administrator reason, approval idempotency key, BitPro paper instance, and
  bounded source evidence. Only the explicit administrator service path can
  configure/start BitPro paper; Agent paper lifecycle writes are blocked by the
  governance registry even when an Agent supplies an idempotency key. The
  read-only observation join captures `paper_dashboard`, events, equity curve,
  monitor drift, and candidate performance evidence. Missing data becomes
  `paper_degraded`, alerts become `paper_review_required`; neither makes a
  lifecycle write or changes a backtest conclusion. Admin API and local/remote
  `/research-program` CLI expose request, inspect, approve, and observe flows.
- Implemented Sprint 82 BitPro backtest matrix and validation gates. The
  `ResearchOrchestrator` only runs an operator-triggered, mandate-bounded
  matrix after BitPro capabilities/health, real K-line coverage, and code
  validation checks. It stores limited result references and deterministic
  metrics/gates in `ResearchExperimentEvidence`; unavailable data, upstream
  failure, or missing locked-sample metrics cannot become a passing result.
  Dynamic DB strategy writes and every backtest carry an idempotency key.
  No paper-control or live method exists in this worker.
- Implemented Sprint 81 research mandates and durable jobs. `ResearchMandate`
  persists allowed symbols, timeframes, strategy categories, research budgets,
  chronological validation windows, and immutable `manual_approval`/`disabled`
  promotion boundaries. `ResearchJob` enforces an idempotency key and exposes a
  trace-backed lifecycle (`queued`, `planning`, terminal states); it has no
  worker, scheduler, backtest, paper, or BitPro mutation path. Admin API,
  `/research-program` CLI, and Agent read/draft tools keep the same bounded
  draft-only contract.
- Implemented the Sprint 80 paper-strategy performance evidence path. The new
  `bitpro_paper_strategy_performance` tool validates every dashboard response
  against the requested strategy id, sorts only comparable rows by reported
  `return_pct`, and returns explicit total/comparable/unavailable coverage.
  Mismatched current-dashboard responses and missing return metrics remain
  visible data gaps and cannot become ranking rows. Planner guidance now routes
  simulated-strategy winner/comparison questions to this bounded tool instead
  of repeated curves or historical backtests. Focused tests passed (`161
  passed`) and full `./scripts/check.sh` passed (`312 passed`). Production smoke
  confirmed that only strategy #105 had identity-matched evidence and that the
  other eight strategy ids were explicitly marked unavailable; auxiliary
  inventory calls remain available in Trace rather than the final answer.
- Implemented Sprint 79 CLI unified report rendering: default plain and Rich
  output now shows a completed Agent report before `report_blocks`, which stay
  available through `HYPERTRADE_REPORT_SOURCE=tools|audit`. Existing structured
  market and BitPro backtest renderers remain unchanged. The paper-ranking
  prompt now requires a conclusion/comparison/risk/next-step structure and
  forbids inferred returns; the deterministic paper report reports a full
  ranking as unavailable when BitPro's running inventory lacks per-strategy
  PnL/drawdown. Production smoke `run_ef3acad3a6a447d6af75` exposed a compound
  evidence path where the Planner read multiple curves and backtest rows; the
  follow-up suppresses repeated per-tool curve lines and unrelated historical
  backtest rows, retaining one evidence-bound paper comparison summary. Focused
  tests passed (`141 passed`) and full `./scripts/check.sh` passed. Deployment
  run `29075436585` succeeded for SHA `f6cbaa5`; production smoke
  `run_b5ccda159bb341bb80bb` reduced nine curve reads to a single comparison
  status, with no repeated raw curves, raw monitor blocks, or historical
  backtest rows in default output.
- Implemented Sprint 78 CLI market-answer quality: `global_market_snapshot`
  now maps to a known read-only `global_market.snapshot` policy, preventing the
  governance false denial. Planner guidance keeps generic current-market
  prompts on `market_summary`; WorldState reports start with a compact final
  market conclusion and omit candidate actions, portfolio details, and source
  internals from the default answer while retaining them in persisted audit
  blocks/Trace. The host CLI wrapper detects an interactive terminal and sets
  Rich rendering unless an operator explicitly selects a renderer. Focused
  tests passed (`114 passed`) and full `./scripts/check.sh` passed (`pytest`
  305 passed). Deployment run `29073733483` succeeded for SHA `982f2d5`; host
  CLI smoke `run_7219679fc9a649df8456` selected `market_summary`, rendered the
  conclusion and market panels/tables in Rich, and showed no policy denial.
- Implemented Sprint 77 CLI Flight Recorder: `HYPERTRADE_TRACE=summary|full`
  now renders a trace-safe terminal ledger from the persisted observability
  projection (provider/model, exact reported Tokens or explicit unavailable,
  duration, tool aggregate, Memory read/write counts) before the folded or full
  trace. Full trace rows include only tool name, status, and duration; prompts,
  credentials, raw tool payloads, and private reasoning remain hidden.
  `HYPERTRADE_RENDERER=enhanced` now uses the standard Rich run envelope, and
  `/run <run_id>` loads local or remote historical runs through the same
  renderer. Focused CLI tests passed (`72 passed`) and full `./scripts/check.sh`
  passed (`pytest` 298 passed). Deployment run `29066526591` succeeded for SHA
  `fedfe22`; production DeepSeek smoke `run_7ad26af4667d41559afc` completed
  with 30,408 reported Tokens, and `/run` replayed its full redacted trace.
- Implemented Sprint 76 Agent Flight Recorder: OpenAI-compatible Chat
  Completions and Codex Responses normalize provider-reported input, output,
  cached-input, reasoning, and total Token usage; `AgentPlanner` records one
  trace-safe `graph.model_call` per iteration without persisting prompts,
  credentials, or private reasoning text; `AgentObservabilityService` exposes
  `GET /api/agent/runs/{run_id}/observability` plus recent-run overview
  telemetry; Memory reads/writes retain audited ids and source metadata. The
  frontend adds a responsive `AgentFlightRecorder` feature component with
  Token ledger, latency tape, category lanes, Memory drilldown, and explicit
  redaction states. Focused backend tests passed (37), CLI/report regressions
  passed (70), frontend tests passed (6), browser desktop/mobile checks passed,
  and full `./scripts/check.sh` passed with `pytest` 293 tests. Deployment run
  `29064831516` succeeded for SHA `e7096c6`; production `/api/health`, overview
  observability, and historical Run observability smokes passed.
- Completed world-model Agent evaluation across Sprints 71-74 and added
  `docs/qa/world-model-agent-evaluation-2026-06-25.md`. Local focused
  verification passed with world-model/eval tests (`23 passed`) and
  Agent/API regression tests (`17 passed`); full `./scripts/check.sh` passed
  with frontend install/lint/test/build, ruff, mypy, and Python pytest
  (`254 passed`). Production smoke confirmed `/api/health`, `/api/evals/status`
  (`status=passed`, `case_count=14`), `/api/world-model/snapshot`,
  `/api/world-model/portfolio`, and admin protection on defensive-action
  inspection. Production Agent prompt smoke confirmed `world_model_snapshot`
  usage and no live-write tools for global state, hold/reduce-risk, and
  strategy-weight prompts; it also found a follow-up gap where decision and
  portfolio prompts can still over-select `market_summary` alongside
  `world_model_snapshot`.
- Implemented Sprint 74 world-model portfolio scheduler: added
  `PortfolioScheduler`, `GET /api/world-model/portfolio`, portfolio state in
  `world_model_snapshot`, report blocks for portfolio risk/strategy fit/
  recommendations, planner guidance for portfolio and `策略权重` prompts, and
  eval coverage requiring `world_model_snapshot` for portfolio review. The
  scheduler remains rule-based and evidence-bound: missing strategy or
  cross-asset evidence leads to observation, targeted backtest/experiment, or
  human-review recommendations instead of allocation increases; live allocation
  mutation remains out of scope. Focused verification passed with portfolio/eval
  tests (13 passed), broader world-model/API regression tests (24 passed), and
  full `./scripts/check.sh` (`pytest` 254 passed).
- Implemented Sprint 73 world-model defensive automation gate: added
  `DefensiveActionEngine`, config fields
  `WORLD_MODEL_DEFENSIVE_ACTIONS_ENABLED` and
  `WORLD_MODEL_DEFENSIVE_ACTION_ALLOWLIST`, ToolRegistry/governance policy for
  `world_model.defensive_action`, trace-backed action attempts, monitor-alert
  creation for `raise_human_confirmation_alert`, and admin APIs to inspect
  config, attempts, and execute allowlisted actions. Missing idempotency,
  offensive actions, unsupported actions, stale evidence, disabled automation,
  and non-allowlisted requests are rejected or skipped without adapter/exchange
  calls. Focused verification passed with defensive-action/governance tests
  (7 passed), world-model/report/API regression tests (10 passed), and full
  `./scripts/check.sh` (`pytest` 250 passed).
- Implemented Sprint 72 world-model scenario decision layer: `ScenarioSimulator`
  and `ActionScorer` compare observe/hold/monitor/trace/human-confirmation/
  pause-request/risk-reduction-request actions against the read-only
  `WorldState`. `world_model_snapshot` now returns `action_scenarios` and a
  hash-linked `decision` record; reports render scenario comparison and
  `policy_status`; evals fail if global operator answers omit scenario evidence
  or policy status. The scorer is deterministic and source-bound, and missing
  cross-asset data keeps risk-changing recommendations from ranking first.
  Verification passed with focused scenario/acceptance tests (19 passed) and
  full `./scripts/check.sh` (`pytest` 246 passed).
- Implemented Sprint 71 read-only global WorldState snapshot: new
  `hypertrade.world_model` module assembles `global_market`, `crypto_market`,
  strategy, execution, tool-health, deployment, `missing_data`, source refs, and
  L0/L1 candidate actions without calling paper, BitPro lifecycle, Testnet, or
  live write tools. The snapshot is exposed through
  `GET /api/world-model/snapshot` and Agent tool `world_model_snapshot`;
  reports render a `全局世界模型` section and structured report blocks; `/evals`
  includes `world_model_global_operator_state` to forbid `market_summary`
  fallback for global operator prompts. Verification passed with focused
  world-model/planner/eval/report tests (41 passed) and full
  `./scripts/check.sh` (`pytest` 242 passed).
- Added world-model phased development docs: `docs/architecture/22-world-model-development-roadmap.md`
  maps LeCun-style world-model modules onto HyperTrade's production Agent
  boundary, keeps market state global and cross-asset, and defines the phase
  sequence for read-only `WorldState`, scenario decision, defensive automation,
  and portfolio scheduling. Sprint contracts 71-74 split those phases into
  small, verifiable implementation slices with explicit source, permission,
  missing-data, and no-live-write boundaries. Verification passed with full
  `./scripts/check.sh` (`pytest` 236 passed).
- Added Sprint 69 README framework guide: the root README now gives a
  framework-grade introduction for operators, engineers, and external Agent
  integrators. It documents the HyperTrade/BitPro boundary, layered
  architecture, component map, prompt execution flow, local SQLite quickstart,
  CLI/API usage, BitPro workflows, monitoring, Testnet guardrails,
  configuration, production deployment, evals, troubleshooting, repository
  layout, and development workflow. Verification passed with full
  `./scripts/check.sh` (`pytest` 236 passed). Deployment run `28086647977`
  completed successfully for SHA `944a062`, and public
  `GET http://47.79.36.92:3333/api/health` returned `ok`.
- Added Sprint 68 live BitPro routing evals: `/evals` now includes
  `live_order_history_source` and `live_strategy_performance_source`, requiring
  `bitpro_live_order_history` / `bitpro_live_strategy_performance`, forbidding
  `market_summary`, and failing if reports render `Market Report`, `Top Movers`,
  or `市场热度总结` instead of BitPro live evidence. Focused verification passed
  with `uv run pytest tests/test_agent_eval_suite.py tests/test_api.py -q`.
  Production Agent smoke `run_4601238b5b324c2d8df7` answered
  `我的实盘最近的一笔订单是什么` with `BitPro 实盘订单` and
  `bitpro.live_order_history` trace, without `Market Report`/`Top Movers`.
- Added Sprint 67 LLM planner routing: `AgentKernel.run_chat_with_events()` no
  longer maps natural-language prompts to tools through keyword branches or a
  no-key market/RAG/Memory fallback. Provider-backed runs go through
  `AgentPlanner`; provider-unavailable runs produce an auditable report with no
  business tool calls. Planner-backed `market_summary` reports still promote
  heat-summary metadata for API/front-end consumers. Regression tests cover
  provider-backed market heat, live order history, live strategy performance,
  API streaming, local CLI no-provider behavior, and the provider-unavailable
  boundary. Verification passed with full `./scripts/check.sh` (`pytest` 236
  passed). Deployment run `28085079651` completed successfully for SHA
  `3638c8f`, and public `GET http://47.79.36.92:3333/api/health` returned `ok`.
  Production Agent smoke `run_a45184edde354514abdf` answered
  `看下实盘收益最高的策略` with `BitPro 实盘策略收益` and
  `bitpro.live_strategy_performance` trace, without `Market Report`/`Top
  Movers`.
- Added Sprint 66 README architecture/onboarding refresh: the root README now
  embeds `docs/assets/hypertrade-architecture.svg`, explains the
  HyperTrade/BitPro boundary, summarizes V1 capabilities, documents core
  workflows, names the Codex model allowlist behavior, and adds safety,
  documentation-map, and repository-layout sections. Verification passed with
  full `./scripts/check.sh` (`pytest` 233 passed). Deployment run `28083972320`
  completed successfully for SHA `c58b21498247ff6a55b87b0a4f62c5591fa0d880`, and
  public `GET http://47.79.36.92:3333/api/health` returned `ok`.
- Added Sprint 65 live strategy performance coverage: prompts such as
  `看下实盘收益最高的策略` gained read-only
  `bitpro_live_strategy_performance` evidence instead of falling back to OKX
  market heat. Sprint 67 later moved free-form natural-language selection to
  the LLM planner rather than kernel keyword routing. The BitPro adapter
  preflights capability/health, reads
  `/live/strategies`, ranks returned rows by the page metric `return_pct`,
  reports `total_pnl` when present, and renders a `BitPro 实盘策略收益` section.
  Verification passed with focused Agent/planner/adapter/report/registry tests
  and full `./scripts/check.sh` (`pytest` 233 passed). Deployment run
  `28083803949` completed successfully for SHA `d3173a1`, public
  `GET http://47.79.36.92:3333/api/health` returned `ok`, and remote CLI smoke
  run `run_233a0cf96acb45a9a12f` answered `看下实盘收益最高的策略` with
  `BitPro 实盘策略收益` plus `bitpro.live_strategy_performance` trace.
- Added Sprint 64 Codex GPT-5.5 option: default `CODEX_MODEL_OPTIONS` now
  includes `gpt-5.5` between `gpt-5.4` and `gpt-5.4-mini`, while `CODEX_MODEL`
  remains `gpt-5.4`. This explains why 5.5 was missing before: the CLI model
  picker is backed by a configured allowlist rather than live model discovery.
  Verification passed with focused provider tests and full `./scripts/check.sh`
  (`pytest` 229 passed).
- Added Sprint 63 CLI selectable candidates: slash command and slash argument
  candidate lists now render numbered alternatives, interactive chat prompts
  for a candidate number, and selected candidates dispatch through the same
  deterministic slash-command handlers. This includes partial commands such as
  `/st` and argument candidates such as `/model c`, which continues into the
  Codex model picker after selecting `codex`. Verification passed with focused
  CLI tests and full `./scripts/check.sh` (`pytest` 228 passed).
- Added Sprint 62 live order-history coverage: live/real-account order-history
  prompts such as `我的实盘最近的一笔订单是什么` gained read-only
  `bitpro_live_order_history` evidence instead of market fallback. Sprint 67
  later moved free-form natural-language selection to the LLM planner rather
  than kernel keyword routing. The BitPro adapter preflights capability/health,
  reads `/trading/orders/history`, records source tool calls, and planner
  guidance forbids `market_summary` for live account order-history questions.
  Verification passed with focused
  planner/adapter/Agent tests and full `./scripts/check.sh` (`pytest` 225
  passed).
- Added Sprint 61 CLI Codex model picker: interactive `/model` now renders a
  numbered provider list and, when Codex is selected, a numbered Codex model
  list sourced from `CODEX_MODEL_OPTIONS`. Local and remote sessions carry the
  selected model into `AgentKernel` chat/planner calls, API provider selection
  validates optional model overrides, and provider status exposes
  `model_options` without exposing Codex tokens. Verification passed with
  focused provider/API/CLI tests and full `./scripts/check.sh` (`pytest` 225
  passed).
- Added Sprint 60 monitor scheduler worker: default monitor definitions now use
  conservative interval schedules, `MonitorService.run_due_monitors()` runs due
  monitors while skipping manual/disabled/not-due definitions, and
  `hypertrade.worker` has a `MONITOR_SCHEDULER_ENABLED`-gated scheduler loop
  that persists monitor runs and alert events without calling paper/live write
  tools. Verification passed with focused monitor/worker tests and full
  `./scripts/check.sh` (`pytest` 225 passed).
- Added Sprint 59 CLI argument candidate display fix: slash-command candidate
  rendering now also understands argument completions from
  `SLASH_ARGUMENT_COMPLETIONS`, so inputs such as `/model c` show `codex`
  instead of displaying no matches or dispatching `c` as a fake provider. The
  readline display hook and Enter-on-partial-argument path are covered by
  focused CLI regression tests. Verification passed with focused candidate
  tests and full `./scripts/check.sh` (`pytest` 213 passed).
- Added Sprint 58 Codex provider runtime: HyperTrade now exposes `codex` as a
  selectable chat/planner provider, accepts Hermes-style `openai-codex` as an
  alias, reads server-only `CODEX_API_KEY` or `CODEX_AUTH_JSON` access tokens
  without exposing secrets in provider status, and routes planner calls through
  the Codex Responses API while HyperTrade still owns ToolRegistry execution,
  risk policy, trace, RAG, and Memory. Verification passed with focused
  ruff/mypy/provider/API/CLI tests and full `./scripts/check.sh` (`pytest` 211
  passed).
- Added Sprint 57 architecture diagram: `docs/assets/hypertrade-architecture.svg`
  provides a poster-style layered map for client access, data inputs, Agent
  gateway, HyperTrade engine, execution/output, multi-Agent workflow,
  infrastructure, closed-loop workflow, and safety/compliance. The companion
  `docs/architecture/19-hypertrade-architecture-diagram.md` documents layer
  responsibilities and the HyperTrade/BitPro boundary.
- Completed Agent 52 / Sprint 52 frontend operator console polish:
  `/harness` keeps BitPro result ids labeled as `bitpro_result`, reads monitor
  alerts from the actual `/api/alerts` endpoint, and documents the Strategy
  Library, structured report block, evidence drilldown, alert empty-state, and
  read-only approval/risk surfaces. Verification passed with frontend
  lint/test/build, API smoke for `/api/strategy/library`, `/api/alerts`, and
  `/api/health`, plus full `./scripts/check.sh` (`pytest` 207 passed).
- Added Sprint 54 connector framework: trusted connector protocol/dataclasses,
  `ConnectorRegistry`, deterministic `FixtureConnector`, and `BitProConnector`
  compatibility wrapper over the existing BitPro MCP adapter. Redacted
  connector capabilities are exposed through `GET /api/connectors/capabilities`,
  `/api/harness/overview.connectors`, CLI `/connectors`, and ToolRegistry
  `connector_origin` metadata for BitPro-backed tools. Focused verification:
  `uv run pytest tests/test_connector_framework.py tests/test_tool_registry.py
  -q`, `uv run pytest tests/test_cli.py -q`,
  `uv run pytest tests/test_api.py -q`, contract verification
  `uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_tool_registry.py
  -q`, `uv run pytest tests/test_agent_acceptance.py -q`, and full
  `./scripts/check.sh` (`pytest` 207 passed).
- Added Agent 53 / Sprint 53 evaluation suite hardening: `/evals` now exposes
  deterministic guardrail cases for strategy-library source use, BitPro
  page-parity result metrics, missing artifact disclosure, paper-monitor
  read-only behavior, and compact/default report rendering. The eval contract
  includes required/forbidden tools, report fragments, source ids, and
  missing-data expectations; fixture helpers cover source-bound tool outputs and
  strategy-memory evidence.
- Verification: `uv run pytest tests/test_agent_acceptance.py -q` -> 16
  passed; `uv run pytest tests/test_agent_eval_suite.py -q` -> 5 passed;
  `uv run pytest tests/test_api.py tests/test_cli.py -q` -> 69 passed;
  `./scripts/check.sh` -> frontend install/lint/test/build passed, ruff and
  mypy passed, pytest 207 passed.
- Added the Sprint 51 monitoring and alerts runbook and docs links for
  `/monitors`, `/monitor run <monitor_id>`, `/alerts`, and the matching monitor
  API. The runbook records the read-only boundary, default monitors,
  threshold/alert payloads, and manual smoke path for BitPro paper monitoring,
  strategy-library freshness, and connector health.
- Added Sprint 56 market heat summaries: broad all-market heat/sentiment/breadth
  prompts now route to `market_summary`, compute OKX SWAP breadth metrics
  (`advancers`, `decliners`, average UTC0 change, strongest/weakest symbols),
  and render a conclusion before raw ticker details. CLI market detail runs now
  default to final-summary-first output while `HYPERTRADE_REPORT_SOURCE=tools`
  keeps raw ticker/candle tables available for debugging.
- Added Sprint 55 CLI slash-command candidate filtering: incomplete prefixes
  such as `/st` or `/me` now render filtered command candidates with the same
  descriptions as `/help`, and real TTY readline completion registers a display
  hook for described Tab candidates.
- Added Sprint 49 risk governance policy: `RiskGovernancePolicy` evaluates
  registered Agent tools before execution, classifies read/research-write/
  paper-write/testnet-write/live-diagnostic scopes, denies write-like external
  actions missing `idempotency_key`, records `policy_decision` in graph trace,
  and renders denied BitPro lifecycle writes in a `风控治理` report section
  without calling the external adapter.
- Added Sprint 48 multi-source market intelligence: connector-neutral result
  schema/service layer, OKX funding/open-interest client reads, curated context
  fixture, Agent planner schema, kernel executor branch, ToolRegistry entry, and
  compact report rendering. Verification is covered by
  `tests/test_market_intelligence.py`, planner/registry tests, and the combined
  `./scripts/check.sh` pass with 203 Python tests.
- Added Sprint 47 evidence-driven strategy loop: `StrategyIterationService`
  reads `StrategyLibraryService` before iteration, produces bounded
  source-backed variant plans, and lets API/CLI experiment flows compare a new
  winner against prior best evidence without claiming improvement when metrics
  are missing or worse.
- Added Sprint 46 strategy evidence schema: new `strategy_knowledge` Memory
  writes now store versioned `StrategyEvidence` JSON payloads in
  `MemoryItem.content`, preserving exact Memory dedupe/search behavior while
  letting `StrategyLibraryService` prefer structured evidence and fall back to
  legacy text cards. The strategy library now preserves schema version,
  optional BitPro result ids, source data, research-only boundaries, gate
  results, failure reasons, and safe missing-field defaults; focused Sprint 46
  verification passed with `uv run pytest tests/test_strategy_library.py
  tests/test_strategy_backtest_api.py -q` and `uv run pytest tests/test_cli.py
  tests/test_agent_planner.py -q`.
- Added the post-Sprint-44 capability roadmap for parallel Agent development:
  `docs/architecture/18-hypertrade-capability-roadmap.md` defines the target
  capability map and dependencies, and Sprint contracts 45-54 split Agent
  runtime reliability, strategy evidence schema, evidence-driven strategy loops,
  multi-source market intelligence, risk governance, report provenance,
  monitoring/alerts, frontend operator console, evals, and connector framework
  into independent handoff packages.
- Added copy-ready prompts for parallel development agents in
  `docs/agent-prompts/parallel-sprint-prompts.md`, covering Sprint 45-54 plus a
  coordination-only lead Agent prompt.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 161 tests.
- Aligned the HyperTrade BitPro adapter with BitPro MCP Agent Token management: local `bitpro_capabilities` and `/api/harness/overview` now expose `remote_mcp`, `agent_auth`, token-management routes, R/W/L/T scope classes, live-diagnostic grouping, and idempotency-required tools without exposing token plaintext; `/harness` also shows a compact BitPro MCP access status panel for Token source/header/scope checks.
- Tightened CLI/Agent paper-report output: default stream progress now folds to `Agent: running/completed`, Rich and plain renderers prefer concise final BitPro paper reports, old noisy paper Markdown with strategy inventories or equity-point samples is folded into a compact paper summary, and `HYPERTRADE_PROGRESS=full` / `HYPERTRADE_REPORT_SOURCE=tools` keep debug/audit detail available.
- Shortened server-side BitPro paper final reports: paper dashboard/events/equity/snapshot sections now include the planner conclusion plus core metrics, alerts, data gaps, and latest error only, without raw strategy inventory rows, equity-point samples, ordinary event rows, contract/tool-order fields, or citation sections.
- Made default CLI run rendering report-focused and compact: run headers, status/tool trace tables, folded-trace notices, and wrapper `Agent Report` panels are hidden unless `HYPERTRADE_TRACE=summary/full` is set; Markdown report spacing is compacted and horizontal separators are removed.
- Added Sprint 44 strategy library memory: audited `strategy_knowledge` Memory cards now aggregate into strategy-level summaries with evidence counts, pass/fail counts, best/latest evidence, variants, failure reasons, next experiments, and source memory ids. The capability is exposed through `GET /api/strategy/library`, CLI `/strategy library [query]`, Agent planner tool `strategy_library_search`, and ToolRegistry entry `strategy.library_search`; new strategy memory cards include variant count, gate results, and failure reasons.
- Cleaned default CLI/Rich report rendering so low-value citation sections, poor terminal emoji/keycap glyphs, and noisy per-tool progress lines are hidden by default while `HYPERTRADE_REPORT_SOURCE=tools` and `HYPERTRADE_PROGRESS=full` keep audit/detail paths available.
- `uv run pytest tests/test_strategy_library.py tests/test_strategy_backtest_api.py tests/test_agent_planner.py tests/test_market_candles_tool.py tests/test_cli.py tests/test_tool_registry.py -q` -> 84 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 155 tests.
- Added CLI slash-command discovery: entering `/` now displays the command list without an unknown-command warning, and real TTY readline sessions register Tab completion for slash commands plus common subcommands such as `/model`, `/memory`, `/paper`, `/live`, and `/backtest`.
- Added Sprint 43 BitPro paper monitor snapshots: Agent tool `bitpro_paper_monitor_snapshot` now captures dashboard, event summary, and equity summary through read-only BitPro MCP/API tools, persists normalized metrics and nested BitPro tool calls, compares with the previous snapshot for the same scope, and renders PnL/equity/drawdown/error drift in Agent/CLI reports without triggering paper or live write tools.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 143 tests.
- Added Sprint 42 BitPro paper evidence layer: Agent tools `bitpro_paper_events` and `bitpro_paper_equity_curve` now preflight through BitPro MCP, read bounded event/error and equity/drawdown evidence, record nested trace calls, and render source-bound Agent/CLI paper monitoring evidence without synthesizing missing rows.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 137 tests.
- Added Sprint 41 documentation refresh: root READMEs, `docs/README.md`, knowledge guides, architecture notes, deployment docs, testing plan, and smoke runbook now describe the current production Agent surface, BitPro MCP boundaries, page-focused BitPro reports, strategy knowledge memory, and operator validation paths.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 131 tests.
- Improved BitPro backtest detail CLI formatting: plain and Rich output now group core metrics and artifact samples with Chinese labels, and Rich metric values use semantic colors while respecting `NO_COLOR`.
- Kept default BitPro backtest Agent reports page-focused: completed backtest result/detail sections no longer include MCP contract/tool-order debug fields, lifecycle polling summaries, or RAG citation lists unless operators explicitly inspect trace/debug evidence.
- Added Sprint 40 strategy knowledge memory sedimentation: completed local strategy experiments now write one audited `strategy_knowledge` Memory item with experiment/research/backtest ids, winning variant, parameters, return, drawdown, trade count, evidence gates, data selection, and next-experiment guidance. The item is tagged for strategy, experiment, evidence, strategy key, and winning variant searches so future Agent runs can retrieve prior evidence through existing Memory API/CLI/UI surfaces.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 131 tests.
- Updated CLI structured BitPro rendering so `bitpro_backtest_get_result` appears as a dedicated backtest detail block in both Rich and plain output, and mixed ranking/detail runs no longer hide the page-parity result details behind the ranking table.
- Suppressed BitPro lifecycle polling logs when a report already contains BitPro backtest result/detail evidence, so strategy backtest prompts stay focused on page-parity metrics and artifact availability instead of appending tool lifecycle rows.
- Added semantic CLI colors for interactive TTY output: slash-command help now colors commands/descriptions, `/tools` colors tool names/categories/approval markers/descriptions, Agent streaming status colors progress/tool/success/error lines, remote API errors use error color, and non-TTY or `NO_COLOR=1` output remains plain for scripts.
- Fixed remote CLI streaming for long BitPro backtests: `hypertrade`/`ht` now keeps SSE reads open while preserving connect/write/pool timeouts, so a quiet upstream BitPro backtest does not bounce the local chat session with a misleading deploy/restart connection error. Remote connection error text now states that the run may still be continuing and points operators to retry or inspect `/runs`.
- Added readline-backed interactive CLI command history: real TTY `hypertrade` chat sessions now load/write `~/.hypertrade/history`, add non-empty prompts and slash commands to history, skip consecutive duplicates, and keep non-TTY/script behavior unchanged so up-arrow recalls prior requests instead of printing escape sequences.
- Fixed mixed-tool CLI rendering for BitPro paper monitoring: structured Agent output now keeps the `bitpro_paper_dashboard` monitor block when market ticker tools appear in the same run, instead of rendering only ticker sections and hiding the BitPro report evidence.
- Fixed BitPro backtest job result reporting: Agent-triggered `bitpro_backtest_start_job` now waits for the BitPro-owned job to reach a terminal state, normalizes the completed `job.result`, links it back to the saved BitPro result row when available, and renders a concise `BitPro 回测结果` section with page-parity metrics instead of a lifecycle polling log.
- Added a deterministic BitPro paper monitor summary: unfiltered `bitpro_paper_dashboard` now returns `monitor_summary` with current dashboard equity/PnL/Sharpe/drawdown, running strategy inventory coverage, data gaps, alerts, and read-only recommended actions. Agent reports render a `监控结论` block and explicitly avoid inferring per-strategy PnL/drawdown when BitPro's running-strategy inventory does not include those metrics.
- Added a read-only BitPro backtest detail evidence path: Agent tool `bitpro_backtest_get_result` now preflights `bitpro_capabilities`/`bitpro_health`, reads `backtest_get_result`, normalizes metrics plus bounded equity curve/trades/orders/fills/drawdown artifact samples, records nested `bitpro.backtest_get_result` trace evidence, and renders a dedicated `BitPro 回测详情` report section without synthesizing missing artifacts or appending model-generated evidence prose.
- Clarified BitPro live-state reporting in HyperTrade: `live_trading_enabled` is now explicitly labeled as the HyperTrade MCP live write/order gate, `/harness` exposes the same scope/note, and the planner/report renderer are instructed not to infer BitPro paper/live runtime mode from that flag. Runtime mode should come from BitPro dashboard/live read tools instead; paper/dry-run dashboard evidence must not be summarized as BitPro globally having live trading disabled.
- Upgraded the local strategy experiment workflow into a small evidence loop: `/experiment <prompt>` now runs baseline, fast, and conservative `momentum_breakout_v1` variants through normal Backtrader `BacktestRun` persistence, stores `variants`, `winner`, and `evidence_gates` in `strategy_experiments.report_json`, records the winning backtest id on the experiment row, and renders a candidate comparison table plus winning rationale in the report.
- Removed model-generated emoji/icons from CLI Markdown report rendering: Rich and plain Agent reports now strip poor terminal emoji glyphs such as chart/check/warning icons before display, while keeping the report headings, list structure, and text readable.
- Improved CLI readability for BitPro backtest result reports: `bitpro_backtest_list_results` trace payloads now render as a Rich summary panel plus compact ranking table with rounded total return, drawdown, Sharpe, win rate, trade count, and period fields instead of falling back to long raw Markdown bullets. Plain structured output also uses concise ranking rows while preserving the `total_return_pct` source-of-truth metric.
- Updated the high-visibility product positioning copy to emphasize HyperTrade as "A crypto trading agent for market research and execution" instead of a platform/system/harness; README, product spec, Chinese README, and CLI welcome banner now use the trading-agent framing.
- Added first-class local remote-login configuration to the CLI: `hypertrade /login` / `ht /login` now prompts for API URL, username, and password, writes `~/.hypertrade/client.env` with `0600` permissions, and makes later `ht` / `ht ask ...` commands default to the saved remote API unless `--local` is passed. Explicit `HYPERTRADE_*` environment variables still override saved config for automation.
- Simplified `/harness` into a core operator workbench: the page now keeps Agent run creation, report reading, tool trace, Memory search/detail, RAG search, OKX top movers, recent runs, and core telemetry. Advanced controls for BitPro MCP contract display, provider switching, paper lifecycle, live approval/execution, strategy lab/backtests, evals, Feishu send, and Memory disable were removed from the primary UI; the underlying privileged API/CLI paths remain guarded where they still exist.
- Removed the `/harness` login wall for workbench observability: the frontend now loads live overview/Memory data directly, shows real run history and trace instead of preview zeros, and no longer renders the sidebar login form. Public workbench/research endpoints cover overview, Agent runs, market reads, RAG, Memory list, strategy research/experiments, and backtests; privileged mutations such as provider selection, paper controls, live approval/execution, Memory disable, and Feishu send remain admin-authenticated.
- Added a BitPro backtest result read path for page-parity questions: `bitpro_backtest_list_results` now preflights `bitpro_capabilities`/`bitpro_health`, reads `backtest_list_results` with `offset`/`limit` pagination, filters actual `total_return_pct`, enriches strategy names through `strategy_get`, renders a dedicated `BitPro 回测结果` report section, and teaches the planner not to substitute annualized return or inferred values for total backtest return.
- Changed the production host CLI wrapper so `/usr/local/bin/hypertrade` starts a short-lived remote client container that connects to `http://api:3334` instead of `docker compose exec` into the long-running `hypertrade-api` service. Deployment can still interrupt an in-flight API request, but it no longer kills the operator's terminal session; the CLI now prints a retryable remote API message on HTTP disconnects and returns to the chat loop.
- Folded low-signal Rich CLI trace output by default: graph runtime nodes, BitPro capability/health preflight rows, and nested BitPro subcalls are now summarized instead of printed as a long table; business-level tools remain visible with call counts, and `HYPERTRADE_TRACE=full` restores full trace output for audits through both local CLI and the server host wrapper.
- Fixed BitPro paper/simulation inventory reporting: production `paper_dashboard` was verified to expose only the current dashboard strategy (`strategy_id=105`), while `strategy_search(status=running)` exposed 12 running strategies. HyperTrade now augments unfiltered `bitpro_paper_dashboard` with safe-paginated running strategy inventory, adds `paper_scope` metadata, teaches the planner not to infer a single strategy from the current dashboard view, and renders a dedicated `BitPro 模拟盘状态` report section.
- Implemented the BitPro MCP adapter in HyperTrade: server-side settings for `BITPRO_MCP_API_BASE`/token/header, `BitProMcpClient`, `BitProToolAdapter`, Agent tool schemas and executor wiring, nested trace events for `bitpro_capabilities` -> `bitpro_health` -> read/non-live lifecycle tool calls, admin API endpoints for health/K-lines/paper dashboard/live positions, `/harness` BitPro adapter status, and `candle_source=bitpro_mcp` backtest data access.
- Added Rich Markdown fallback rendering for CLI reports: when structured JSON/trace sections are unavailable, interactive/Rich output now formats Markdown headings, lists, and tables instead of showing raw `###` and pipe-table source; `HYPERTRADE_RENDERER=plain` keeps script-friendly raw Markdown.
- Added interactive CLI Agent thinking feedback: free-form prompts now show a live `Thought` / `Thinking` animation in TTY sessions while waiting for planner/tool/final-report events, while non-TTY script output keeps stable `Agent status:` lines.
- Added CLI command/tool descriptions: `/help` now renders every slash command with a purpose statement, and `/tools` prints each registered Agent tool with category, approval marker, and registry description.
- Added BitPro strategy lifecycle Agent tools: strategy search/generation/creation, BitPro-owned backtest job start/status reads, and paper/simulation configure/start/pause/resume/stop. Live mutation tools remain blocked by the BitPro adapter.
- Added HyperTrade-side support for the forthcoming BitPro `strategy_update` MCP tool: API-path mapping to `PUT /strategies/{strategy_id}`, `BitProToolAdapter.strategy_update`, Agent planner schema, AgentKernel dispatch, nested trace name `bitpro.strategy_update`, `/harness` tool listing, and docs. This lets HyperTrade rename or patch BitPro strategies through MCP once BitPro exposes the tool, without direct DB writes.
- Validated the production BitPro MCP strategy R&D loop on the server using MCP tools only. `bitpro_capabilities` returned `bitpro-mcp-v1` with live trading disabled, `bitpro_health` returned healthy, and `market_klines` confirmed 720 real ETH/USDT:USDT 1h candles from `2026-05-10T14:00:00Z` to `2026-06-09T13:00:00Z`.
- Created DB-backed BaseStrategy strategy `#293` named `[永续][1h][趋势突破] ETH/USDT · Agent EMA ATR 回撤 · paper-v1 20260609134540` through `strategy_validate_code` and `strategy_create(script_content=...)`; no BitPro Python strategy files were edited and no BitPro restart was required.
- Started BitPro-owned backtest job `a292d098-0657-411d-9fff-3c82b9b384d8`; result `#196` completed for `2026-05-10` to `2026-06-09` with `4.0441%` total return, `1.4438%` max drawdown, `11` trades, `0.8029` Sharpe, `63.64%` win rate, and final capital `10404.4128`.
- Because the explicit gate passed (trade count >= 1, return > 0, absolute max drawdown <= 15%), configured and started paper dry-run for strategy `#293`. Live mutation tools were not called.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 86 tests for the BitPro strategy lifecycle slice.
- Redesigned the `/harness` operator UI toward a Chinese-first production console: sidebar, header, run monitor, tool trace, Memory/RAG, paper runtime, live approval, strategy lab, and status labels now use consistent Chinese technical copy while preserving protocol/tool names. Added a visible BitPro MCP access panel that documents the required `bitpro_capabilities` -> `bitpro_health` -> read-tool selection flow, and added `docs/runbooks/bitpro-mcp-data-access.md` for server-side MCP data access.
- Fixed the `/harness` sidebar section navigation so clicking `行情摘要`, `Memory`, or `RAG` updates the active sidebar item instead of leaving `Harness` permanently highlighted. Added a frontend regression test for the clicked section state and browser-verified the local page with Playwright.
- Reduced repetitive investment-advice disclaimer output for routine Agent/CLI usage: the welcome banner, deterministic market shortcuts, structured market reports, and planner system prompt no longer force a fixed disclaimer on every ordinary market/RAG/Memory response. Strategy, backtest, Testnet, live-order, and recommendation-like prompts still retain the research/risk boundary. Updated acceptance tests, `docs/spec.md`, `docs/contracts/sprint-32-production-agent-bitpro-tools.md`, `docs/testing/agent-acceptance-test-plan.md`, and `docs/knowledge/tool-usage-guide.md`.
- Applied `codex-project-template` development harness.
- Added FastAPI backend, AgentKernel, ToolRegistry, RAG, Memory, OKX market parser, worker loops, Alembic migration.
- Added React/Vite `/harness` and market summary frontend surface.
- Added Docker Compose, Nginx config, self-hosted GitHub Actions deployment.
- Added `/api/harness/overview` and wired `/harness` to live Provider, Tool, market, Agent run, RAG, Memory, and trace state.
- Added configurable `COOKIE_SECURE` so the current HTTP `3333` deployment can keep admin sessions, while HTTPS deployments can opt in to secure cookies.
- Added Sprint 02 automatic paper trading runtime with paper sessions, deterministic signals, simulated fills/positions, pause/resume API, worker loop, and `/harness` Paper Runtime panel.
- Added Sprint 03 strategy research and Backtrader backtest workflow with persisted research records, backtest runs, Markdown/JSON reports, API endpoints, and `/harness` Strategy Lab panel.
- Added Sprint 04 CLI conversation harness with `hypertrade ask` and `hypertrade chat` over the same FastAPI Agent runtime.
- Added Sprint 05 standalone hybrid CLI runtime so bare `hypertrade` starts an Agent terminal, `--local` forces local AgentKernel mode, and `--remote` connects to a deployed API.
- Added Sprint 06 CLI slash commands for `/help`, `/status`, `/model`, `/providers`, `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in local and remote interactive chat.
- Added Sprint 07 CLI workflow shortcuts `/research <prompt>` and `/backtest` to trigger strategy research and Backtrader backtests without a full Agent run.

- Added Sprint 08 LLM-driven agent planner: `DeepSeekClient`, `AgentPlanner` multi-turn tool-calling loop, and updated `AgentKernel` to use real DeepSeek function calling when `DEEPSEEK_API_KEY` is configured. Sprint 67 later removed the natural-language no-key market fallback.
- Fixed DeepSeek thinking-mode compatibility by preserving `reasoning_content` across tool-call turns.
- Added Sprint 09 exact market ticker path: `market_ticker` planner tool, `market.ticker` registry entry, exact `MarketRepository.get_ticker()`, and symbol normalization for any listed OKX USDT SWAP symbol such as ETH, SOL, DOGE, or PEPE.
- Added stable planner report rendering for successful `market_ticker` calls so CLI/API answers always include exact price, UTC0 change, 24h volume, source, and timestamp.
- Added Sprint 10 market candles research path locally: OKX candle parsing, REST candle fetcher, deterministic trend feature extraction, `market_candles` planner tool, `market.candles` registry entry, AgentKernel execution, and stable K-line trend report block.
- Added Sprint 11 market relative-strength compare locally: `market_compare` planner tool, `market.compare` registry entry, deterministic strength scoring, ranking payload, and stable multi-symbol comparison report block.
- Added Sprint 12 CLI/API streaming locally: AgentKernel progress event emission, `POST /api/agent/runs/stream` SSE endpoint, remote SSE parsing, local streaming rendering, and CLI progress lines for run/tool events.
- Added Sprint 13 live candle backtest path locally: BacktestService can fetch OKX candles, convert them into Strategy SDK candles, accept API live-candle options, and pass `/backtest --live --symbol ETH --bar 1H --limit 100` from CLI.
- Added Sprint 14 Agent acceptance tests locally: deterministic replay tests now cover exact-symbol ticker output, K-line trend plus relative-strength comparison, RAG + Memory auditability, strategy research + backtest chaining, and report quality guardrails.
- Added `docs/testing/agent-acceptance-test-plan.md` with automated cases, server smoke commands, expected output checks, and forbidden advice phrases.
- Added Sprint 15 CLI market shortcuts locally: `/price`, `/candles`, and `/compare` call deterministic market payloads without waiting for LLM planning.
- Improved CLI Agent streaming status text so free-form runs show run creation, planning, tool execution, tool completion, and final report generation.
- Added Sprint 16 structured CLI report rendering locally: market-summary `report_json` and market tool trace outputs now render as structured CLI sections before falling back to Markdown.
- Added Sprint 17 Rich CLI rendering locally: structured market reports can render as terminal panels/tables when `HYPERTRADE_RENDERER=rich` or when running on a TTY, while `HYPERTRADE_RENDERER=plain` keeps script-friendly output.
- Updated the host CLI wrapper to pass safe display environment variables (`HYPERTRADE_RENDERER`, `NO_COLOR`) into the API container.
- Added Sprint 18 paper CLI controls locally: `/paper status`, `/paper pause`, and `/paper resume` call the existing paper runtime without starting an Agent run.
- Added Sprint 19 BitPro archived K-line backtest source locally: `BITPRO_SQLITE_PATH` can point to a BitPro SQLite DB, `/backtest --source bitpro --symbol ETH --bar 1H --limit 500` routes archived K-lines into Backtrader, and Compose mounts `${BITPRO_HOST_DATA_DIR:-/opt/bitpro/data}` read-only at `/bitpro-data`.
- Added Sprint 20 paper lifecycle controls locally: API and CLI now support `/paper close [symbol]` and `/paper reset`, close positions with realized PnL/events/fills, and reset by creating a new auditable running session.
- Added Sprint 21 live/testnet order approval gate locally: `live_order_intents` schema/service/API/CLI, Agent planner `live_order_intent` tool, and approve/reject status transitions without exchange execution.
- Added Sprint 22 frontend harness parity locally: `/harness` now includes Agent streaming status, market ticker/candle/compare shortcuts, paper close/reset controls, and Live Approval intent create/approve/reject UI.
- Added Sprint 23 frontend UX locally: styled Markdown report reader with raw toggle, Memory Manager with inspect/disable, and full backtest parameter form for strategy/source/symbol/bar/limit/cash.
- Added Sprint 24 Agent graph runtime locally: graph node trace events, `run_state_json`, and streaming graph status. Sprint 67 later replaced the natural-language deterministic fallback path with provider-unavailable reporting.
- Added Sprint 25 Provider Router locally: `ChatProvider` protocol, OpenAI-compatible adapter, provider selection API, CLI `/model <provider>`, and frontend provider switcher.
- Added Sprint 26 RAG v2 locally: citation-ready RAG hits, deterministic vector fallback, `/api/rag/search`, CLI `/rag`, frontend RAG search, and Agent citation block support.
- Added Sprint 27 Memory v2 locally: importance/tags/confidence/usage fields, exact dedupe, search API, CLI `/memory search` and `/memory disable`, and frontend Memory search/tag display.
- Added Sprint 28 RiskEngine locally: Mainnet execution block, SWAP-only checks, max notional/open-intent checks, risk status persistence, and frontend/CLI risk display.
- Added Sprint 29 OKX Testnet signed execution locally: signed REST client, execute endpoint, CLI `/live execute`, redacted execution audit, and frontend execute button for approved intents.
- Added Sprint 30 strategy experiment workflow locally: hypothesis/data/backtest/critique/revision/report graph, `strategy_experiments`, API/CLI/frontend surfaces.
- Added Sprint 31 observability/evals/runbooks locally: deterministic eval suite, `/api/evals/status`, CLI `/evals`, frontend eval panel, and operations runbooks.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 72 tests.
- Implementation commit `4730898` pushed to `origin/main`; GitHub Actions run `26862283002` completed successfully and recorded deployed SHA `4730898c0b5bf9ce7778da230afb1930e427b910`.
- Server smoke passed for Sprints 24-31: server-local API `GET 127.0.0.1:3334/api/health` and Nginx `GET 127.0.0.1:3333/api/health` returned OK.
- Server authenticated `/api/harness/overview` smoke returned default provider `deepseek` with key status `configured`, `359` tickers, `12` tools, `4` RAG chunks, `17` active memory items, `33` Agent runs, `110` trace events, `0` pending live intents, and eval suite `passed` with `5` cases.
- Server CLI smoke passed through host `hypertrade --remote http://127.0.0.1:3334`: `/status`, `/model`, `/evals`, `/rag 风控`, and `/memory search 风控` all returned stable output.
- Server Agent graph smoke passed with `hypertrade --remote http://127.0.0.1:3334 ask "看下ETH行情"`: run `run_387de54f5531475f8d02` completed with graph trace events for `intent_classify`, `plan_tools`, `approval_check`, `execute_tool`, `reflect`, and `final_report`, plus market ticker/candle tool calls.
- Reframed Sprint 32 toward production-grade Agent operation: project copy, source comments, and `docs/knowledge/tool-usage-guide.md` now emphasize stability, auditability, operator workflows, and BitPro API tool-surface requirements.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `3a83b18`; frontend build produced `index-BLcqGC9-.js` and `index-Dty7kLGl.css`.
- Server smoke passed: API and Nginx health OK; authenticated overview returned `359` tickers, `17` active memory items, `0` pending live order intents; authenticated `/api/memory` returned `17` items.
- `npm exec --yes pnpm@10 -- -C frontend lint`, `test`, and `build` -> passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `a35e374`; server-local `GET 127.0.0.1:3334/api/health` and Nginx `GET 127.0.0.1:3333/api/health` returned OK.
- Server authenticated `/api/harness/overview` smoke returned `359` tickers, `0` pending live order intents, `1` recent live order intent, and paper session `running`.
- `uv run pytest tests/test_paper_service.py tests/test_api.py tests/test_cli.py -q` -> 27 passed.
- `uv run pytest tests/test_live_order_intents.py tests/test_api.py tests/test_cli.py -q` -> 23 passed.
- `uv run ruff check backend tests`, `uv run mypy backend/src` -> clean.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `9f02367`; Alembic migrated `0003_strategy_backtest -> 0004_live_order_intents`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server host CLI smoke passed: `/paper status` rendered the running paper session, `/live intent ETH buy 0.01 --reason deploy smoke` created pending testnet intent `loi_10c5e2b8e34f469cb5e7`, and `/live reject loi_10c5e2b8e34f469cb5e7 --reason deploy smoke cleanup` moved it to `rejected`.
- Sprint 32 production repositioning completed locally: removed non-production project wording, replaced Sprint 32 contract with production Agent + BitPro tool-surface requirements, added `docs/architecture/17-bitpro-tool-adapter.md`, and fixed Agent market-summary tests to isolate OKX REST through injected settings.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, and pytest passed with 72 tests.

- `uv run pytest -q` -> 33 passed (5 new planner tests).
- `uv run ruff check` and `uv run mypy` -> clean.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 34 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 10 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 38 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 39 tests.
- `uv run pytest tests/test_market_candles_tool.py tests/test_agent_planner.py -q` -> 12 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 44 tests.
- `uv run pytest tests/test_market_compare_tool.py tests/test_agent_planner.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 47 tests.
- `uv run pytest tests/test_cli.py tests/test_api.py -q` -> 15 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 49 tests.
- `uv run pytest tests/test_live_candle_backtest.py tests/test_strategy_backtest_api.py tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 52 tests.
- `uv run pytest tests/test_agent_acceptance.py -q` -> 4 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 56 tests.
- `uv run pytest tests/test_cli.py tests/test_api.py -q` -> 17 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 57 tests.
- `uv run pytest tests/test_cli.py -q` -> 15 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 59 tests.
- `uv run pytest tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 60 tests.
- `uv run pytest tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 60 tests.
- `uv run pytest tests/test_bitpro_archive_backtest.py tests/test_cli.py -q` -> 19 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 63 tests.
- Server deployed SHA `bd58dd7`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server BitPro archive backtest smoke passed through host `hypertrade`: `/research 研究BTC趋势突破` created research `srch_c51a2aabfa4a448194c8`; `/backtest --source bitpro --symbol BTC --bar 1H --limit 200` created `bt_26ee2b9416b24f5db66c` using `bitpro_sqlite_candles`, `BTC-USDT-SWAP`, `1H`, and 200 candles.
- Server deployed SHA `9f3fa0c`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server paper CLI smoke passed through host `hypertrade`: `/paper status` printed session, positions, fills, and events; `/paper pause` reported paused; `/paper resume` reported running.
- Server deployed SHA `cb02da6`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server Rich CLI smoke passed with `HYPERTRADE_RENDERER=rich hypertrade ask "看下ETH行情"`: output showed Rich panels and tables for run header, tool trace, `Agent Report`, and `Ticker`.
- Server deployed SHA `fee6be7`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server structured CLI smoke passed with `hypertrade ask "看下ETH行情"`: output showed `Agent Report`, `Ticker`, and multiple `Trend` sections rendered from structured trace outputs instead of raw Markdown.
- Server deployed SHA `e975d00`; server-local `GET 127.0.0.1:3334/api/health` and `GET 127.0.0.1:3333/api/health` returned OK.
- Server CLI shortcut smoke passed through host `hypertrade`: `/price ETH`, `/candles ETH --bar 1H --limit 50`, and `/compare ETH SOL --bar 4H --limit 100` returned exact ticker, K-line trend, and relative-strength output with `okx_rest` data source.
- Server CLI Agent status smoke passed with `hypertrade ask "看下ETH行情"`: output showed run creation, planning, tool execution, tool completion, final report generation, and completed report.
- Server deployed SHA `0afb197`; external `GET /api/health` returned OK.
- Server deployed SHA `48859cb`; external `GET /api/health` returned OK.
- Server live-candle backtest smoke passed with host `hypertrade`: `/research 研究ETH趋势突破` created `srch_987a780e0715494a99a3`, then `/backtest --live --symbol ETH --bar 1H --limit 100` created `bt_480d647199dd4d16b960` using `okx_rest_candles`, `ETH-USDT-SWAP`, `1H`, and 100 candles.
- Server deployed SHA `4ce55f8`; external `GET /api/health` returned OK.
- Server streaming smoke `hypertrade ask "比较 ETH 和 SOL 哪个更强"` produced run `run_c6909801a50243649c32` and printed progress lines before the final report: `Run started`, `Tool call`, `Tool result`, and `Run completed`.
- Server deployed SHA `4de0a4b`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.compare [market]`.
- Server comparison smoke `hypertrade ask "比较 ETH 和 SOL 哪个更强"` produced run `run_7b35c4bfa1e34c899425` with `market_compare` calls, and the final answer included stable relative-strength ranking blocks for ETH/SOL across 1H, 4H, and 1D.
- Server deployed SHA `a258e05`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.candles [market]`.
- Server non-BTC trend smoke `hypertrade ask "看下ETH这两天走势"` produced run `run_f6d262efb67147eca905` with `market_ticker` and two `market_candles` calls, and the final answer included stable K-line trend blocks for `ETH-USDT-SWAP` 1H and 1D.
- Server deployed SHA `16b4ac6`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.ticker [market]`.
- Server non-BTC CLI smoke `hypertrade ask "看下ETH行情"` produced run `run_d745abf2ec4246a38315` with `market_ticker`, `market_summary`, and `memory_write` tool calls.
- Server trace query verified `market_ticker` output `inst_id=ETH-USDT-SWAP`, `found=true`, `data_source=okx_rest`.
- Server deployed SHA `38f484f`; external `GET /api/health` returned OK.
- Server non-BTC CLI smoke `hypertrade ask "看下ETH行情"` produced run `run_674ab692117a443cb969` with `market_ticker` and `rag_search`, and the final answer included the stable exact ticker block for `ETH-USDT-SWAP`.
- Server deployed SHA `8d91748`; external `GET /api/health` returned OK.
- Server `/status` slash command smoke passed through host `hypertrade`.
- Server DeepSeek planner smoke passed with `hypertrade ask "看下比特币行情"`, producing run `run_363a592c965141a8b914` with `market_summary`, `rag_search`, `memory_search`, and `memory_write` tool calls.

## Verification Evidence (previous sprints)

- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 17 tests.
- `uv run pytest -q` -> 15 passed.
- `npm exec --yes pnpm@10 -- -C frontend test` -> 1 passed.
- `npm exec --yes pnpm@10 -- -C frontend build` -> production build passed.
- Playwright opened `http://127.0.0.1:3333`, logged in, and triggered an Agent market summary.
- Server deployment verified `http://47.79.36.92:3333/api/health`.
- Server authenticated `/api/harness/overview` through Nginx verified with 344 OKX SWAP tickers, 3 Agent runs, DeepSeek configured, 1 RAG document, 3 active Memory items, and 9 trace events.
- Server authenticated `/api/paper/status` through Nginx verified paper session `running`, equity `100000`, 10 positions, and 10 recent fills.
- Worker logs verified `paper_trading tick status=running fills=10`.
- Server deployment ran Alembic `0003_strategy_backtest`, rebuilt API/worker images, and deployed SHA `e38f3e3`.
- Server authenticated strategy/backtest smoke created research `srch_12196a7d8aff4fbda649`, backtest `bt_9fc24eda9bff4e02bde0`, strategy `momentum_breakout_v1`, return `0.019000`, trade count `1`, and confirmed `/api/harness/overview.strategy_lab`.
- `uv run pytest tests/test_cli.py -q` -> 3 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 20 tests.
- Server deployed SHA `8528171`; external `GET /api/health` returned OK.
- Server container CLI smoke passed with `docker compose exec -T -e HYPERTRADE_API_URL=http://127.0.0.1:3334 api hypertrade ask "请做行情归纳"`, producing run `run_24d3927e3e324496bac3` with `market.summary`, `rag.search`, and `memory.write` tool calls.
- `uv run pytest tests/test_cli.py -q` -> 6 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 23 tests.
- Server deployed SHA `d125406`; external `GET /api/health` returned OK.
- Server local standalone CLI smoke passed with `docker compose exec -T api hypertrade ask "请做行情归纳"`, producing run `run_77da091e850346fa9da7` with `market.summary`, `rag.search`, and `memory.write`.
- Server remote CLI smoke passed with `docker compose exec -T api hypertrade --remote http://127.0.0.1:3334 ask "请做行情归纳"`, producing run `run_d5b161b8d5a54f659328`.
- Server bare interactive CLI smoke passed with `printf ":q\n" | docker compose exec -T api hypertrade`.
- Server host CLI wrapper installed at `/usr/local/bin/hypertrade` via `deploy/deploy.sh`; root shell `hypertrade` enters chat and `hypertrade ask "请做行情归纳"` produced run `run_83db62b8e9184eadaab7`.
- `uv run pytest tests/test_cli.py -q` -> 9 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 25 tests.
- `uv run pytest tests/test_cli.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 28 tests.
- Implemented the read-only BitPro MCP adapter and Agent/API/backtest data-direct wiring: `bitpro_capabilities -> bitpro_health -> market_klines` preflight order, HyperTrade tools `bitpro.*`, `candle_source=bitpro_mcp`, and `/api/bitpro/*` admin endpoints.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 79 tests before deploy.
- Deployed SHA `1dab3c1` to production; server `/api/health` passed and `/api/harness/overview` reported BitPro adapter `mcp_read_only`, token configured, and live writes disabled.
- Production BitPro MCP smoke initially returned API 500 because the HyperTrade container used `127.0.0.1:8889`, which pointed to the container itself. Added structured BitPro 502 handling and Docker Compose host-gateway mapping so containerized deployments can use `host.docker.internal:8889`.

## Known Gaps

- OKX live WebSocket ingestion is implemented but not exercised against the remote server in this local run.
- V1 does not include automatic PostgreSQL backup.
- Sprint 13 adds live OKX candle input, but does not persist historical candles to PostgreSQL.
- OKX Testnet signed execution is implemented and documented, but this smoke pass did not place an external Testnet order; use `docs/runbooks/okx-testnet-order-smoke.md` for an explicit tiny-size order smoke.
- Public `http://47.79.36.92:3333/api/health` timed out from the current local environment after Sprint 15 deploy, while server-local Nginx/API health checks passed; likely requires cloud security group or caller IP whitelist review.

## Recommended Next Steps

1. Check cloud security group / caller IP whitelist for public port `3333`.
2. Add an archived candle source reader for BitPro file-store data if server data expands beyond SQLite.
3. Run an explicit OKX Testnet tiny-size order smoke after confirming the server `.env` testnet credentials and desired symbol/size.
