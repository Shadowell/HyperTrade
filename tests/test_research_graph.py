from __future__ import annotations

from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient
from hypertrade.agent.tasks import AgentTaskService, TaskBudget, TaskControl
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.research.graph import (
    ResearchGraphCreate,
    ResearchGraphRuntime,
    ResearchGraphTaskService,
)
from hypertrade.research.graph_tools import BuiltinResearchToolRunner
from hypertrade.research.node_runs import TaskNodeRunService
from hypertrade.research.role_provider import (
    DeterministicGapRoleProvider,
    ProviderResult,
    RoleProviderContext,
    RoleSchemaError,
)
from hypertrade.research.roles.definitions import RoleDefinition
from hypertrade.research.roles.schemas import (
    DataGapDraft,
    FactDraft,
    RoleOutput,
    RoleToolCall,
    RoleToolPlan,
    RoleUsage,
)
from hypertrade.research.schemas import ResearchMandateCreate, StrategySpecDraft
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.tool_policy import RoleToolPolicy


def _db(tmp_path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'research-graph.db'}")
    db.create_all()
    return db


def _mandate(db: Database) -> dict[str, object]:
    return ResearchProgramService(db).create_mandate(
        ResearchMandateCreate(
            name="BTC bounded graph research",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )


def _graph_task(db: Database, mandate_id: str, *, key: str = "graph-task-001") -> str:
    result = ResearchGraphTaskService(db).create(
        ResearchGraphCreate(
            mandate_id=mandate_id,
            objective="Research a bounded BTC trend candidate without trading actions",
            idempotency_key=key,
            capabilities={"derivatives": False, "event_context": False},
        ),
        created_by="test",
    )
    return str(result["task"]["id"])


def test_fixed_graph_completes_with_explicit_optional_and_provider_gaps(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]))
    runtime = ResearchGraphRuntime(
        db,
        provider=DeterministicGapRoleProvider(),
        tool_runner=BuiltinResearchToolRunner(db),
    )

    result = runtime.run(task_id)

    assert result["task"]["status"] == "completed"
    latest_by_role = {row["role_key"]: row for row in result["nodes"]}
    assert set(latest_by_role) == {
        result["topology"]["roles"][index]["key"] for index in range(13)
    }
    assert all(row["status"] == "completed" for row in latest_by_role.values())
    assert {row["evidence_type"] for row in result["evidence"]} == {"data_gap"}
    optional_roles = {
        row["role_key"]
        for row in result["evidence"]
        if str(row["claim"]).startswith("Optional research role unavailable")
    }
    assert optional_roles == {"derivatives_flow", "event_context"}
    assert result["latest_checkpoint"]["state"]["final_node"] == "risk_committee"


class FailOnceProvider(DeterministicGapRoleProvider):
    def __init__(self, role_key: str) -> None:
        self.role_key = role_key
        self.failed = False
        self.calls: Counter[str] = Counter()

    def synthesize(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        observations,
    ) -> ProviderResult[RoleOutput]:
        self.calls[role.key] += 1
        if role.key == self.role_key and not self.failed:
            self.failed = True
            raise RoleSchemaError("injected invalid role schema")
        return super().synthesize(role, context, observations)


def test_retry_replays_completed_nodes_and_only_retries_failed_attempts(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]), key="graph-retry-001")
    provider = FailOnceProvider("market_regime")
    runtime = ResearchGraphRuntime(
        db,
        provider=provider,
        tool_runner=BuiltinResearchToolRunner(db),
    )

    with pytest.raises(RoleSchemaError):
        runtime.run(task_id)
    assert AgentTaskService(db).get(task_id).status == "failed"
    evidence_before = len(runtime.projection(task_id)["evidence"])
    AgentTaskService(db).retry(
        task_id,
        TaskControl(
            reason="retry injected role failure",
            idempotency_key="graph-retry-control-001",
            actor="test",
        ),
    )

    completed = runtime.run(task_id)
    assert completed["task"]["status"] == "completed"
    attempts = Counter(row.node_key for row in TaskNodeRunService(db).list(task_id))
    assert attempts["preflight"] == 1
    assert attempts["data_quality"] == 1
    assert attempts["market_regime"] == 2
    assert len(completed["evidence"]) > evidence_before
    assert provider.calls["preflight"] == 1


class DangerousProvider(DeterministicGapRoleProvider):
    def plan(
        self,
        role: RoleDefinition,
        context: RoleProviderContext,
        policy: RoleToolPolicy,
    ) -> ProviderResult[RoleToolPlan]:
        del role, context, policy
        return ProviderResult(
            RoleToolPlan(
                tool_calls=[RoleToolCall(name="bitpro.paper_start")],
                rationale="adversarial write attempt",
            ),
            RoleUsage(),
        )


class SpyToolRunner(BuiltinResearchToolRunner):
    def __init__(self, db: Database) -> None:
        super().__init__(db)
        self.calls = 0

    def run(self, call, context):
        self.calls += 1
        return super().run(call, context)


