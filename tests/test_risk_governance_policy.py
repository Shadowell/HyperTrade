from hypertrade.risk.governance import RiskGovernancePolicy
from hypertrade.tools.registry import ToolRegistry


def test_governance_policy_allows_read_tools_without_idempotency() -> None:
    policy = RiskGovernancePolicy(ToolRegistry.default())

    decision = policy.evaluate("market_summary", {})

    assert decision.allowed is True
    assert decision.status == "allowed"
    assert decision.registry_tool_name == "market.summary"
    assert decision.policy.scope == "read"
    assert decision.requires_idempotency is False
    assert decision.as_trace_payload()["denial_reason"] == ""


def test_governance_policy_denies_paper_write_without_idempotency_key() -> None:
    policy = RiskGovernancePolicy(ToolRegistry.default())

    decision = policy.evaluate("bitpro_paper_start", {"strategy_id": 7})

    assert decision.allowed is False
    assert decision.status == "denied"
    assert decision.registry_tool_name == "bitpro.paper_start"
    assert decision.policy.scope == "paper_write"
    assert decision.requires_idempotency is True
    assert decision.missing_fields == ["idempotency_key"]
    assert decision.denial_reason == "missing required field: idempotency_key"


def test_governance_policy_marks_live_order_intent_approval_required() -> None:
    policy = RiskGovernancePolicy(ToolRegistry.default())

    decision = policy.evaluate(
        "live_order_intent",
        {
            "symbol": "ETH",
            "side": "buy",
            "size": "0.01",
            "reason": "operator requested testnet intent",
            "idempotency_key": "run_1_live_order",
        },
    )

    assert decision.allowed is True
    assert decision.status == "approval_required"
    assert decision.registry_tool_name == "live.order_intent"
    assert decision.policy.scope == "testnet_write"
    assert decision.requires_approval is True
    assert decision.requires_idempotency is True
    assert decision.missing_fields == []
