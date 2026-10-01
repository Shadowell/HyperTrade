from decimal import Decimal

from hypertrade.paper.stage_gate import (
    ProgressiveStageGate,
    StrategyStage,
)


def test_progressive_stage_gate_lifecycle_and_promotion():
    gate = ProgressiveStageGate()
    strat_key = "momentum_breakout_v1"

    # Initial stage is paper_observing
    assert gate.get_stage(strat_key) == StrategyStage.PAPER_OBSERVING

    # Record 12 winning trades to trigger promotion to CANARY_LIVE
    for _ in range(12):
        gate.record_trade(
            strat_key,
            realized_pnl=Decimal("150"),
            notional=Decimal("2000"),
        )

    promotions = gate.evaluate_promotions()
    assert len(promotions) == 1
    assert promotions[0]["strategy"] == strat_key
    assert promotions[0]["to"] == StrategyStage.CANARY_LIVE.value
    assert gate.get_stage(strat_key) == StrategyStage.CANARY_LIVE


def test_progressive_stage_gate_circuit_breaker_demotion():
    gate = ProgressiveStageGate()
    strat_key = "rsi_reversal"

    # Record 4 consecutive losses to trip circuit breaker
    for _ in range(4):
        gate.record_trade(
            strat_key,
            realized_pnl=Decimal("-250"),
            notional=Decimal("2000"),
        )

    assert gate.get_stage(strat_key) == StrategyStage.DEGRADED

    summary = gate.summary()
    strat_summary = next(s for s in summary if s["strategy_key"] == strat_key)
    assert strat_summary["stage"] == "degraded"
    assert strat_summary["consecutive_losses"] == 4
