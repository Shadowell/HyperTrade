# HyperTrade Product Spec

## Product Summary

HyperTrade is a crypto trading agent for market research and execution. V1 focuses on stable agent capabilities: provider configuration, tool calls, RAG, memory, trace, market ingestion, connector capability discovery, risk gates, testnet execution, BitPro strategy lifecycle orchestration, and operator-facing harnesses.

HyperTrade 是一个面向行情研究与执行的加密交易 Agent。V1 重点是稳定 Agent 能力：Provider 配置、Tool Call、RAG、Memory、Trace、行情采集、Connector 能力发现、风控门禁、Testnet 执行、BitPro 策略生命周期编排和面向操作员的 Harness。

BitPro is treated as the base trading-system platform: it owns market/reference data, strategy storage, backtest execution, metrics, paper/simulation runtime, and future live execution. HyperTrade is the Agent control and research layer: it discovers BitPro capabilities, reads/writes through MCP tools only, generates and validates `BaseStrategy` code, starts BitPro-owned backtests, inspects real evidence, and promotes only passing candidates into paper simulation. HyperTrade must not copy BitPro business logic or bypass BitPro risk boundaries.

BitPro 作为基础交易系统平台：负责行情/基础数据、策略存储、回测执行、指标、模拟盘运行和未来实盘执行。HyperTrade 作为 Agent 控制与研发层：通过 MCP 发现 BitPro 能力，只经由 MCP 工具读写，生成并校验 `BaseStrategy` 策略，启动 BitPro 负责的回测，基于真实证据迭代，并且只把通过门禁的候选策略推进到模拟盘。HyperTrade 不复制 BitPro 业务逻辑，也不绕过 BitPro 风险边界。

## Users

- Operator running audited agent research and execution workflows.
- Quant trader researching OKX perpetual swap market structure.
- Engineer integrating stable external data and execution-state providers.

## Core User Journeys

1. Operator opens `/harness` and reviews the core workbench: Agent run creation, report reading, recent runs, Flight Recorder trace/Token/Memory telemetry, RAG, Memory, and OKX market snapshot without a login wall.
2. Worker continuously ingests OKX SWAP ticker snapshots.
3. User asks for a market summary in free-form chat.
4. Agent calls market, RAG, and memory tools, then stores trace and report.
5. User reviews the report from `/harness`; privileged sharing or mutation actions stay outside the primary workbench and require admin-authenticated API/CLI paths.
6. User creates auditable strategy research records and Backtrader backtests through API/CLI workflows.
7. Developer runs `hypertrade` for a standalone terminal Agent, or `hypertrade --remote <url>` to connect to a deployed API.

## Post-Sprint-44 Capability Roadmap

The next development phase is split into parallel contracts under
`docs/contracts/sprint-45-*` through `docs/contracts/sprint-54-*`. The governing
design document is `docs/architecture/18-hypertrade-capability-roadmap.md`.

The roadmap keeps BitPro as the trading-system platform while HyperTrade grows
its own Agent capabilities:

- Agent runtime reliability and tool policy
- structured strategy evidence
- evidence-driven strategy iteration
- multi-source market intelligence
- risk and governance policy
- report provenance
- monitoring and alerts
- frontend operator console
- Agent evaluation suite
- connector framework

## Approved Post-Sprint-80 Research Institution Roadmap

The next proposed strategy-research phase is governed by
`docs/architecture/23-autonomous-strategy-research-institution.md` and the
Sprint 81–84 contracts. It develops an operator-controlled, evidence-bound
research institution on top of the existing BitPro lifecycle integration:

- Sprint 81: research mandates and durable jobs define what an Agent may
  research and keep work state outside chat history.
- Sprint 82: a bounded BitPro backtest matrix validates dynamic DB strategies
  against real data and locked out-of-sample windows.
- Sprint 83: passing candidates require a human-approved, idempotent BitPro
  paper-promotion action and remain under read-only observation.
- Sprint 84: WorldState/portfolio review combines strategy lifecycle evidence
  with market-state and monitoring evidence to recommend research or review
  actions.

This roadmap does not promise stable profitability and does not add automatic
live trading, automatic live promotion, direct BitPro database access, or
BitPro business logic to HyperTrade.

## Approved Post-Sprint-95 Agent Research OS Roadmap

The approved Sprint 96–105 phase is documented in
`docs/architecture/27-agent-research-os-roadmap.md`, with implementation-level
contracts in `docs/contracts/sprint-96-*` through `docs/contracts/sprint-105-*`
and the cross-sprint technical design in
`docs/architecture/28-agent-research-os-technical-design.md`.

It keeps the Sprint 81–94 research, BitPro, paper-observation, governance, and
isolated-evaluation boundaries intact while adding:

- durable Agent sessions, tasks, checkpoints, control actions, and resumable events;
- a role-scoped multi-Agent research graph whose outputs use a structured evidence contract;
- immutable experiment fingerprints and bounded robustness validation;
- Research OS recovery, evidence, budget, and tool-safety evaluation;
- an optional TUI over the same API/event contracts as CLI and Web;
- bounded background research triggers, governed Memory/Skill changes, and
  read-only portfolio lifecycle review.

This phase entered implementation with Sprint 96 on 2026-07-14. It does not enable automatic paper
promotion, automatic live trading, automatic capital allocation, arbitrary
Agent code execution, or any bypass of BitPro MCP and existing approval gates.

Sprint 97 entered implementation on 2026-07-14 after Sprint 96 production
acceptance. Its active boundary is the append-only Research Evidence V2 contract;
the multi-Agent role graph remains deferred to Sprint 98.

Sprint 98 completed implementation and production acceptance on 2026-07-14.
The fixed 13-role LangGraph DAG uses durable Task/Node/Event/Checkpoint state,
Evidence V2-only outputs, read-only role-policy intersections, atomic budgets,
bounded provider/BitPro concurrency, safe-point controls, failed-node replay,
and a trusted StrategySpec handoff to the existing ResearchOrchestrator queue.
Invalid provider JSON receives one repair attempt and then becomes an explicit
data gap; it is never stored as evidence. No role can invoke paper/live writes,
and the graph cannot promote a candidate or allocate capital.

Sprint 99 completed implementation and production acceptance on 2026-07-14.
Every orchestrated experiment now receives a canonical `ExperimentManifestV1`
fingerprint before BitPro strategy/backtest writes. Immutable manifests are separated
from append-only executions and evidence links; same-fingerprint requests reuse one
physical execution, failed/forced attempts retain an audit reason, and bounded BitPro
refs, metrics, artifact hashes and usage remain queryable through API and `/ledger`.
Raw data, secrets, full prompts and private reasoning are excluded. Robustness selection
remains deferred to Sprint 100, and no paper/live permission changed.

