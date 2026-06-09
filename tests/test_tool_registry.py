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
        "bitpro.live_positions",
    } <= names
    assert registry.get("market.summary").requires_approval is False
    assert registry.get("bitpro.market_klines").requires_approval is False
    assert registry.get("live.order_intent").requires_approval is True
