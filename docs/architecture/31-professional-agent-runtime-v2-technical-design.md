# Professional Agent Runtime V2 Technical Design

> Implementation baseline: Sprint 111 active on 2026-07-15. This document records the architecture
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