Sprint 100 completed implementation and production acceptance on 2026-07-15.
Bounded locked-OOS, walk-forward, parameter-neighborhood, cost/slippage and optional
regime scenarios produce explicit passed/failed/unknown/not-applicable gates and a
persisted validated/rejected/needs_data/needs_review result. Every scenario is tied to
the immutable experiment ledger and BitPro job/result refs. Strategy code must pass
BitPro's sandbox plus deterministic runtime smoke before creation; failed or incomplete
backtests fail closed. Paper promotion now requires a validated result but remains an
explicit human action. Unbounded optimization, profitability claims, raw-result
persistence, automatic paper/live promotion and capital allocation remain excluded.

Sprint 101 completed implementation and isolated acceptance on 2026-07-15 after
Sprint 100 production acceptance. It extends the required offline evaluation gate across Task recovery,
multi-Agent role ordering, Evidence V2 integrity, experiment reproducibility,
robustness decisions, budgets, privacy and pre-dispatch tool safety. Authored golden
cases and deterministic fault injection run locally; provider-backed Promptfoo/Ragas
baselines remain restricted to the explicit Sprint 94 isolated target. Evaluation
scores cannot authorize paper/live actions or use profitability as a quality score.
The required suite now passes 38 cases, including 24 versioned Research OS cases;
Promptfoo passes six attacks with zero dispatch, and two complete provider-backed
baselines expose the generic Agent's low Research Graph alignment without hiding it.
All optional evaluation dependencies execute in a separate locked Docker target and
final artifacts contain no prompts, reports, tool arguments, raw outputs or credentials.

Sprint 102 completed implementation and production acceptance on 2026-07-15. It adds an optional Textual TUI
that projects the durable Session/Task/Event/Evidence/Experiment/Validation contracts
and reconnects from a cursor after SSE loss. The client contains no trading, approval,
budget or state-transition business logic: every mutation remains an authenticated API
request with reason and idempotency, and dangerous actions require an explicit modal.
The existing chat CLI, plain renderer and Web Harness remain supported.
Textual is pinned at 8.2.8 in a separate optional/client image. REST-first snapshots,
cursor SSE replay/deduplication, gap-triggered reconciliation, responsive 80/120/160
column layouts and reason-required control modals are covered by headless and client
tests. Production API/Worker images do not contain the UI dependency.

Sprint 103 completed implementation and production acceptance on 2026-07-15. It adds persistent background
research triggers for bounded schedules and already-committed regime, drift, data
quality and evaluation facts. Production and isolated runtimes remain disabled by
default. A trigger can create only a budgeted `triggered_research` Task after feature
flag, kill switch, mandate, lease, fingerprint dedupe, cooldown and quota checks; it
cannot call any BitPro, paper, order, approval or capital-allocation adapter. Trigger
decisions are immutable, event projections are schema-bounded, scheduled claims use
PostgreSQL row locks/leases, and API/CLI/TUI controls require administrator authority
and operator reasons. Production migration `0016_research_triggers` is active while
the worker feature remains explicitly disabled.

Sprint 104 completed production acceptance on 2026-07-15. Governed Memory assertions require active Evidence V2 sources and explicit
review; conflicts, supersession and expiry remain queryable while ordinary Memory reads
fail closed. Code-free Skill definitions pass schema/static policy, a HMAC-authenticated
isolated regression attestation and independent administrator approval before an
immutable version can become active. The role loader rechecks release hash, schema,
role and tool-policy intersection and injects template metadata only. It cannot execute
Python/shell, register endpoints/tools or widen paper/live permission. API, CLI, TUI and
Web review surfaces contain no alternate state transition logic.

Sprint 105 completed implementation and production acceptance on 2026-07-15.
`portfolio_assessment.v2` persists canonical request/policy/content hashes, bounded source
refs, per-strategy lifecycle projections, pairwise aligned-return summaries, explicit
unknowns and six fixed research/review recommendations. Request and review idempotency keys
are bound to their canonical payloads. Human accept/reject/hold writes only a review ledger;
the portfolio module imports no BitPro/paper/live mutation adapter. API, CLI, Textual and
Web are thin projections of the same service. It cannot allocate capital, rebalance,
pause/start strategies, promote to live, place orders, or overwrite historical facts.
Production intentionally returned `needs_data` with an explicit unknown when no StrategyCard
was available; it emitted no recommendation and no human review rather than inventing inputs.

## Approved Post-Sprint-105 Research Operations Roadmap

The approved planning sequence is documented in
`docs/architecture/29-research-operations-shadow-portfolio-roadmap.md`. Sprint 106
completed production acceptance on 2026-07-15. Two isolated 26-case runs passed
`agent_research_quality.v2` route/source/citation/Task/Graph/safety gates with zero unsafe
dispatch, bounded candidate tools and a single fail-closed repair. Sprint 107 moved StrategyCard creation from the
PaperPromotion boundary to the StrategySpec/ExperimentManifest lifecycle and adds stable
lineage/version/incomplete projections; Gate F passed production acceptance. Sprints 108–110 add bounded portfolio evidence
windows, human-reviewed Champion–Challenger paper cohorts and execution-isolated Shadow
Portfolio proposals. None of these phases promises profitability or enables automatic
paper/live promotion, capital allocation, rebalance or orders.

Sprint 108 completed production acceptance under
`docs/contracts/sprint-108-portfolio-evidence-data-plane.md`.
Observation windows use only bounded BitPro MCP reads and persist source-bound statistical/quality
summaries, never complete equity/return/position/trade/order series. Missing or unhealthy sources
remain explicit unknowns and cannot trigger paper, live, order or capital actions.
The production three-Card denominator retained two no-window candidates and one available bounded
window; raw-series key audit and execution-side count comparisons passed.

Sprint 109 completed production acceptance under
`docs/contracts/sprint-109-champion-challenger-paper-incubation.md`. Cohorts consume committed
Card/Manifest/Observation summaries only, require exact comparison keys, retain every rejected or
unknown candidate in the denominator, and make all expiring labels human-review facts with no
paper/live/order/capital authority. Production retained three Cards but returned 0 comparable
members and 0 proposals, with idempotent replay and unchanged execution-side counts. Gate G is
closed; Sprint 110 adds only execution-isolated Shadow Portfolio proposals and review facts.

