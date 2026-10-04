"""Tests for QuantLab quantitative workbench target compatibility."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from hypertrade.agent.kernel import AgentKernel
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.config import get_settings
from hypertrade.db import Database
from hypertrade.targets import (
    QUANTLAB_TARGET_ID,
    QUANTLAB_TARGET_PROFILE,
    QuantLabTargetAdapter,
    get_active_market_target,
    get_market_target,
    quantlab_adapter_factory,
    register_quantlab_target,
    registered_market_targets,
    reset_market_targets,
)
from hypertrade.targets.mcp_contract import McpContractClient
from hypertrade.targets.ports import (
    EvidencePort,
    MarketWritePort,
    PaperProvisionPort,
    PaperSessionPort,
    StrategySourcePort,
)
from hypertrade.targets.registry import MarketTargetUnavailable
from hypertrade.tools.registry import ToolRegistry


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    settings = get_settings()
    monkeypatch.setattr(settings, "quantlab_mcp_url", None, raising=False)
    reset_market_targets()
    yield
    reset_market_targets()


def test_quantlab_target_profile_properties() -> None:
    profile = QUANTLAB_TARGET_PROFILE
    assert profile.target_id == QUANTLAB_TARGET_ID
    assert profile.transport == "mcp_contract_v1"
    assert profile.tool_contract == "market-evolution.v1"
    assert profile.venue == "multi_asset"
    assert profile.market_type == "cash"
    assert profile.quote_currency == "CNY"
    assert profile.strategy_id_format == "string"
    assert profile.calendar.mode == "sessions"
    assert profile.calendar.timezone == "Asia/Shanghai"
    assert profile.calendar.session_open == "09:30"
    assert profile.calendar.session_close == "15:00"
    assert profile.calendar.evidence_window_days == 14
    assert profile.capabilities.running_inventory is True
    assert profile.capabilities.session_snapshot is True
    assert profile.capabilities.paper_launch is True
    assert profile.capabilities.live_preflight is False


def test_quantlab_target_registration_and_retrieval() -> None:
    binding = register_quantlab_target()
    assert binding.profile.target_id == QUANTLAB_TARGET_ID
    assert binding.adapter_factory is not None

    retrieved = get_market_target("quantlab")
    assert retrieved.profile.target_id == QUANTLAB_TARGET_ID
    assert retrieved.profile.display_name == "QuantLab 量化交易工作台"

    # Idempotent registration
    register_quantlab_target(replace=False)
    assert "quantlab" in {t.target_id for t in registered_market_targets()}


def test_quantlab_active_target_switching(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "market_target", "quantlab", raising=False)

    binding = get_active_market_target()
    assert binding.profile.target_id == "quantlab"
    assert binding.adapter_factory is not None
    adapter = quantlab_adapter_factory(simulation=True)
    assert isinstance(adapter, QuantLabTargetAdapter)


def test_quantlab_adapter_conforms_to_typed_ports() -> None:
    adapter = QuantLabTargetAdapter(simulation=True)
    assert isinstance(adapter, StrategySourcePort)
    assert isinstance(adapter, PaperSessionPort)
    assert isinstance(adapter, EvidencePort)
    assert isinstance(adapter, PaperProvisionPort)
    assert isinstance(adapter, MarketWritePort)


def test_quantlab_read_ports_operations() -> None:
    adapter = QuantLabTargetAdapter(simulation=True)

    # Strategy source port
    running = adapter.list_running_strategies(limit=10)
    assert len(running) >= 1
    sid = running[0].strategy_id
    assert sid.startswith("quantlab:")

    total, unavailable = adapter.inventory_coverage()
    assert total >= 1
    assert unavailable == ()

    source = adapter.get_strategy_source(sid)
    assert source.strategy_id == sid
    assert "QuantLabMovingAverageStrategy" in source.code
    assert source.timeframe == "1H"
    assert len(source.symbols) >= 1

    # Paper session port
    snapshot = adapter.get_session_snapshot(strategy_id=sid)
    assert snapshot.strategy_id == sid
    assert snapshot.status == "running"
    assert snapshot.trade_count >= 50
    assert snapshot.session_started_at is not None
    assert snapshot.session_started_at.tzinfo is not None

    # Evidence port: fills
    fills = adapter.list_fills(sid, limit=50)
    assert len(fills) > 0
    assert fills[0].strategy_id == sid

    # Evidence port: trading sessions
    cal = adapter.list_trading_sessions(start_date="2026-09-01", end_date="2026-09-20")
    assert cal.timezone == "Asia/Shanghai"
    assert cal.complete is True
    assert len(cal.trading_dates) > 10

    # Evidence port: equity series
    iid = snapshot.instance_id
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    series = adapter.read_equity_series(iid, start_ms=0, end_ms=now_ms)
    assert series.complete is True
    assert len(series.points) >= 15
    assert series.currency == "CNY"
    assert series.timezone == "Asia/Shanghai"


def test_quantlab_write_ports_lifecycle() -> None:
    adapter = QuantLabTargetAdapter(simulation=True)

    # 1. Deploy strategy
    custom_code = 'class CustomTrendAlpha:\n    pass\n'
    deploy_res = adapter.deploy_strategy(
        name="[现货][1H][CTA] 600519 · 动量追踪 · 200000CNY",
        code=custom_code,
        config={"fast": 5, "slow": 20, "symbols": ("600519.SH",)},
    )
    assert deploy_res["status"] == "deployed"
    sid = deploy_res["strategy_id"]
    assert sid.startswith("quantlab:deployed_")

    # Verify deployed strategy appears in source
    src = adapter.get_strategy_source(sid)
    assert src.code == custom_code

    # 2. Configure paper
    cfg_res = adapter.configure_paper(
        candidate_key="cand_12345678",
        strategy_id=sid,
        capital=200000.0,
        symbols=("600519.SH",),
    )
    assert cfg_res["status"] == "configured"
    assert cfg_res["capital"] == 200000.0

    # 3. Start paper
    start_res = adapter.start_paper("cand_12345678", strategy_id=sid)
    assert start_res["status"] == "running"
    snap = adapter.get_session_snapshot(strategy_id=sid)
    assert snap.status == "running"

    # 4. Stop paper
    stop_res = adapter.stop_paper("cand_12345678", strategy_id=sid)
    assert stop_res["status"] == "stopped"
    snap_stopped = adapter.get_session_snapshot(strategy_id=sid)
    assert snap_stopped.status == "stopped"


def test_quantlab_agent_kernel_tool_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "hypertrade.targets.quantlab.quantlab_adapter_factory",
        lambda: QuantLabTargetAdapter(simulation=True),
    )
    db = Database(f"sqlite:///{tmp_path}/agent_quantlab.db")
    db.create_all()

    kernel = AgentKernel(db=db)

    # 1. target_profile tool
    prof_result = kernel._dispatch_tool(
        "target_profile",
        {},
        run_id="run_test_prof",
        policy=ToolRegistry.default().get("target.profile").policy,
    )
    assert "target_id" in prof_result
    assert "calendar" in prof_result

    # 2. quantlab_capabilities tool
    cap_result = kernel._dispatch_tool(
        "quantlab_capabilities",
        {},
        run_id="run_test_cap",
        policy=ToolRegistry.default().get("quantlab.capabilities").policy,
    )
    assert cap_result["target_id"] == "quantlab"
    assert cap_result["venue"] == "multi_asset"
    assert cap_result["calendar"]["mode"] == "sessions"

    # 3. quantlab_strategies tool
    strat_result = kernel._dispatch_tool(
        "quantlab_strategies",
        {"limit": 10},
        run_id="run_test_strat",
        policy=ToolRegistry.default().get("quantlab.strategies").policy,
    )
    assert strat_result["target_id"] == "quantlab"
    assert strat_result["count"] >= 1
    assert len(strat_result["strategies"]) >= 1

    # 4. quantlab_paper_snapshot tool
    snap_result = kernel._dispatch_tool(
        "quantlab_paper_snapshot",
        {"strategy_id": "quantlab:alpha_trend_01"},
        run_id="run_test_snap",
        policy=ToolRegistry.default().get("quantlab.paper_snapshot").policy,
    )
    assert snap_result["strategy_id"] == "quantlab:alpha_trend_01"
    assert snap_result["status"] == "running"
    assert snap_result["trade_count"] >= 50

    # 5. quantlab_deploy tool
    deploy_result = kernel._dispatch_tool(
        "quantlab_deploy",
        {
            "name": "[现货][1H][CTA] 000858 · 智能自进化 · 500000CNY",
            "code": "class SelfEvolvedAlpha:\n    pass\n",
            "config": {"symbols": ["000858.SZ"]},
            "start_paper": True,
        },
        run_id="run_test_deploy",
        policy=ToolRegistry.default().get("quantlab.deploy").policy,
    )
    assert deploy_result["status"] == "deployed"
    assert deploy_result["paper_session"]["status"] == "running"


def test_quantlab_factory_requires_real_transport_or_explicit_simulator() -> None:
    with pytest.raises(MarketTargetUnavailable, match="MCP URL is not configured"):
        quantlab_adapter_factory()

    assert isinstance(
        quantlab_adapter_factory(simulation=True), QuantLabTargetAdapter
    )


class _QuantLabMcpRegistry:
    def __init__(
        self, *, omit: str | None = None, identity_mismatch: str | None = None
    ) -> None:
        self.omit = omit
        self.identity_mismatch = identity_mismatch
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self, server: str, *, force_refresh: bool = False):
        names = {
            "evolution_list_running_strategies",
            "evolution_get_session_snapshot",
            "evolution_get_equity_series",
            "evolution_list_session_trades",
            "evolution_get_strategy_source",
            "evolution_list_trading_sessions",
            "evolution_configure_paper",
            "evolution_start_paper",
            "evolution_stop_paper",
            "backtest_start_job",
            "backtest_get_job",
        }
        return [SimpleNamespace(name=name) for name in names if name != self.omit]

    async def call_tool(self, server: str, name: str, arguments: dict):
        self.calls.append((name, arguments))
        base = {"schema_version": "market-evolution.v1", "target_id": "quantlab"}
        if name == "evolution_configure_paper":
            return {
                **base,
                "status": "configured",
                "instance_id": "paper_remote_1",
                "strategy_id": (
                    "wrong-strategy"
                    if self.identity_mismatch == "configure_strategy"
                    else arguments["strategy_id"]
                ),
            }
        if name == "evolution_start_paper":
            return {
                **base,
                "status": "running",
                "instance_id": (
                    "wrong-instance"
                    if self.identity_mismatch == "start_instance"
                    else arguments["instance_id"]
                ),
                "strategy_id": arguments["strategy_id"],
            }
        if name == "backtest_start_job":
            return {**base, "status": "running", "job_id": "bt_remote_1"}
        if name == "backtest_get_job":
            return {**base, "status": "completed", "job_id": arguments["job_id"], "metrics": {}}
        raise AssertionError(name)


def _remote_quantlab_adapter(registry: _QuantLabMcpRegistry) -> QuantLabTargetAdapter:
    return QuantLabTargetAdapter(
        McpContractClient(registry, "quantlab", QUANTLAB_TARGET_PROFILE)
    )


def test_quantlab_remote_writes_forward_verified_identity_and_idempotency() -> None:
    registry = _QuantLabMcpRegistry()
    adapter = _remote_quantlab_adapter(registry)
    configured = adapter.configure_paper(
        "candidate-1",
        strategy_id="opaque-42",
        capital=100000,
        symbols=["600519.SH"],
        timeframe="1D",
    )
    started = adapter.start_paper(
        "candidate-1",
        strategy_id="opaque-42",
        instance_id=configured["instance_id"],
    )
    assert started["instance_id"] == "paper_remote_1"
    assert registry.calls[0][1]["idempotency_key"] == "quantlab:candidate-1:configure"
    assert registry.calls[1][1]["idempotency_key"] == "quantlab:candidate-1:start"
    assert registry.calls[1][1]["instance_id"] == configured["instance_id"]
    started_job = adapter.backtest_start_job(strategy_id="opaque-42")
    completed_job = adapter.backtest_get_job(started_job["job_id"])
    assert completed_job["status"] == "completed"
    with pytest.raises(MarketTargetUnavailable, match="relay status"):
        adapter.paper_relay_status("opaque-42")


def test_quantlab_remote_write_requires_advertised_tool() -> None:
    adapter = _remote_quantlab_adapter(
        _QuantLabMcpRegistry(omit="evolution_configure_paper")
    )
    with pytest.raises(MarketTargetUnavailable, match="does not advertise"):
        adapter.configure_paper(
            "candidate-1",
            strategy_id="opaque-42",
            symbols=["600519.SH"],
            timeframe="1D",
        )


@pytest.mark.parametrize(
    "mismatch,operation",
    [("configure_strategy", "configure"), ("start_instance", "start")],
)
def test_quantlab_remote_write_rejects_identity_mismatch(mismatch, operation) -> None:
    adapter = _remote_quantlab_adapter(
        _QuantLabMcpRegistry(identity_mismatch=mismatch)
    )
    if operation == "configure":
        with pytest.raises(MarketTargetUnavailable, match="strategy identity mismatch"):
            adapter.configure_paper(
                "candidate-1",
                strategy_id="opaque-42",
                symbols=["600519.SH"],
                timeframe="1D",
            )
    else:
        with pytest.raises(MarketTargetUnavailable, match="instance identity mismatch"):
            adapter.start_paper(
                "candidate-1",
                strategy_id="opaque-42",
                instance_id="paper_remote_1",
            )


def test_quantlab_evolution_service_integration(tmp_path: Path) -> None:
    register_quantlab_target(replace=True)
    db = Database(f"sqlite:///{tmp_path}/evolution_quantlab.db")
    db.create_all()

    adapter = quantlab_adapter_factory(simulation=True)
    service = EvolutionService(db, adapter)

    config = EvolutionConfig(
        enabled=True,
        target_id="quantlab",
        strategy_ids=["quantlab:alpha_trend_01"],
        min_trades=50,
        threshold_pp=Decimal("5"),
    )
    service.configure(config, revision=0, actor="test_operator")

    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 9, 25, 14, 0, tzinfo=tz)

    diagnostics, chosen = service._scan(config, now)
    assert len(diagnostics) == 1
    diag = diagnostics[0]
    assert diag["target_id"] == "quantlab"
    assert diag["strategy_id"] == "quantlab:alpha_trend_01"

    # Verify tick does NOT defer because quantlab adapter implements write ports!
    tick_result = service.tick(now)
    assert tick_result["status"] != "deferred_target_write_port"
