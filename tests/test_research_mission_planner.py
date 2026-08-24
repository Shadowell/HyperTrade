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
async def test_planner_reads_testnet_intents_without_unrelated_paper_state() -> None:
    mission = await _mission("查看待批准的 Testnet 订单")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "execution.intent_summary",
    ]


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
async def test_best_live_strategy_synonym_uses_a_ranked_performance_read() -> None:
    mission = await _mission("看下我最好的实盘策略是哪个？")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert plan.steps[-1].capability_id == "bitpro.live_strategy_summary"
    assert plan.steps[-1].arguments == {
        "exchange": "okx",
        "limit": 20,
        "sort": "desc",
        "presentation": "best",
    }


@pytest.mark.anyio
async def test_bare_explicit_market_symbol_uses_an_exact_ticker_read() -> None:
    mission = await _mission("看下 LAB 的价格")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert plan.steps[-1].capability_id == "market.summary"
    assert plan.steps[-1].arguments == {"limit": 10, "inst_id": "LAB-USDT-SWAP"}


@pytest.mark.anyio
async def test_market_overview_does_not_turn_market_language_into_a_symbol() -> None:
    mission = await _mission("现在合约市场整体怎么样")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert plan.steps[-1].capability_id == "market.summary"
    assert plan.steps[-1].arguments == {"limit": 10}


@pytest.mark.anyio
async def test_memory_source_question_uses_memory_without_an_unrelated_rag_gap() -> None:
    mission = await _mission("历史策略记忆的来源是什么")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "memory.search",
    ]


@pytest.mark.anyio
async def test_missing_memory_query_never_falls_back_to_unrelated_rag() -> None:
    mission = await _mission("记忆里没有记录的策略表现如何")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "memory.search",
        "strategy.performance_summary",
    ]


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


class _MarketQuoteProvider:
    name = "test"
    model = "semantic-intent"

    def chat(self, messages, tools=None):  # type: ignore[no-untyped-def]
        del messages, tools
        return ChatResponse(
            content='{"intent":{"kind":"market_quote","assets":["LAB"]}}',
            usage=TokenUsage(total_tokens=12, reported=True),
        )


class _InventedMarketQuoteProvider:
    name = "test"
    model = "semantic-intent"

    def chat(self, messages, tools=None):  # type: ignore[no-untyped-def]
        del messages, tools
        return ChatResponse(
            content='{"intent":{"kind":"market_quote","assets":["ETH"]}}',
            usage=TokenUsage(total_tokens=12, reported=True),
        )


class _BtcQuoteProvider:
    name = "test"
    model = "semantic-intent"

    def chat(self, messages, tools=None):  # type: ignore[no-untyped-def]
        del messages, tools
        return ChatResponse(
            content='{"intent":{"kind":"market_quote","assets":["BTC"]}}',
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


@pytest.mark.anyio
async def test_provider_semantic_intent_can_bind_a_user_verbatim_market_symbol() -> None:
    mission = await _mission("Show LAB price")

    plan = await ProviderBackedResearchPlanner(provider=_MarketQuoteProvider()).plan(mission)

    assert plan.steps[-1].capability_id == "market.summary"
    assert plan.steps[-1].arguments == {"limit": 10, "inst_id": "LAB-USDT-SWAP"}
    assert plan.assumptions[-1].startswith("Provider-extracted market symbol")


@pytest.mark.anyio
async def test_provider_cannot_invent_market_symbol_absent_from_objective() -> None:
    mission = await _mission("Show LAB price")

    plan = await ProviderBackedResearchPlanner(provider=_InventedMarketQuoteProvider()).plan(
        mission
    )

    # The deterministic route remains a generic summary; provider ETH is
    # discarded because it is not a standalone symbol in the objective.
    assert plan.steps[-1].arguments == {"limit": 10}


@pytest.mark.anyio
async def test_provider_cannot_extract_a_partial_market_symbol_from_a_word() -> None:
    mission = await _mission("Show ETHEREUM price")

    plan = await ProviderBackedResearchPlanner(provider=_InventedMarketQuoteProvider()).plan(
        mission
    )

    assert plan.steps[-1].arguments == {"limit": 10}


@pytest.mark.anyio
async def test_chinese_alias_binds_the_symbol_on_the_deterministic_path() -> None:
    """“比特币” carries no ASCII token; the closed alias table resolves it."""
    mission = await _mission("比特币现在多少钱一个？")

    plan = await DeterministicResearchPlanner().plan(mission)

    assert plan.steps[-1].capability_id == "market.summary"
    assert plan.steps[-1].arguments == {"limit": 10, "inst_id": "BTC-USDT-SWAP"}


@pytest.mark.anyio
async def test_chinese_alias_validates_the_provider_symbol() -> None:
    mission = await _mission("比特币现在多少钱一个？")

    plan = await ProviderBackedResearchPlanner(provider=_BtcQuoteProvider()).plan(mission)

    assert plan.steps[-1].capability_id == "market.summary"
    assert plan.steps[-1].arguments == {"limit": 10, "inst_id": "BTC-USDT-SWAP"}


@pytest.mark.anyio
async def test_provider_symbol_without_alias_fails_closed_on_chinese_objective() -> None:
    """An invented symbol still fails: only the closed alias table unlocks Chinese."""
    mission = await _mission("比特币现在多少钱一个？")

    plan = await ProviderBackedResearchPlanner(provider=_InventedMarketQuoteProvider()).plan(
        mission
    )

    assert plan.steps[-1].arguments == {"limit": 10, "inst_id": "BTC-USDT-SWAP"}