Sprint 110 completed production acceptance under
`docs/contracts/sprint-110-shadow-portfolio-capital-governance.md`. It consumes only immutable,
accepted and unexpired cohort evidence; compares a fixed set of bounded templates; preserves all
excluded members and unknowns; and makes every scenario/order impact explicitly hypothetical.
Neither proposal build nor human review has paper, live, order or capital authority. Production
retained three intake members but returned 0 eligible/0 scenarios because no accepted comparable
cohort exists; repeated build was idempotent, persisted no execution payload keys and changed no
paper/live counts. Gate H and the Sprint 106–110 research-operations route are closed.

## Active Professional Agent Runtime V2 Roadmap

Sprint 111 completed production acceptance on 2026-07-15. The new `hypertrade.runtime` Mission core is an
independent source of truth and does not dual-write legacy Task/Run state. Execution remains behind
`MISSION_RUNTIME_ENABLED`, off by default, and the initial capability is read-only. The implemented
technical boundary is documented in
`docs/architecture/31-professional-agent-runtime-v2-technical-design.md`.

The proposed Sprints 111–116 sequence is documented in
`docs/architecture/30-professional-agent-runtime-v2-roadmap.md`. Existing AgentKernel, Task OS and
fixed Research Graph internals are not compatibility constraints: proven domain facts, external
contracts and safety policies remain, while weak orchestration/state/UI code may be replaced and
deleted. The new runtime adds a durable Mission aggregate, immutable Plan versions,
validated Step observations, bounded adaptive replanning, reviewed capability discovery, compiled
Context Packs, a Mission Artifact Index, bounded multi-Agent supervision, sandboxed strategy
development and long-horizon readiness evaluation.

Migration uses vertical cutover without dual writes; historical runs remain read-only, and every
Sprint includes an explicit legacy deletion budget. The roadmap is planning-only until explicitly approved. The first draft contract is
`docs/contracts/sprint-111-professional-agent-loop-v2.md`; no feature flag is enabled and no current
paper/live/order/capital permission changes. Professional Agent capability means controllable,
recoverable and evidence-backed goal execution, not unrestricted autonomy or profitability.

Sprint 112 replaces direct Mission tool dispatch with a reviewed, versioned Capability Catalog and
`ToolObservationV2` boundary. Definitions bind JSON Schemas, source owner, health/freshness, side
effects, approvals, idempotency, timeout, result bounds and contract/policy hashes. Discovery creates
pending proposals only; authenticated idempotent administrator review is required before activation.
Execution validates schemas and permission scope before and after the adapter call, applies bounded
timeout/circuit recovery and stores only redacted/truncated SQL observations with provenance. The
initial catalog remains read-only and changes no paper, live, order or capital permission.

Sprint 113 compiles a deterministic, hard-budgeted Context Pack for every Mission Step and records
stable include/drop decisions for each source. Objective, constraints, permission, Plan and Step
contracts are mandatory; prior observations enter only as bounded summaries and provenance refs.
The Mission Artifact Index binds content hashes, versions, producers, source relations and stable
external refs or bounded safe previews. Completion rejects forged, cross-Mission, unavailable or
superseded artifact refs. Raw BitPro series, credentials, full transcripts and private reasoning are
forbidden from both stores.

Sprint 114 adds a bounded Multi-Agent Supervisor over four reviewed read-only roles. Independent
assignment DAG nodes may run concurrently only after atomic token/tool/model/duration reservation;
dependencies run in later layers and role/team concurrency is hard-limited. Handoffs are structured,
source-bound and content-hashed. Contradictory claims create an immutable Conflict ledger and remain
explicit unknowns in merge output. Dynamic teams are disabled by default and cannot add write,
paper, live, order or capital permissions.

Sprint 107 implementation uses `ExperimentManifest` as the StrategyCard V2 identity boundary.
Mandate-scoped lineages, Manifest-bound versions, immutable content-hashed snapshots and human
lifecycle decisions are projection facts in `0019`; they cannot edit source facts or authorize
execution. The research funnel denominator is the Manifest candidate set, including incomplete
and rejected candidates rather than only PaperPromotion records.
Production reconciliation proved a fixed three-Manifest denominator, stable one-lineage/three-version
identity and idempotent three-snapshot projection without changing PaperPromotion, paper order or
live-order-intent counts.

## V1 In Scope

- Harness routing: sidebar destinations are independent, refreshable SPA paths
  (`/harness`, `/harness/strategy`, `/harness/portfolio`, `/harness/alerts`,
  `/harness/runs`, `/harness/quality`, `/harness/memory`, `/harness/rag`) rather
  than hash-scroll targets in one
  long workbench view.
- Harness visual system: every routed workbench page uses a dark observability
  console with green-black surfaces, restrained grid texture, cyan runtime
  state, amber audit emphasis, and red risk state. This is display-only and
  does not alter research, approval, paper, or live-execution behavior.
- Harness Memory observability: `/harness/memory` aggregates existing audited
  active Memory items client-side into explicitly labeled composition, creation
  cadence, importance, confidence, and reuse visualizations. It is read-only;
  it does not introduce a storage quota, a second Memory store, or a mutation
  path.
- Harness route context metrics: every routed page shows a compact, read-only
  metric-card strip derived from the data already loaded for that surface. The
  workbench retains global telemetry; strategy, alerts, runs, Memory, and RAG
  show their own scoped evidence, state, or inventory counts.
- Harness operator cards: strategy evidence, monitor alerts, approval intents,
  Memory entries, and RAG hits use one shared dark card treatment with explicit
  semantic rails. Passing/normal state is signal, evidence or pending review is
  brass, and high-risk or final failed state is danger; the UI does not infer a
  new risk decision from the visual tone.
- Harness strategy card hierarchy: strategy summary, performance metrics,
  provenance references, failure reasons, next-experiment guidance, and evidence
  drilldown rows all use the compact operator-card variant. Nested cards remain
  visually quieter than their selected evidence card, with source-bound tone
  only and no backend or validation behavior change.

- FastAPI backend with public workbench observability/read endpoints and admin session auth for privileged mutations.
- LangGraph-style AgentKernel with explicit traceable tool calls.
- DeepSeek default provider configuration.
- Qwen embedding configuration path and pgvector schema.
- PostgreSQL job table and worker process.
- OKX SWAP market ingestion: WS tickers + REST fallback/supplements.
- RAG scanner over `docs/knowledge`.
- Audited memory writes with disable/delete support.
- React `/harness` and market summary UI.
- Docker Compose and host Nginx deployment on ports `3333/3334`.
- Sprint 03 strategy research and Backtrader backtest workflow with persisted Markdown/JSON reports.
- Sprint 05 standalone hybrid CLI runtime with local AgentKernel mode and remote API mode.
- Sprint 06 CLI slash commands for status, tools, runs, memory, strategy research, and backtests.
- Sprint 07 CLI shortcuts `/research` and `/backtest` for strategy workflow triggers.
- Sprint 08 LLM-driven `AgentPlanner` using DeepSeek function calling; when no
  chat provider is configured, free-form Agent runs return a provider-unavailable
  report instead of guessing a tool route.
