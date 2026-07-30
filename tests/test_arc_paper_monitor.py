"""
Unit & Integration Tests for Phase 1: Dynamic Paper Trading Observation Feedback Loop
"""

from hypertrade.arc.reflexion import ARCReflexionLedger
from hypertrade.bitpro.paper_monitor import (
    IncrementalEvolutionTrigger,
    PaperAnomalyDetector,
    PaperAnomalyEvent,
    PaperObservationSnapshot,
    PaperReflexionTranslator,
)


def test_paper_anomaly_detector_triggers_events():
    detector = PaperAnomalyDetector(
        max_drawdown_threshold=0.10,
        min_win_rate_threshold=0.45,
        max_consecutive_losses=4,
        max_slippage_bps=15.0,
    )

    snapshot = PaperObservationSnapshot(
        instance_id="bitpro_paper_001",
        symbol="CL-USDT-SWAP",
        cumulative_return_pct=-0.12,
        current_drawdown_pct=0.14,
        consecutive_losses=5,
        win_rate_30d=0.40,
        avg_slippage_bps=18.5,
    )

    events = detector.detect_anomalies(snapshot)
    assert len(events) == 4
    event_types = {e.anomaly_type for e in events}
    assert "MAX_DRAWDOWN_BREACH" in event_types
    assert "WIN_RATE_DECAY" in event_types
    assert "LOSS_STREAK" in event_types
    assert "SLIPPAGE_SURGE" in event_types


def test_paper_reflexion_translator_generates_negative_constraints():
    translator = PaperReflexionTranslator()

    event = PaperAnomalyEvent(
        instance_id="bitpro_paper_001",
        symbol="CL-USDT-SWAP",
        anomaly_type="MAX_DRAWDOWN_BREACH",
        observed_value=0.12,
        threshold_value=0.10,
        message="Drawdown exceeded 10%",
    )

    constraints = translator.translate_anomaly_to_constraints(event)
    assert len(constraints) > 0
    assert any("stop_loss <= 0.07" in c for c in constraints)


def test_incremental_evolution_trigger_creates_re_training_controller():
    trigger = IncrementalEvolutionTrigger()
    reflexion_ledger = ARCReflexionLedger()

    event = PaperAnomalyEvent(
        instance_id="bitpro_paper_001",
        symbol="CL-USDT-SWAP",
        anomaly_type="WIN_RATE_DECAY",
        observed_value=0.38,
        threshold_value=0.45,
        message="Win rate dropped to 38%",
    )

    ctrl = trigger.trigger_re_training(event, reflexion_ledger)
    assert ctrl is not None
    assert ctrl.projection.goal is not None
    assert ctrl.projection.goal.symbols == ["CL-USDT-SWAP"]
    assert len(reflexion_ledger.get_history()) > 0