def test_dangerous_role_tool_is_denied_before_runner_dispatch(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]), key="graph-danger-001")
    runner = SpyToolRunner(db)
    runtime = ResearchGraphRuntime(db, provider=DangerousProvider(), tool_runner=runner)

    with pytest.raises(PermissionError, match="bitpro.paper_start"):
        runtime.run(task_id)

    assert runner.calls == 0
    task = AgentTaskService(db).get(task_id)
    assert task.status == "failed"
    assert task.error_json["code"] == "role_tool_denied"


class TimeoutProvider(DeterministicGapRoleProvider):
    def synthesize(self, role, context, observations):
        del role, context, observations
        raise httpx.ReadTimeout("injected role timeout")


def test_provider_timeout_enters_retry_wait_with_checkpoint_and_gap(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]), key="graph-timeout-001")
    runtime = ResearchGraphRuntime(
        db,
        provider=TimeoutProvider(),
        tool_runner=BuiltinResearchToolRunner(db),
    )

    with pytest.raises(httpx.ReadTimeout):
        runtime.run(task_id)

    projection = runtime.projection(task_id)
    assert projection["task"]["status"] == "retry_wait"
    assert projection["task"]["error"]["code"] == "role_timeout"
    assert any(
        row["claim"] == "Research graph stopped: role_timeout"
        for row in projection["evidence"]
    )


def test_global_budget_is_reserved_before_provider_dispatch(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    result = ResearchGraphTaskService(db).create(
        ResearchGraphCreate(
            mandate_id=str(mandate["id"]),
            objective="Budget must stop dispatch before any unreserved model call",
            idempotency_key="graph-budget-zero-001",
            budget=TaskBudget(
                max_tokens=1,
                max_model_calls=1,
                max_tool_calls=0,
                max_backtests=0,
                max_duration_seconds=60,
                max_concurrency=1,
            ),
        ),
        created_by="test",
    )
    task_id = str(result["task"]["id"])
    runtime = ResearchGraphRuntime(
        db,
        provider=DeterministicGapRoleProvider(),
        tool_runner=BuiltinResearchToolRunner(db),
    )

    with pytest.raises(RuntimeError, match="budget exhausted"):
        runtime.run(task_id)

    projection = runtime.projection(task_id)
    assert projection["task"]["status"] == "failed"
    assert projection["task"]["usage"]["model_calls"] == 0
    assert projection["nodes"][0]["error"]["code"] == "role_execution_failed"


class OverRoleBudgetProvider(DeterministicGapRoleProvider):
    def synthesize(self, role, context, observations):
        result = super().synthesize(role, context, observations)
        return ProviderResult(
            result.value,
            RoleUsage(model_calls=1, tokens=role.budget.max_tokens + 1),
        )


def test_role_budget_failure_does_not_persist_partial_role_evidence(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]), key="graph-role-budget-001")
    runtime = ResearchGraphRuntime(
        db,
        provider=OverRoleBudgetProvider(),
        tool_runner=BuiltinResearchToolRunner(db),
    )

    with pytest.raises(RoleSchemaError, match="role token budget exceeded"):
        runtime.run(task_id)

    projection = runtime.projection(task_id)
    assert projection["task"]["status"] == "failed"
    assert {row["role_key"] for row in projection["evidence"]} == {
        "research_graph_runtime"
    }


class SemanticInvalidProvider(DeterministicGapRoleProvider):
    def synthesize(self, role, context, observations):
        del role, context, observations
        return ProviderResult(
            RoleOutput(
                summary="schema-valid but source ownership is invalid",
                evidence=[
                    FactDraft(
                        claim="This fact cites a source that was never observed.",
                        confidence=0.5,
                        source_ids=["invented_source"],
                    )
                ],
            ),
            RoleUsage(),
        )


def test_semantic_invalid_role_output_fails_closed_to_data_gap(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]), key="graph-semantic-gap-001")
    runtime = ResearchGraphRuntime(
        db,
        provider=SemanticInvalidProvider(),
        tool_runner=BuiltinResearchToolRunner(db),
    )

    completed = runtime.run(task_id)

    assert completed["task"]["status"] == "completed"
    assert all(row["evidence_type"] == "data_gap" for row in completed["evidence"])
    assert any(
        row["claim"] == "preflight provider output failed evidence semantic validation"
        for row in completed["evidence"]
    )


class PauseOnceProvider(DeterministicGapRoleProvider):
    def __init__(self, db: Database) -> None:
        self.db = db
        self.paused = False

    def plan(self, role, context, policy):
        if not self.paused:
            self.paused = True
            AgentTaskService(self.db).pause(
                context.task_id,
                TaskControl(
                    reason="test safe point",
                    idempotency_key="pause-safe-point-001",
                    actor="test",
                ),
            )
        return super().plan(role, context, policy)


