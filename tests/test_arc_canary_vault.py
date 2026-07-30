"""
Unit & Integration Tests for Phase 7: Live Canary Vault & Risk Gate Pipeline
"""

from hypertrade.risk.canary import (
    CanaryTier,
    CanaryVaultPipeline,
    StrategyCanaryInstance,
)


def test_canary_tier_promotion_from_paper():
    pipeline = CanaryVaultPipeline()
    inst = StrategyCanaryInstance(
        instance_id="inst_c1",
        symbol="BTC-USDT-SWAP",
        current_tier=CanaryTier.PAPER_INCUBATION,
        observation_days=14,
        stop_loss_pct=0.05,
    )

    promoted, new_tier, msg = pipeline.evaluate_promotion(inst)
    assert promoted is True
    assert new_tier == CanaryTier.CANARY_LIVE_MICRO
    assert "0.5% Capital Allocation" in msg


def test_canary_emergency_demotion_on_drawdown_circuit_breaker():
    pipeline = CanaryVaultPipeline()
    inst = StrategyCanaryInstance(
        instance_id="inst_c2",
        symbol="CL-USDT-SWAP",
        current_tier=CanaryTier.CANARY_LIVE_MICRO,
        current_daily_drawdown_pct=0.035,  # Exceeds 3.0% limit!
    )

    demoted, new_tier, msg = pipeline.evaluate_emergency_demotion(inst)
    assert demoted is True
    assert new_tier == CanaryTier.PAPER_INCUBATION
    assert "EMERGENCY_DEMOTION" in msg


def test_canary_emergency_demotion_on_pnl_drift():
    pipeline = CanaryVaultPipeline()
    inst = StrategyCanaryInstance(
        instance_id="inst_c3",
        symbol="ETH-USDT-SWAP",
        current_tier=CanaryTier.CANARY_LIVE_MICRO,
        paper_pnl_pct=0.15,
        live_pnl_pct=0.02,  # Drift is 13%, > 10% limit!
    )

    demoted, new_tier, msg = pipeline.evaluate_emergency_demotion(inst)
    assert demoted is True
    assert new_tier == CanaryTier.PAPER_INCUBATION
    assert "PnL drift" in msg
