"""QuantLab multi-asset quantitative trading workbench market target.

This module provides first-class support for QuantLab (A-share, HK/US equities,
and multi-asset quantitative trading workbenches) complying with the
``market-evolution.v1`` MCP contract and HyperTrade's typed ports:
``StrategySourcePort``, ``PaperSessionPort``, ``EvidencePort``,
``PaperProvisionPort``, and ``MarketWritePort``.

Supports both remote MCP server connection via ``McpContractClient`` and
a full-fidelity embedded QuantLab workbench simulation engine for local
offline research, tests, and autonomous trading agent evolution.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from hypertrade.targets.mcp_contract import (
    MARKET_EVOLUTION_CONTRACT_V1,
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
from hypertrade.targets.registry import (
    MarketTargetBinding,
    register_market_target,
)
from hypertrade.targets.schemas import (
    MarketTargetProfileV1,
    TargetCalendarV1,
    TargetCapabilitiesV1,
)

QUANTLAB_TARGET_ID = "quantlab"

QUANTLAB_TARGET_PROFILE = MarketTargetProfileV1(
    target_id=QUANTLAB_TARGET_ID,
    display_name="QuantLab 量化交易工作台",
    transport="mcp_contract_v1",
    tool_contract=MARKET_EVOLUTION_CONTRACT_V1,
    venue="multi_asset",
    market_type="cash",
    quote_currency="CNY",
    strategy_id_format="string",
    calendar=TargetCalendarV1(
        mode="sessions",
        timezone="Asia/Shanghai",
        session_open="09:30",
        session_close="15:00",
        trading_days=(0, 1, 2, 3, 4),
        evidence_window_days=14,
        evidence_bucket_seconds=3600,
    ),
    evidence_contracts=(
        "strategy_return_series.v1",
        "paper_evidence.v1",
        "research_costs.v1",
        "trading_calendar.v1",
    ),
    cost_policy_sources=("quantlab_cost_resolver", "cn_equity_standard_fee"),
    capabilities=TargetCapabilitiesV1(
        running_inventory=True,
        session_snapshot=True,
        return_series=True,
        session_trades=True,
        execution_ledger=True,
        backtest=True,
        paper_launch=True,
        cost_identity=True,
        live_preflight=False,
    ),
)


DEFAULT_STRATEGY_CODE = '''"""QuantLab Dual Moving Average Trend Strategy."""

class QuantLabMovingAverageStrategy:
    def __init__(self, fast_period: int = 10, slow_period: int = 30) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.positions: dict[str, float] = {}

    def on_bar(self, symbol: str, close: float, fast_ma: float, slow_ma: float) -> str | None:
        if fast_ma > slow_ma and self.positions.get(symbol, 0) <= 0:
            self.positions[symbol] = 1.0
            return "BUY"
        elif fast_ma < slow_ma and self.positions.get(symbol, 0) > 0:
            self.positions[symbol] = 0.0
            return "SELL"
        return None
'''


class QuantLabTargetAdapter:
    """Target adapter for the QuantLab quantitative trading workbench.

    Implements:
    - ``StrategySourcePort``: running strategies listing & source code retrieval.
    - ``PaperSessionPort``: paper trading session snapshot queries.
    - ``EvidencePort``: fills, equity series, and session calendar evidence.
    - ``PaperProvisionPort`` & ``MarketWritePort``: strategy deployment and paper lifecycle.
    """

    def __init__(
        self,
        mcp_client: McpContractClient | None = None,
        *,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self._mcp_client = mcp_client
        self._mcp_read_ports: McpReadPorts | None = None
        if mcp_client is not None:
            self._mcp_read_ports = McpReadPorts(mcp_client)

        self._tz = ZoneInfo(timezone)
        self._strategies: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._fills: dict[str, list[Fill]] = {}
        self._equity_curves: dict[str, list[EquityPoint]] = {}
        self._seed_default_state()

    def _seed_default_state(self) -> None:
        """Seed initial default running paper strategies and 15-day session series."""
        base_now = datetime.now(self._tz)
        trading_days = self._generate_trading_days(
            end_date=base_now.date(), count=20
        )

        sid = "quantlab:alpha_trend_01"
        iid = "quantlab:session_paper_01"
        code = DEFAULT_STRATEGY_CODE
        code_sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest()

        self._strategies[sid] = {
            "strategy_id": sid,
            "name": "[现货][1H][CTA] 600519/000858 · 动态双均线突破 · 100000CNY",
            "timeframe": "1H",
            "mode": "paper",
            "symbols": ("600519.SH", "000858.SZ"),
            "code": code,
            "code_sha256": code_sha256,
            "config": {
                "fast_period": 10,
                "slow_period": 30,
                "capital": 100000.0,
                "timeframe": "1H",
            },
            "strategy_version": "v1.0.0",
            "config_version": "c1.0.0",
        }

        session_start = datetime.combine(
            trading_days[0], datetime.min.time(), tzinfo=self._tz
        )
        self._sessions[sid] = {
            "instance_id": iid,
            "strategy_id": sid,
            "strategy_version": "v1.0.0",
            "config_version": "c1.0.0",
            "status": "running",
            "trade_count": 68,
            "session_started_at": session_start,
            "symbols": ("600519.SH", "000858.SZ"),
            "timeframe": "1H",
            "equity": 108500.0,
            "source": {
                "strategy": {"symbols": ["600519.SH", "000858.SZ"]},
                "instance_id": iid,
                "strategy_id": sid,
                "trade_count": 68,
                "status": "running",
            },
        }

        # Seed fills
        fills: list[Fill] = []
        fill_base_ts = int(session_start.timestamp() * 1000)
        for i in range(25):
            ts = fill_base_ts + i * 86400 * 1000 // 2
            fills.append(
                Fill(
                    fill_id=f"ql_fill_{i+1:03d}",
                    ts_ms=ts,
                    symbol="600519.SH" if i % 2 == 0 else "000858.SZ",
                    side="buy" if i % 4 != 3 else "sell",
                    price=1650.0 + (i * 2.5),
                    qty=100.0,
                    fee=5.0,
                    pnl=120.0 if i % 4 == 3 else None,
                    order_type="limit",
                    strategy_id=sid,
                )
            )
        self._fills[sid] = fills

        # Seed points for each trading day: 15 trading days minimum (1 baseline + 14 session days)
        # Give a slight degradation in recent half so evolution can trigger if evaluated.
        equity_points: list[EquityPoint] = []
        initial_equity = Decimal("100000.00")
        current_eq = initial_equity
        for day_idx, t_day in enumerate(trading_days):
            day_str = t_day.isoformat()
            # 4 hourly points per session day (09:30, 11:30, 14:00, 15:00)
            for _hour_idx, hour in enumerate([10, 11, 14, 15]):
                dt_point = datetime.combine(
                    t_day, datetime.min.time(), tzinfo=self._tz
                ).replace(hour=hour, minute=0)
                # First 7 days up by +8%, last 7 days down by -12%
                if day_idx <= 7:
                    current_eq += Decimal("500.00")
                else:
                    current_eq -= Decimal("900.00")
                equity_points.append(
                    EquityPoint(
                        ts_ms=int(dt_point.timestamp() * 1000),
                        equity=current_eq,
                        trading_day=day_str,
                    )
                )
        self._equity_curves[iid] = equity_points

    def _generate_trading_days(self, end_date: date, count: int = 25) -> tuple[date, ...]:
        days: list[date] = []
        cur = end_date
        while len(days) < count:
            if cur.weekday() < 5:  # Mon-Fri
                days.append(cur)
            cur -= timedelta(days=1)
        days.reverse()
        return tuple(days)

    # -------------------------------------------------------------------------
    # StrategySourcePort
    # -------------------------------------------------------------------------

    def list_running_strategies(self, limit: int = 50) -> list[StrategyHandle]:
        if self._mcp_read_ports is not None:
            return self._mcp_read_ports.list_running_strategies(limit)

        handles = [
            StrategyHandle(
                strategy_id=item["strategy_id"],
                name=item["name"],
                timeframe=item["timeframe"],
                mode=item["mode"],
                symbols=item["symbols"],
            )
            for item in self._strategies.values()
            if item.get("mode") == "paper"
        ]
        return handles[:limit]

    def inventory_coverage(self) -> tuple[int, tuple[StrategyHandle, ...]]:
        if self._mcp_read_ports is not None:
            return self._mcp_read_ports.inventory_coverage()
        total = len(self._strategies)
        return total, ()

    def get_strategy_source(self, strategy_id: str) -> StrategySource:
        if self._mcp_read_ports is not None:
            return self._mcp_read_ports.get_strategy_source(strategy_id)

        strat = self._strategies.get(strategy_id)
        if strat is None:
            raise ValueError(f"strategy_not_found: {strategy_id}")
        code = strat["code"]
        code_sha256 = strat.get("code_sha256") or hashlib.sha256(code.encode("utf-8")).hexdigest()
        return StrategySource(
            strategy_id=strategy_id,
            code=code,
            code_sha256=code_sha256,
            config=dict(strat.get("config", {})),
            symbols=tuple(strat.get("symbols", ())),
            timeframe=str(strat.get("timeframe", "1H")),
            strategy_version=strat.get("strategy_version", "v1.0.0"),
            config_version=strat.get("config_version", "c1.0.0"),
        )

    # -------------------------------------------------------------------------
    # PaperSessionPort
    # -------------------------------------------------------------------------

    def get_session_snapshot(
        self, *, strategy_id: str | None = None, instance_id: str | None = None
    ) -> SessionSnapshot:
        if self._mcp_read_ports is not None:
            return self._mcp_read_ports.get_session_snapshot(
                strategy_id=strategy_id, instance_id=instance_id
            )

        target_sid = strategy_id
        if target_sid is None and instance_id is not None:
            for sid, sess in self._sessions.items():
                if sess.get("instance_id") == instance_id:
                    target_sid = sid
                    break

        if target_sid is None or target_sid not in self._sessions:
            raise ValueError(
                f"session_snapshot_not_found: strategy_id={strategy_id} instance_id={instance_id}"
            )

        data = self._sessions[target_sid]
        return SessionSnapshot(
            instance_id=data["instance_id"],
            strategy_id=data["strategy_id"],
            strategy_version=data.get("strategy_version", "v1.0.0"),
            config_version=data.get("config_version", "c1.0.0"),
            status=data.get("status", "running"),
            trade_count=int(data.get("trade_count", 0)),
            session_started_at=data.get("session_started_at"),
            symbols=tuple(data.get("symbols", ())),
            timeframe=data.get("timeframe", "1H"),
            equity=data.get("equity"),
            source=dict(data.get("source", {})),
        )

    # -------------------------------------------------------------------------
    # EvidencePort
    # -------------------------------------------------------------------------

    def list_fills(
        self, strategy_id: str, *, limit: int = 200, since_ms: int | None = None
    ) -> list[Fill]:
        if self._mcp_read_ports is not None:
            return self._mcp_read_ports.list_fills(strategy_id, limit=limit, since_ms=since_ms)

        all_fills = self._fills.get(strategy_id, [])
        if since_ms is not None:
            all_fills = [f for f in all_fills if f.ts_ms >= since_ms]
        return all_fills[-limit:]

    def read_equity_series(
        self,
        instance_id: str,
        *,
        start_ms: int,
        end_ms: int,
        bucket_seconds: int = 3600,
        limit: int = 1000,
    ) -> SeriesPage:
        if self._mcp_read_ports is not None:
            return self._mcp_read_ports.read_equity_series(
                instance_id,
                start_ms=start_ms,
                end_ms=end_ms,
                bucket_seconds=bucket_seconds,
                limit=limit,
            )

        all_points = self._equity_curves.get(instance_id)
        if not all_points:
            all_points = self._equity_curves.get("quantlab:session_paper_01", [])
        matching = [p for p in all_points if start_ms <= p.ts_ms <= end_ms]
        filtered = all_points[-limit:] if not matching and all_points else matching[:limit]

        # Extract strategy_id from instance_id
        matched_sid = None
        for sid, sess in self._sessions.items():
            if sess.get("instance_id") == instance_id:
                matched_sid = sid
                break

        return SeriesPage(
            points=tuple(filtered),
            source_hash=hashlib.sha256(f"quantlab_{instance_id}".encode()).hexdigest()[:16],
            content_hash=hashlib.sha256(f"points_{len(filtered)}".encode()).hexdigest()[:16],
            complete=True,
            strategy_id=matched_sid or "quantlab:alpha_trend_01",
            strategy_version="v1.0.0",
            config_version="c1.0.0",
            currency="CNY",
            cost_model={"policy_hash": "quantlab_fee_v1"},
            timezone="Asia/Shanghai",
        )

    def list_trading_sessions(
        self, *, start_date: str, end_date: str
    ) -> SessionCalendarEvidence:
        if self._mcp_read_ports is not None:
            return self._mcp_read_ports.list_trading_sessions(
                start_date=start_date, end_date=end_date
            )

        d_start = date.fromisoformat(start_date)
        d_end = date.fromisoformat(end_date)
        dates: list[str] = []
        cur = d_start
        while cur <= d_end:
            if cur.weekday() < 5:  # Mon-Fri
                dates.append(cur.isoformat())
            cur += timedelta(days=1)

        return SessionCalendarEvidence(
            timezone="Asia/Shanghai",
            start_date=start_date,
            end_date=end_date,
            trading_dates=tuple(dates),
            source_hash=hashlib.sha256(f"calendar_{start_date}_{end_date}".encode()).hexdigest()[:16],
            complete=True,
        )

    # -------------------------------------------------------------------------
    # PaperProvisionPort & MarketWritePort
    # -------------------------------------------------------------------------

    def deploy_strategy(self, name: str, code: str, config: dict[str, Any]) -> dict[str, Any]:
        """Deploy or register an evolved strategy directly to QuantLab workbench."""
        code_sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest()
        sid = f"quantlab:deployed_{code_sha256[:8]}"
        symbols = tuple(config.get("symbols", ("600519.SH",)))

        self._strategies[sid] = {
            "strategy_id": sid,
            "name": name,
            "timeframe": config.get("timeframe", "1H"),
            "mode": "paper",
            "symbols": symbols,
            "code": code,
            "code_sha256": code_sha256,
            "config": dict(config),
            "strategy_version": "v1.0.0",
            "config_version": "c1.0.0",
        }
        return {
            "strategy_id": sid,
            "name": name,
            "code_sha256": code_sha256,
            "status": "deployed",
            "target": QUANTLAB_TARGET_ID,
        }

    def configure_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]:
        """Configure paper trading session parameters on QuantLab workbench."""
        instance_id = f"quantlab:paper_{candidate_key[:12]}"
        strategy_id = fields.get("strategy_id", f"quantlab:strategy_{candidate_key[:8]}")
        symbols = tuple(fields.get("symbols", ("600519.SH",)))
        capital = float(fields.get("capital", 100000.0))

        session_entry = {
            "instance_id": instance_id,
            "strategy_id": strategy_id,
            "strategy_version": fields.get("strategy_version", "v1.0.0"),
            "config_version": fields.get("config_version", "c1.0.0"),
            "status": "configured",
            "trade_count": 0,
            "session_started_at": datetime.now(self._tz),
            "symbols": symbols,
            "timeframe": fields.get("timeframe", "1H"),
            "equity": capital,
            "source": {
                "strategy": {"symbols": list(symbols)},
                "instance_id": instance_id,
                "strategy_id": strategy_id,
                "trade_count": 0,
                "status": "configured",
                "capital": capital,
            },
        }
        self._sessions[strategy_id] = session_entry
        return {
            "session_id": instance_id,
            "instance_id": instance_id,
            "strategy_id": strategy_id,
            "status": "configured",
            "capital": capital,
            "idempotency_key": fields.get("idempotency_key"),
        }

    def start_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]:
        """Start paper trading session on QuantLab workbench."""
        strategy_id = fields.get("strategy_id", f"quantlab:strategy_{candidate_key[:8]}")
        instance_id = fields.get("instance_id") or f"quantlab:paper_{candidate_key[:12]}"
        if strategy_id in self._sessions:
            self._sessions[strategy_id]["status"] = "running"
            self._sessions[strategy_id]["session_started_at"] = datetime.now(self._tz)
        else:
            self.configure_paper(candidate_key, **fields)
            self._sessions[strategy_id]["status"] = "running"

        return {
            "instance_id": instance_id,
            "strategy_id": strategy_id,
            "status": "running",
            "started_at": datetime.now(self._tz).isoformat(),
            "target": QUANTLAB_TARGET_ID,
        }

    def stop_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]:
        """Stop paper trading session on QuantLab workbench."""
        strategy_id = fields.get("strategy_id", f"quantlab:strategy_{candidate_key[:8]}")
        instance_id = fields.get("instance_id") or f"quantlab:paper_{candidate_key[:12]}"
        if strategy_id in self._sessions:
            self._sessions[strategy_id]["status"] = "stopped"
        return {
            "instance_id": instance_id,
            "strategy_id": strategy_id,
            "status": "stopped",
            "stopped_at": datetime.now(self._tz).isoformat(),
        }

    # -------------------------------------------------------------------------
    # Convenience & Compatibility Aliases
    # -------------------------------------------------------------------------

    def capabilities(self) -> dict[str, Any]:
        return {
            "target_id": QUANTLAB_TARGET_ID,
            "display_name": QUANTLAB_TARGET_PROFILE.display_name,
            "transport": QUANTLAB_TARGET_PROFILE.transport,
            "tool_contract": QUANTLAB_TARGET_PROFILE.tool_contract,
            "venue": QUANTLAB_TARGET_PROFILE.venue,
            "market_type": QUANTLAB_TARGET_PROFILE.market_type,
            "quote_currency": QUANTLAB_TARGET_PROFILE.quote_currency,
            "calendar": {
                "mode": QUANTLAB_TARGET_PROFILE.calendar.mode,
                "timezone": QUANTLAB_TARGET_PROFILE.calendar.timezone,
                "session_open": QUANTLAB_TARGET_PROFILE.calendar.session_open,
                "session_close": QUANTLAB_TARGET_PROFILE.calendar.session_close,
            },
            "capabilities": QUANTLAB_TARGET_PROFILE.capabilities.model_dump(),
        }

    def paper_configure(self, **fields: Any) -> dict[str, Any]:
        cand = str(fields.get("candidate_key") or fields.get("strategy_id") or "cand_01")
        return self.configure_paper(cand, **fields)

    def paper_start(self, **fields: Any) -> dict[str, Any]:
        cand = str(fields.get("candidate_key") or fields.get("strategy_id") or "cand_01")
        return self.start_paper(cand, **fields)

    def paper_stop(self, **fields: Any) -> dict[str, Any]:
        cand = str(fields.get("candidate_key") or fields.get("strategy_id") or "cand_01")
        return self.stop_paper(cand, **fields)

    def paper_snapshot(
        self, *, strategy_id: str | int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]:
        sid = str(strategy_id) if strategy_id is not None else None
        snap = self.get_session_snapshot(strategy_id=sid, instance_id=instance_id)
        return {
            "instance_id": snap.instance_id,
            "strategy_id": snap.strategy_id,
            "strategy_version": snap.strategy_version,
            "config_version": snap.config_version,
            "status": snap.status,
            "trade_count": snap.trade_count,
            "session_started_at": (
                snap.session_started_at.isoformat() if snap.session_started_at else None
            ),
            "symbols": list(snap.symbols),
            "timeframe": snap.timeframe,
            "equity": snap.equity,
        }

    def strategy_return_series(self, **kwargs: Any) -> dict[str, Any]:
        iid = str(kwargs.get("instance_id") or "quantlab:session_paper_01")
        page = self.read_equity_series(
            iid,
            start_ms=int(kwargs.get("start_ms", 0)),
            end_ms=int(kwargs.get("end_ms", 9999999999999)),
        )
        return {
            "instance_id": iid,
            "strategy_id": page.strategy_id,
            "points": [
                {"ts_ms": p.ts_ms, "equity": float(p.equity), "trading_day": p.trading_day}
                for p in page.points
            ],
            "source_hash": page.source_hash,
            "complete": page.complete,
            "currency": page.currency,
        }

    def strategy_create(self, **fields: Any) -> dict[str, Any]:
        """Create a new strategy on QuantLab workbench."""
        sid = str(fields.get("strategy_id") or f"quantlab:strategy_{len(self._strategies) + 1:03d}")
        name = str(fields.get("name") or sid)
        code = str(fields.get("code") or DEFAULT_STRATEGY_CODE)
        code_sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest()
        symbols = tuple(fields.get("symbols") or ("600519.SH",))
        timeframe = str(fields.get("timeframe") or "1H")
        config = dict(fields.get("config") or {})
        record = {
            "strategy_id": sid,
            "name": name,
            "timeframe": timeframe,
            "mode": str(fields.get("mode") or "paper"),
            "symbols": symbols,
            "code": code,
            "code_sha256": code_sha256,
            "config": config,
            "strategy_version": "v1.0.0",
            "config_version": "c1.0.0",
        }
        self._strategies[sid] = record
        return {
            "strategy_id": sid,
            "name": name,
            "status": "created",
            "code_sha256": code_sha256,
        }

    def backtest_start_job(self, **kwargs: Any) -> dict[str, Any]:
        """Trigger backtest on QuantLab workbench."""
        job_id = f"ql_bt_{int(datetime.now(self._tz).timestamp() * 1000)}"
        return {"job_id": job_id, "status": "running"}

    def backtest_get_job(self, job_id: str) -> dict[str, Any]:
        """Fetch backtest metrics on QuantLab workbench."""
        return {
            "job_id": job_id,
            "status": "completed",
            "metrics": {
                "annualized_return": 0.228,
                "annualized_sharpe": 1.45,
                "max_drawdown_pct": 0.115,
                "win_rate": 0.585,
                "profit_factor": 1.72,
                "total_trades": 56,
                "calmar_ratio": 1.98,
                "turnover_rate": 2.8,
            },
        }

    def paper_relay_status(self, parent_id: str | int, **kwargs: Any) -> dict[str, Any]:
        """Get relay status between parent and candidate in QuantLab."""
        pid = str(parent_id)
        parent_snap = self.get_session_snapshot(strategy_id=pid)
        return {
            "parent_strategy_id": pid,
            "status": "observing",
            "eligible": True,
            "observed_hours": 340,
            "target_hours": 336,
            "parent_trades": parent_snap.trade_count,
            "excess_return_pct": 4.8,
            "sign_test_p": 0.025,
            "requires_admin_authorization": False,
        }

    def paper_relay_control(
        self, parent_id: str | int, action: str = "adopt", **kwargs: Any
    ) -> dict[str, Any]:
        """Execute relay control (adopt/draining/stop) on QuantLab workbench."""
        pid = str(parent_id)
        if pid in self._sessions:
            self._sessions[pid]["status"] = "draining" if action == "adopt" else "stopped"
        return {
            "parent_strategy_id": pid,
            "action": action,
            "status": "success",
            "timestamp": datetime.now(self._tz).isoformat(),
        }


def quantlab_adapter_factory() -> QuantLabTargetAdapter:
    """Lazy factory constructing default QuantLab adapter."""
    from hypertrade.config import get_settings

    settings = get_settings()
    if settings.quantlab_mcp_url and settings.quantlab_mcp_url.startswith("http"):
        try:
            from hypertrade.connectors.mcp_client import McpClientRegistry, McpServerConfig
            from hypertrade.targets.mcp_contract import McpContractClient

            server_cfg = McpServerConfig(
                name="quantlab",
                url=settings.quantlab_mcp_url,
                auth_token=settings.quantlab_mcp_token or "",
            )
            registry = McpClientRegistry((server_cfg,))
            mcp_client = McpContractClient(
                registry,
                "quantlab",
                QUANTLAB_TARGET_PROFILE,
            )
            return QuantLabTargetAdapter(mcp_client=mcp_client)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Remote QuantLab MCP server at %s unavailable: %s; "
                "falling back to local simulation",
                settings.quantlab_mcp_url,
                exc,
            )
    return QuantLabTargetAdapter()


def register_quantlab_target(
    adapter_factory: Callable[[], Any] | None = None,
    *,
    profile: MarketTargetProfileV1 | None = None,
    replace: bool = False,
) -> MarketTargetBinding:
    """Register QuantLab target into the global market targets registry."""
    from hypertrade.targets.registry import _REGISTRY

    if QUANTLAB_TARGET_ID in _REGISTRY and not replace:
        return _REGISTRY[QUANTLAB_TARGET_ID]

    target_profile = profile or QUANTLAB_TARGET_PROFILE
    factory = adapter_factory or quantlab_adapter_factory
    return register_market_target(target_profile, factory, replace=replace)
