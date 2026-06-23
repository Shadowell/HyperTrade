from hypertrade.tools.registry import ToolRegistry


def test_tool_registry_exposes_sprint_one_tools_and_live_gate():
    registry = ToolRegistry.default()

    names = {tool.name for tool in registry.list_tools()}

    assert {"market.summary", "rag.search", "memory.write", "live.order_intent"} <= names
    assert {
        "bitpro.capabilities",
        "bitpro.health",
        "bitpro.market_klines",
        "bitpro.paper_dashboard",
        "bitpro.paper_events",
        "bitpro.paper_equity_curve",
        "bitpro.paper_monitor_snapshot",
        "bitpro.live_positions",
    } <= names
    assert "market.intelligence" in names
    assert "strategy.library_search" in names
    assert "strategy.experiment_plan" in names
    assert all(tool.description.strip() for tool in registry.list_tools())
    assert registry.get("market.summary").requires_approval is False
    assert registry.get("bitpro.market_klines").requires_approval is False
    assert registry.get("live.order_intent").requires_approval is True


def test_tool_registry_attaches_policy_metadata_to_every_tool():
    registry = ToolRegistry.default()

    for tool in registry.list_tools():
        policy = tool.policy
        assert policy.scope in {
            "read",
            "research_write",
            "paper_write",
            "testnet_write",
            "live_diagnostic_read",
            "live_write",
        }
        assert policy.approval in {"none", "required", "blocked"}
        assert policy.idempotency in {"not_required", "required"}
        assert policy.source_of_truth
        assert policy.timeout_class in {"quick", "standard", "long"}
        assert policy.safe_sample_limit >= 0

    assert registry.get("market.summary").policy.scope == "read"
    assert registry.get("market.summary").policy.approval == "none"
    assert registry.get("bitpro.paper_start").policy.scope == "paper_write"
    assert registry.get("bitpro.paper_start").policy.idempotency == "required"
    assert registry.get("live.order_intent").policy.scope == "testnet_write"
    assert registry.get("live.order_intent").policy.approval == "required"
    assert registry.get("live.order_intent").policy.idempotency == "required"
