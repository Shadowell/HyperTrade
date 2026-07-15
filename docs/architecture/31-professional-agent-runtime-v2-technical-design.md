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

The initial executor is read-only and catalog-governed. A provider may propose a transient strict
plan, but unavailable or invalid provider output falls back to deterministic reviewed research steps;
the provider never dispatches a capability. `MISSION_RUNTIME_ENABLED` plus a stable
`MISSION_RUNTIME_CANARY_PERCENT` gate the default chat route, while create/list/get/event projections
remain inspectable. Every successful observation requires a source or artifact ref. Model text alone
cannot complete a Mission.

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
reconciled on startup and currently expose objective inspection, market summary, RAG search, Memory
search, strategy/backtest performance summary, paper portfolio summary and Testnet intent summary.
The last three are bounded local database reads: they cannot start paper trading, approve an intent or
execute an order.

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

Production and staging instantiate the sandbox in fail-closed mode. Candidate code is submitted over
a Unix-domain socket to a distinct Compose service rather than executing in the API container. That
service runs as UID/GID `65532`, has no network namespace, no provider secrets, no BitPro mount, no
Docker socket, a read-only filesystem, a bounded tmpfs and cgroup/pids limits. It validates the file
map again and creates a new temporary workspace per fixed command. If its immutable image digest or
socket service is unavailable, the authenticated API returns `503` instead of executing a host/API
subprocess.

## Sprint 116 Full Cutover, Professional UX & Readiness

Sprint 116 closes the local development slice with one server-owned Mission projection consumed by
the React operator workspace. The workspace lives at `/harness/missions` and reuses the existing
operator-card/Flight Recorder visual language. It lists Missions, selects a detail, and projects
status, plan versions, step attempts, budget usage, artifact/unknown counts and cursor events.
Create, run, pause, resume, cancel and steer actions call authenticated Mission REST endpoints;
after every mutation the client reloads detail and events from the server. This keeps UI state from
becoming a second workflow state machine. The current implementation uses the REST `after=0` replay
path; the existing SSE stream remains the live upgrade path and reconnect fallback.

The readiness gate is deterministic and provider-independent. `ResearchOSEvalSuite` has a dedicated
`test_professional_agent_readiness.py` contract asserting at least 20 cases, recovery/fault/safety/
cursor categories, and zero `dangerous_tool_dispatched` or `write_scope_not_fail_closed` findings.
It is a safety gate, not a performance claim and does not score Sharpe, return or model eloquence.

The public answer is a separate projection, not a dump of Mission internals. `OperatorResponseV1`
contains only a bounded decision, confidence, source/artifact-bound evidence, explicit unknowns and
safe next actions. It excludes Mission ids, plan versions, tool counts, raw result payloads, prompts
and private reasoning from the default terminal/Web answer. Runtime, tool, approval and recovery state
remain independently available as audited events. The isolated `operator_answer_golden_v1` evaluates
market, strategy, portfolio, execution, context and delivery behavior; its retained artifacts contain
only check outcomes and aggregate sizes. Missing conversation context or public answer-stream support
is a visible `not_supported` result, never a pass. A completed evaluator run may therefore report
`complete_with_declared_gaps`: its exit status is successful only when no supported case failed, while
the separate `not_supported_count` remains explicit and is not folded into `passed_count`.

Before planning, a deterministic ingress classifier recognizes a narrow safety set: mainnet execution
requests terminalize as blocked without a Plan; unapproved/Testnet execution and excessive leverage
hold at `waiting_approval`; and explicitly stale inputs hold at `waiting_input`. The classifier is an
audited permission boundary, never a natural-language execution mechanism. Only the physically isolated
operator-evaluation target can enable `HYPERTRADE_OPERATOR_EVAL_FIXTURES_ENABLED`; two named fixture
cases inject a bounded timeout/source-unavailable terminal state without a provider or connector call.
Production rejects an `evaluation_case_id` and never enables that flag.

The isolated evaluator seeds a small idempotent fact set only after its own migrations: one synthetic
backtest, paper session/position/order and pending Testnet intent. The seeder requires both
`HYPERTRADE_EVAL_TARGET=isolated` and `APP_ENV=evaluation`; it is not present in the production deploy
path and does not call an exchange, BitPro, paper execution or approval service. These facts exercise
the same read capability contracts used by the normal Mission path rather than teaching the evaluator
to fabricate evidence.

