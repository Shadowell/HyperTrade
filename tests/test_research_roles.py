from __future__ import annotations

import json

import pytest
from hypertrade.providers.chat import ChatResponse, TokenUsage
from hypertrade.research.graph import ResearchGraphSelector, graph_topology_projection
from hypertrade.research.role_provider import ChatResearchRoleProvider, RoleProviderContext
from hypertrade.research.roles.definitions import ROLE_CATALOG, role_catalog_hash
from hypertrade.research.roles.schemas import RoleToolCall
from hypertrade.research.tool_policy import RoleToolDenied, RoleToolPolicyResolver


def test_role_catalog_has_fixed_versioned_topology_and_prompt_hashes() -> None:
    topology = graph_topology_projection()

    assert topology["fixed"] is True
    assert topology["dynamic_agents_allowed"] is False
    assert topology["catalog_hash"] == role_catalog_hash()
    assert set(ROLE_CATALOG) == {
        "preflight",
        "data_quality",
        "market_regime",
        "technical_structure",
        "derivatives_flow",
        "event_context",
        "evidence_synthesis",
        "bull_case",
        "bear_case",
        "strategy_engineer",
        "bitpro_validation",
        "validation_reviewer",
        "risk_committee",
    }
    assert all(len(role.prompt_hash) == 64 for role in ROLE_CATALOG.values())
    assert topology["edges"][-1] == {"from": ["risk_committee"], "to": "__end__"}


def test_selector_never_skips_required_roles_and_marks_optional_gaps() -> None:
    selector = ResearchGraphSelector()
    disabled = selector.select(capabilities={}, max_parallel_roles=99)
    enabled = selector.select(
        capabilities={"derivatives": True, "event_context": True},
        max_parallel_roles=2,
    )

    required = {key for key, role in ROLE_CATALOG.items() if role.required}
    assert required <= set(disabled.selected_nodes)
    assert disabled.disabled_nodes == {
        "derivatives_flow": "capability_unavailable:derivatives",
        "event_context": "capability_unavailable:event_context",
    }
    assert set(enabled.selected_nodes) == set(ROLE_CATALOG)
    assert disabled.max_parallel_roles == 4


def test_role_tool_policy_is_read_only_and_denies_writes_before_dispatch() -> None:
    resolver = RoleToolPolicyResolver()
    for role in ROLE_CATALOG.values():
        policy = resolver.resolve(role)
        assert all(tool.policy.scope == "read" for tool in policy.allowed)
        assert all(tool.policy.approval == "none" for tool in policy.allowed)
        assert "bitpro.paper_start" not in {tool.name for tool in policy.allowed}
        assert "live.order_intent" not in {tool.name for tool in policy.allowed}

    policy = resolver.resolve(ROLE_CATALOG["risk_committee"])
    with pytest.raises(RoleToolDenied, match="not_in_read_only_intersection"):
        resolver.authorize(policy, [RoleToolCall(name="bitpro.paper_start")])
    with pytest.raises(RoleToolDenied, match="secret_or_reasoning_argument"):
        resolver.authorize(
            policy,
            [RoleToolCall(name="research.evidence_read", arguments={"token": "secret"})],
        )


class RepairingChatProvider:
    name = "repair-test"
    model = "repair-test-v1"

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None):
        del messages, tools
        self.calls += 1
        if self.calls == 1:
            content = "not-json"
        else:
            content = (
                '{"summary":"explicit gap","evidence":[{"evidence_type":"data_gap",'
                '"claim":"source unavailable","confidence":0,"source_ids":[],'
                '"supporting_evidence_ids":[],"opposing_evidence_ids":[],'
                '"valid_for_seconds":null,"expected_sources":["tool"],'
                '"remediation":"restore source"}],"strategy_spec":null}'
            )
        return ChatResponse(
            content=content,
            usage=TokenUsage(total_tokens=10, reported=True),
        )


def test_role_output_gets_exactly_one_schema_repair() -> None:
    chat = RepairingChatProvider()
    provider = ChatResearchRoleProvider(chat)
    result = provider.synthesize(
        ROLE_CATALOG["preflight"],
        RoleProviderContext(
            task_id="task_test",
            node_run_id="node_test",
            objective="bounded test",
            mandate={"id": "rman_test"},
            evidence=(),
        ),
        [],
    )

    assert chat.calls == 2
    assert result.value.evidence[0].evidence_type == "data_gap"
    assert result.usage.model_calls == 2
    assert result.usage.tokens == 20


class CapturingPlanProvider:
    name = "capture-test"
    model = "capture-test-v1"

    def __init__(self) -> None:
        self.request: dict = {}

    def chat(self, messages, tools=None):
        del tools
        self.request = json.loads(messages[-1]["content"])
        return ChatResponse(content='{"tool_calls":[],"rationale":"no read needed"}')


def test_tool_plan_contract_enumerates_real_names_without_placeholder() -> None:
    chat = CapturingPlanProvider()
    provider = ChatResearchRoleProvider(chat)
    role = ROLE_CATALOG["preflight"]
    policy = RoleToolPolicyResolver().resolve(role)

    result = provider.plan(
        role,
        RoleProviderContext(
            task_id="task_test",
            node_run_id="node_test",
            objective="bounded test",
            mandate={"id": "rman_test"},
            evidence=(),
        ),
        policy,
    )

    assert result.value.tool_calls == []
    assert chat.request["allowed_tools"] == [tool.name for tool in policy.allowed]
    assert "research.mandate_read" in chat.request["allowed_tools"]
    assert chat.request["output_contract"]["tool_calls"] == []
    assert "allowed.tool" not in json.dumps(chat.request)
