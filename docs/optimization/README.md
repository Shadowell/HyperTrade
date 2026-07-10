# HyperTrade Optimization Program

This index is the implementation order and review record for the five detailed
optimization proposals in this directory. The proposals remain useful design
inputs, but they are not independent patches and should not be implemented in
filename order.

## Reviewed Baseline

- Review date: 2026-07-10
- Baseline: 254 Python tests plus frontend lint/test/build
- Agent runtime: explicit graph nodes, governed ToolRegistry, audited Trace and
  Memory, provider routing, SSE progress, report provenance, and risk gates
- Main structural pressure: `agent/kernel.py` is about 2,600 lines and
  `frontend/src/App.tsx` is about 2,200 lines
- Sprint 76 establishes the shared run event and observability vocabulary before
  logging exporters, handler refactors, or async conversion.

## Correct Implementation Order

1. **Agent Flight Recorder (Sprint 76)** — normalize model usage and correlate
   graph, model, tool, policy, evidence, and Memory events in one run timeline.
2. **Structured logging and OpenTelemetry** — emit the same stable event fields
   to logs, metrics, and OTLP instead of creating a second trace vocabulary.
3. **Tool handler boundary** — move dispatch behind registered handlers while
   preserving ToolRegistry policy enforcement and Flight Recorder events.
4. **Frontend feature extraction** — continue splitting operator-console
   domains behind typed API clients and focused components.
5. **Database constraints and indexes** — migrate only after production data,
   orphan rows, deletion semantics, and PostgreSQL query plans are audited.
6. **End-to-end async conversion** — convert provider, DB, market, and connector
   boundaries after handler interfaces and cancellation semantics are stable.

## Proposal Review

| Proposal | Decision | Required correction |
| --- | --- | --- |
| `01-structured-logging-opentelemetry.md` | Proceed next | The repository is not “zero logging”; it lacks a unified production event contract. Build on Sprint 76 correlation fields, support OTLP rather than console-only export, redact prompts/secrets, and keep DB Trace as the audit source of truth. |
| `02-tool-handler-strategy-pattern.md` | Proceed after telemetry | High-value because the kernel dispatch is too large, but avoid one ceremonial class per trivial tool. Register cohesive handlers by capability, keep governance in the kernel boundary, and make handler results emit the existing tool event contract. |
| `03-frontend-component-refactor.md` | Proceed incrementally | The diagnosis is correct. Sprint 76 extracts the first feature component (`AgentFlightRecorder`). Continue with typed API, run console, evidence, Memory/RAG, and market domains; do not perform a risky all-at-once rewrite. |
| `04-full-async-refactor.md` | Defer until interfaces stabilize | Highest regression risk. Remove `asyncio.run` from server paths, use `httpx.AsyncClient` and SQLAlchemy `AsyncSession`, propagate cancellation/deadlines, and retain a deliberate sync CLI bridge. Avoid thread wrappers presented as “full async.” |
| `05-database-fk-indexes.md` | Proceed as an isolated migration | The example model definitions do not exactly match the current schema. Audit existing orphan rows and real query plans first. Do not blindly cascade-delete Agent traces or financial audit evidence; prefer retention-safe `RESTRICT`/`SET NULL` where appropriate and verify SQLite foreign-key enforcement plus PostgreSQL lock impact. |

## Professional Agent Boundary

HyperTrade should become professional through explicit, inspectable components,
not by adding role names alone:

- **Runtime kernel** owns run lifecycle, budgets, cancellation, and event order.
- **Provider adapters** normalize model responses and provider-reported usage.
- **Tool handlers** own one capability boundary and return structured evidence.
- **Governance** remains the trusted permission, approval, idempotency, and risk
  gate before any handler executes.
- **Memory and RAG** remain different systems and expose source/run linkage.
- **Specialist financial Agents** (market, strategy, risk, portfolio, execution)
  require distinct source contracts, tool budgets, output schemas, eval sets,
  and visible traces before they are considered production components.
- **Operator UI** explains what ran, which evidence was used, what it cost in
  tokens/time, which Memory was touched, and which policy decision applied.

The design is informed by the public
[Hermes Agent](https://github.com/NousResearch/hermes-agent) separation of
trajectory, context breakdown, usage/pricing, tool guardrails, and Memory, and
the public [TradingAgents](https://github.com/TauricResearch/TradingAgents)
graph separation of analysis, debate, risk, portfolio decisions, checkpoints,
and outcome-reflection Memory. HyperTrade retains its own business logic,
governance model, and BitPro contract boundary.

## Sprint 76 Status

- Provider-reported Chat Completions and Codex Responses usage is normalized.
- Planner model calls are trace-safe graph events; private reasoning is not
  persisted.
- Run observability projects timeline, model, tool, policy, Memory, duration,
  and Token summaries through a dedicated API.
- `/harness` includes a componentized Agent Flight Recorder with responsive
  desktop/mobile layouts and explicit missing-usage behavior.
