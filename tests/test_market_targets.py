from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from hypertrade.config import get_settings
from hypertrade.targets import (
    CANONICAL_TOOLS,
    MARKET_EVOLUTION_CONTRACT_V1,
    MarketTargetProfileV1,
    MarketTargetUnavailable,
    McpContractClient,
    TargetCalendarV1,
    build_mcp_contract_profile,
    get_active_market_target,
    get_market_target,
    register_market_target,
    registered_market_targets,
    reset_market_targets,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_market_targets()
    yield
    reset_market_targets()


def test_bitpro_target_registers_from_profile() -> None:
    binding = get_market_target("bitpro")
    profile = binding.profile
    assert profile.transport == "bitpro_mcp_v1"
    assert profile.venue == "okx"
    assert profile.market_type == "swap"
    assert profile.strategy_id_format == "integer"
    assert profile.calendar.mode == "continuous"
    assert profile.calendar.evidence_window_days == 14
    assert profile.calendar.evidence_bucket_seconds == 3600
    assert "strategy_return_series.v1" in profile.evidence_contracts
    assert "bitpro_backtest_cost_resolver" in profile.cost_policy_sources
    assert profile.capabilities.paper_launch is True


def test_bitpro_adapter_factory_builds_lazy_client() -> None:
    binding = get_market_target("bitpro")
    assert binding.adapter_factory is not None
    adapter = binding.adapter_factory()
    assert hasattr(adapter, "paper_snapshot")
    assert hasattr(adapter, "strategy_return_series")


def test_unknown_target_is_refused_with_registered_list() -> None:
    with pytest.raises(MarketTargetUnavailable) as excinfo:
        get_market_target("quantlab")
    assert "bitpro" in str(excinfo.value)


def test_duplicate_registration_is_refused_unless_replaced() -> None:
    profile = build_mcp_contract_profile("quantlab", "QuantLab")
    register_market_target(profile)
    with pytest.raises(ValueError):
        register_market_target(profile)
    register_market_target(profile, replace=True)
    assert "quantlab" in {item.target_id for item in registered_market_targets()}


def test_active_target_follows_settings(monkeypatch) -> None:
    profile = build_mcp_contract_profile(
        "quantlab", "QuantLab（A股/美股）", venue="cn", market_type="cash"
    )
    marker = object()
    register_market_target(profile, lambda: marker)
    settings = get_settings()
    monkeypatch.setattr(settings, "market_target", "quantlab", raising=False)
    binding = get_active_market_target()
    assert binding.profile.target_id == "quantlab"
    assert binding.adapter_factory is not None
    assert binding.adapter_factory() is marker


def test_mcp_contract_profile_defaults_and_validation() -> None:
    profile = build_mcp_contract_profile("quantlab", "QuantLab")
    assert profile.transport == "mcp_contract_v1"
    assert profile.tool_contract == MARKET_EVOLUTION_CONTRACT_V1
    assert profile.strategy_id_format == "string"
    assert profile.capabilities.live_preflight is False
    with pytest.raises(ValueError):
        MarketTargetProfileV1(
            target_id="Bad Id!",
            display_name="x",
            transport="mcp_contract_v1",
        )
    with pytest.raises(ValueError):
        TargetCalendarV1(evidence_window_days=0)


class FakeMcpRegistry:
    """Minimal stand-in for McpClientRegistry's async surface."""

    def __init__(self, tools: list[str], *, fail_list: bool = False) -> None:
        self._tools = tools
        self._fail_list = fail_list
        self.calls: list[tuple[str, str, dict]] = []

    async def list_tools(self, server: str, *, force_refresh: bool = False):
        if self._fail_list:
            raise RuntimeError("discovery down")
        return [SimpleNamespace(name=name) for name in self._tools]

    async def call_tool(self, server: str, tool_name: str, arguments: dict):
        self.calls.append((server, tool_name, arguments))
        return {"called": tool_name, "server": server}


def _client(tools: list[str] | None = None, *, fail_list: bool = False):
    profile = build_mcp_contract_profile("quantlab", "QuantLab")
    registry = FakeMcpRegistry(
        tools if tools is not None else sorted(CANONICAL_TOOLS.values()),
        fail_list=fail_list,
    )
    return profile, registry, McpContractClient(registry, "quantlab", profile)


def test_mcp_contract_preflight_ok_when_all_canonical_tools_present() -> None:
    _, _, client = _client()
    report = asyncio.run(client.preflight())
    assert report.ok is True
    assert report.missing == ()
    assert set(report.present) == set(CANONICAL_TOOLS.values())


def test_mcp_contract_preflight_reports_missing_tools() -> None:
    tools = sorted(CANONICAL_TOOLS.values())[:-1]
    _, _, client = _client(tools)
    report = asyncio.run(client.preflight())
    assert report.ok is False
    assert report.missing == (CANONICAL_TOOLS["start_paper"],)


def test_mcp_contract_preflight_reports_discovery_errors() -> None:
    _, _, client = _client(fail_list=True)
    report = asyncio.run(client.preflight())
    assert report.ok is False
    assert report.errors and "discovery down" in report.errors[0]


def test_mcp_contract_call_routes_canonical_capability() -> None:
    _, registry, client = _client()
    result = asyncio.run(
        client.call_canonical("get_session_snapshot", {"strategy_id": "600519.SH"})
    )
    assert result == {"called": "evolution_get_session_snapshot", "server": "quantlab"}
    assert registry.calls == [
        ("quantlab", "evolution_get_session_snapshot", {"strategy_id": "600519.SH"})
    ]
    with pytest.raises(MarketTargetUnavailable):
        asyncio.run(client.call_canonical("nonsense", {}))


def test_mcp_contract_client_refuses_non_contract_profile() -> None:
    bitpro_profile = get_market_target("bitpro").profile
    with pytest.raises(ValueError):
        McpContractClient(FakeMcpRegistry([]), "bitpro", bitpro_profile)