Production sandbox activation is explicit. `AGENT_STRATEGY_SANDBOX_IMAGE` must name an immutable
`repository@sha256:<64 lowercase hex>` image identity; the deployment script derives a
`local@sha256:...` identity from the reviewed service image. Tags, including `:latest`, are rejected.
The API binds every UDS request to that digest, and the service rejects a mismatch. When
`APP_ENV` is production/staging and the digest or service socket is absent, the API returns 503 and
no host/API subprocess is started. The production canary verified the deployed service's networkless,
non-root, read-only, no-Docker-socket boundary; static network-import rejection, CPU-limit termination
and a 20-second wall-timeout all completed without a provider, BitPro or external strategy write.

The initial Sprint 116 UI/readiness implementation passed its local checks, but a subsequent
completion audit reopened the Sprint because default chat and worker paths still retained legacy
AgentKernel/AgentTask writes. The completed cutover replaces those controlled entrypoints with a
Mission projection while keeping historical records read-only. Production was promoted through a
stable 25% cohort and then 100%; repeated keys replay the same Mission, and legacy writes now return
HTTP 410.

The reopened slice replaces the single-step `FoundationPlanner` in application composition with a
provider-backed, catalog-bounded research planner. Providers may propose transient JSON plans only;
unavailable, malformed or over-scoped proposals fall back to a deterministic read-only plan. Neither
path can introduce an unreviewed capability, a write scope, approval bypass or model-defined budget.

The default chat API can now be moved by an explicit stable percentage canary. It turns the prompt
into a canonical read-only Mission with a caller idempotency key, runs it through the Mission Runtime
and returns a chat-compatible projection generated only from Mission/Plan/Attempt/Event facts. The
new path never creates `AgentTask` or `AgentRun` rows. A temporary no-header request receives a new
key; API clients that need retry semantics must send `Idempotency-Key`.

Mission worker delivery uses the same PostgreSQL Mission Store rather than a second queue. When both
`MISSION_RUNTIME_ENABLED` and `MISSION_RUNTIME_WORKER_ENABLED` are true, the worker claims a
non-terminal Mission with a bounded SQL lease, renews it by heartbeat and releases it on terminal
transition or orderly exit. PostgreSQL uses `FOR UPDATE SKIP LOCKED`; local SQLite acceptance covers
lease contention. A worker exception records only the bounded `worker_execution_failure` reason code
and fails the Mission without storing provider/private error text. The code default remains disabled;
the production canary observed a worker lease claim, terminal lease cleanup and a bounded public SSE
stream before the worker was explicitly enabled.

Textual and Web are Mission projections rather than workflow authorities. The TUI prefers Mission
list/detail/plan/attempt/event APIs and retains its legacy Task adapter only for an older server that
does not expose the Mission contract. Browser chat creates a stable request idempotency key per
submission; the default Mission stream sends a public acceptance `answer_delta` before execution,
then bounded `evidence_ready`, answer `answer_delta`, `warning` and `final` events. Internal
plan/tool events remain only on the authenticated Mission audit stream. At a 100% Mission canary,
new AgentTask/ResearchGraph writes return HTTP 410 and legacy worker/trigger loops do not start;
historical read endpoints remain available.

If `MISSION_RUNTIME_WORKER_ENABLED` is true, `POST /missions/{id}/run` records no inline execution:
the leased worker claims the durable Mission and the event stream tails its cursor until terminal.
The default chat SSE follows that same Mission rather than creating a second in-process execution.
The worker flag is independently disabled by default, so a fresh deployment remains explicit and
fail-closed when no worker process is deployed. The verified production deployment is an intentional
exception: `MISSION_RUNTIME_ENABLED=true`, `MISSION_RUNTIME_WORKER_ENABLED=true` and canary `100`.

### Production Gate M evidence — 2026-07-16

The isolated public-answer evaluator completed with 20 supported cases passed, 0 failed and 4
explicit multi-turn `not_supported` cases; its API, database, Docker network and synthetic facts are
separate from production. The production sandbox canary validated a lint/test/limited-backtest
candidate, rejected a network import before execution, terminated an infinite CPU candidate by its
resource limit and a sleeping candidate by the 20-second wall timeout. Sandbox review recorded
`external_write_performed=false`; no BitPro import, paper action, order or capital action occurred.

The Mission rollout first validated a stable 25% cohort, then set the percentage to 100. At both
stages a repeated idempotency key returned the same `mission_v2` projection and the legacy
`agent_tasks`/`agent_runs` counts remained unchanged. The 100% probe observed an SQL worker lease,
terminal lease cleanup, public `answer_delta`, `evidence_ready` and `final` events, and HTTP 410 for
a legacy session-write request. Historical legacy read endpoints remain available for audit only.
