"""
Unit Tests for Agent Flight Recorder & Replay Telemetry (flight_recorder.py)
"""

from hypertrade.agent.flight_recorder import AgentFlightRecorder, StepSnapshot


def test_agent_flight_recorder():
    recorder = AgentFlightRecorder()
    session_id = "session_test_001"

    snap1 = StepSnapshot(
        session_id=session_id,
        step_idx=0,
        tool_calls=[{"name": "market_ticker", "args": {"symbol": "BTC"}}],
        tool_results=[{"status": "ok"}],
        llm_response="Observed BTC ticker.",
        input_tokens=150,
        output_tokens=30,
        latency_ms=210.0,
    )

    recorder.record_step(snap1)

    log = recorder.get_flight_log(session_id)
    assert len(log) == 1
    assert log[0].step_idx == 0

    replayed = recorder.replay_step(session_id, 0)
    assert replayed is not None
    assert replayed.llm_response == "Observed BTC ticker."

    exported_json = recorder.export_flight_log_json(session_id)
    assert session_id in exported_json
    assert "market_ticker" in exported_json