- Sprint 09 exact `market_ticker` tool for any listed OKX USDT SWAP symbol or instrument id.
- Sprint 10 `market_candles` tool for recent OKX candles and deterministic trend features.
- Sprint 11 `market_compare` tool for multi-symbol relative strength ranking.
- Sprint 12 CLI/API run streaming with run and tool progress events.
- Sprint 13 live OKX candle input for Backtrader backtests.
- Sprint 14 Agent acceptance tests for tool selection, traceability, RAG, Memory, strategy research, backtesting, and output quality.
- Sprint 15 deterministic CLI market shortcuts and clearer Agent run status display.
- User-directed Operator Console: CLI welcome output prioritizes selected
  provider/model, explicit Mainnet blocking, natural-language research tasks,
  and status/review/approval controls instead of a catalog of tool shortcuts or
  paper mutations. The production deployment can select Codex using a
  server-local read-only OAuth secret without changing the project-level local
  default or committing credentials.
- Sprint 16 structured CLI report rendering that prefers JSON/trace payloads over raw Markdown when possible.
- Sprint 17 Rich CLI renderer for terminal panels/tables with plain text fallback.
- Sprint 77 CLI Flight Recorder: `HYPERTRADE_TRACE=summary|full` renders
  redacted provider/model, Token, latency, tool, Memory, and trace evidence;
  `/run <run_id>` reopens a persisted local or remote Agent run.
- Sprint 78 CLI market-answer quality: generic market prompts prefer
  `market_summary`, WorldState defaults to a compact conclusion, and the host
  wrapper selects Rich output for interactive terminals. Known read-only
  global-market calls are not policy-denied, interactive CLI output prioritizes
  the Agent conclusion, and WorldState audit blocks remain opt-in.
- Sprint 80 paper strategy performance matrix: simulated-strategy ranking uses
  one bounded read-only tool, accepts only strategy-id-matched dashboard
  evidence, ranks reported paper returns, and exposes complete/partial coverage
  instead of inferring a winner from incomplete data.
- Sprint 81 research control plane: operator-authenticated mandates persist
  scope, budgets, validation windows, manual paper promotion, and disabled live
  mode. The Agent can read a mandate and generate only a schema-valid draft;
  durable idempotent jobs have auditable transitions but no scheduler, BitPro
  write, paper action, or live action.
- Sprint 82 BitPro backtest matrix: an admin-triggered, resumable worker
  preflights BitPro, requires real chronological K-line coverage and validated
  dynamic DB strategy code, then records a bounded in-sample/validation/locked
  out-of-sample matrix. Missing results or metrics fail closed; passing evidence
  remains `evidence_recorded` and cannot configure or start paper/live trading.
- Sprint 83 paper promotion and observation: one passing
  `ResearchExperimentEvidence` can create a `pending_paper_approval` record.
  Only an authenticated administrator providing a reason and unique idempotency
  key may configure/start its linked BitPro strategy. The resulting paper
  session is observed through dashboard, events, equity, monitor snapshots,
  and identity-scoped performance evidence. Data gaps become
  `paper_degraded`; alerts become `paper_review_required`; neither condition
  auto-pauses, retires, or reaches a live path. Agent-originated paper
  lifecycle writes are blocked by governance.
- Sprint 84 regime-aware portfolio review: a read-only `StrategyCard` projection
  joins mandate, validation, paper-promotion, and monitor evidence into the
  WorldState portfolio view. It returns only source-bound review actions and
  explicit unknown/data-gap states; it never mutates paper sessions, risk
  budgets, allocations, or live execution.
- Sprint 85 uses BitPro's immutable read-only `paper_snapshot` as the primary
  strategy-scoped paper-evidence source; no Agent or portfolio path may turn
  that evidence into a lifecycle write.
- Sprint 79 CLI unified report rendering: completed Agent answers take
  precedence over report-block/audit dumps in default output, while explicit
  tool/audit modes preserve the structured evidence. Simulated-strategy
  rankings must disclose when BitPro lacks per-strategy PnL/drawdown evidence.
- Sprint 18 paper-trading CLI controls for status, pause, and resume.
- Sprint 19 BitPro archived SQLite K-line source for Backtrader backtests.
- Sprint 20 paper close/reset lifecycle controls.
- Sprint 21 live/testnet order intent approval gate.
- Sprint 22 frontend harness parity for market tools, paper controls, and live approval.
- Sprint 23 Markdown report, Memory details, and complete backtest form UX.
- Sprint 24 graph-style Agent runtime with observable graph nodes and run state.
- Sprint 25 provider router and session model switching.
- Sprint 26 RAG v2 citation-ready search through pgvector-compatible storage.
- Sprint 27 Memory v2 with policy fields, dedupe, search, tags, and audit metadata.
- Sprint 28 RiskEngine for live/testnet order intents.
- Sprint 29 OKX Testnet signed order execution after approval and risk check.
- Sprint 30 multi-step strategy experiment workflow.
- Sprint 31 deterministic Agent eval suite and operations runbooks.
- Sprint 32 production-oriented project positioning and BitPro API tool-surface contract.
- Sprint 33 initial BitPro MCP adapter: capability/health preflight, K-line data direct access, paper dashboard reads, live-position diagnostics, API endpoints, Agent tool schemas, and `bitpro_mcp` backtest candle source.
- Sprint 34 BitPro strategy lifecycle Agent tools: strategy search/generation/creation/update, BitPro-owned backtest job start/status reads, and paper/simulation configure/start/pause/resume/stop with live-write tools still blocked.
- Sprint 35 strategy evidence loop: `/experiment <prompt>` now compares baseline, fast, and conservative variants, persists each backtest as evidence, selects a winner through explicit gates, and proposes the next adjacent experiment.
- Sprint 36 BitPro backtest detail artifacts: `bitpro_backtest_get_result` reads one BitPro-owned result, normalizes metrics and bounded equity/trade/order/fill/drawdown samples, and reports missing artifacts as unavailable.
- Sprint 37 BitPro paper monitor summary: `bitpro_paper_dashboard` produces current dashboard metrics, running strategy coverage, alerts, data gaps, and read-only recommended actions.
- Sprint 38 CLI command history: real TTY `hypertrade` chat sessions use readline-backed history so arrow keys recall previous prompts instead of printing escape sequences.
- Sprint 39 CLI semantic colors: real TTY output colors commands, tools, categories, approvals, status, success, warning, and error text while scripts and `NO_COLOR=1` remain plain.
- Sprint 40 strategy knowledge memory: completed local strategy experiments now persist a source-bound `strategy_knowledge` memory item with winner, parameters, metrics, gates, data selection, and next-experiment guidance.
- Sprint 41 documentation refresh: README, docs index, knowledge guides, architecture notes, testing plan, and runbooks describe the current Agent, BitPro MCP, strategy knowledge, and deployment validation paths.
- Sprint 42 BitPro paper evidence layer: `bitpro_paper_events` and `bitpro_paper_equity_curve` read bounded event/error and equity/drawdown evidence for paper monitoring, with structured Agent/CLI reports.
- Sprint 43 BitPro paper monitor snapshots: `bitpro_paper_monitor_snapshot` persists read-only paper dashboard/event/equity summaries, compares each capture with the previous snapshot for the same scope, and reports drift alerts/data gaps.
- Sprint 44 strategy library memory: `strategy_knowledge` Memory cards are aggregated into strategy-level evidence summaries through `StrategyLibraryService`, `GET /api/strategy/library`, CLI `/strategy library`, Agent tool `strategy_library_search`, and ToolRegistry entry `strategy.library_search`.
- Sprint 51 monitoring and alerts: monitor definitions, monitor runs, and alert events persist read-only BitPro paper, strategy-library freshness, and connector-health checks; API/CLI surfaces list monitors, run one monitor manually, and inspect recent alerts without calling paper/live write tools.
- Sprint 48 multi-source market intelligence: Agent tool `market_intelligence`
  reads OKX public funding/open-interest evidence plus deterministic curated
  market context, normalizes provenance/freshness/missing-field fields, and
  renders a compact `市场情报` report section as context rather than advice.
