"""Non-BitPro contract evidence reaches scan decisions without external writes."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypertrade.arc.contracts import PaperFeedbackPolicyV1
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.evolution_continuation import ContinuationLedger, continuation_source_id
from hypertrade.arc.feedback import collect_windows
from hypertrade.connectors.mcp_client import (
    McpClientRegistry,
    McpServerConfig,
    McpToolDescriptor,
)
from hypertrade.db import Database
from hypertrade.targets import (
    TargetCalendarV1,
    build_mcp_contract_profile,
    register_market_target,
    reset_market_targets,
)
from hypertrade.targets.mcp_contract import (
    MARKET_EVOLUTION_CONTRACT_V1,
    READ_EXTENSION_TOOLS,
    McpContractClient,
)
from hypertrade.targets.mcp_read_ports import McpReadPorts
from hypertrade.targets.ports import (
    EquityPoint,
    Fill,
    SeriesPage,
    SessionCalendarEvidence,
    SessionSnapshot,
    StrategyHandle,
    StrategySource,
)
from hypertrade.targets.read_ports import BitProReadPorts
from hypertrade.targets.registry import MarketTargetUnavailable

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 19, 10, tzinfo=TZ)
CALENDAR = TargetCalendarV1(
    mode="sessions",
    timezone="Asia/Shanghai",
    session_open="09:30",
    session_close="15:30",
    trading_days=(0, 1, 2, 3, 4),
)


class ContractReads:
    def __init__(self, *, falling: bool = True) -> None:
        self.dates = tuple(
            date(2026, 8, 31) + timedelta(days=offset)
            for offset in range(19)
            if (date(2026, 8, 31) + timedelta(days=offset)).weekday() < 5
        )
        self.falling = falling
        self.missing_day: str | None = None
        self.calendar_complete = True
        self.calendar_timezone = "Asia/Shanghai"
        self.reads: list[str] = []

    def list_running_strategies(self, limit: int) -> list[StrategyHandle]:
        self.reads.append("inventory")
        return [StrategyHandle("cn-strategy:alpha", "A share", "1H", "paper")]

    def inventory_coverage(self) -> tuple[int, tuple[StrategyHandle, ...]]:
        return 1, ()

    def get_strategy_source(self, strategy_id: str) -> StrategySource:
        self.reads.append("source")
        code = "class Source: pass"
        return StrategySource(
            strategy_id,
            code,
            hashlib.sha256(code.encode()).hexdigest(),
            {"timeframe": "1H"},
            ("600519.SH",),
            "1H",
        )

    def get_session_snapshot(
        self, *, strategy_id: str | None = None, instance_id: str | None = None
    ) -> SessionSnapshot:
        self.reads.append("snapshot")
        return SessionSnapshot(
            "cn-paper:1",
            "cn-strategy:alpha",
            "v1",
            "c1",
            "running",
            60,
            datetime(2026, 8, 1, tzinfo=UTC),
            ("600519.SH",),
            "1H",
        )

    def list_fills(
        self, strategy_id: str, *, limit: int, since_ms: int | None = None
    ) -> list[Fill]:
        self.reads.append("fills")
        return [
            Fill(
                "fill-1",
                int(datetime(2026, 9, 17, tzinfo=UTC).timestamp() * 1000),
                "600519.SH",
                "buy",
                100,
                1,
                strategy_id=strategy_id,
            )
        ]

    def list_trading_sessions(self, *, start_date: str, end_date: str) -> SessionCalendarEvidence:
        self.reads.append("calendar")
        return SessionCalendarEvidence(
            self.calendar_timezone,
            start_date,
            end_date,
            tuple(day.isoformat() for day in self.dates),
            "calendar-source",
            self.calendar_complete,
        )

    def read_equity_series(
        self,
        instance_id: str,
        *,
        start_ms: int,
        end_ms: int,
        bucket_seconds: int,
        limit: int,
    ) -> SeriesPage:
        self.reads.append("series")
        start = datetime.fromtimestamp(start_ms / 1000, UTC).astimezone(TZ)
        day = start.date().isoformat()
        index = self.dates.index(start.date())
        points = []
        for hour in range(7):
            stamp = start + timedelta(hours=hour)
            fraction = (index * 6 + hour) / ((len(self.dates) - 1) * 6)
            equity = 100 + 30 * fraction
            if fraction > 0.5 and self.falling:
                equity = 130 - 45 * ((fraction - 0.5) * 2)
            points.append(
                EquityPoint(
                    int(stamp.timestamp() * 1000),
                    equity,
                    None if day == self.missing_day else day,
                )
            )
        return SeriesPage(
            tuple(points),
            f"source-{day}",
            f"content-{day}",
            True,
            strategy_id="cn-strategy:alpha",
            strategy_version="v1",
            config_version="c1",
            currency="CNY",
            cost_model={"policy_hash": "cost-v1"},
            timezone="Asia/Shanghai",
        )


class OfflineMcpTransport:
    def __init__(self, reads: ContractReads, *, omit: str | None = None) -> None:
        self.reads = reads
        self.omit = omit
        self.target_id = "market-fixture"
        self.called: list[str] = []

    async def list_tools(self, server: McpServerConfig) -> list[McpToolDescriptor]:
        names = {
            "evolution_list_running_strategies",
            "evolution_get_session_snapshot",
            "evolution_get_equity_series",
            "evolution_list_session_trades",
            *READ_EXTENSION_TOOLS.values(),
        }
        return [McpToolDescriptor(server.name, name) for name in names if name != self.omit]

    async def call_tool(self, server: McpServerConfig, tool_name: str, arguments: dict) -> dict:
        self.called.append(tool_name)
        base = {"schema_version": MARKET_EVOLUTION_CONTRACT_V1, "target_id": self.target_id}
        if tool_name == "evolution_list_running_strategies":
            rows = self.reads.list_running_strategies(arguments["limit"])
            return {
                **base,
                "reported_total": 1,
                "strategies": [
                    {
                        "strategy_id": row.strategy_id,
                        "name": row.name,
                        "timeframe": row.timeframe,
                        "mode": row.mode,
                        "symbols": list(row.symbols),
                    }
                    for row in rows
                ],
            }
        if tool_name == "evolution_get_strategy_source":
            row = self.reads.get_strategy_source(arguments["strategy_id"])
            return {
                **base,
                "strategy_id": row.strategy_id,
                "code": row.code,
                "code_sha256": row.code_sha256,
                "config": row.config,
                "symbols": list(row.symbols),
                "timeframe": row.timeframe,
            }
        if tool_name == "evolution_get_session_snapshot":
            row = self.reads.get_session_snapshot(**arguments)
            return {
                **base,
                "instance_id": row.instance_id,
                "strategy_id": row.strategy_id,
                "strategy_version": row.strategy_version,
                "config_version": row.config_version,
                "status": row.status,
                "trade_count": row.trade_count,
                "session_started_at": row.session_started_at.isoformat(),
                "symbols": list(row.symbols),
                "timeframe": row.timeframe,
            }
        if tool_name == "evolution_list_session_trades":
            rows = self.reads.list_fills(arguments["strategy_id"], limit=arguments["limit"])
            return {
                **base,
                "fills": [
                    {
                        "fill_id": row.fill_id,
                        "ts_ms": row.ts_ms,
                        "symbol": row.symbol,
                        "side": row.side,
                        "price": row.price,
                        "qty": row.qty,
                        "fee": row.fee,
                        "pnl": row.pnl,
                        "strategy_id": row.strategy_id,
                    }
                    for row in rows
                ],
            }
        if tool_name == "evolution_list_trading_sessions":
            row = self.reads.list_trading_sessions(**arguments)
            return {
                **base,
                "timezone": row.timezone,
                "start_date": row.start_date,
                "end_date": row.end_date,
                "trading_dates": list(row.trading_dates),
                "source_hash": row.source_hash,
                "complete": row.complete,
            }
        if tool_name == "evolution_get_equity_series":
            row = self.reads.read_equity_series(
                arguments["instance_id"],
                start_ms=arguments["start"],
                end_ms=arguments["end"],
                bucket_seconds=arguments["bucket_seconds"],
                limit=arguments["limit"],
            )
            return {
                **base,
                "instance_id": arguments["instance_id"],
                "strategy_id": row.strategy_id,
                "strategy_version": row.strategy_version,
                "config_version": row.config_version,
                "currency": row.currency,
                "cost_model": row.cost_model,
                "timezone": row.timezone,
                "source_hash": row.source_hash,
                "content_hash": row.content_hash,
                "complete": row.complete,
                "points": [
                    {"ts_ms": point.ts_ms, "equity": point.equity, "trading_day": point.trading_day}
                    for point in row.points
                ],
            }
        raise AssertionError(f"unexpected MCP tool {tool_name}")


@pytest.fixture(autouse=True)
def registry():
    reset_market_targets()
    yield
    reset_market_targets()


def test_string_target_scan_reaches_session_degradation_and_write_boundary(tmp_path):
    client = ContractReads()
    register_market_target(
        build_mcp_contract_profile(
            "market-fixture",
            "Market fixture",
            calendar=CALENDAR,
            venue="cn",
            market_type="cash",
            quote_currency="CNY",
        ),
        lambda: client,
    )
    db = Database(f"sqlite:///{tmp_path}/target-read.db")
    db.create_all()
    service = EvolutionService(db, client)
    config = EvolutionConfig(target_id="market-fixture", strategy_ids=["cn-strategy:alpha"])
    service.configure(config, revision=0, actor="test")
    diagnostics, chosen = service._scan(config, NOW)
    assert chosen is not None
    assert chosen["target_id"] == "market-fixture"
    assert chosen["source_strategy_id"] == "cn-strategy:alpha"
    assert chosen["paper_feedback"]["triggered"] is True
    assert chosen["paper_feedback"]["measurement"] == "session_paper_equity"
    assert len(chosen["paper_feedback"]["receipts"]) == 14
    assert diagnostics[-1]["status"] == "opportunity"
    assert "trading_calendar_evidence" not in {
        row["code"] for row in diagnostics[-1]["continuation"]["blockers"]
    }
    assert {"inventory", "snapshot", "source", "fills", "calendar", "series"} <= set(client.reads)
    result = service.tick(NOW)
    assert result["status"] == "deferred_target_write_port"
    assert result["payload"]["skip_reason"] == "target_paper_write_port_not_migrated"


@pytest.mark.parametrize("fault", ["missing_day", "calendar_incomplete", "calendar_timezone"])
def test_session_evidence_missing_or_ambiguous_fails_closed(fault):
    client = ContractReads()
    if fault == "missing_day":
        client.missing_day = client.dates[-1].isoformat()
    elif fault == "calendar_incomplete":
        client.calendar_complete = False
    else:
        client.calendar_timezone = "UTC"
    with pytest.raises(ValueError, match="trading_day|session_calendar"):
        collect_windows(
            client,
            "cn-paper:1",
            "cn-strategy:alpha",
            NOW,
            PaperFeedbackPolicyV1(enabled=True),
            calendar=CALENDAR,
        )


def test_stable_session_series_does_not_trigger():
    result = collect_windows(
        ContractReads(falling=False),
        "cn-paper:1",
        "cn-strategy:alpha",
        NOW,
        PaperFeedbackPolicyV1(enabled=True),
        calendar=CALENDAR,
    )
    assert result["triggered"] is False
    assert result["calendar"]["timezone"] == "Asia/Shanghai"
    assert len(result["calendar"]["trading_dates"]) == 14
    assert result["previous"]["end_at"] < result["recent"]["start_at"]


def test_scan_does_not_infer_eligibility_from_calendar_days(tmp_path):
    client = ContractReads()
    client.calendar_complete = False
    register_market_target(
        build_mcp_contract_profile("market-fixture", "Market fixture", calendar=CALENDAR),
        lambda: client,
    )
    db = Database(f"sqlite:///{tmp_path}/missing-calendar.db")
    db.create_all()
    config = EvolutionConfig(target_id="market-fixture")
    diagnostics, chosen = EvolutionService(db, client)._scan(config, NOW)
    assert chosen is None
    assert diagnostics[-1]["status"] == "unavailable"
    continuation = diagnostics[-1]["continuation"]
    assert continuation["next_eligible_at"] is None
    assert continuation["evidence_cursor"]["requested_window_start"] is None
    assert "trading_calendar_evidence" in {item["code"] for item in continuation["blockers"]}


def test_session_profile_rejects_ambiguous_timezone_and_hours():
    with pytest.raises(ValueError):
        TargetCalendarV1(
            mode="sessions", timezone="Unknown/Market", session_open="09:30", session_close="15:30"
        )
    with pytest.raises(ValueError):
        TargetCalendarV1(
            mode="sessions", timezone="Asia/Shanghai", session_open="15:30", session_close="09:30"
        )


def test_bitpro_numeric_id_compatibility_and_target_scope_validation(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/target-config.db")
    db.create_all()
    service = EvolutionService(db)
    state = service.configure(EvolutionConfig(strategy_ids=["44"]), revision=0, actor="test")
    assert state["config"]["strategy_ids"] == [44]
    with pytest.raises(ValueError, match="正整数"):
        service.configure(
            EvolutionConfig(strategy_ids=["cn-strategy:alpha"]), revision=1, actor="test"
        )
    with pytest.raises(ValueError, match="booleans"):
        EvolutionConfig(strategy_ids=[True])
    with pytest.raises(ValueError, match="integers or strings"):
        EvolutionConfig(strategy_ids=[44.0])


@pytest.mark.parametrize("returned_id", [None, 99])
def test_bitpro_source_read_never_relabels_missing_or_wrong_identity(returned_id):
    class WrongSource:
        def strategy_get(self, *, strategy_id):
            source = {"script_content": "class Source: pass", "config": {"timeframe": "1H"}}
            if returned_id is not None:
                source["id"] = returned_id
            return {"strategy": source}

    with pytest.raises(ValueError, match="strategy_source_identity_mismatch"):
        BitProReadPorts(WrongSource()).get_strategy_source("44")


def test_long_lived_scanner_rebuilds_adapter_when_target_changes(tmp_path):
    first, second = object(), object()
    register_market_target(build_mcp_contract_profile("market-one", "Market one"), lambda: first)
    register_market_target(build_mcp_contract_profile("market-two", "Market two"), lambda: second)
    db = Database(f"sqlite:///{tmp_path}/adapter-switch.db")
    db.create_all()
    service = EvolutionService(db)
    assert service._client(EvolutionConfig(target_id="market-one")) is first
    assert service._client(EvolutionConfig(target_id="market-two")) is second


def test_bitpro_scan_keeps_numeric_inventory_order(tmp_path, monkeypatch):
    from test_arc_evolution import Paper

    class UnsortedPaper(Paper):
        def paper_strategy_performance(self, **kwargs):
            return {
                "strategies": [
                    {
                        "strategy_id": 100,
                        "strategy_name": "later",
                        "mode": "paper",
                        "timeframe": "1H",
                    },
                    {
                        "strategy_id": 44,
                        "strategy_name": "earlier",
                        "mode": "paper",
                        "timeframe": "1H",
                    },
                ]
            }

    db = Database(f"sqlite:///{tmp_path}/bitpro-order.db")
    db.create_all()
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows", lambda *a, **k: {"triggered": False}
    )
    diagnostics, _ = EvolutionService(db, UnsortedPaper())._scan(
        EvolutionConfig(), datetime(2026, 9, 12, 12, tzinfo=UTC)
    )
    assert [row["strategy_id"] for row in diagnostics] == [44, 100]


def test_offline_mcp_registry_reaches_same_scan_decision(tmp_path):
    reads = ContractReads()
    transport = OfflineMcpTransport(reads)
    registry = McpClientRegistry(
        (McpServerConfig("offline", "https://offline.invalid", max_retries=0),),
        transport=transport,
    )
    profile = build_mcp_contract_profile("market-fixture", "Market fixture", calendar=CALENDAR)
    register_market_target(
        profile,
        lambda: McpReadPorts(McpContractClient(registry, "offline", profile)),
    )
    db = Database(f"sqlite:///{tmp_path}/mcp-read.db")
    db.create_all()
    service = EvolutionService(db)
    config = EvolutionConfig(target_id="market-fixture", strategy_ids=["cn-strategy:alpha"])
    service.configure(config, revision=0, actor="test")
    diagnostics, chosen = service._scan(config, NOW)
    assert chosen is not None
    assert chosen["source_strategy_id"] == "cn-strategy:alpha"
    assert chosen["paper_feedback"]["triggered"] is True
    assert diagnostics[-1]["status"] == "opportunity"
    assert {
        "evolution_list_running_strategies",
        "evolution_get_strategy_source",
        "evolution_get_session_snapshot",
        "evolution_list_session_trades",
        "evolution_list_trading_sessions",
        "evolution_get_equity_series",
    } <= set(transport.called)
    assert service.tick(NOW)["status"] == "deferred_target_write_port"


def test_mcp_read_preflight_rejects_missing_source_tool():
    profile = build_mcp_contract_profile("market-fixture", "Market fixture", calendar=CALENDAR)
    registry = McpClientRegistry(
        (McpServerConfig("offline", "https://offline.invalid", max_retries=0),),
        transport=OfflineMcpTransport(ContractReads(), omit="evolution_get_strategy_source"),
    )
    with pytest.raises(MarketTargetUnavailable, match="evolution_get_strategy_source"):
        McpReadPorts(McpContractClient(registry, "offline", profile))


def test_mcp_read_rejects_response_from_another_target():
    profile = build_mcp_contract_profile("market-fixture", "Market fixture", calendar=CALENDAR)
    transport = OfflineMcpTransport(ContractReads())
    transport.target_id = "another-market"
    registry = McpClientRegistry(
        (McpServerConfig("offline", "https://offline.invalid", max_retries=0),),
        transport=transport,
    )
    ports = McpReadPorts(McpContractClient(registry, "offline", profile))
    with pytest.raises(ValueError, match="target_mismatch"):
        ports.list_running_strategies(50)


@pytest.mark.parametrize("length,accepted", [(400, True), (100_001, False)])
def test_mcp_source_code_uses_research_contract_bound(length, accepted):
    class SizedCodeReads(ContractReads):
        def get_strategy_source(self, strategy_id: str) -> StrategySource:
            code = "x" * length
            return StrategySource(
                strategy_id,
                code,
                hashlib.sha256(code.encode()).hexdigest(),
                {"timeframe": "1H"},
                ("600519.SH",),
                "1H",
            )

    profile = build_mcp_contract_profile("market-fixture", "Market fixture", calendar=CALENDAR)
    registry = McpClientRegistry(
        (McpServerConfig("offline", "https://offline.invalid", max_retries=0),),
        transport=OfflineMcpTransport(SizedCodeReads()),
    )
    ports = McpReadPorts(McpContractClient(registry, "offline", profile))
    if accepted:
        assert len(ports.get_strategy_source("cn-strategy:alpha").code) == length
    else:
        with pytest.raises(ValueError, match="strategy_code_missing_or_out_of_bounds"):
            ports.get_strategy_source("cn-strategy:alpha")


def test_continuations_with_same_strategy_and_session_id_stay_target_scoped(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/continuation-scope.db")
    db.create_all()
    ledger = ContinuationLedger(db)
    state = {
        "observed_at": NOW.astimezone(UTC).isoformat(),
        "evidence_cursor": {"instance_id": "shared-session"},
        "blockers": [],
        "next_eligible_at": None,
    }
    ledger.record_check(
        "cycle-1",
        [
            {"target_id": "bitpro", "strategy_id": 44, "continuation": state},
            {"target_id": "market-fixture", "strategy_id": "44", "continuation": state},
        ],
    )
    rows = ledger.view()
    assert len(rows) == 2
    assert {row["target_id"] for row in rows} == {"bitpro", "market-fixture"}
    assert continuation_source_id("bitpro", 44, "shared-session") != continuation_source_id(
        "market-fixture", "44", "shared-session"
    )
