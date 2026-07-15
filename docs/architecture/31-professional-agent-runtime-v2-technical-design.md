# Professional Agent Runtime V2 Technical Design

> Implementation baseline: Sprint 111 completed on 2026-07-15. This document records the architecture
> that is actually shipped; the roadmap remains in `30-professional-agent-runtime-v2-roadmap.md`.

## Runtime Boundary

The new core lives under `backend/src/hypertrade/runtime` and follows a strict dependency direction:

```text
domain <- ports <- application <- adapters/api
```

- `domain` contains frozen Pydantic contracts, state transitions and budget invariants. It imports no
  FastAPI, SQLAlchemy, provider, MCP, AgentKernel or trading service.
- `ports` defines MissionStore, MissionPlanner, StepExecutor and CapabilityPolicy protocols.
- `application` owns the adaptive Mission loop, safe points, validated completion and bounded replan.
- `adapters` own async SQLAlchemy, provider/tool bridges, telemetry and infrastructure conversion.
- FastAPI, CLI, Textual and React consume the same server-side Mission projection and cursor events.

PostgreSQL Mission events and immutable plan/attempt rows are canonical. `agent_missions` is a
rebuildable projection. LangGraph may express the stable control topology, but it is not a source of
business truth and cannot expand the persisted plan, permission or budget.

## Sprint 111 Vertical Slice

```text
POST mission -> draft -> planning -> PlanV2 validation -> running
-> pre-dispatch safe point -> governed read-only execution
-> StepObservationV2 validation -> completion checks -> completed/waiting/failed
```

The first executor is deliberately local and read-only: it validates the objective and safety
boundary without a provider or external mutation. `MISSION_RUNTIME_ENABLED` gates execution and is
off by default; create/list/get/event projections remain inspectable. Every successful observation
requires a source or artifact ref. Model text alone cannot complete a Mission.

Hard limits are schema-enforced and cannot be enlarged by a plan: three plan versions, twelve steps
per version, two attempts per step and four model calls per step by default. Tool/token/duration
budgets are checked before another dispatch. Pause and cancel become requested states and take
effect only at a runtime safe point. Steer appends an immutable event and activates a new Plan version
without overwriting the original objective.

## Persistence

Migration `0023_agent_missions` adds:

- `agent_missions`: optimistic-versioned read projection and lease fields;
- `agent_mission_events`: append-only cursor stream;
- `agent_plan_versions`: immutable plan JSON plus content hash;
- `agent_step_attempts`: immutable attempt identity and validated observation;
- `agent_steering_events`: immutable operator steer facts.

The async adapter uses SQLAlchemy AsyncSession with psycopg/aiosqlite. A state transition locks the
projection, compares `version`, appends an event and commits atomically. New Mission writes never
touch `agent_tasks` or `agent_runs`; history stays read-only.

## Fitness Audit: Keep, Rewrite, Delete

| Area | Decision | Reason / migration action |
|---|---|---|
| Tool policy, approval and risk facts | Keep and adapt | Proven production safety boundary; exposed only through ports |
| BitPro MCP contracts and stable refs | Keep and adapt | External system-of-record boundary |
| Evidence/Memory/RAG schemas | Keep domain facts | Sprint 113 recompiles them into bounded context/artifacts |
| AgentKernel orchestration | Rewrite | 2,400+ line concrete service mixes planning, tools, persistence and formatting |
| AgentTask/AgentRun write path | Archive | New Mission never dual-writes; old read APIs remain during cutover |
| Fixed ResearchGraph top-level DAG | Replace | Roles/schemas may survive; Sprint 114 moves selection to bounded supervisor |
| Duplicated CLI/Web state machines | Delete during cutover | Clients must project server events only |
| Permanent fallback/compat-v2 layer | Forbidden | Rollback uses release deployment, not two runtime truth sources |

GitNexus found five direct AgentKernel importers (`main.py`, `worker.py`, `cli.py`,
`agent/task_executor.py` and an old QA document) plus the TUI through CLI. These are the ordered
cutover surface. Sprint 111 adds no reverse import from the new runtime; later Sprints migrate one
entry at a time and delete the replaced caller branch.

## Safety and Observability

OpenTelemetry spans start at `mission.run` and `mission.step` with mission, plan, step and capability
identifiers only. Prompts, raw provider output, credentials and private reasoning are excluded.
Mission cursor events carry bounded summaries, refs and error taxonomy. Paper/live/order/capital
permissions are unchanged and the foundation policy accepts only `read_only.v1`.

## Sprint 112 Capability and Tool Runtime

Mission V2 no longer dispatches a planner-supplied tool name directly. Every `PlanStepV2` resolves
`capability_id@version` through an in-process projection of the reviewed catalog. The snapshot binds
the input/output JSON Schemas, source owner, handler key, side-effect class, approval requirement,
idempotency rule, timeout, result bound, health/freshness, contract hash and policy hash. Unknown,
pending, rejected, stale or unhealthy definitions fail before a handler call.

```text
PlanStepV2
  -> reviewed CapabilitySnapshotV1
  -> permission/approval/side-effect/hash preflight
  -> input JSON Schema
  -> timeout + circuit + idempotency boundary
  -> adapter
  -> output JSON Schema
  -> bounded/redacted ToolObservationV2
  -> StepObservationV2
```

`SqlCapabilityCatalog` persists snapshots, discovery proposals and append-only idempotent reviews.
Discovery from MCP/OpenAPI is represented only as `pending_review`; it cannot enter the active map
until an authenticated administrator reviews the exact definition. Code-owned built-ins are
reconciled on startup and currently expose only objective inspection, market summary, RAG search and
Memory search as read capabilities.