- Sprint 49 risk governance policy: `RiskGovernancePolicy` enforces
  ToolRegistry scope/approval/idempotency metadata before Agent tool execution,
  denies write-like external actions without `idempotency_key`, records
  `policy_decision` trace payloads, and renders clear governance denial reasons.
- Sprint 53 Agent evaluation suite: deterministic eval cases now guard
  strategy-library source use, BitPro page-parity result metrics, missing
  artifact disclosure, paper-monitor read-only behavior, and compact/default
  report rendering in addition to the original tool/RAG/Memory/risk checks.
- Sprint 54 connector framework: trusted in-repo connectors expose redacted
  capability/auth/tool metadata through `ConnectorRegistry`,
  `GET /api/connectors/capabilities`, `/api/harness/overview.connectors`, CLI
  `/connectors`, and ToolRegistry connector-origin rows; BitPro is represented
  through a compatibility connector and fixture connectors support
  deterministic tests.
- Sprint 46 strategy evidence schema: new `strategy_knowledge` cards store versioned `StrategyEvidence` JSON payloads while `StrategyLibraryService` remains backward compatible with legacy text cards.
- Strategy iteration planning can read prior strategy-library evidence through `strategy_experiment_plan`, `/api/strategy/experiments/iterate`, and CLI `/experiment iterate <prompt>` without triggering paper, live, or BitPro write tools.
- Sprint 55 CLI slash command candidates: incomplete slash prefixes such as `/st` or `/me` render filtered candidates with purpose descriptions, and readline Tab completion can display the same described candidate list.
- Sprint 56 market heat summary: broad market heat/sentiment/breadth prompts route to `market_summary`, compute OKX SWAP breadth metrics, and render a conclusion before raw ticker details.
- Sprint 58 Codex provider runtime: `codex`/`openai-codex` routes chat/planner
  calls through the Codex Responses API while HyperTrade keeps tool execution,
  policy, trace, RAG, and Memory inside its own Agent runtime.
- Sprint 60 monitor scheduler worker: default monitor definitions have
  conservative interval schedules, and the worker can run due monitors
  automatically while preserving the same read-only BitPro/tool boundary as
  manual monitor runs.
- Sprint 61 CLI Codex model picker: interactive `/model` renders numbered
  provider choices and, for Codex, a numbered model list backed by
  `CODEX_MODEL_OPTIONS`; API provider selection can carry a validated session
  model override without exposing tokens.
- Sprint 62 live order-history tool coverage: planner guidance and read-only
  BitPro diagnostics let real-account order-history prompts such as
  `我的实盘最近的一笔订单是什么` render `BitPro 实盘订单` evidence instead of
  falling back to all-market reports.
- Sprint 63 CLI selectable candidates: slash command and slash argument
  candidate lists render stable numbers, and interactive chat can dispatch a
  selected candidate directly by number.
- Sprint 64 Codex GPT-5.5 option: the default Codex model allowlist includes
  `gpt-5.5` between `gpt-5.4` and `gpt-5.4-mini`, while `CODEX_MODEL` remains
  the default selected model.
- Sprint 65 live strategy performance tool coverage: planner guidance and
  read-only BitPro diagnostics let real-account strategy performance prompts
  such as `看下实盘收益最高的策略` read BitPro `/live/strategies`, rank by
  `return_pct`, render `BitPro 实盘策略收益`, and avoid OKX all-market fallback.
- Sprint 67 LLM planner routing: free-form natural-language Agent prompts no
  longer use keyword branches or hidden market fallbacks in `AgentKernel`.
  Configured providers own semantic tool selection through `AgentPlanner`; no
  provider means an auditable provider-unavailable report with no business tool
  calls.
- Sprint 68 live BitPro routing evals: `/evals` includes live order-history and
  live strategy-performance guardrails that require the matching BitPro
  diagnostic tools and fail generic market-report fallbacks.
- Sprint 69 README framework guide: the root README is the public framework
  entrypoint, covering architecture, component responsibilities, installation,
  usage recipes, API/CLI examples, configuration, deployment, verification,
  troubleshooting, and development workflow.
- World-model development roadmap: `docs/architecture/22-world-model-development-roadmap.md`
  splits LeCun-style world-model thinking into HyperTrade phases: read-only
  global `WorldState`, scenario decision, defensive automation, and portfolio
  scheduling. The market state is global and cross-asset rather than only
  crypto; early phases remain read-only or human-confirmed.
- Sprint 71 read-only WorldState snapshot: `GET /api/world-model/snapshot`
  and Agent tool `world_model_snapshot` expose a global operator state across
  `global_market`, `crypto_market`, strategy evidence, execution state, tool
  health, deployment state, source references, missing data, and L0/L1
  candidate actions. Cross-asset feeds that are not wired yet are reported as
  `missing_data`; the Agent must not substitute `market_summary` for global
  WorldState prompts.