def test_pause_stops_at_safe_point_and_resume_retries_only_interrupted_node(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]), key="graph-pause-001")
    runtime = ResearchGraphRuntime(
        db,
        provider=PauseOnceProvider(db),
        tool_runner=BuiltinResearchToolRunner(db),
    )

    paused = runtime.run(task_id)
    assert paused["task"]["status"] == "paused"
    assert paused["nodes"][0]["status"] == "paused"
    AgentTaskService(db).resume(
        task_id,
        TaskControl(
            reason="resume safe point",
            idempotency_key="resume-safe-point-001",
            actor="test",
        ),
    )

    completed = runtime.run(task_id)
    assert completed["task"]["status"] == "completed"
    attempts = Counter(row.node_key for row in TaskNodeRunService(db).list(task_id))
    assert attempts["preflight"] == 2
    assert attempts["data_quality"] == 1


class StrategySpecProvider(DeterministicGapRoleProvider):
    def synthesize(self, role, context, observations):
        if role.key != "strategy_engineer":
            return super().synthesize(role, context, observations)
        mandate = context.mandate
        spec = StrategySpecDraft(
            mandate_id=str(mandate["id"]),
            strategy_key="btc_trend_graph_candidate",
            title="BTC trend graph candidate",
            hypothesis="A bounded trend rule may persist after declared costs.",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_category="TREND",
            entry_logic="Enter only after a deterministic bounded trend condition.",
            exit_logic="Exit on deterministic invalidation and bounded risk controls.",
            risk_conditions=["Never exceed the mandate drawdown boundary."],
            data_requirements=["Chronological real BTC 1H OHLCV and declared costs."],
            parameter_bounds={"lookback": {"min": 10, "max": 50}},
            invalidation_conditions=["Locked out-of-sample evidence does not pass."],
        )
        return ProviderResult(
            RoleOutput(
                summary="Queued candidate for trusted orchestrator validation.",
                evidence=[
                    DataGapDraft(
                        claim="Validation is pending in the trusted orchestrator queue.",
                        confidence=0,
                        expected_sources=["tool"],
                        remediation="Run the linked ResearchOrchestrator job.",
                    )
                ],
                strategy_spec=spec.model_dump(mode="json"),
            ),
            RoleUsage(),
        )


def test_strategy_spec_handoff_queues_existing_orchestrator_contract(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    task_id = _graph_task(db, str(mandate["id"]), key="graph-handoff-001")
    runtime = ResearchGraphRuntime(
        db,
        provider=StrategySpecProvider(),
        tool_runner=BuiltinResearchToolRunner(db),
    )

    completed = runtime.run(task_id)

    assert completed["task"]["status"] == "completed"
    validation_job_id = completed["configuration"]["validation_job_id"]
    validation_job = ResearchProgramService(db).get_job(validation_job_id)
    assert validation_job["status"] == "queued"
    assert validation_job["strategy_spec"]["strategy_key"] == "btc_trend_graph_candidate"
    assert validation_job["source_run_id"] == task_id


class FakeBitProReads:
    def capabilities(self):
        return {"contract_version": "test", "status": "available"}

    def health(self):
        return {"status": "ok"}

    def market_klines(self, **kwargs):
        return {"status": "available", "request": kwargs, "candles": []}

    def backtest_get_job(self, **kwargs):
        return {"status": "completed", "request": kwargs}

    def backtest_get_result(self, **kwargs):
        return {"status": "completed", "request": kwargs, "metrics": {}}


def test_research_graph_api_requires_admin_mutation_and_has_public_projection(tmp_path) -> None:
    db = _db(tmp_path)
    mandate = _mandate(db)
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="graph-api-test",
            DEEPSEEK_API_KEY="",
            KNOWLEDGE_DIR=knowledge,
        ),
        db=db,
        bitpro_adapter=FakeBitProReads(),  # type: ignore[arg-type]
    )
    client = TestClient(app)
    payload = {
        "mandate_id": mandate["id"],
        "objective": "Bounded API research graph with no trading action",
        "idempotency_key": "graph-api-task-001",
        "capabilities": {"derivatives": False, "event_context": False},
    }

    assert client.post("/api/research/graphs", json=payload).status_code == 401
    assert client.get("/api/research/graphs/topology").status_code == 200
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    created = client.post("/api/research/graphs", json=payload)
    assert created.status_code == 200
    task_id = created.json()["task"]["id"]
    replay = client.post("/api/research/graphs", json=payload)
    assert replay.json()["idempotency_replayed"] is True

    completed = client.post(f"/api/research/graphs/{task_id}/run")
    assert completed.status_code == 200
    assert completed.json()["task"]["status"] == "completed"
    client.cookies.clear()
    public = client.get(f"/api/research/graphs/{task_id}")
    assert public.status_code == 200
    assert len(public.json()["nodes"]) == 13
    assert [item["id"] for item in client.get("/api/research/graphs").json()["items"]] == [
        task_id
    ]