`GovernedToolExecutor` is the single dispatch boundary. It validates JSON Schema, requires matching
contract/policy hashes, denies writes to read-only Missions, applies a bounded timeout, opens
per-capability circuits for repeated transport failures, and replays required idempotency keys
without a second handler call. The recovery taxonomy separates contract, permission, timeout,
rate-limit, source, unsafe and unknown failures; text errors cannot be treated as success.

Migration `0024_agent_capabilities` adds catalog snapshots, proposals, review facts, bounded tool
observations and circuit projections. Production uses `SqlObservationStore`; it persists only a
redacted/truncated preview, content hash, refs, taxonomy and timing. Raw connector output,
credentials, prompts and private reasoning are excluded. The old foundation executor remains only
as a Sprint 111 test fixture; the production Mission composition depends on the reviewed catalog and
governed runtime.

## Sprint 113 Context and Artifact Engine

`ContextArtifactEngine.prepare` runs after capability policy validation and before a Step attempt is
opened. It compiles a separate `AgentContextPackV1` for the exact Mission/Plan/Step/attempt identity.
Required sources are the objective, constraints plus permission profile, Plan completion contract and
Step contract. Prior validated observations enter as lower-tier optional sources containing only
bounded summaries and refs, never raw results or a hidden transcript.

The compiler uses a provider-independent UTF-8 estimator, stable required/tier/ref/hash ordering and
a hard ledger. Required blocks cannot be dropped; if they do not fit, the Mission fails closed as
`budget_exhausted`. Optional blocks record one explicit decision: selected, compacted, stale, budget,
unsafe or duplicate. Compaction is deterministic and content-hash marked. Manifest hashes exclude
wall-clock and random identifiers, so identical inputs, policy and budget replay identically.

The Mission Artifact Index is metadata-first. `MissionArtifactV1` binds kind, version, producer,
media type, size, content hash, source refs and a stable external URI or at most 32 KiB inline
preview. Secret-bearing keys and raw candle/equity/return/order/trade/position fields fail validation.
Same Mission/content hashes dedupe; a new version may atomically supersede a current artifact while
retaining immutable `derived_from` and `supersedes` edges. Cross-Mission supersede is forbidden.

Migration `0025_agent_context_artifacts` adds immutable context manifests, artifact metadata and
lineage relations. REST projections expose packs, artifacts and relations under the Mission. Before
completion, every observation artifact ref must resolve to a current artifact in that Mission and an
`artifact_kind_exists` criterion queries the index rather than trusting a model-written string.

## Sprint 114 Bounded Multi-Agent Supervisor

The Supervisor selects only version-controlled `RoleDefinitionV1` entries. The initial catalog has
research lead, market analyst, evidence analyst and critic roles; every role permits only reviewed
read capabilities and `read_only.v1`. Assignment identity is an idempotent hash of the team request
and immutable work contract. Unknown roles/capabilities, permission mismatch, repeated identities,
unknown dependencies and per-role concurrency excess fail before dispatch.

Assignments form a DAG. Independent ready nodes execute in an AnyIO TaskGroup; dependent layers wait
for their prerequisites. The maximum team is four. Before a node runs, the store atomically reserves
tokens, tool calls, model calls and duration against canonical Mission usage plus every active sibling
reservation. Success commits the reservation; timeout, failure or cancellation releases it under a
shielded cleanup boundary. PostgreSQL locks the Mission projection during reservation.

`HandoffV1` carries summary, claims, Context Pack/Artifact/source refs, unknowns and a replayable
output hash. It cannot contain hidden transcript/private-reasoning markers and must cite one of its
assigned Context Packs. Merge groups claims by key and exact value: one value is agreed, multiple
values create an immutable `ConflictV1` and an explicit merge unknown. There is no majority vote or
last-writer resolution.

Migration `0026_agent_supervision` adds assignments, budget reservations, handoffs and conflicts.
REST exposes the reviewed role catalog, team run and shared supervision projection. Team execution
is disabled by default with `AGENT_DYNAMIC_TEAM_ENABLED=false`; enabling it does not add write,
paper, live, order or capital capabilities.

## Sprint 115 Sandboxed Strategy Development

The strategy sandbox is a separate, short-lived execution boundary below the Mission/Supervisor
ports. `SandboxRequestV1` accepts only a succeeded assignment, exact Context Pack refs, optional
current Mission Artifact refs, an in-memory file map and a fixed command union (`ruff`, `pytest`,
`limited_backtest`). The domain validates path roots/extensions, Python syntax and known process/
network/dynamic-execution hazards before any process starts.

The local/CI adapter creates a mode-700 temporary workspace, clears inherited provider secrets,
disables stdin, uses a bounded temporary output file, applies host resource limits and starts each
command in its own process group. Timeout cleanup kills the group and the typed command ledger
records status, exit code, duration, output bytes, preview hash and truncation. This fallback is not
treated as a production security boundary.

Every run produces a content-addressed `SandboxArtifactV1` ledger for source files, unified patch,
command output and manifest metadata. The SQL projection stores only metadata/previews in
`agent_sandbox_runs` and `agent_sandbox_artifacts`; the ephemeral workspace is discarded. Review
facts bind the exact patch/artifact hash, target contract and idempotency key. Accept is an import
proposal fact only: it does not apply a patch, call BitPro, create a strategy, start paper trading or
submit an order. Replays with the same idempotency key must have identical canonical content.

Production and staging instantiate the sandbox in fail-closed mode. If a rootless Docker/OCI adapter
has not been configured, the authenticated API returns `503` instead of executing candidate code on
the application host. The Sprint 116 deployment canary must provide network namespace denial,
read-only filesystem, non-root UID, cgroup/pids limits, no secrets and no host Docker socket before
the flag can be enabled.
