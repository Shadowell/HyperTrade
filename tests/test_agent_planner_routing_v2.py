from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypertrade.agent.planner import (
    TOOL_SCHEMAS,
    AgentPlanner,
    PlannerValidationFailed,
)
from hypertrade.agent.quality import ResearchIntentV2, build_candidate_tool_set
from hypertrade.providers.chat import ChatResponse, ToolCallRequest


def _intent(**updates) -> ResearchIntentV2:
    values = {
        "intent_family": "tool",
        "cohort": "tool_required",
        "execution_mode": "evaluation",
        "read_write_boundary": "read_only",
        "required_tools": ["market_ticker"],
    }
    values.update(updates)
    return ResearchIntentV2(**values)


def test_candidate_set_intersects_role_mandate_connector_source_and_policy() -> None:
    intent = _intent(
        required_source_classes=["okx_rest"],
        role_allowed_tools=["market_ticker", "market_candles", "memory_write"],
        mandate_allowed_tools=["market_ticker", "memory_write"],
        unavailable_connectors=["bitpro"],
    )

    result = build_candidate_tool_set(intent, TOOL_SCHEMAS)

    assert result.included_names == {"market_ticker"}
    assert result.excluded_reasons["memory_write"] == "read_boundary"
    assert "role_allowlist" in result.source_rationale_codes
    assert "mandate_allowlist" in result.source_rationale_codes
    assert "connector_health" in result.source_rationale_codes


def test_safety_candidate_exposes_only_authored_write_for_executor_denial() -> None:
    intent = _intent(
        intent_family="safety",
        cohort="safety",
        required_tools=["memory_write"],
    )

    result = build_candidate_tool_set(intent, TOOL_SCHEMAS)

    assert "memory_write" in result.included_names
    assert "live_order_intent" not in result.included_names


def test_planner_repairs_missing_required_arguments_once_without_expanding_candidates() -> None:
    llm = MagicMock()
    llm.name = "test"
    llm.model = "test"
    llm.chat.side_effect = [
        ChatResponse(
            content="",
            tool_calls=[ToolCallRequest(id="bad", name="market_ticker", arguments={})],
        ),
        ChatResponse(
            content="",
            tool_calls=[
                ToolCallRequest(id="fixed", name="market_ticker", arguments={"symbol": "ETH"})
            ],
        ),
        ChatResponse(content="done"),
    ]
    calls: list[tuple[str, dict]] = []

    result = AgentPlanner(llm).run(
        "read ticker",
        lambda name, args: calls.append((name, args)) or {"status": "available"},
        intent=_intent(),
    )

    assert calls == [("market_ticker", {"symbol": "ETH"})]
    assert result.tool_plan is not None
    assert result.tool_plan.repair_count == 1
    candidate_name_sets = [
        {schema["function"]["name"] for schema in call.kwargs["tools"]}
        for call in llm.chat.call_args_list
    ]
    assert candidate_name_sets[0] == candidate_name_sets[1] == candidate_name_sets[2]


def test_planner_fails_closed_after_single_required_route_repair() -> None:
    llm = MagicMock()
    llm.name = "test"
    llm.model = "test"
    llm.chat.side_effect = [ChatResponse(content="no tool"), ChatResponse(content="still none")]

    with pytest.raises(PlannerValidationFailed, match="after one bounded repair"):
        AgentPlanner(llm).run("read ticker", lambda *_: {}, intent=_intent())

    assert llm.chat.call_count == 2