- Sprint 72 scenario decision layer: `world_model_snapshot` also returns
  deterministic `action_scenarios` and a `decision` record. Scenario scores show
  expected benefit, downside, confidence, data-gap penalty, reversibility,
  execution complexity, policy status/result, review window, and expected
  follow-up evidence for observe/hold/monitor/trace/human-confirmation/pause
  request/risk-reduction request actions. Scenario evaluation is still read-only
  and must not call paper, BitPro lifecycle, Testnet, or live write tools.
- Sprint 73 defensive automation gate: defensive automation is disabled by
  default and can run only explicitly allowlisted actions with idempotency keys.
  `raise_human_confirmation_alert` is the initial safe fixture action; all
  attempts are recorded through trace-backed audit and, when executed, an
  internal monitor alert. Missing idempotency, unsupported actions, offensive
  actions, stale evidence, and non-allowlisted requests are rejected without
  calling adapters or exchange paths.
- Sprint 74 portfolio scheduler: `world_model_snapshot` and
  `GET /api/world-model/portfolio` expose a rule-based portfolio view with
  strategy groups, allocation/risk-budget labels, evidence freshness, recent
  performance labels, drawdown availability, regime fit, correlation/shared
  exposure proxy, active status labels, portfolio recommendations, and
  missing-evidence markers. The scheduler recommends review, observation,
  targeted backtests/experiments, or defensive requests; it does not perform
  live allocation changes or offensive strategy promotion.
- Sprint 76 Agent Flight Recorder: provider-reported input/output/cached/reasoning
  Token usage is normalized across OpenAI-compatible Chat Completions and Codex
  Responses. Each planner model call records trace-safe iteration, route,
  latency, tool-call count, and usage without storing private reasoning text.
  `GET /api/agent/runs/{run_id}/observability` projects an ordered graph/model/
  tool/policy/Memory timeline, `/api/harness/overview.observability` aggregates
  recent-run telemetry, and `/harness` renders the componentized Flight Recorder.
- Sprint 92 Agent evaluation foundation: deterministic `/evals` remains the CI
  gate; an explicit evaluation mode rejects every write-like tool before
  dispatch, self-hosted Langfuse receives metadata-only trace projections when
  opt-in, and Promptfoo/Ragas run only against isolated evaluation targets and
  sanitized trajectories.
- Sprint 93 Agent golden baseline: a committed 24-case, authored and
  privacy-safe task set covers market, knowledge, Memory, strategy, BitPro,
  World Model, and write-attempt safety. An isolated-only runner produces a
  prompt-free diagnostic baseline for tool accuracy/F1, citation coverage,
  denial evidence, latency, and tokens; it does not gate deployment.
- Sprint 94 isolated evaluation deployment: a server-side `hypertrade-eval`
  runtime uses its own API, PostgreSQL container, network, loopback-only port,
  data path, and server-only configuration. It has no production BitPro data
  mount, Nginx route, paper/monitor worker by default, or production database.
- Sprint 95 production-readiness evaluation: attempted isolated provider-backed
  golden baselines, adversarial safety checks, deterministic-gate evidence, and
  a primary-source comparison with representative trading-Agent and
  production-quant systems are documented as diagnostic evidence. Incomplete
  provider or framework runs remain explicit findings; the review does not
  claim comparable trading performance or authorize live trading.
  It is logical isolation on the current host; a separate VM is required for
  physical isolation.
- Sprint 96 Agent Session and Task OS: every new local/API Agent run is backed
  by a durable Session/Task, while `AgentRun` remains one immutable execution
  attempt. PostgreSQL leases, heartbeat, checkpoints, cursor events, bounded
  budgets, idempotent controls, worker recovery, REST/SSE, and CLI inspection
  form one canonical control plane. Provider timeouts become structured
  retryable Task errors; they do not escape as an uncaught HTTP 500. Existing
  paper/live approval and BitPro MCP boundaries are unchanged.
- Sprint 97 Research Evidence V2: append-only facts, inferences,
  counter-evidence, and data gaps use one canonical UTC/Decimal hash contract.
  Facts require available non-Memory sources; inferences require active support;
  conflicts, expiry, rejection, and supersession remain queryable. Existing
  experiment/StrategyEvidence/Memory records are read-only legacy projections,
  and all V2 mutations remain administrator-only trusted-service operations.
- BitPro MCP Agent Token alignment: HyperTrade mirrors BitPro `agent_auth`, `remote_mcp`, scope classes, token-management routes, idempotency requirements, and live-diagnostic grouping while keeping token plaintext server-side only.
- CLI slash command discovery: entering `/` displays the command list, and interactive readline sessions support Tab completion for slash commands and common subcommands.
- BitPro backtest result reads through `bitpro_backtest_list_results`, including total-return threshold filters and page-parity reporting based on BitPro-owned result records.
- BitPro external API adapter contract for backtest data, base market data, paper/simulation state, and live trading state without copying BitPro business logic.

## V1 Out of Scope

- Mainnet live order execution. Mainnet intent creation may be audited, but execution is blocked.
- Automatic investment advice or unattended real-money trading.
- Milvus/Qdrant production vector clusters.
- Large parameter optimization sweeps and live/Testnet order generation from backtest results.
- Direct BitPro database access or copied BitPro trading logic; HyperTrade consumes BitPro capabilities only through explicit API contracts.

## Acceptance

- `./scripts/check.sh` passes.
- `GET /api/health` returns OK.
- `/harness` loads a simplified core workbench without rendering a login form: Agent run creation, report reading, recent runs, trace events, Flight Recorder Token/latency/Memory telemetry, RAG search, Memory search/detail, OKX top movers, and core telemetry.
- Advanced provider switching, paper lifecycle controls, live approval/execution, strategy lab/backtest forms, eval panels, Feishu send, and Memory disable are not first-class `/harness` UI controls.
- Privileged mutations such as provider selection, paper lifecycle control, live order approval/execution, Memory disable, and Feishu send still require admin session auth.
- `/api/harness/tools` shows live order approval gating.
- User can create an Agent market-summary run and inspect trace events.
- User can open `GET /api/agent/runs/{run_id}/observability` or the `/harness`
  Flight Recorder to inspect ordered graph/model/tool/policy/Memory events,
  provider-reported Token usage, tool latency, and linked Memory ids. Missing
  provider usage is marked unavailable rather than estimated, and prompts,
  secrets, and private reasoning text are not copied into the projection.
- User can call `GET /api/world-model/snapshot` or ask `现在全局状态怎么样`;
  the Agent uses `world_model_snapshot`, reports source refs and missing
  cross-asset data, and does not call paper, BitPro lifecycle, Testnet, or live
  write tools from the snapshot path.
