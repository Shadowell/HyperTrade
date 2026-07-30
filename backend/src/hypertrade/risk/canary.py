"""
ARC Live Canary Vault & Risk Gate Pipeline
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CanaryTier(StrEnum):
    PAPER_INCUBATION = "paper_incubation"  # Tier 0: 0% real capital
    CANARY_LIVE_MICRO = "canary_live_micro"  # Tier 1: 0.5% max capital
    CANARY_LIVE_MINI = "canary_live_mini"  # Tier 2: 2.0% max capital
    PRODUCTION_LIVE_VAULT = "production_live_vault"  # Tier 3: Dynamic capital allocation


class RiskGatePolicy(BaseModel):
    max_daily_drawdown_pct: float = 0.03  # 3% daily loss circuit breaker
    max_pnl_drift_pct: float = 0.10  # 10% max paper-to-live PnL drift
    mandatory_stop_loss_limit_pct: float = 0.07  # Mandatory 7% hard stop loss
    min_paper_observation_days: int = 14


class StrategyCanaryInstance(BaseModel):
    instance_id: str
    symbol: str
    current_tier: CanaryTier = CanaryTier.PAPER_INCUBATION
    paper_pnl_pct: float = 0.0
    live_pnl_pct: float = 0.0
    current_daily_drawdown_pct: float = 0.0
    observation_days: int = 0
    stop_loss_pct: float = 0.05
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanaryVaultPipeline:
    """
    Manages deterministic promotion & emergency demotion of strategy instances
    across paper incubation and live Canary vault tiers under strict risk gates.
    """

    def __init__(self, policy: RiskGatePolicy | None = None) -> None:
        self.policy = policy or RiskGatePolicy()

    def evaluate_promotion(
        self, instance: StrategyCanaryInstance
    ) -> tuple[bool, CanaryTier, str]:
        """
        Evaluates whether strategy instance qualifies for advancement to the next Canary tier.
        """
        if instance.stop_loss_pct > self.policy.mandatory_stop_loss_limit_pct:
            return (
                False,
                instance.current_tier,
                f"STOP_LOSS_GATE_BREACH: Strategy stop_loss ({instance.stop_loss_pct:.1%}) "
                f"exceeds limit ({self.policy.mandatory_stop_loss_limit_pct:.1%})",
            )

        if instance.current_daily_drawdown_pct >= self.policy.max_daily_drawdown_pct:
            dd = instance.current_daily_drawdown_pct
            return (
                False,
                instance.current_tier,
                f"DRAWDOWN_CIRCUIT_BREAKER: Daily drawdown ({dd:.1%}) exceeds 3.0% threshold",
            )

        if instance.current_tier == CanaryTier.PAPER_INCUBATION:
            if instance.observation_days < self.policy.min_paper_observation_days:
                return (
                    False,
                    instance.current_tier,
                    f"INSUFFICIENT_OBSERVATION: {instance.observation_days} days observed, "
                    f"requires {self.policy.min_paper_observation_days} days",
                )
            return (
                True,
                CanaryTier.CANARY_LIVE_MICRO,
                "Promoted to Tier 1 (Canary Live Micro - 0.5% Capital Allocation)",
            )

        if instance.current_tier == CanaryTier.CANARY_LIVE_MICRO:
            if instance.observation_days < 30:
                return (
                    False,
                    instance.current_tier,
                    "Requires 30 days of clean Live Micro observation",
                )
            return (
                True,
                CanaryTier.CANARY_LIVE_MINI,
                "Promoted to Tier 2 (Canary Live Mini - 2.0% Capital Allocation)",
            )

        if instance.current_tier == CanaryTier.CANARY_LIVE_MINI:
            if instance.observation_days < 60:
                return (
                    False,
                    instance.current_tier,
                    "Requires 60 days of clean Live Mini observation",
                )
            return (
                True,
                CanaryTier.PRODUCTION_LIVE_VAULT,
                "Promoted to Tier 3 (Production Live Vault - Dynamic Capital Allocation)",
            )

        return False, instance.current_tier, "Strategy is already in top production vault tier"

    def evaluate_emergency_demotion(
        self, instance: StrategyCanaryInstance
    ) -> tuple[bool, CanaryTier, str]:
        """
        Evaluates emergency risk triggers and demotes strategy instance back to Tier 0 if breached.
        """
        if instance.current_daily_drawdown_pct >= self.policy.max_daily_drawdown_pct:
            instance.current_tier = CanaryTier.PAPER_INCUBATION
            dd = instance.current_daily_drawdown_pct
            return (
                True,
                CanaryTier.PAPER_INCUBATION,
                f"EMERGENCY_DEMOTION: Daily drawdown ({dd:.1%}) triggered 3.0% circuit breaker.",
            )

        if instance.current_tier != CanaryTier.PAPER_INCUBATION:
            drift = abs(instance.paper_pnl_pct - instance.live_pnl_pct)
            if drift > self.policy.max_pnl_drift_pct:
                instance.current_tier = CanaryTier.PAPER_INCUBATION
                limit = self.policy.max_pnl_drift_pct
                return (
                    True,
                    CanaryTier.PAPER_INCUBATION,
                    f"EMERGENCY_DEMOTION: PnL drift ({drift:.1%}) exceeded {limit:.1%} limit.",
                )

        return False, instance.current_tier, "All risk gates satisfied cleanly"
