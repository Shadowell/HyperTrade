"""
Unit & Integration Tests for ARC Canary Vault & Risk Engine (Sprint 132 / Phase 7)
"""

from decimal import Decimal

from hypertrade.arc.canary_vault import CanaryVaultPipeline, RiskGatePolicy
from hypertrade.arc.contracts import CanaryTier, LiveTradingMandateV1


def test_canary_mandate_and_tier_enum() -> None:
    mandate = LiveTradingMandateV1(
        mandate_id="mandate_test_001",
        approved_by="operator",
        approval_token="token_valid_12345",
        symbol="BTC-USDT-SWAP",
        candidate_id="cand_001",
        canary_tier=CanaryTier.PAPER_INCUBATION,
        max_capital_u=Decimal("100"),
    )
    assert mandate.schema_version == "live_trading_mandate.v1"
    assert mandate.canary_tier == "paper_incubation"
    assert mandate.is_active is True


def test_risk_gate_policy_check_metrics() -> None:
    policy = RiskGatePolicy(
        max_daily_drawdown_pct=Decimal("3.0"),
        max_pnl_drift_pct=Decimal("10.0"),
        mandatory_stop_loss_pct=Decimal("7.0"),
    )

    # 1. Clean healthy metrics
    passed, reason = policy.check_metrics(
        {
            "daily_drawdown_pct": 1.5,
            "pnl_drift_pct": 4.2,
            "max_trade_loss_pct": 2.1,
        }
    )
    assert passed is True
    assert reason is None

    # 2. Daily drawdown circuit breaker violation
    passed, reason = policy.check_metrics(
        {
            "daily_drawdown_pct": 3.5,
            "pnl_drift_pct": 2.0,
            "max_trade_loss_pct": 1.0,
        }
    )
    assert passed is False
    assert "Daily drawdown 3.5% exceeds 3.0%" in str(reason)

    # 3. PnL drift violation
    passed, reason = policy.check_metrics(
        {
            "daily_drawdown_pct": 1.0,
            "pnl_drift_pct": 12.5,
            "max_trade_loss_pct": 1.0,
        }
    )
    assert passed is False
    assert "Paper-to-Live PnL drift 12.5% exceeds 10.0%" in str(reason)

    # 4. Mandatory stop loss violation
    passed, reason = policy.check_metrics(
        {
            "daily_drawdown_pct": 1.0,
            "pnl_drift_pct": 2.0,
            "max_trade_loss_pct": 8.5,
        }
    )
    assert passed is False
    assert "violates mandatory 7.0% stop-loss limit" in str(reason)


def test_canary_vault_pipeline_promotion_and_demotion() -> None:
    pipeline = CanaryVaultPipeline()
    mandate = LiveTradingMandateV1(
        mandate_id="mandate_test_002",
        approved_by="operator",
        approval_token="token_valid_67890",
        symbol="BTC-USDT-SWAP",
        candidate_id="cand_002",
        canary_tier=CanaryTier.PAPER_INCUBATION,
    )

    # Promotion from Tier 0 to Tier 1 after 14 days clean paper incubation
    new_tier, msg = pipeline.evaluate_promotion(
        mandate,
        metrics={"paper_sharpe": 1.5, "daily_drawdown_pct": 1.0},
        paper_days=14,
    )
    assert new_tier == CanaryTier.CANARY_LIVE_MICRO
    assert "Promoted from Paper Incubation to Canary Micro" in msg

    # Immediate automatic demotion upon drawdown breach
    mandate.canary_tier = CanaryTier.CANARY_LIVE_MICRO
    demoted_tier, was_demoted, demote_msg = pipeline.evaluate_demotion(
        mandate,
        metrics={"daily_drawdown_pct": 4.5},
    )
    assert demoted_tier == CanaryTier.PAPER_INCUBATION
    assert was_demoted is True
    assert "EMERGENCY CIRCUIT BREAKER" in demote_msg
