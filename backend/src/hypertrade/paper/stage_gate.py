"""Progressive Stage Gate and Circuit Breaker for multi-strategy execution.

Manages strategy lifecycle:
INCUBATING -> PAPER_OBSERVING -> CANARY_LIVE -> CONTROLLED_LIVE -> FULL_LIVE
with automatic circuit breaker demotion and Feishu Reflexion alert dispatching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from hypertrade.arc.reflexion_alert import (
    ReflexionAlertPayload,
    dispatch_reflexion_alert,
)
from hypertrade.db import utc_now

logger = logging.getLogger(__name__)


class StrategyStage(StrEnum):
    INCUBATING = "incubating"
    PAPER_OBSERVING = "paper_observing"
    CANARY_LIVE = "canary_live"
    CONTROLLED_LIVE = "controlled_live"
    FULL_LIVE = "full_live"
    DEGRADED = "degraded"


STAGE_MULTIPLIERS: dict[StrategyStage, float] = {
    StrategyStage.INCUBATING: 0.0,
    StrategyStage.PAPER_OBSERVING: 0.25,
    StrategyStage.CANARY_LIVE: 0.50,
    StrategyStage.CONTROLLED_LIVE: 0.75,
    StrategyStage.FULL_LIVE: 1.00,
    StrategyStage.DEGRADED: 0.0,
}


@dataclass
class StrategyMetrics:
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    total_realized_pnl: Decimal = Decimal("0")
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    consecutive_losses: int = 0
    peak_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    max_drawdown_pct: float = 0.0

    @property
    def win_rate(self) -> float:
        return float(self.win_count / self.trade_count) if self.trade_count > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss <= Decimal("0"):
            return 999.0 if self.gross_profit > Decimal("0") else 1.0
        return float(self.gross_profit / self.gross_loss)


class ProgressiveStageGate:
    """Manages progression gates and circuit breakers across running strategies."""

    def __init__(self) -> None:
        self._stages: dict[str, StrategyStage] = {
            "rsi_reversal": StrategyStage.PAPER_OBSERVING,
            "momentum_breakout_v1": StrategyStage.PAPER_OBSERVING,
            "macd_trend": StrategyStage.PAPER_OBSERVING,
            "utc0_momentum_legacy": StrategyStage.PAPER_OBSERVING,
        }
        self._metrics: dict[str, StrategyMetrics] = {}
        self._history: list[dict[str, Any]] = []

    def get_stage(self, strategy_key: str) -> StrategyStage:
        return self._stages.get(strategy_key, StrategyStage.PAPER_OBSERVING)

    def set_stage(self, strategy_key: str, stage: StrategyStage, reason: str = "") -> None:
        previous = self.get_stage(strategy_key)
        self._stages[strategy_key] = stage
        self._history.append(
            {
                "timestamp": utc_now().isoformat(),
                "strategy_key": strategy_key,
                "previous_stage": previous.value,
                "new_stage": stage.value,
                "reason": reason or "manual_override",
            }
        )
        logger.info(
            "Strategy %s stage transitioned %s -> %s (reason: %s)",
            strategy_key,
            previous.value,
            stage.value,
            reason,
        )

    def get_stage_multipliers(self) -> dict[str, float]:
        """Returns allocation scaling multipliers for all known strategies."""
        return {
            key: STAGE_MULTIPLIERS.get(stage, 0.25)
            for key, stage in self._stages.items()
        }

    def record_trade(
        self,
        strategy_key: str,
        *,
        realized_pnl: Decimal,
        notional: Decimal,
        inst_id: str = "BTC-USDT-SWAP",
    ) -> None:
        """Update strategy performance metrics and check for circuit breakers."""
        m = self._metrics.setdefault(strategy_key, StrategyMetrics())
        m.trade_count += 1
        m.total_realized_pnl += realized_pnl

        if realized_pnl > Decimal("0"):
            m.win_count += 1
            m.gross_profit += realized_pnl
            m.consecutive_losses = 0
        else:
            m.loss_count += 1
            m.gross_loss += abs(realized_pnl)
            m.consecutive_losses += 1

        # Track peak equity & drawdown
        if m.total_realized_pnl > m.peak_pnl:
            m.peak_pnl = m.total_realized_pnl

        current_dd = m.peak_pnl - m.total_realized_pnl
        if current_dd > m.max_drawdown:
            m.max_drawdown = current_dd

        if notional > Decimal("0"):
            m.max_drawdown_pct = float(m.max_drawdown / notional)

        # Check circuit breaker
        self._evaluate_circuit_breaker(strategy_key, m, inst_id=inst_id)

    def _evaluate_circuit_breaker(
        self, strategy_key: str, m: StrategyMetrics, inst_id: str = "BTC-USDT-SWAP"
    ) -> None:
        current_stage = self.get_stage(strategy_key)
        if current_stage == StrategyStage.DEGRADED:
            return

        breaker_tripped = False
        reasons: list[str] = []

        if m.consecutive_losses >= 4:
            breaker_tripped = True
            reasons.append(f"consecutive_losses_{m.consecutive_losses}")

        if m.max_drawdown_pct >= 0.08:
            breaker_tripped = True
            reasons.append(f"max_drawdown_breach_{m.max_drawdown_pct * 100:.1f}%")

        if m.trade_count >= 10 and m.win_rate < 0.35:
            breaker_tripped = True
            reasons.append(f"win_rate_decay_{m.win_rate * 100:.1f}%")

        if breaker_tripped:
            reason_str = "; ".join(reasons)
            self.set_stage(
                strategy_key,
                StrategyStage.DEGRADED,
                reason=f"circuit_breaker: {reason_str}",
            )

            # Dispatch Feishu Reflexion alert
            try:
                alert_payload = ReflexionAlertPayload(
                    alert_id=f"cb_{strategy_key}_{utc_now().strftime('%Y%m%dT%H%M%S')}",
                    strategy_name=strategy_key,
                    strategy_family=strategy_key.split("_")[0],
                    target_symbol=inst_id,
                    timeframe="1m",
                    failure_class="CIRCUIT_BREAKER_TRIGGERED",
                    severity="BLOCKING",
                    observed_metrics={
                        "trade_count": m.trade_count,
                        "win_rate": f"{m.win_rate * 100:.1f}%",
                        "profit_factor": f"{m.profit_factor:.2f}",
                        "max_drawdown_pct": f"{m.max_drawdown_pct * 100:.1f}%",
                        "consecutive_losses": m.consecutive_losses,
                    },
                    regime_attribution={
                        "dominant_regime": "HIGH_VOLATILITY_CHOP",
                        "breakdown_reason": (
                            f"Strategy {strategy_key} hit risk guardrail: {reason_str}"
                        ),
                    },
                    negative_constraints=[
                        f"halt_new_positions_for_{strategy_key}",
                        "require_re_evolution_before_promotion",
                    ],
                    evolution_action={
                        "action": "DEMOTE_TO_DEGRADED",
                        "status": "awaiting_reflexion_evolution",
                    },
                )
                dispatch_reflexion_alert(alert_payload)
            except Exception as exc:
                logger.warning("Failed to dispatch circuit breaker alert: %s", exc)

    def evaluate_promotions(self) -> list[dict[str, Any]]:
        """Evaluate running strategies and auto-promote those meeting criteria."""
        promoted: list[dict[str, Any]] = []
        for key, stage in list(self._stages.items()):
            m = self._metrics.get(key)
            if not m or stage in {StrategyStage.FULL_LIVE, StrategyStage.DEGRADED}:
                continue

            target_stage = _evaluate_target_stage(stage, m)
            if target_stage is not None:
                self.set_stage(key, target_stage, reason="performance_criteria_satisfied")
                promoted.append({"strategy": key, "from": stage.value, "to": target_stage.value})

        return promoted

    def summary(self) -> list[dict[str, Any]]:
        """Provide audit summary of all registered strategies."""
        results: list[dict[str, Any]] = []
        for key, stage in sorted(self._stages.items()):
            m = self._metrics.get(key, StrategyMetrics())
            results.append(
                {
                    "strategy_key": key,
                    "stage": stage.value,
                    "multiplier": STAGE_MULTIPLIERS.get(stage, 0.0),
                    "trade_count": m.trade_count,
                    "win_rate": round(m.win_rate, 4),
                    "profit_factor": round(m.profit_factor, 2),
                    "total_realized_pnl": str(m.total_realized_pnl),
                    "consecutive_losses": m.consecutive_losses,
                    "max_drawdown_pct": round(m.max_drawdown_pct, 4),
                }
            )
        return results


def _evaluate_target_stage(stage: StrategyStage, m: StrategyMetrics) -> StrategyStage | None:
    if stage == StrategyStage.PAPER_OBSERVING and (
        m.trade_count >= 10
        and m.win_rate >= 0.50
        and m.profit_factor >= 1.3
        and m.max_drawdown_pct <= 0.06
    ):
        return StrategyStage.CANARY_LIVE

    if stage == StrategyStage.CANARY_LIVE and (
        m.trade_count >= 25
        and m.win_rate >= 0.55
        and m.profit_factor >= 1.5
        and m.max_drawdown_pct <= 0.05
    ):
        return StrategyStage.CONTROLLED_LIVE

    if stage == StrategyStage.CONTROLLED_LIVE and (
        m.trade_count >= 50
        and m.win_rate >= 0.60
        and m.profit_factor >= 1.8
        and m.max_drawdown_pct <= 0.04
    ):
        return StrategyStage.FULL_LIVE

    return None
