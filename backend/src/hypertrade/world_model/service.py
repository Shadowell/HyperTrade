"""Read-only global operator WorldState assembly.

The world model is intentionally a snapshot layer in Sprint 71. It reads local
market, strategy, execution, connector, monitor, and deployment evidence, then
returns missing-data markers where a broader cross-asset feed is not wired yet.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, func, select

from hypertrade.config import Settings, get_settings
from hypertrade.connectors.registry import ConnectorRegistry
from hypertrade.db import (
    AgentRun,
    Database,
    MarketTicker,
    MemoryItem,
    MonitorAlertEvent,
    PaperEvent,
    PaperFill,
    PaperPosition,
    PaperSession,
    TraceEvent,
    utc_now,
)
from hypertrade.market.repository import MarketRepository
from hypertrade.world_model.actions import candidate_actions
from hypertrade.world_model.collectors import collect_global_market
from hypertrade.world_model.defensive_actions import DefensiveActionEngine
from hypertrade.world_model.portfolio import PortfolioScheduler
from hypertrade.world_model.records import build_decision_record
from hypertrade.world_model.scenarios import ScenarioSimulator
from hypertrade.world_model.schemas import WORLD_STATE_SCHEMA_VERSION, WorldStatePayload


class WorldModelService:
    """Assemble a source-bound read-only WorldState snapshot."""

    def __init__(self, db: Database, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def snapshot(self) -> WorldStatePayload:
        generated_at = utc_now().isoformat()
        missing_data: list[str] = []
        crypto_market = self._crypto_market(missing_data)
        global_market = self._global_market(crypto_market=crypto_market, missing_data=missing_data)
        strategy = self._strategy_state(missing_data)
        execution = self._execution_state(missing_data)
        tool_health = self._tool_health_state(missing_data)
        deployment = self._deployment_state(missing_data)
        source_refs = self._source_refs(
            generated_at=generated_at,
            crypto_market=crypto_market,
            strategy=strategy,
            execution=execution,
            tool_health=tool_health,
            deployment=deployment,
        )
        snapshot: WorldStatePayload = {
            "schema_version": WORLD_STATE_SCHEMA_VERSION,
            "source_id": "world_model:latest",
            "status": "completed",
            "generated_at": generated_at,
            "global_market": global_market,
            "crypto_market": crypto_market,
            "strategy": strategy,
            "execution": execution,
            "tool_health": tool_health,
            "deployment": deployment,
            "missing_data": _dedupe(missing_data),
            "source_refs": source_refs,
        }
        snapshot["candidate_actions"] = candidate_actions(snapshot)
        snapshot["action_scenarios"] = ScenarioSimulator().simulate(
            snapshot,
            snapshot["candidate_actions"],
        )
        snapshot["decision"] = build_decision_record(
            snapshot,
            snapshot["action_scenarios"],
        )
        snapshot["defensive_automation"] = DefensiveActionEngine(
            self.db,
            settings=self.settings,
        ).status()
        snapshot["portfolio"] = PortfolioScheduler().build(snapshot)
        return snapshot

    def _crypto_market(self, missing_data: list[str]) -> dict[str, Any]:
        movers = MarketRepository(self.db).top_movers(limit=8)
        with self.db.session() as session:
            ticker_count = int(session.scalar(select(func.count()).select_from(MarketTicker)) or 0)
            latest_ticker_at = session.scalar(select(func.max(MarketTicker.updated_at)))
            rows = session.scalars(
                select(MarketTicker)
                .order_by(desc(MarketTicker.updated_at), desc(MarketTicker.volume_ccy_24h))
                .limit(250)
            ).all()
        changes = [_decimal(row.change_utc0_pct) for row in rows]
        advancers = sum(1 for value in changes if value > 0)
        decliners = sum(1 for value in changes if value < 0)
        average_change = sum(changes, Decimal("0")) / Decimal(len(changes)) if changes else None
        if ticker_count == 0:
            missing_data.append("crypto_market.okx_tickers_unavailable")
        return {
            "status": "available" if ticker_count else "unavailable",
            "source_id": "okx_rest:market_tickers",
            "ticker_count": ticker_count,
            "latest_ticker_at": _iso(latest_ticker_at),
            "advancers_count": advancers,
            "decliners_count": decliners,
            "average_change_utc0_pct": _decimal_text(average_change),
            "top_movers": [
                {
                    "inst_id": row.inst_id,
                    "last": str(row.last),
                    "volume_ccy_24h": str(row.volume_ccy_24h),
                    "change_utc0_pct": str(row.change_utc0_pct),
                }
                for row in movers
            ],
        }

    def _global_market(
        self,
        *,
        crypto_market: dict[str, Any],
        missing_data: list[str],
    ) -> dict[str, Any]:
        """Collect live global market state via GlobalMarketService.

        Replaces Sprint 71 fixture data with real yfinance data.
        """
        global_data = collect_global_market()

        # Add missing data markers
        if global_data.get("missing_data"):
            for symbol in global_data["missing_data"]:
                missing_data.append(f"global_market.{symbol}_unavailable")

        # Extract regime classifications
        return {
            "status": "healthy" if global_data.get("risk_regime") != "unknown" else "watch",
            "risk_regime": global_data.get("risk_regime", "unknown"),
            "volatility_regime": global_data.get("volatility_regime", "unknown"),
            "dollar_pressure": global_data.get("dollar_pressure", "unknown"),
            "rates_pressure": global_data.get("rates_pressure", "unknown"),
            "cross_asset_signal": global_data.get("cross_asset_signal", "unknown"),
            "tickers": global_data.get("tickers", []),
            "source_id": "global_market:yfinance",
            "as_of": global_data.get("as_of"),
        }

    def _strategy_state(self, missing_data: list[str]) -> dict[str, Any]:
        with self.db.session() as session:
            items = session.scalars(
                select(MemoryItem)
                .where(MemoryItem.disabled.is_(False))
                .where(MemoryItem.kind == "strategy_knowledge")
                .order_by(desc(MemoryItem.created_at))
                .limit(5)
            ).all()
            total_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(MemoryItem)
                    .where(MemoryItem.disabled.is_(False))
                    .where(MemoryItem.kind == "strategy_knowledge")
                )
                or 0
            )
        if total_count == 0:
            missing_data.append("strategy.strategy_knowledge_unavailable")
        return {
            "status": "healthy" if total_count else "unknown",
            "source_id": "memory:strategy_knowledge",
            "memory_count": total_count,
            "recent_items": [
                {
                    "memory_id": item.id,
                    "source_run_id": item.source_run_id,
                    "source_tool": item.source_tool,
                    "created_at": item.created_at.isoformat(),
                    "tags": item.tags,
                }
                for item in items
            ],
        }

    def _execution_state(self, missing_data: list[str]) -> dict[str, Any]:
        with self.db.session() as session:
            paper_session = session.scalars(
                select(PaperSession)
                .where(PaperSession.status != "reset")
                .order_by(desc(PaperSession.created_at))
                .limit(1)
            ).first()
            if paper_session is None:
                missing_data.append("execution.paper_session_unavailable")
                return {
                    "status": "watch",
                    "source_id": "hypertrade_db:paper_sessions",
                    "paper_session": None,
                    "open_position_count": 0,
                    "recent_fill_count": 0,
                    "recent_event_count": 0,
                }
            open_positions = int(
                session.scalar(
                    select(func.count())
                    .select_from(PaperPosition)
                    .where(PaperPosition.session_id == paper_session.id)
                    .where(PaperPosition.status == "open")
                )
                or 0
            )
            recent_fills = int(
                session.scalar(
                    select(func.count())
                    .select_from(PaperFill)
                    .where(PaperFill.session_id == paper_session.id)
                )
                or 0
            )
            recent_events = int(
                session.scalar(
                    select(func.count())
                    .select_from(PaperEvent)
                    .where(PaperEvent.session_id == paper_session.id)
                )
                or 0
            )
            return {
                "status": "healthy" if paper_session.status == "running" else "watch",
                "source_id": f"paper_session:{paper_session.id}",
                "paper_session": {
                    "id": paper_session.id,
                    "name": paper_session.name,
                    "status": paper_session.status,
                    "cash": str(paper_session.cash),
                    "equity": str(paper_session.equity),
                    "realized_pnl": str(paper_session.realized_pnl),
                    "created_at": paper_session.created_at.isoformat(),
                    "updated_at": paper_session.updated_at.isoformat(),
                },
                "open_position_count": open_positions,
                "recent_fill_count": recent_fills,
                "recent_event_count": recent_events,
            }

    def _tool_health_state(self, missing_data: list[str]) -> dict[str, Any]:
        connectors = ConnectorRegistry.default(settings=self.settings).capabilities_payload()
        connector_payload = connectors.get("connectors", {})
        with self.db.session() as session:
            alerts = session.scalars(
                select(MonitorAlertEvent)
                .order_by(desc(MonitorAlertEvent.created_at))
                .limit(10)
            ).all()
        recent_alerts = [
            {
                "id": alert.id,
                "monitor_id": alert.monitor_id,
                "run_id": alert.run_id,
                "level": alert.level,
                "code": alert.code,
                "message": alert.message,
                "source_id": alert.source_id,
                "status": alert.status,
                "created_at": alert.created_at.isoformat(),
            }
            for alert in alerts
        ]
        if not isinstance(connector_payload, dict) or not connector_payload:
            missing_data.append("tool_health.connectors_unavailable")
        alert_levels = {str(alert["level"]).lower() for alert in recent_alerts}
        status = "critical" if "critical" in alert_levels else "degraded" if alerts else "healthy"
        return {
            "status": status,
            "source_id": "connector_registry:capabilities",
            "connectors": connector_payload,
            "recent_alert_count": len(recent_alerts),
            "recent_alerts": recent_alerts,
        }

    def _deployment_state(self, missing_data: list[str]) -> dict[str, Any]:
        with self.db.session() as session:
            latest_run = session.scalars(
                select(AgentRun).order_by(desc(AgentRun.created_at)).limit(1)
            ).first()
            latest_trace = session.scalars(
                select(TraceEvent).order_by(desc(TraceEvent.created_at)).limit(1)
            ).first()
        if latest_run is None:
            missing_data.append("deployment.agent_run_history_unavailable")
        return {
            "status": "healthy",
            "source_id": "hypertrade_api:health",
            "api_health": "ok",
            "database_health": "ok",
            "latest_agent_run": (
                {
                    "id": latest_run.id,
                    "status": latest_run.status,
                    "created_at": latest_run.created_at.isoformat(),
                    "updated_at": latest_run.updated_at.isoformat(),
                }
                if latest_run is not None
                else None
            ),
            "latest_trace_event": (
                {
                    "id": latest_trace.id,
                    "run_id": latest_trace.run_id,
                    "tool_name": latest_trace.tool_name,
                    "status": latest_trace.status,
                    "created_at": latest_trace.created_at.isoformat(),
                }
                if latest_trace is not None
                else None
            ),
        }

    def _source_refs(
        self,
        *,
        generated_at: str,
        crypto_market: dict[str, Any],
        strategy: dict[str, Any],
        execution: dict[str, Any],
        tool_health: dict[str, Any],
        deployment: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                "source_type": "world_model",
                "source_id": "world_model:latest",
                "tool_name": "world_model_snapshot",
                "path": "hypertrade.world_model.service",
                "as_of": generated_at,
            },
            {
                "source_type": "market_data",
                "source_id": str(crypto_market.get("source_id", "okx_rest:market_tickers")),
                "tool_name": "world_model_snapshot",
                "path": "market_tickers",
                "as_of": str(crypto_market.get("latest_ticker_at") or generated_at),
            },
            {
                "source_type": "memory",
                "source_id": str(strategy.get("source_id", "memory:strategy_knowledge")),
                "tool_name": "world_model_snapshot",
                "path": "memory_items.kind=strategy_knowledge",
                "as_of": generated_at,
            },
            {
                "source_type": "execution",
                "source_id": str(execution.get("source_id", "hypertrade_db:paper_sessions")),
                "tool_name": "world_model_snapshot",
                "path": "paper_sessions",
                "as_of": generated_at,
            },
            {
                "source_type": "tool_health",
                "source_id": str(tool_health.get("source_id", "connector_registry:capabilities")),
                "tool_name": "world_model_snapshot",
                "path": "connectors.registry",
                "as_of": generated_at,
            },
            {
                "source_type": "deployment",
                "source_id": str(deployment.get("source_id", "hypertrade_api:health")),
                "tool_name": "world_model_snapshot",
                "path": "agent_runs,trace_events",
                "as_of": generated_at,
            },
        ]


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return str(value.quantize(Decimal("0.000001")))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