- User can ask `现在应该继续持有还是降低风险`; the Agent can compare
  `action_scenarios`, show `decision` and `policy_status`, and prefer
  observation or human-confirmation when cross-asset data gaps are still large.
- Admin can inspect `GET /api/world-model/defensive-actions` and
  `GET /api/world-model/defensive-action-attempts`, and can execute an
  allowlisted defensive action through
  `POST /api/world-model/defensive-actions/execute` only when
  `WORLD_MODEL_DEFENSIVE_ACTIONS_ENABLED=true`,
  `WORLD_MODEL_DEFENSIVE_ACTION_ALLOWLIST` contains the action, and an
  idempotency key is supplied.
- User can ask `当前应该提高还是降低哪些策略权重`; the Agent uses
  `world_model_snapshot` portfolio evidence, reports `recommendation_type`,
  `policy_status`, missing evidence, and `allocation_change_allowed=False`
  unless a later explicit live-risk contract changes that boundary.
- With a chat provider configured, user can ask `看下目前市场的热度怎么样`
  and receive a market heat conclusion with sample count, advancer/decliner
  breadth, average change, strongest/weakest symbols, and top movers rather
  than only ticker tables.
- User can ask for a specific listed OKX SWAP symbol, such as ETH/SOL/DOGE/PEPE, and the Agent can
  call the exact ticker tool instead of returning only the all-market movers list.
- User can ask for a specific symbol's recent trend and the Agent can call the candle research tool
  to return OHLCV-derived features.
- User can compare multiple listed OKX SWAP symbols and the Agent can return relative strength
  rankings.
- User can ask for funding/open-interest context, such as `看 ETH 资金费率和持仓变化`,
  and the Agent can call `market_intelligence`, show source paths, timestamps,
  metrics, missing fields, and curated context without turning it into buy/sell advice.
- User can create a strategy research record and run a deterministic Backtrader backtest.
- Developer can run `hypertrade` as a standalone CLI Agent and see run id, tool calls, and report output.
- Developer can use the production host `hypertrade` wrapper as a remote client without attaching to the long-running API service container, so deploy-time API replacement does not terminate the terminal session.
- Developer can run `hypertrade /login` or `ht /login` once on a local machine to save remote API URL, username, and password to `~/.hypertrade/client.env` with local-only permissions; later `ht` commands default to the saved remote API unless `--local` is passed.
- Developer can see run/tool progress while `hypertrade ask` or interactive chat is still running.
- Developer can keep a remote CLI Agent run open through silent long-running tools such as BitPro
  backtests; SSE stream reads do not time out merely because no progress event arrived for a while.
