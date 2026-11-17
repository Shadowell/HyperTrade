from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.controller import ARCMissionProjection
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.forward_outcomes import ForwardOutcomeLedger
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.bitpro.mcp import BitProMcpError
from hypertrade.db import ArcMission, Database
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    LayeredMemoryService,
    SemanticMemoryAssertionV1,
)
from hypertrade.memory.service import MemoryService
from hypertrade.runtime.adapters.capability_catalog import (
    InMemoryCapabilityCatalog,
    builtin_capabilities,
)
from hypertrade.runtime.adapters.foundation import (
    FoundationExecutor,
    FoundationPlanner,
    ReadOnlyCapabilityPolicy,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.research_planner import (
    DeterministicResearchPlanner,
    LlmPlanV2Planner,
)
from hypertrade.runtime.adapters.thread_store import InMemoryThreadStore
from hypertrade.runtime.adapters.tool_runtime import GovernedToolExecutor, builtin_handlers
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.application.thread_context import compile_thread_context
from hypertrade.runtime.application.thread_service import ThreadTurnService
from hypertrade.runtime.domain.models import (
    MissionCreate,
    PlanDiffV1,
    PlanStepV2,
    PlanV2,
    SuccessCriterionV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeBitProAdapter:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]:
        self.calls.append(
            ("paper_snapshot", {"strategy_id": strategy_id, "instance_id": instance_id})
        )
        if self.fail:
            raise BitProMcpError("connection refused")
        return {
            "status": "ok",
            "snapshot": {
                "strategy_id": strategy_id or 583,
                "strategy_name": "Trend Alpha 583",
                "instance_id": instance_id or "paper_583",
                "status": "running",
                "equity": "1042.50",
                "return_pct": "4.25",
                "max_drawdown_pct": "1.80",
                "sharpe_ratio": "1.65",
                "trade_count": 18,
                "symbols": ["BTC-USDT-SWAP"],
            },
        }

    def paper_dashboard(self, *, strategy_id: int | None = None) -> dict[str, Any]:
        self.calls.append(("paper_dashboard", {"strategy_id": strategy_id}))
        if self.fail:
            raise BitProMcpError("connection refused")
        return {
            "status": "ok",
            "dashboard": {
                "system": {"strategy_id": 583, "strategy": "Trend Alpha 583", "state": "running"},
                "equity": {"current": "1042.50"},
                "performance": {
                    "total_pnl_pct": "4.25",
                    "max_drawdown_pct": "1.80",
                    "sharpe_ratio": "1.65",
                    "trade_count": 18,
                },
            },
            "running_strategies": {
                "items": [
                    {
                        "id": 583,
                        "name": "Trend Alpha 583",
                        "status": "running",
                        "total_pnl_pct": "4.25",
                        "max_drawdown_pct": "1.80",
                    }
                ]
            },
        }

    def paper_strategy_performance(self, *, limit: int = 20) -> dict[str, Any]:
        self.calls.append(("paper_strategy_performance", {"limit": limit}))
        if self.fail:
            raise BitProMcpError("connection refused")
        return {
            "status": "ok",
            "strategies": [
                {
                    "strategy_id": 583,
                    "strategy_name": "Trend Alpha 583",
                    "status": "running",
                    "equity": "1042.50",
                    "return_pct": "4.25",
                    "max_drawdown_pct": "1.80",
                    "sharpe_ratio": "1.65",
                    "trade_count": 18,
                }
            ],
            "performance_summary": {"comparable_count": 1},
        }

    def paper_relay_plans(self) -> list[dict[str, Any]]:
        self.calls.append(("paper_relay_plans", {}))
        if self.fail:
            raise BitProMcpError("connection refused")
        return [
            {"parent_id": 583, "challenger_id": 901, "state": "observing", "generation": 2},
            {"parent_id": 100, "challenger_id": 200, "state": "completed", "generation": 1},
        ]

    def strategy_research_variant_policy(self, *, strategy_id: int) -> dict[str, Any]:
        self.calls.append(("strategy_research_variant_policy", {"strategy_id": strategy_id}))
        if self.fail:
            raise BitProMcpError("connection refused")
        return {
            "contract_version": "strategy_research_variant_policy.v1",
            "parent_strategy_id": strategy_id,
            "parent_manifest_sha256": "a" * 64,
            "parent_execution_identity_sha256": "e" * 64,
            "authorized_parameters": [
                {"key": "fast_window", "type": "integer", "min": 5, "max": 50},
                {"key": "stop_atr_mult", "type": "number", "min": 1.0, "max": 4.0},
            ],
            "relay": {
                "role": "parent",
                "plan_state": "observing",
                "blocks_evolution": False,
                "slots": {"total": 3, "used": 1, "free": 2, "queued": 1},
            },
        }


async def _make_executor(
    db: Database,
    *,
    adapter: _FakeBitProAdapter | None = None,
) -> tuple[InMemoryCapabilityCatalog, GovernedToolExecutor]:
    catalog = InMemoryCapabilityCatalog()
    await catalog.bootstrap(builtin_capabilities())
    fake = adapter or _FakeBitProAdapter()
    executor = GovernedToolExecutor(
        catalog,
        builtin_handlers(
            db,
            knowledge_dir="docs/knowledge",
            bitpro_adapter_factory=lambda: fake,  # type: ignore[arg-type, return-value]
        ),
    )
    return catalog, executor


async def _mission(objective: str, *, profile: str = "read_only.v1") -> Any:
    return await InMemoryMissionStore().create(
        MissionCreate(
            objective=objective,
            permission_profile_ref=profile,
            success_criteria=(
                SuccessCriterionV1(
                    criterion_id="validated",
                    kind="all_steps_validated",
                    description="All steps validated.",
                ),
            ),
        )
    )


@pytest.mark.anyio
async def test_bitpro_paper_snapshot_single_overview_and_unreachable(tmp_path: Any) -> None:
    db = Database(f"sqlite:///{tmp_path / 'paper.db'}")
    db.create_all()

    adapter = _FakeBitProAdapter()
    _, executor = await _make_executor(db, adapter=adapter)
    mission = await _mission("查看 BitPro 策略 #583 模拟盘快照")
    plan = await DeterministicResearchPlanner().plan(mission)
    step = plan.steps[-1]
    assert step.capability_id == "bitpro.paper_snapshot"
    assert step.arguments["strategy_id"] == 583

    obs = await executor.execute(mission, plan, step, 1)
    assert obs.status == "succeeded"
    assert obs.source_refs == ("bitpro_mcp:paper_snapshot", "bitpro_mcp:paper_snapshot:583")
    assert obs.result["count"] == 1
    assert obs.result["items"][0]["equity"] == "1042.50"
    assert obs.result["items"][0]["trade_count"] == 18
    assert "1042.5" in obs.summary
    assert "4.25%" in obs.summary
    assert "1.65" in obs.summary

    # Overview mode (no strategy_id) calls dashboard + performance
    overview_mission = await _mission("BitPro 模拟盘运行概况")
    overview_plan = await DeterministicResearchPlanner().plan(overview_mission)
    overview_obs = await executor.execute(
        overview_mission, overview_plan, overview_plan.steps[-1], 1
    )
    assert overview_obs.status == "succeeded"
    assert overview_obs.result["count"] == 1
    assert any(name == "paper_dashboard" for name, _ in adapter.calls)
    assert any(name == "paper_strategy_performance" for name, _ in adapter.calls)

    # Unreachable BitPro returns structured unknown cleanly
    _, down_executor = await _make_executor(db, adapter=_FakeBitProAdapter(fail=True))
    down_obs = await down_executor.execute(mission, plan, step, 1)
    assert down_obs.status == "succeeded"
    assert down_obs.source_refs == ("bitpro_mcp:paper_snapshot:no_matches",)
    assert down_obs.unknowns
    assert down_obs.result["source_available"] is False


@pytest.mark.anyio
async def test_bitpro_variant_status_and_arc_evolution_status(tmp_path: Any) -> None:
    db = Database(f"sqlite:///{tmp_path / 'evo.db'}")
    db.create_all()
    configure_store(db)
    try:
        service = EvolutionService(db)
        service.configure(
            EvolutionConfig(enabled=True, launch_enabled=True), revision=0, actor="test"
        )
        ForwardOutcomeLedger(db).record(
            target_id="bitpro",
            parent_strategy_id=583,
            challenger_strategy_id=901,
            verdict="won",
            metrics={"excess_return_pp": "2.4"},
            ended_at=datetime.now(UTC),
        )
        with db.session() as session:
            proj = ARCMissionProjection(
                mission_id="arc_obs_583",
                state="paper_observing",
                goal=ARCGoalV1(
                    objective="583 variant",
                    symbols=["BTC-USDT"],
                    timeframes=["1H"],
                    evolution_context={"source_strategy_id": 583},
                ),
            )
            session.add(
                ArcMission(
                    mission_id="arc_obs_583",
                    state="paper_observing",
                    projection_json=proj.model_dump(mode="json"),
                )
            )

        _, executor = await _make_executor(db)
        mission = await _mission("为什么策略 #583 没有生成变体？看下槽位、赛马和 ARC 自进化状态")
        plan = await DeterministicResearchPlanner().plan(mission)
        assert [step.capability_id for step in plan.steps] == [
            "runtime.objective_inspection",
            "arc.evolution_status",
            "bitpro.variant_status",
        ]
        assert plan.steps[1].arguments == {"strategy_id": 583}
        assert plan.steps[2].arguments == {"strategy_id": 583}

        arc_obs = await executor.execute(mission, plan, plan.steps[1], 1)
        assert arc_obs.status == "succeeded"
        assert arc_obs.source_refs == ("hypertrade_db:arc_evolution",)
        assert arc_obs.result["forward_outcomes"]["by_verdict"]["won"] == 1
        assert arc_obs.result["active_missions"][0]["mission_id"] == "arc_obs_583"
        assert "前向赛马胜/负 1/0" in arc_obs.summary

        var_obs = await executor.execute(mission, plan, plan.steps[2], 1)
        assert var_obs.status == "succeeded"
        assert "bitpro_mcp:variant_status" in var_obs.source_refs
        assert var_obs.result["slots"] == {
            "total": 3,
            "used": 1,
            "free": 2,
            "queued": 1,
            "open": 1,
        }
        assert len(var_obs.result["active_races"]) == 1
        assert "槽位 1/3 已占用" in var_obs.summary
    finally:
        reset_store()


@pytest.mark.anyio
async def test_memory_write_governance_and_unified_memory_search(tmp_path: Any) -> None:
    db = Database(f"sqlite:///{tmp_path / 'memory.db'}")
    db.create_all()

    _, executor = await _make_executor(db)
    write_step = PlanStepV2(
        step_id="write_note",
        title="Write operator memory note",
        capability_id="memory.write",
        arguments={
            "content": "策略 #583 在高波动震荡市需收紧回撤阈值",
            "kind": "operator_note",
            "tags": ["#583", "BTC"],
        },
        read_only=False,
    )
    write_plan = PlanV2(
        plan_id="plan_mem_write",
        version=1,
        goal_interpretation="write memory",
        completion_checks=("validated",),
        steps=(write_step,),
        diff=PlanDiffV1(reason_code="initial_plan"),
    )

    # read_only.v1 denies research_write memory.write
    ro_mission = await _mission("记住策略观察", profile="read_only.v1")
    denied = await executor.execute(ro_mission, write_plan, write_step, 1)
    assert denied.status == "failed"
    assert denied.error_category == "permission_denied"

    # research.v1 allows memory.write and replays idempotently
    rw_mission = await _mission("记住策略观察", profile="research.v1")
    first = await executor.execute(rw_mission, write_plan, write_step, 1)
    replay = await executor.execute(rw_mission, write_plan, write_step, 2)
    assert first.status == "succeeded"
    assert replay.status == "succeeded"
    assert first.result["memory_id"] == replay.result["memory_id"]

    # Seed Tier 2/3 cognitive memory rows + one recall_eligible=False row
    layered = LayeredMemoryService(db)
    layered.record_semantic_assertion(
        SemanticMemoryAssertionV1(
            id="asmt_583_rule",
            assertion_type="causal_heuristic",
            claim="策略 #583 在震荡市缩短快线周期可降低回撤",
            applicable_regimes=["sideways_range"],
            confidence=Decimal("0.7500"),
            derived_from_episodes=["ep_1", "ep_2"],
        )
    )
    layered.record_episode(
        EpisodicMemoryItemV1(
            id="ep_583_won",
            mission_id="mis_583_1",
            symbols=["BTC-USDT-SWAP"],
            timeframe="1H",
            market_regime="sideways_range",
            event_type="paper_race_won",
            reflection_summary="策略 #583 变体前向赛马胜出，超额收益 +2.4pp",
            metadata={"recall_eligible": True},
        )
    )
    layered.record_episode(
        EpisodicMemoryItemV1(
            id="ep_583_hidden",
            mission_id="mis_583_2",
            symbols=["BTC-USDT-SWAP"],
            timeframe="1H",
            market_regime="sideways_range",
            event_type="backtest_success",
            reflection_summary="策略 #583 未通过准入的噪声实验",
            metadata={"recall_eligible": False},
        )
    )

    search_step = PlanStepV2(
        step_id="memory_context",
        title="Search unified memory",
        capability_id="memory.search",
        arguments={"query": "583", "limit": 10},
    )
    search_plan = PlanV2(
        plan_id="plan_mem_search",
        version=1,
        goal_interpretation="search memory",
        completion_checks=("validated",),
        steps=(search_step,),
        diff=PlanDiffV1(reason_code="initial_plan"),
    )
    search_obs = await executor.execute(ro_mission, search_plan, search_step, 1)
    assert search_obs.status == "succeeded"
    assert "items" in search_obs.result and "count" in search_obs.result
    assert any(ref.startswith("memory:") for ref in search_obs.source_refs)
    assert any(ref == "cognitive_semantic:asmt_583_rule" for ref in search_obs.source_refs)
    assert any(ref == "cognitive_episodic:ep_583_won" for ref in search_obs.source_refs)
    assert all("ep_583_hidden" not in ref for ref in search_obs.source_refs)

    # Sentinel unrecorded query must never false-match unrelated cognitive memory
    miss_step = search_step.model_copy(
        update={"arguments": {"query": "__unrecorded_strategy__", "limit": 10}}
    )
    miss_plan = search_plan.model_copy(update={"steps": (miss_step,)})
    miss_obs = await executor.execute(ro_mission, miss_plan, miss_step, 1)
    assert miss_obs.source_refs == ("memory:no_matches",)
    assert miss_obs.result == {"items": [], "count": 0}


@pytest.mark.anyio
async def test_thread_context_numeric_bitpro_strategy_ids_and_followup() -> None:
    store = InMemoryThreadStore()
    snapshot = await store.create_thread(
        tenant_id="default",
        owner="operator",
        title="BitPro 583",
        retention="durable",
    )
    assert snapshot.thread is not None
    tid = snapshot.thread.thread_id
    snapshot, t1, _ = await store.start_turn(
        tid,
        client_message_id="m1",
        text="看下策略 #583 在 BTC-USDT-SWAP 的模拟盘快照",
        actor="operator",
    )
    ctx1 = compile_thread_context(snapshot, t1.turn_id)
    assert ctx1.subject_kind == "bitpro_strategy"
    assert ctx1.subject_refs == ("#583",)
    assert ctx1.resolved_subject == "#583"

    snapshot = await store.append(
        tid,
        "turn.contextualization_started",
        actor="runtime",
        payload={"turn_id": t1.turn_id},
    )
    snapshot = await store.append(
        tid,
        "turn.context_resolved",
        actor="runtime",
        payload={"turn_id": t1.turn_id, "resolved_context": ctx1.model_dump(mode="json")},
    )
    snapshot = await store.append(
        tid,
        "turn.failed",
        actor="runtime",
        payload={"turn_id": t1.turn_id, "code": "done"},
    )
    snapshot, t2, _ = await store.start_turn(
        tid,
        client_message_id="m2",
        text="它的变体槽位有哪些？",
        actor="operator",
    )
    ctx2 = compile_thread_context(snapshot, t2.turn_id)
    assert ctx2.subject_kind == "bitpro_strategy"
    assert ctx2.resolved_subject == "#583"
    assert ctx2.normalized_objective.startswith("上文指代对象为 #583")

    # Planner keeps generic routes unchanged while routing new prompts accurately
    memory_mission = await _mission("之前在记忆里保存的偏好是什么")
    mem_plan = await DeterministicResearchPlanner().plan(memory_mission)
    assert [s.capability_id for s in mem_plan.steps] == [
        "runtime.objective_inspection",
        "memory.search",
    ]
    research_mission = await _mission("Research BTC market strategy evidence")
    research_plan = await DeterministicResearchPlanner().plan(research_mission)
    assert "arc.evolution_status" not in [s.capability_id for s in research_plan.steps]

    planner = LlmPlanV2Planner(provider=None)
    assert {
        "bitpro.paper_snapshot",
        "bitpro.variant_status",
        "arc.evolution_status",
    } <= set(planner._envelope_for_profile("read_only.v1"))
    assert "memory.write" not in planner._envelope_for_profile("read_only.v1")
    assert "memory.write" in planner._envelope_for_profile("research.v1")


@pytest.mark.anyio
async def test_thread_service_consolidates_remember_and_bitpro_observations(tmp_path: Any) -> None:
    db = Database(f"sqlite:///{tmp_path / 'thread_mem.db'}")
    db.create_all()
    thread_store = InMemoryThreadStore()
    mission_store = InMemoryMissionStore()
    catalog = InMemoryCapabilityCatalog()
    await catalog.bootstrap(builtin_capabilities())
    adapter = _FakeBitProAdapter()
    executor = GovernedToolExecutor(
        catalog,
        builtin_handlers(
            db,
            knowledge_dir="docs/knowledge",
            bitpro_adapter_factory=lambda: adapter,  # type: ignore[arg-type, return-value]
        ),
    )
    runtime = MissionRuntime(
        mission_store,
        DeterministicResearchPlanner(),
        executor,
        CatalogCapabilityPolicyStub(catalog),
    )
    service = ThreadTurnService(thread_store, mission_store, runtime, worker_enabled=False)
    thread = await service.create_thread(owner="operator", title="Consolidate", retention="durable")
    assert thread.thread is not None
    tid = thread.thread.thread_id

    # 1. Explicit remember note
    _, turn1, _ = await service.start_turn(
        tid,
        client_message_id="remember-1",
        text="记住：策略 #583 在震荡市不要加仓",
        actor="operator",
    )
    await service.execute_turn(tid, turn1.turn_id)
    notes = MemoryService(db).search(kind="operator_note")
    assert len(notes) == 1
    assert notes[0].source_tool == "thread_turn.consolidate"
    assert "#583" in notes[0].tags

    # 2. BitPro Paper observation automatically consolidated
    _, turn2, _ = await service.start_turn(
        tid,
        client_message_id="obs-583",
        text="看下策略 #583 的 BitPro 模拟盘快照",
        actor="operator",
    )
    await service.execute_turn(tid, turn2.turn_id)
    observations = MemoryService(db).search(kind="strategy_observation")
    assert len(observations) == 1
    assert "4.25%" in observations[0].content
    assert observations[0].source_tool == "thread_turn.consolidate"

    # 3. Unreachable BitPro (no grounded evidence) does not pollute strategy_observation
    down_executor = GovernedToolExecutor(
        catalog,
        builtin_handlers(
            db,
            knowledge_dir="docs/knowledge",
            bitpro_adapter_factory=lambda: _FakeBitProAdapter(fail=True),  # type: ignore[arg-type, return-value]
        ),
    )
    down_service = ThreadTurnService(
        thread_store,
        mission_store,
        MissionRuntime(
            mission_store,
            DeterministicResearchPlanner(),
            down_executor,
            CatalogCapabilityPolicyStub(catalog),
        ),
        worker_enabled=False,
    )
    _, turn3, _ = await down_service.start_turn(
        tid,
        client_message_id="obs-583-down",
        text="看下策略 #583 的 BitPro 模拟盘快照",
        actor="operator",
    )
    await down_service.execute_turn(tid, turn3.turn_id)
    assert len(MemoryService(db).search(kind="strategy_observation")) == 1

    # 4. Pure InMemory runtime without DB never fails consolidation
    mem_thread_store = InMemoryThreadStore()
    mem_mission_store = InMemoryMissionStore()
    mem_service = ThreadTurnService(
        mem_thread_store,
        mem_mission_store,
        MissionRuntime(
            mem_mission_store,
            FoundationPlanner(),
            FoundationExecutor(),
            ReadOnlyCapabilityPolicy(),
        ),
        worker_enabled=False,
    )
    mem_thread = await mem_service.create_thread(owner="op", title="NoDB", retention="durable")
    assert mem_thread.thread is not None
    _, mem_turn, _ = await mem_service.start_turn(
        mem_thread.thread.thread_id,
        client_message_id="nodb-1",
        text="remember this note without db",
        actor="op",
    )
    await mem_service.execute_turn(mem_thread.thread.thread_id, mem_turn.turn_id)
    done = await mem_thread_store.get(mem_thread.thread.thread_id)
    assert done.turn(mem_turn.turn_id).status.value == "completed"


class CatalogCapabilityPolicyStub:
    def __init__(self, catalog: InMemoryCapabilityCatalog) -> None:
        from hypertrade.runtime.adapters.capability_catalog import CatalogCapabilityPolicy

        self._inner = CatalogCapabilityPolicy(catalog)

    def validate_step(self, step: PlanStepV2, permission_profile_ref: str) -> None:
        self._inner.validate_step(step, permission_profile_ref)
