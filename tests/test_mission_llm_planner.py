"""Sprint-138: LLM-proposed mission plan DAGs with deterministic validation.

The model may choose which reviewed read capabilities to use, in what order,
and with which bounded arguments. Every test here pins a trust boundary:
capability envelope, JSON Schema arguments, verbatim market entities, step
budgets, and the deterministic fallback contract.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypertrade.providers.chat import ChatResponse
from hypertrade.runtime.adapters.capability_catalog import builtin_capabilities
from hypertrade.runtime.adapters.research_planner import (
    DeterministicResearchPlanner,
    LlmPlanV2Planner,
    build_mission_planner,
)
from hypertrade.runtime.domain.models import MissionProjection, ReplanRequestV1


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _mission(objective: str = "研究 BTC-USDT-SWAP 现在的行情并给出结论") -> MissionProjection:
    from hypertrade.runtime.domain.models import (
        MissionBudgetV1,
        MissionStatus,
        SuccessCriterionV1,
    )

    return MissionProjection(
        mission_id="mis_llm_planner_01",
        objective=objective,
        original_objective=objective,
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="all_validated",
                kind="all_steps_validated",
                description="Every step validated.",
            ),
        ),
        constraints=(),
        status=MissionStatus.PLANNING,
        budget=MissionBudgetV1(),
        permission_profile_ref="read_only.v1",
        context_policy_ref="mission_context.v1",
        created_by="operator",
    )


class _ScriptedProvider:
    """Replays canned chat responses; records prompts for assertions."""

    def __init__(self, *responses: str | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []
        self.name = "scripted"
        self.model = "llm-planner-test"

    def chat(self, messages: list[dict[str, Any]]) -> ChatResponse:
        self.calls.append(messages)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResponse(content=item)


def _plan_content(steps: list[dict[str, Any]], goal: str = "读取行情并检索知识") -> str:
    return json.dumps(
        {"goal_interpretation": goal, "steps": steps},
        ensure_ascii=False,
    )


def _summary_step(inst_id: str | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {"limit": 10}
    if inst_id:
        arguments["inst_id"] = inst_id
    return {
        "step_id": "market_snapshot",
        "title": "Read verified market summary",
        "capability_id": "market.summary",
        "arguments": arguments,
        "depends_on": ["inspect_objective"],
    }


def _base_step() -> dict[str, Any]:
    return {
        "step_id": "inspect_objective",
        "title": "Validate the research objective",
        "capability_id": "runtime.objective_inspection",
        "arguments": {"objective": "研究 BTC-USDT-SWAP 现在的行情并给出结论"},
        "depends_on": [],
    }


@pytest.mark.anyio
async def test_llm_plan_proposes_valid_dag_within_envelope() -> None:
    provider = _ScriptedProvider(
        _plan_content(
            [
                _base_step(),
                _summary_step("BTC-USDT-SWAP"),
                {
                    "step_id": "knowledge_gap",
                    "title": "Search curated knowledge",
                    "capability_id": "rag.search",
                    "arguments": {"query": "BTC 行情 研究结论", "limit": 5},
                    "depends_on": ["market_snapshot"],
                },
            ]
        )
    )
    planner = LlmPlanV2Planner(provider=provider)

    plan = await planner.plan(_mission())

    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "market.summary",
        "rag.search",
    ]
    market_step = plan.steps[1]
    assert market_step.arguments["inst_id"] == "BTC-USDT-SWAP"
    assert market_step.read_only is True
    assert market_step.requires_approval is False
    # Output schemas come from the catalog, never from the model.
    catalog_output = next(
        definition.output_schema
        for definition in builtin_capabilities()
        if definition.capability_id == "market.summary"
    )
    assert market_step.expected_output_schema == dict(catalog_output)
    assert plan.diff.reason_code == "llm_initial_plan"
    assert any("re-validates against the reviewed" in item for item in plan.assumptions)


@pytest.mark.anyio
async def test_llm_plan_rejects_capabilities_outside_the_read_envelope() -> None:
    provider = _ScriptedProvider(
        _plan_content(
            [
                _base_step(),
                {
                    "step_id": "sneaky_write",
                    "title": "Start a paper instance",
                    "capability_id": "paper.start",
                    "arguments": {},
                    "depends_on": [],
                },
            ]
        ),
        _plan_content([_base_step()], goal="缩到只检查目标"),
    )
    planner = LlmPlanV2Planner(provider=provider)

    plan = await planner.plan(_mission())

    # Repair round dropped the out-of-envelope step, but the inspect-only repair
    # then omits the suggested capabilities, so the deterministic plan wins.
    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "market.summary",
        "rag.search",
    ]
    assert plan.diff.reason_code == "initial_plan"
    assert len(provider.calls) == 2
    # The repair round's user message carries the first round's rejection reason;
    # the suggested-capabilities rejection terminalizes to the deterministic plan
    # without a third provider call.
    repair_rejected = provider.calls[1][-1]["content"]
    assert "outside the reviewed read-only envelope" in repair_rejected


@pytest.mark.anyio
async def test_llm_plan_falls_back_after_two_invalid_rounds() -> None:
    provider = _ScriptedProvider(
        _plan_content(
            [
                _base_step(),
                {
                    "step_id": "sneaky_write",
                    "title": "Start a paper instance",
                    "capability_id": "paper.start",
                    "arguments": {},
                    "depends_on": [],
                },
            ]
        ),
        _plan_content(
            [
                _base_step(),
                {
                    "step_id": "still_sneaky",
                    "title": "Try live writes instead",
                    "capability_id": "live.order_intent",
                    "arguments": {},
                    "depends_on": [],
                },
            ]
        ),
    )
    planner = LlmPlanV2Planner(provider=provider)

    plan = await planner.plan(_mission())

    # Both rounds invalid -> deterministic fallback, byte-for-byte current behavior.
    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "market.summary",
        "rag.search",
    ]
    assert plan.diff.reason_code == "initial_plan"
    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_llm_plan_arguments_must_satisfy_catalog_json_schema() -> None:
    bad = _summary_step()
    bad["arguments"] = {"limit": 999}  # catalog caps limit at 50
    provider = _ScriptedProvider(
        _plan_content([_base_step(), bad]),
        _plan_content([_base_step(), _summary_step()]),
    )
    planner = LlmPlanV2Planner(provider=provider)

    plan = await planner.plan(_mission())

    # Repair round succeeded with schema-valid arguments.
    assert plan.steps[1].arguments["limit"] == 10
    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_llm_plan_cannot_invent_market_entity_absent_from_objective() -> None:
    provider = _ScriptedProvider(
        _plan_content(
            [
                _base_step(),
                _summary_step("ETH-USDT-SWAP"),  # objective only mentions BTC
            ]
        ),
        _plan_content([_base_step()]),
    )
    planner = LlmPlanV2Planner(provider=provider)

    plan = await planner.plan(_mission())

    # The repaired inspect-only plan omits the deterministically suggested
    # capabilities, so the planner falls back to the deterministic plan — whose
    # market step carries the objective's OWN symbol, never the invented ETH.
    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "market.summary",
        "rag.search",
    ]
    inst_ids = [
        step.arguments.get("inst_id")
        for step in plan.steps
        if "inst_id" in step.arguments
    ]
    assert inst_ids == ["BTC-USDT-SWAP"]


@pytest.mark.anyio
async def test_llm_plan_step_budget_is_enforced() -> None:
    steps = [_base_step()]
    for index in range(12):
        steps.append(
            {
                "step_id": f"step_{index}",
                "title": f"Extra step {index}",
                "capability_id": "rag.search",
                "arguments": {"query": "x", "limit": 1},
                "depends_on": ["inspect_objective"],
            }
        )
    provider = _ScriptedProvider(_plan_content(steps), _plan_content([_base_step()]))
    planner = LlmPlanV2Planner(provider=provider)

    plan = await planner.plan(_mission())

    # The budget-rejected proposal goes through repair; the repaired inspect-only
    # plan then omits the suggested capabilities and the deterministic fallback
    # (which respects the step budget) wins.
    assert [step.capability_id for step in plan.steps] == [
        "runtime.objective_inspection",
        "market.summary",
        "rag.search",
    ]


@pytest.mark.anyio
async def test_provider_failure_falls_back_deterministically() -> None:
    provider = _ScriptedProvider(RuntimeError("provider down"))
    planner = LlmPlanV2Planner(provider=provider)

    plan = await planner.plan(_mission())

    assert plan.diff.reason_code == "initial_plan"
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_replan_uses_llm_path_and_increments_version() -> None:
    mission = _mission()
    planner = LlmPlanV2Planner(
        provider=_ScriptedProvider(
            _plan_content(
                [
                    _base_step(),
                    _summary_step("BTC-USDT-SWAP"),
                ]
            )
        )
    )
    first = await planner.plan(mission)

    provider = _ScriptedProvider(_plan_content([_base_step()], goal="缩到最小计划"))
    planner = LlmPlanV2Planner(provider=provider)
    request = ReplanRequestV1(
        trigger="capability_unavailable",
        summary="market summary source unavailable",
        failed_step_id="market_snapshot",
    )
    second = await planner.replan(mission, first, request)

    assert second.version == 2
    assert second.parent_version == 1
    assert second.diff.reason_code == "capability_unavailable"
    assert all(step.capability_id != "market.summary" for step in second.steps)


def test_factory_respects_flag_and_provider_availability() -> None:
    class _Settings:
        mission_llm_planner_enabled = True

    class _OffSettings:
        mission_llm_planner_enabled = False

    assert isinstance(build_mission_planner(_Settings(), None), DeterministicResearchPlanner)

    provider = _ScriptedProvider()
    off = build_mission_planner(_OffSettings(), provider)
    assert type(off).__name__ == "ProviderBackedResearchPlanner"

    on = build_mission_planner(_Settings(), provider)
    assert isinstance(on, LlmPlanV2Planner)
    # The envelope only contains reviewed read capabilities.
    assert "paper.start" not in on._envelope
    assert "market.summary" in on._envelope
    catalog_ids = {
        definition.capability_id
        for definition in builtin_capabilities()
        if definition.scope == "read"
        and definition.approval == "none"
        and definition.side_effect == "none"
    }
    assert set(on._envelope) <= catalog_ids
