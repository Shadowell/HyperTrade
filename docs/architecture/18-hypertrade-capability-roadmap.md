# 18 HyperTrade Capability Roadmap / 能力版图路线图

## Purpose

HyperTrade is not a replacement for BitPro. BitPro remains the trading-system
platform for market/reference data, strategy storage, backtest execution,
paper/simulation runtime, metrics, and future live execution.

HyperTrade owns the Agent layer above that platform:

- planning and tool calling
- research workflow design
- evidence capture and report generation
- strategy-memory and strategy-library reasoning
- risk, approval, and governance
- monitoring, alerts, and operator workflows
- connectors to other data or execution systems through stable contracts

The goal of this roadmap is to split the next work into parallel sprint
contracts that multiple Agents can implement without stepping on each other.

## Current Baseline

The latest completed implementation is Sprint 44:

- BitPro MCP read/lifecycle adapter exists.
- Strategy lifecycle tools exist for BitPro search/generate/create/update,
  backtest job start/status/result reads, and paper/simulation control.
- Local strategy experiments write audited `strategy_knowledge` Memory cards.
- `StrategyLibraryService`, `/api/strategy/library`, CLI `/strategy library`,
  Agent tool `strategy_library_search`, and ToolRegistry
  `strategy.library_search` expose grouped strategy-memory evidence.
- CLI output is report-focused by default, with `HYPERTRADE_TRACE`,
  `HYPERTRADE_PROGRESS`, and `HYPERTRADE_REPORT_SOURCE` available for audits.

Known active development caveat:

- If the working tree contains local changes, each parallel Agent must inspect
  `git status --short` before editing and must not overwrite unrelated work.

## Product Boundary

HyperTrade should do:

- Ask the right tools for source evidence.
- Normalize evidence into stable internal contracts.
- Explain missing data instead of inventing it.
- Store strategy knowledge with provenance.
- Plan next experiments from prior evidence.
- Gate writes and live-risk actions.
- Make operator review efficient.

HyperTrade should not do:

- Copy BitPro business logic or connect directly to BitPro databases.
- Treat LLM text as a source of truth.
- Auto-promote strategies to live trading.
- Hide tool calls or missing source data in polished prose.
- Bind the product to only BitPro when other read-only research data sources
  can be integrated through safe connector contracts.

## Target Capability Map

| Capability | HyperTrade Responsibility | Primary Surfaces |
| --- | --- | --- |
| Agent Runtime Reliability | Durable runs, retries, timeouts, cancellation, trace quality, tool policy | `AgentKernel`, API, CLI, trace |
| Strategy Evidence Schema | Structured strategy knowledge and migration-safe parsing | Memory, Strategy Library, reports |
| Strategy Research Loop | Evidence-based experiment planning, variant generation, result comparison | Agent tools, `/experiment`, BitPro MCP |
| Multi-Source Market Intelligence | Funding/OI/news/onchain/sentiment connector reads with provenance | Agent tools, reports, RAG |
| Risk And Governance | Permission policy, approval gates, idempotency, scope classes | Agent executor, live/testnet tools |
| Report And Provenance System | Reusable report blocks, source paths, missing-data notes, compact rendering | API, CLI, frontend |
| Monitoring And Alerts | Scheduled paper/live-read monitors, drift detection, notifications | Scheduler, run history, alerts |
| Frontend Operator Console | Strategy library, monitors, reports, approvals, trace drilldown | `/harness` |
| Agent Evaluation | Tool-choice, anti-hallucination, parity, report-quality evals | tests, `/evals`, CI |
| Connector Framework | Provider-neutral connector registry, capability discovery, secrets boundary | adapters, settings, docs |

## Parallel Sprint Plan

| Sprint | Contract | Theme | Parallel Group | Depends On |
| --- | --- | --- | --- | --- |
| 45 | `sprint-45-agent-runtime-reliability.md` | Durable Agent runtime and tool policy | A | Current baseline |
| 46 | `sprint-46-strategy-evidence-schema.md` | Structured strategy evidence schema | A | Sprint 44 |
| 47 | `sprint-47-evidence-driven-strategy-loop.md` | Evidence-driven strategy iteration | B | Sprint 46 |
| 48 | `sprint-48-multi-source-market-intelligence.md` | Non-BitPro research data connectors | A | Current baseline |
| 49 | `sprint-49-risk-governance-policy.md` | Unified risk and permission governance | A | Current baseline |
| 50 | `sprint-50-report-provenance-system.md` | Report block and provenance model | A | Current baseline |
| 51 | `sprint-51-monitoring-alerts.md` | Scheduled monitoring and alerts | B | Sprint 49, Sprint 50 |
| 52 | `sprint-52-frontend-operator-console.md` | Frontend operator console expansion | B | Sprint 46, Sprint 50 |
| 53 | `sprint-53-agent-evaluation-suite.md` | Evaluation and anti-hallucination suite | A | Current baseline |
| 54 | `sprint-54-connector-framework.md` | Generic connector/plugin framework | A | Current baseline |

