"""Portfolio Coordinator Service for multi-strategy execution and risk parity monitoring."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypertrade.config import Settings, get_settings
from hypertrade.db import Database
from hypertrade.paper.service import PaperTradingService
from hypertrade.paper.stage_gate import ProgressiveStageGate, StrategyStage

# Global shared stage gate so API and background loops share the same state in memory
_GLOBAL_STAGE_GATE = ProgressiveStageGate()


class PortfolioCoordinatorService:
    """Provides high-level coordination and portfolio analytics."""

    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        paper_service: PaperTradingService | None = None,
        stage_gate: ProgressiveStageGate | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.stage_gate = stage_gate or _GLOBAL_STAGE_GATE
        self.paper_service = paper_service or PaperTradingService(
            db, settings=self.settings, stage_gate=self.stage_gate
        )

    def get_summary(self) -> dict[str, Any]:
        """Aggregate full portfolio balance, margin usage, and risk-parity breakdown."""
        status = self.paper_service.status()
        session_info = status["session"]
        positions = status["positions"]

        equity = Decimal(session_info.get("equity", "0"))
        cash = Decimal(session_info.get("cash", "0"))
        realized_pnl = Decimal(session_info.get("realized_pnl", "0"))

        total_notional = sum(Decimal(p["notional"]) for p in positions)
        total_unrealized_pnl = sum(Decimal(p["unrealized_pnl"]) for p in positions)
        leverage_ratio = float(total_notional / equity) if equity > 0 else 0.0

        # Current strategy stages
        strategy_summaries = self.stage_gate.summary()

        return {
            "session_id": session_info.get("id"),
            "status": session_info.get("status"),
            "equity": str(equity),
            "cash": str(cash),
            "realized_pnl": str(realized_pnl),
            "unrealized_pnl": str(total_unrealized_pnl),
            "total_notional": str(total_notional),
            "leverage_ratio": round(leverage_ratio, 4),
            "max_leverage": float(self.settings.paper_max_leverage),
            "open_position_count": len(positions),
            "max_positions": self.settings.paper_max_positions,
            "positions": positions,
            "strategies": strategy_summaries,
            "recent_fills": status["recent_fills"],
        }

    def get_strategies(self) -> list[dict[str, Any]]:
        """Return all registered execution strategies and their stage gate status."""
        return self.stage_gate.summary()

    def set_strategy_stage(
        self, strategy_key: str, stage_str: str, reason: str = ""
    ) -> dict[str, Any]:
        """Manually transition a strategy's operational stage."""
        try:
            target_stage = StrategyStage(stage_str.lower().strip())
        except ValueError as exc:
            valid_stages = [s.value for s in StrategyStage]
            raise ValueError(
                f"Invalid stage '{stage_str}'. Must be one of {valid_stages}"
            ) from exc

        self.stage_gate.set_stage(strategy_key, target_stage, reason=reason)
        return {
            "strategy_key": strategy_key,
            "stage": target_stage.value,
            "reason": reason or "manual_override",
            "updated": True,
        }

    def trigger_rebalance(self) -> dict[str, Any]:
        """Trigger an immediate portfolio risk-parity and mark-to-market cycle."""
        result = self.paper_service.run_once()
        summary = self.get_summary()
        return {
            "run_result": {
                "status": result.status,
                "fill_count": result.fill_count,
                "event_count": result.event_count,
            },
            "portfolio": summary,
        }