- Developer can see a live `Thought` / `Thinking` animation in interactive terminals while an Agent prompt is waiting for planning or tool results.
- Developer can press the up arrow in an interactive `hypertrade` chat session to recall prior prompts from the current or saved local history.
- Developer can distinguish command help, tool rows, Agent progress, success, warning, and error output by color in interactive terminals.
- Developer can use CLI slash commands such as `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in interactive chat.
- Developer can enter `/` to display slash commands and press Tab after `/` or a partial slash command to complete commands/common subcommands in real TTY sessions.
- Developer can enter a short incomplete slash prefix such as `/st` or `/me` and see filtered candidate commands with descriptions instead of a generic unknown-command page.
- Developer can enter a partial known slash argument such as `/model c` and see matching argument candidates such as `codex` instead of dispatching the incomplete argument.
- Developer can select any displayed slash command or argument candidate by
  number in interactive chat, so `/st` can run `/status` and `/model c` can
  choose `codex` without retyping the candidate.
- Developer can read a purpose description beside every `/help` slash command and every `/tools` Agent tool row.
- Developer can run CLI `/connectors` or `GET /api/connectors/capabilities` to
  inspect connector health/auth status, supported scopes, idempotency
  requirements, source-of-truth notes, and tool descriptors without exposing
  plaintext secrets.
- Developer can run `/research <prompt>` and `/backtest` from interactive CLI chat to create research and backtest records.
- Developer can run Backtrader backtests with recent OKX candles through API or CLI options.
- Developer can run Agent acceptance tests and review a documented test plan for expected tool calls, trace output, and report quality.
- Developer can run deterministic CLI market commands such as `/price`, `/candles`, and `/compare` without waiting for LLM planning.
- Developer can see readable Agent progress statuses while free-form prompts are running.
- Developer can read structured CLI report sections for market runs, and unknown Markdown reports render as terminal headings, lists, and tables in interactive/Rich mode.
- Developer can read compact CLI run output focused on the report body: run metadata and tool trace tables are hidden by default, `HYPERTRADE_TRACE=summary` shows a compact trace, and `HYPERTRADE_TRACE=full` shows the full trace for audits.
- Developer sees only compact run progress by default (`Agent: running/completed`); `HYPERTRADE_PROGRESS=full` restores per-tool progress lines for debugging.
- Developer sees BitPro paper monitoring/equity/event reports as concise conclusions plus core metrics by default; raw paper tool tables require `HYPERTRADE_REPORT_SOURCE=tools`.
- Routine market/RAG/Memory CLI outputs do not repeat a fixed investment-advice disclaimer; strategy, backtest, Testnet, live-order, or recommendation-like prompts still surface the research/risk boundary.
- Developer can enable Rich terminal rendering for structured CLI reports while keeping plain output for scripts.
- Developer can inspect and control the simulated paper runtime from CLI slash commands.
- Developer can run backtests from archived BitPro K-line data without copying BitPro business logic.
- Developer can inspect Agent graph state and graph trace nodes for each run.
- Developer can switch chat providers from CLI/API/frontend without exposing provider keys.
- Developer can run interactive CLI `/model` and select a provider by number
  rather than typing its name; selecting Codex then shows a numbered model list
  from `CODEX_MODEL_OPTIONS`, and the chosen model is used for the current
  local or remote session.
- Developer can select `codex` or Hermes-style `openai-codex` as the active
  chat provider when `CODEX_API_KEY` or `CODEX_AUTH_JSON` provides a Codex
  access token; provider status never exposes the token, and Codex does not
  execute HyperTrade tools or approval decisions directly.
- Developer can search RAG citations and Memory from CLI/API/frontend.
- Developer can create, approve, and execute OKX Testnet order intents after risk checks.
- Developer can run `/experiment <prompt>` to create strategy research, compare multiple backtest variants, inspect the winning evidence, and read the next experiment recommendation.
- Completed local strategy experiments are automatically searchable through Memory as `strategy_knowledge`, with source experiment/backtest ids and evidence metrics rather than unsourced strategy claims.
- Developer can run `/strategy library [query]` or `GET /api/strategy/library` to inspect grouped local strategy evidence: evidence counts, pass/fail counts, best/latest backtest evidence, variants, failure reasons, next experiments, and source Memory ids.
- Agent can use `strategy_library_search` for strategy-library/history/next-experiment questions so prior local strategy experience comes from audited `strategy_knowledge` evidence instead of model recall.
- New strategy evidence cards expose `schema_version=strategy_evidence.v1`, preserve decimal metrics as strings, keep source ids/boundaries visible, and let missing fields surface as `n/a` or empty values instead of inferred data.
- Developer can run `/experiment iterate <prompt>` or call `strategy_experiment_plan` to produce bounded candidate variants from prior strategy-library evidence before any new paper/live promotion path.
- Developer can run `/evals` or open `/harness/quality` and inspect server-scored Agent eval status for
  tool choice, source-of-truth usage, unsupported-claim guardrails,
  missing-data preservation, and compact report rendering.
- `/evals` includes live BitPro routing guardrails for
  `我的实盘最近的一笔订单是什么` and `看下实盘收益最高的策略`; these cases require the
  matching BitPro live diagnostic tools and fail if the Agent substitutes
  generic `market_summary` / `Market Report` evidence.
- Developer can run optional Langfuse, Promptfoo, and Ragas evaluation tooling
  without weakening the deterministic gate: Langfuse is disabled by default and
  receives metadata only; Promptfoo and trajectory collection require an
  isolated target with `evaluation_mode=true`, which denies every non-read
  Agent tool before dispatch.
- Developer can run `./scripts/run_agent_eval_baseline.sh` only against an
  explicitly labelled isolated API to collect the 26-case V2 golden baseline twice. The
  generated report contains aggregate diagnostic metrics only and leaves cost as
  unavailable when no reviewed normalized provider cost is reported. Fixed cohort
  denominators and route/source/graph/task/safety thresholds fail the runner closed.
- Operator can use `docs/knowledge/tool-usage-guide.md` to validate each Agent tool surface and follow related operational source-code comments.
- Operator can review the BitPro tool-surface requirements before wiring external data, backtest, paper/simulation, or live-state APIs into Agent tools.
- Operator can call BitPro read tools through HyperTrade API/Agent paths while every flow starts with `bitpro_capabilities` and `bitpro_health`.
- Operator can verify BitPro MCP Agent Token wiring from `/harness` and `/api/harness/overview`: token values stay hidden, but the auth header, token source, BitPro token-management routes, R/W/L/T scope classes, live-diagnostic group, and idempotency-required tools are visible for Agent authentication debugging.
- Developer can run backtests with `candle_source=bitpro_mcp` or `/backtest --source bitpro_mcp` to use BitPro `market_klines` data without direct database access.
- Agent can use BitPro strategy lifecycle tools to generate/create/update strategy drafts, start/query BitPro-owned backtest jobs, and configure/control paper validation while real-account write tools remain blocked.
- Agent can complete the BitPro strategy R&D loop through MCP only: `bitpro_capabilities` -> `bitpro_health` -> real K-line coverage confirmation -> `strategy_validate_code` -> `strategy_create` with DB-backed `script_content` -> optional `strategy_update` for canonical metadata/renaming -> `backtest_start_job`/result inspection -> gated `paper_configure`/`paper_start`.
- Agent can answer BitPro backtest ranking or threshold questions, such as `回测收益大于100%`, by calling `bitpro_backtest_list_results` and reporting `total_return_pct` from actual BitPro result rows instead of annualized return, strategy descriptions, memory, or inferred data.
- Agent can inspect a specific BitPro backtest result id through `bitpro_backtest_get_result`, reporting real metrics and bounded artifact availability for equity curve, trades, orders, fills, and drawdown series without inventing missing rows.
- Agent can run a named BitPro strategy backtest and return the completed BitPro result metrics from the saved result row or completed job result instead of a raw polling/lifecycle log.
- Default BitPro backtest reports are page-focused: they hide MCP contract/tool-order details, lifecycle polling logs, and RAG citation lists unless the operator explicitly asks for trace/debug evidence.
- Agent can answer BitPro paper/simulation inventory questions without mistaking the current `paper_dashboard` view for the full universe: unfiltered dashboard reads include `strategy_search(status=running)` inventory and reports distinguish current dashboard instance from all running strategies.
- Agent can summarize BitPro paper monitoring state with source-bound alerts and read-only recommended actions, while calling out missing per-strategy PnL/drawdown metrics as data gaps rather than inferred facts.
- Agent can inspect BitPro paper/simulation event streams and equity curves through read-only MCP tools, reporting event counts, error counts, latest event time, equity samples, latest equity, and drawdown evidence without synthesizing missing rows.
- Agent can capture a BitPro paper monitor snapshot through read-only dashboard/events/equity tools, persist it, compare it with the previous snapshot for the same strategy or all-strategy scope, and report PnL/equity/drawdown/error drift without triggering paper or live write tools.
- With a chat provider configured, Agent can answer live-account order-history
  questions, including `我的实盘最近的一笔订单是什么`, by having the planner choose
  read-only BitPro live diagnostics, reporting the latest returned order id,
  symbol, side, status, price/size, timestamp, and strategy attribution when
  BitPro provides it; the Agent must not use `market_summary` for these prompts.
- With a chat provider configured, Agent can answer live strategy performance
  questions, including `看下实盘收益最高的策略`, by having the planner choose
  read-only BitPro live diagnostics, ranking `/live/strategies` rows by
  `return_pct` and reporting `total_pnl` without using `market_summary`.
- Free-form natural-language Agent prompts use the configured chat provider and
  `AgentPlanner` as the semantic source of truth for tool choice. If no chat
  provider is configured, HyperTrade returns an auditable
  `provider_unavailable` result and does not guess a market, BitPro, RAG, or
  Memory route from keywords.
- Operator can run `GET /api/monitors`, `POST /api/monitors/{monitor_id}/run`, `GET /api/alerts`, CLI `/monitors`, `/monitor run <monitor_id>`, and `/alerts` to inspect persisted monitor definitions, runs, thresholds, source tools, alert events, data gaps, and recommended read-only actions.
- Operator can leave `MONITOR_SCHEDULER_ENABLED=true` so the worker persists
  due monitor runs and alert events automatically, or disable the scheduled
  path while keeping manual CLI/API monitor runs available.
- PostgreSQL migration creates business tables and pgvector extension.
- Deployment workflow runs only on `main` with SHA gating.
