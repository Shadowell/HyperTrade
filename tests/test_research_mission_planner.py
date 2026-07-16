from __future__ import annotations

import pytest
from hypertrade.providers.chat import ChatResponse, TokenUsage
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.research_planner import (
    DeterministicResearchPlanner,
    ProviderBackedResearchPlanner,
)
from hypertrade.runtime.domain.models import MissionCreate, ReplanRequestV1, SuccessCriterionV1


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _mission(objective: str):
    return await InMemoryMissionStore().create(
        MissionCreate(
            objective=objective,
            success_criteria=(
                SuccessCriterionV1(
                    criterion_id="validated",
                    kind="all_steps_validated",
                    description="Every step must have a validated observation.",
                ),
            ),
        )
    )


@pytest.mark.anyio
async def test_deterministic_planner_builds_a_bounded_research_plan() -> None:
    mission = await _mission("研究 BTC 市场状态并寻找策略证据")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "market.summary",
        "rag.search",
        "memory.search",
        "strategy.performance_summary",
    ]
    assert all(step.read_only and not step.requires_approval for step in plan.steps)
    assert plan.steps[-1].depends_on == ("memory_context",)


@pytest.mark.anyio
async def test_planner_adds_read_summaries_for_paper_and_testnet_queries() -> None:
    mission = await _mission("查看待批准的 Testnet 订单与模拟盘持仓")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "paper.summary",
        "execution.intent_summary",
    ]
    assert all(step.read_only and not step.requires_approval for step in plan.steps)


@pytest.mark.anyio
async def test_live_strategy_inventory_uses_bitpro_without_generic_retrieval() -> None:
    mission = await _mission("我的实盘策略有哪些")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "bitpro.live_strategy_summary",
    ]
    assert plan.steps[-1].arguments == {"exchange": "okx", "limit": 20}


@pytest.mark.anyio
async def test_replan_removes_the_failed_data_step_and_preserves_audit_diff() -> None:
    mission = await _mission("Research BTC market strategy evidence")
    planner = DeterministicResearchPlanner()
    original = await planner.plan(mission)

    replanned = await planner.replan(
        mission,
        original,
        ReplanRequestV1(
            trigger="capability_unavailable",
            summary="Market source is unavailable.",
            failed_step_id="market_snapshot",
        ),
    )

    assert replanned.version == 2
    assert replanned.parent_version == 1
    assert "market_snapshot" in replanned.diff.removed
    assert all(step.step_id != "market_snapshot" for step in replanned.steps)


class _UnsafeProvider:
    name = "test"
    model = "unsafe"

    def chat(self, messages, tools=None):  # type: ignore[no-untyped-def]
        return ChatResponse(
            content=(
                '{"goal_interpretation":"do it","steps":[{"step_id":"order",'
                '"title":"Place a live order","depends_on":[],"capability_id":"live.order",'
                '"arguments":{}}]}'
            ),
            usage=TokenUsage(total_tokens=12, reported=True),
        )


class _OmittingProvider:
    name = "test"
    model = "omitting"

    def chat(self, messages, tools=None):  # type: ignore[no-untyped-def]
        return ChatResponse(
            content=(
                '{"goal_interpretation":"inspect only","steps":[{"step_id":"inspect_objective",'
                '"title":"Inspect only","depends_on":[],'
                '"capability_id":"runtime.objective_inspection",'
                '"arguments":{"objective":"ignored"}}]}'
            ),
            usage=TokenUsage(total_tokens=12, reported=True),
        )


@pytest.mark.anyio
async def test_provider_cannot_expand_capability_scope() -> None:
    mission = await _mission("研究 BTC 市场状态")

    plan = await ProviderBackedResearchPlanner(provider=_UnsafeProvider()).plan(mission)

    assert "live.order" not in [step.capability_id for step in plan.steps]
    assert all(step.read_only for step in plan.steps)


@pytest.mark.anyio
async def test_provider_cannot_omit_or_retarget_a_deterministic_market_read() -> None:
    mission = await _mission("看下 ZZZZNOTREALUSDT 合约行情")

    plan = await ProviderBackedResearchPlanner(provider=_OmittingProvider()).plan(mission)

    assert [(step.step_id, step.capability_id) for step in plan.steps] == [
        ("inspect_objective", "runtime.objective_inspection"),
        ("market_snapshot", "market.summary"),
    ]
    assert plan.steps[-1].arguments == {
        "limit": 10,
        "inst_id": "ZZZZNOTREAL-USDT-SWAP",
    }