Suggested parallel execution:

- Wave A can start immediately: S45, S46, S48, S49, S50, S53, S54.
- Wave B should start after the relevant contracts land or should stub against
  the documented interfaces: S47, S51, S52.

## Shared Design Contracts

### Evidence Contract

Every Agent-visible factual output should identify:

- `source_type`: tool, connector, memory, BitPro MCP, local service, or RAG
- `source_id`: stable id when available
- `as_of`: timestamp when the evidence was read or produced
- `path`: API route, tool name, memory id, run id, or document path
- `missing`: missing fields, unavailable artifacts, denied scopes, or stale data
- `confidence`: confidence in the evidence, not in market outcome

### Tool Policy Contract

Every tool should declare:

- category
- read/write/live-write scope
- approval requirement
- idempotency requirement
- source of truth
- maximum payload sample size
- failure behavior

The planner may select a tool. Trusted Python code enforces the policy.

### Strategy Knowledge Contract

Strategy knowledge is evidence, not advice.

Minimum fields:

- strategy key
- experiment id
- research id
- backtest id or BitPro result id
- variant id
- parameters
- metrics
- gate results
- failure reasons
- next experiment
- source data descriptor
- source memory id

### Report Contract

Reports should be readable by default and auditable on demand.

Default report:

- concise conclusion
- source-backed metrics
- missing data notes
- next action candidates

Audit mode:

- tool calls
- inputs
- result snippets
- source ids
- folded internal traces expanded through configuration

### Frontend Contract

The frontend is an operator console, not a marketing page.

Prioritize:

- dense but readable information
- source-backed cards and tables
- click-through evidence
- fast triage
- Chinese-first operational copy with protocol/tool names preserved

Avoid:

- decorative dashboards without workflow value
- raw JSON as primary display
- mixing simulated, paper, and live state without labels

## Agent Handoff Protocol

Each parallel Agent should:

1. Read `README.md`, `docs/spec.md`, `docs/progress.md`, this roadmap, and its
   assigned sprint contract.
2. Check `git status --short` before editing.
3. Stay inside the assigned sprint boundary.
4. Add or update tests before or alongside implementation.
5. Update `docs/progress.md` and any architecture/knowledge doc touched by the
   behavior.
6. Run targeted tests first, then `./scripts/check.sh` before claiming done.
7. Commit only files belonging to its sprint; do not stage unrelated dirty files.
8. Push to `origin/main` only after verification passes, so deployment runs.

## Cross-Sprint Integration Points

| Integration Point | Owner Sprint | Consumers |
| --- | --- | --- |
| `StrategyEvidence` schema | S46 | S47, S52, S53 |
| tool policy metadata | S45, S49 | all Agent tools |
| report block schema | S50 | S51, S52, S53 |
| connector capability registry | S54 | S48, future external systems |
| monitoring event schema | S51 | S52, S53 |
| eval fixture shape | S53 | all future sprints |

## Verification Standard

Every sprint should define:

- focused unit tests
- integration tests when API/CLI behavior changes
- report rendering tests when output changes
- at least one manual smoke path if the behavior is operator-facing
- docs update proving the boundary and source of truth

Do not mark a sprint complete if:

- a report can answer from model memory when a tool source is required
- live or paper write paths lack explicit scope/approval behavior
- missing data is silently omitted from conclusions
- a frontend view hides the source ids needed for audit

## Post-Sprint-80 Research Institution Sequence

The capability roadmap above established the reusable Agent, evidence,
governance, monitoring, connector, and WorldState foundations. The next
sequence applies those foundations to a durable BitPro strategy-research
institution. The governing design is
`docs/architecture/23-autonomous-strategy-research-institution.md`.

| Sprint | Contract | Outcome | Depends On |
| --- | --- | --- | --- |
| 81 | `sprint-81-research-mandates-and-jobs.md` | Operator research mandates and durable job state | Agent policy, database, Trace |
| 82 | `sprint-82-bitpro-backtest-matrix-and-gates.md` | Bounded BitPro research execution and validation evidence | Sprint 81, BitPro MCP |
| 83 | `sprint-83-paper-promotion-and-observation.md` | Human-approved paper promotion and lifecycle evidence | Sprint 82, Paper Monitor |
| 84 | `sprint-84-regime-aware-strategy-portfolio-review.md` | StrategyCard-aware WorldState portfolio review | Sprint 83, Sprints 71–74 |

Sprints 81–84 remain research/paper-only. They must preserve the existing
BitPro MCP boundary and do not authorize direct BitPro database access,
automatic paper mutations, or any live-write tool.
