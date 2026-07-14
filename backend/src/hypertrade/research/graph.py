"""Fixed LangGraph Research DAG over durable HyperTrade Task/Node/Evidence state."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from hypertrade.agent.checkpoints import TaskCheckpointService, checkpoint_to_dict
from hypertrade.agent.sessions import AgentSessionCreate, AgentSessionService
from hypertrade.agent.task_events import TaskEventService
from hypertrade.agent.tasks import (
    AgentTaskCreate,
    AgentTaskService,
    TaskBudget,
    task_to_dict,
)
from hypertrade.db import AgentTask, Database
from hypertrade.research.budgets import TaskBudgetExceeded
from hypertrade.research.evidence import EvidenceService
from hypertrade.research.evidence_schemas import DataGapEvidenceInput, EvidenceScope
from hypertrade.research.graph_control import ResearchGraphControlInterrupted
from hypertrade.research.graph_tools import ResearchToolRunner
from hypertrade.research.node_runs import TaskNodeRunService, node_run_to_dict
from hypertrade.research.role_executor import RoleExecutor
from hypertrade.research.role_provider import ResearchRoleProvider, RoleSchemaError
from hypertrade.research.roles.definitions import (
    RESEARCH_GRAPH_EDGES,
    ROLE_CATALOG,
    role_catalog_hash,
)
from hypertrade.research.schemas import ResearchJobCreate, StrategySpecDraft
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.tool_policy import RoleToolDenied


def _merge_unique(left: list[str], right: list[str]) -> list[str]:
    return sorted(set(left) | set(right))


def _merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class ResearchGraphState(TypedDict):
    task_id: str
    objective: str
    mandate: dict[str, Any]
    job_id: str
    selection: dict[str, Any]
    completed_nodes: Annotated[list[str], _merge_unique]
    evidence_ids: Annotated[list[str], _merge_unique]
    node_outputs: Annotated[dict[str, Any], _merge_dict]


class ResearchGraphCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandate_id: str = Field(min_length=1, max_length=32)
    job_id: str = Field(default="", max_length=32)
    objective: str = Field(min_length=3, max_length=8_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    session_id: str | None = None
    capabilities: dict[str, bool] = Field(default_factory=dict)
    operator_tool_allowlist: list[str] = Field(default_factory=list, max_length=128)
    max_parallel_roles: int = Field(default=2, ge=1, le=4)
    budget: TaskBudget = Field(
        default_factory=lambda: TaskBudget(
            max_tokens=300_000,
            max_model_calls=60,
            max_tool_calls=80,
            max_backtests=3,
            max_duration_seconds=3_600,
            max_concurrency=2,
        )
    )


@dataclass(frozen=True)
class GraphSelection:
    selected_nodes: tuple[str, ...]
    disabled_nodes: dict[str, str]
    max_parallel_roles: int

    def projection(self) -> dict[str, Any]:
        return {
            "selected_nodes": list(self.selected_nodes),
            "disabled_nodes": dict(self.disabled_nodes),
            "max_parallel_roles": self.max_parallel_roles,
        }


class ResearchGraphSelector:
    OPTIONAL_CAPABILITIES = {
        "derivatives_flow": "derivatives",
        "event_context": "event_context",
    }

    def select(
        self,
        *,
        capabilities: dict[str, bool],
        max_parallel_roles: int,
    ) -> GraphSelection:
        selected: list[str] = []
        disabled: dict[str, str] = {}
        for role_key, role in ROLE_CATALOG.items():
            capability = self.OPTIONAL_CAPABILITIES.get(role_key)
            if role.required or capability is None or capabilities.get(capability, False):
                selected.append(role_key)
            else:
                disabled[role_key] = f"capability_unavailable:{capability}"
        return GraphSelection(
            selected_nodes=tuple(selected),
            disabled_nodes=disabled,
            max_parallel_roles=max(1, min(max_parallel_roles, 4)),
        )


class ResearchGraphTaskService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, payload: ResearchGraphCreate, *, created_by: str) -> dict[str, Any]:
        program = ResearchProgramService(self.db)
        mandate = program.get_mandate(payload.mandate_id)
        if mandate["status"] != "active":
            raise ValueError("research graph requires an active mandate")
        if payload.job_id:
            job = program.get_job(payload.job_id)
            if job["mandate_id"] != payload.mandate_id:
                raise ValueError("research graph job must belong to the mandate")
        configuration = {
            "mandate_id": payload.mandate_id,
            "job_id": payload.job_id,
            "capabilities": dict(payload.capabilities),
            "operator_tool_allowlist": sorted(set(payload.operator_tool_allowlist)),
            "max_parallel_roles": min(
                payload.max_parallel_roles, payload.budget.max_concurrency
            ),
            "role_catalog_hash": role_catalog_hash(),
        }
        task_service = AgentTaskService(self.db)
        existing_task = task_service.get_by_idempotency(payload.idempotency_key)
        if existing_task is not None:
            if existing_task.kind != "research_graph":
                raise ValueError("idempotency key is bound to a non-graph task")
            existing_config = dict(existing_task.control_json).get("research_graph")
            if existing_config != configuration or existing_task.objective != payload.objective:
                raise ValueError("idempotency key is bound to different graph configuration")
            return {
                "task": task_to_dict(existing_task),
                "configuration": configuration,
                "idempotency_replayed": True,
            }
        session_id = payload.session_id
        if not session_id:
            agent_session = AgentSessionService(self.db).create(
                AgentSessionCreate(
                    title=f"Research graph: {mandate['name']}",
                    surface="background",
                    created_by=created_by,
                    context_policy={
                        "mandate_id": payload.mandate_id,
                        "evidence_schema": "research_evidence.v2",
                    },
                )
            )
            session_id = agent_session.id
        task = task_service.create(
            AgentTaskCreate(
                session_id=session_id,
                kind="research_graph",
                objective=payload.objective,
                idempotency_key=payload.idempotency_key,
                resource_type="research_job" if payload.job_id else "research_mandate",
                resource_id=payload.job_id or payload.mandate_id,
                budget=payload.budget,
            ),
            actor=created_by,
        )
        with self.db.session() as session:
            row = session.get(AgentTask, task.id)
            if row is None:
                raise KeyError(task.id)
            control = dict(row.control_json)
            existing = control.get("research_graph")
            if isinstance(existing, dict) and existing and existing != configuration:
                raise ValueError("idempotency key is bound to different graph configuration")
            row.control_json = {**control, "research_graph": configuration}
        return {
            "task": task_to_dict(AgentTaskService(self.db).get(task.id)),
            "configuration": configuration,
        }

    def configuration(self, task_id: str) -> dict[str, Any]:
        task = AgentTaskService(self.db).get(task_id)
        if task.kind != "research_graph":
            raise ValueError("task is not a research graph")
        config = dict(task.control_json).get("research_graph")
        if not isinstance(config, dict):
            raise ValueError("research graph configuration missing")
        return dict(config)


class ResearchGraphRuntime:
    def __init__(
        self,
        db: Database,
        *,
        provider: ResearchRoleProvider,
        tool_runner: ResearchToolRunner,
    ) -> None:
        self.db = db
        self.provider = provider
        self.tool_runner = tool_runner
        self.tasks = AgentTaskService(db)
        self.task_graphs = ResearchGraphTaskService(db)
        self.executor = RoleExecutor(db, provider=provider, tool_runner=tool_runner)

    def run(self, task_id: str) -> dict[str, Any]:
        return asyncio.run(self.run_async(task_id))

    async def run_async(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if task.kind != "research_graph":
            raise ValueError("task is not a research graph")
        if task.status == "queued":
            self.tasks.transition(
                task_id,
                "running",
                actor="research_graph_runtime",
                reason="graph_execution_started",
            )
        elif task.status != "running":
            raise ValueError(f"research graph is not runnable from {task.status}")
        config = self.task_graphs.configuration(task_id)
        program = ResearchProgramService(self.db)
        mandate = program.get_mandate(str(config["mandate_id"]))
        job_id = str(config.get("job_id", ""))
        if job_id:
            job = program.get_job(job_id)
            mandate = {**mandate, "strategy_spec": dict(job["strategy_spec"])}
        selection = ResearchGraphSelector().select(
            capabilities={
                str(key): bool(value)
                for key, value in dict(config.get("capabilities", {})).items()
            },
            max_parallel_roles=int(config.get("max_parallel_roles", 2)),
        )
        initial: ResearchGraphState = {
            "task_id": task_id,
            "objective": task.objective,
            "mandate": mandate,
            "job_id": job_id,
            "selection": selection.projection(),
            "completed_nodes": [],
            "evidence_ids": [],
            "node_outputs": {},
        }
        graph = self._compiled_graph(
            selection=selection,
            operator_tool_allowlist=set(config.get("operator_tool_allowlist", [])) or None,
        )
        try:
            result = await graph.ainvoke(
                initial,
                config={"max_concurrency": selection.max_parallel_roles},
            )
        except ResearchGraphControlInterrupted:
            return self.projection(task_id)
        except Exception as exc:
            self._handle_failure(task_id, exc, mandate=mandate)
            raise
        current = self.tasks.get(task_id)
        if current.status == "running":
            self.tasks.transition(
                task_id,
                "completed",
                actor="research_graph_runtime",
                reason="risk_committee_completed",
            )
        TaskCheckpointService(self.db).create(
            task_id,
            {
                "schema_version": "research_graph_checkpoint.v1",
                "completed_nodes": sorted(result.get("completed_nodes", [])),
                "evidence_ids": sorted(result.get("evidence_ids", [])),
                "final_node": "risk_committee",
            },
        )
        return self.projection(task_id)

    def projection(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        config = self.task_graphs.configuration(task_id)
        nodes = TaskNodeRunService(self.db).list(task_id)
        latest = TaskCheckpointService(self.db).latest(task_id)
        return {
            "schema_version": "research_graph.v1",
            "task": task_to_dict(task),
            "configuration": config,
            "topology": graph_topology_projection(),
            "nodes": [node_run_to_dict(node) for node in nodes],
            "evidence": EvidenceService(self.db).query(task_id=task_id, limit=200),
            "latest_checkpoint": checkpoint_to_dict(latest) if latest else None,
            "provider": {"name": self.provider.name, "model": self.provider.model},
        }

    def _compiled_graph(
        self,
        *,
        selection: GraphSelection,
        operator_tool_allowlist: set[str] | None,
    ) -> Any:
        builder = StateGraph(ResearchGraphState)
        dependencies = _dependencies()

        for role_key in ROLE_CATALOG:
            async def run_node(
                state: ResearchGraphState,
                current_role: str = role_key,
            ) -> dict[str, Any]:
                self._control_guard(state["task_id"], None)
                effective_job_id = state["job_id"]
                if current_role == "bitpro_validation":
                    effective_job_id = self._ensure_validation_job(state)
                result = await self.executor.execute(
                    current_role,
                    task_id=state["task_id"],
                    objective=state["objective"],
                    mandate=state["mandate"],
                    job_id=effective_job_id,
                    prior_evidence_ids=list(state.get("evidence_ids", [])),
                    depends_on=list(dependencies[current_role]),
                    enabled=current_role in selection.selected_nodes,
                    disabled_reason=selection.disabled_nodes.get(current_role, ""),
                    operator_tool_allowlist=operator_tool_allowlist,
                    control_guard=lambda node_id: self._control_guard(
                        state["task_id"], node_id
                    ),
                )
                return result.state_update()

            builder.add_node(role_key, run_node)

        builder.add_edge(START, "preflight")
        builder.add_edge("preflight", "data_quality")
        for branch in (
            "market_regime",
            "technical_structure",
            "derivatives_flow",
            "event_context",
        ):
            builder.add_edge("data_quality", branch)
        builder.add_edge(
            [
                "market_regime",
                "technical_structure",
                "derivatives_flow",
                "event_context",
            ],
            "evidence_synthesis",
        )
        builder.add_edge("evidence_synthesis", "bull_case")
        builder.add_edge("evidence_synthesis", "bear_case")
        builder.add_edge(["bull_case", "bear_case"], "strategy_engineer")
        builder.add_edge("strategy_engineer", "bitpro_validation")
        builder.add_edge("bitpro_validation", "validation_reviewer")
        builder.add_edge("validation_reviewer", "risk_committee")
        builder.add_edge("risk_committee", END)
        return builder.compile()

    def _ensure_validation_job(self, state: ResearchGraphState) -> str:
        """Handoff a StrategySpec to the trusted orchestrator queue, never BitPro directly."""
        if state["job_id"]:
            return state["job_id"]
        strategy_node = dict(state.get("node_outputs", {})).get("strategy_engineer", {})
        raw_spec = (
            dict(strategy_node).get("strategy_spec")
            if isinstance(strategy_node, dict)
            else None
        )
        if not isinstance(raw_spec, dict):
            return ""
        spec = StrategySpecDraft.model_validate(raw_spec)
        idempotency_key = f"{state['task_id']}:strategy-engineer"[:128]
        job = ResearchProgramService(self.db).queue_job(
            str(state["mandate"]["id"]),
            ResearchJobCreate(
                prompt=state["objective"],
                idempotency_key=idempotency_key,
                strategy_spec=spec,
                source_run_id=state["task_id"],
            ),
        )
        job_id = str(job["id"])
        with self.db.session() as session:
            task = session.get(AgentTask, state["task_id"])
            if task is None:
                raise KeyError(state["task_id"])
            control = dict(task.control_json)
            graph_config = dict(control.get("research_graph", {}))
            graph_config["validation_job_id"] = job_id
            task.control_json = {**control, "research_graph": graph_config}
            TaskEventService.append_in_session(
                session,
                task,
                "research_validation_handoff_queued",
                actor="research_graph_runtime",
                payload={
                    "job_id": job_id,
                    "strategy_node_run_id": strategy_node.get("node_run_id", ""),
                    "boundary": "research_orchestrator_only_no_role_write",
                },
            )
        return job_id

    def _control_guard(self, task_id: str, node_run_id: str | None) -> None:
        task = self.tasks.get(task_id)
        if task.status == "pause_requested":
            TaskCheckpointService(self.db).create(
                task_id,
                {
                    "schema_version": "research_graph_checkpoint.v1",
                    "control": "pause_requested",
                    "node_run_id": node_run_id,
                },
                node_run_id=node_run_id,
            )
            self.tasks.transition(
                task_id,
                "paused",
                actor="research_graph_runtime",
                reason="graph_safe_point",
            )
            raise ResearchGraphControlInterrupted("paused", "operator_pause")
        if task.status == "cancel_requested":
            self.tasks.transition(
                task_id,
                "canceled",
                actor="research_graph_runtime",
                reason="graph_safe_point",
            )
            raise ResearchGraphControlInterrupted("canceled", "operator_cancel")
        if task.status in {"paused", "canceled"}:
            raise ResearchGraphControlInterrupted(task.status, "task_not_running")
        if task.status != "running":
            raise RuntimeError(f"research graph task is not running: {task.status}")

    def _handle_failure(
        self, task_id: str, exc: Exception, *, mandate: dict[str, Any]
    ) -> None:
        task = self.tasks.get(task_id)
        if task.status != "running":
            return
        node_service = TaskNodeRunService(self.db)
        for node in node_service.list(task_id):
            if node.status == "running":
                node_service.fail(
                    node.id,
                    error={
                        "code": "graph_sibling_canceled",
                        "retryable": True,
                        "cause": type(exc).__name__,
                    },
                )
        retryable = isinstance(exc, httpx.TimeoutException | TimeoutError)
        code = _failure_code(exc)
        with suppress(Exception):
            EvidenceService(self.db).append(
                DataGapEvidenceInput(
                    claim=f"Research graph stopped: {code}",
                    scope=EvidenceScope(
                        symbols=list(mandate.get("symbols", [])),
                        timeframes=list(mandate.get("timeframes", [])),
                        market_type=str(mandate.get("market_type", "")),
                        mandate_id=str(mandate.get("id", "")),
                    ),
                    confidence=Decimal("0"),
                    as_of=_now(),
                    task_id=task_id,
                    role_key="research_graph_runtime",
                    expected_sources=["tool"],
                    remediation="Resolve the structured graph error and retry the failed node.",
                ),
                actor="research_graph_runtime",
            )
        self.tasks.transition(
            task_id,
            "retry_wait" if retryable else "failed",
            actor="research_graph_runtime",
            reason=code,
            error={"code": code, "retryable": retryable, "type": type(exc).__name__},
        )


def graph_topology_projection() -> dict[str, Any]:
    return {
        "schema_version": "research_graph_topology.v1",
        "catalog_hash": role_catalog_hash(),
        "roles": [ROLE_CATALOG[key].projection() for key in ROLE_CATALOG],
        "edges": [
            {"from": list(sources), "to": target}
            for sources, target in RESEARCH_GRAPH_EDGES
        ],
        "fixed": True,
        "dynamic_agents_allowed": False,
    }


def _dependencies() -> dict[str, tuple[str, ...]]:
    dependencies: dict[str, tuple[str, ...]] = dict.fromkeys(ROLE_CATALOG, ())
    for sources, target in RESEARCH_GRAPH_EDGES:
        if target in dependencies:
            dependencies[target] = tuple(source for source in sources if source != "__start__")
    return dependencies


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, TaskBudgetExceeded):
        return f"budget_exhausted:{exc.dimension}"
    if isinstance(exc, RoleToolDenied):
        return "role_tool_denied"
    if isinstance(exc, RoleSchemaError):
        return "role_schema_invalid"
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return "role_timeout"
    return "research_graph_failed"


def _now() -> Any:
    from hypertrade.db import utc_now

    return utc_now()
