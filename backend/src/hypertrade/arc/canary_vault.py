"""
ARC Live Canary Vault & Deterministic Risk Engine Pipeline (Phase 7 / Sprint 132)

FROZEN (2026-08-23): not wired to any runtime path. live_allowed is Literal[False]
everywhere, so no vault stage can ever execute; revisit only when Sprint 132-134
(LiveTradingMandate / Live Canary) are explicitly approved, and then against the
real Risk Engine contract rather than this sketch.
"""

from decimal import Decimal
from typing import Any

from hypertrade.arc.contracts import CanaryTier, LiveTradingMandateV1


class RiskGatePolicy:
    """
    Deterministic risk protection boundary rules for Live Canary Trading.
    """

    def __init__(
        self,
        max_daily_drawdown_pct: Decimal = Decimal("3.0"),
        max_pnl_drift_pct: Decimal = Decimal("10.0"),
        mandatory_stop_loss_pct: Decimal = Decimal("7.0"),
    ) -> None:
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.max_pnl_drift_pct = max_pnl_drift_pct
        self.mandatory_stop_loss_pct = mandatory_stop_loss_pct

    def check_metrics(self, metrics: dict[str, Any]) -> tuple[bool, str | None]:
        """
        Evaluates live metrics against deterministic risk gates.
        Returns: (passed: bool, violation_reason: str | None)
        """
        daily_dd = Decimal(str(metrics.get("daily_drawdown_pct", "0.0")))
        pnl_drift = Decimal(str(metrics.get("pnl_drift_pct", "0.0")))
        max_loss = Decimal(str(metrics.get("max_trade_loss_pct", "0.0")))

        if daily_dd > self.max_daily_drawdown_pct:
            return (
                False,
                f"Daily drawdown {daily_dd}% exceeds 3.0% circuit breaker limit",
            )

        if pnl_drift > self.max_pnl_drift_pct:
            return (
                False,
                f"Paper-to-Live PnL drift {pnl_drift}% exceeds 10.0% max allowed threshold",
            )

        if max_loss > self.mandatory_stop_loss_pct:
            limit = self.mandatory_stop_loss_pct
            return (
                False,
                f"Trade loss {max_loss}% violates mandatory {limit}% stop-loss limit",
            )

        return True, None


class CanaryVaultPipeline:
    """
    Governs automatic tier promotion and demotion between Paper Incubation and Live Canary Tiers.
    """

    def __init__(self, risk_policy: RiskGatePolicy | None = None) -> None:
        self.risk_policy = risk_policy or RiskGatePolicy()

    def evaluate_promotion(
        self,
        mandate: LiveTradingMandateV1,
        metrics: dict[str, Any],
        paper_days: int = 14,
    ) -> tuple[str, str]:
        """
        Evaluates metrics for Tier promotion.
        Returns: (new_tier: str, message: str)
        """
        if not mandate.is_active:
            return mandate.canary_tier, "Mandate is inactive or revoked"

        passed, reason = self.risk_policy.check_metrics(metrics)
        if not passed:
            return CanaryTier.PAPER_INCUBATION, f"Promotion blocked by Risk Gate: {reason}"

        current_tier = mandate.canary_tier

        if current_tier == CanaryTier.PAPER_INCUBATION:
            if paper_days >= 14 and metrics.get("paper_sharpe", 0.0) >= 1.2:
                return (
                    CanaryTier.CANARY_LIVE_MICRO,
                    "Promoted from Paper Incubation to Canary Micro (0.5% Capital)",
                )
            return (
                current_tier,
                f"Requires at least 14 days paper incubation (current: {paper_days}D)",
            )

        elif current_tier == CanaryTier.CANARY_LIVE_MICRO:
            live_days = metrics.get("live_days", 0)
            if live_days >= 30:
                return (
                    CanaryTier.CANARY_LIVE_MINI,
                    "Promoted from Canary Micro to Canary Mini (2.0% Capital)",
                )
            return current_tier, f"Requires 30 days live micro verification (current: {live_days}D)"

        elif current_tier == CanaryTier.CANARY_LIVE_MINI:
            live_days = metrics.get("live_days", 0)
            if live_days >= 60:
                return CanaryTier.PRODUCTION_LIVE_VAULT, "Promoted to Production Live Vault"
            return current_tier, f"Requires 60 days live mini verification (current: {live_days}D)"

        return current_tier, "Already at Production Live Vault Tier"

    def evaluate_demotion(
        self,
        mandate: LiveTradingMandateV1,
        metrics: dict[str, Any],
    ) -> tuple[str, bool, str]:
        """
        Evaluates metrics for immediate demotion upon risk breach.
        Returns: (new_tier: str, demoted: bool, message: str)
        """
        passed, reason = self.risk_policy.check_metrics(metrics)
        if not passed:
            cid = mandate.candidate_id
            msg = f"EMERGENCY CIRCUIT BREAKER: Demoted {cid} to PAPER_INCUBATION ({reason})"
            return CanaryTier.PAPER_INCUBATION, True, msg

        return mandate.canary_tier, False, "All risk gates healthy"
