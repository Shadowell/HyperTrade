# Agent Flight Recorder & Replay Telemetry Architecture Specification

## 1. Executive Summary

This document specifies the **Agent Flight Recorder & Replay Telemetry Subsystem** for HyperTrade. It provides deterministic step tracing, immutable snapshot logging, and step-by-step decision replay capabilities for agent flight recorders.

---

## 2. Architecture & Components

```
+-------------------------------------------------------------------------------------------------------------------------------+
|                                      Agent Flight Recorder & Replay Telemetry                                                 |
+-------------------------------------------------------------------------------------------------------------------------------+
| 1. Step Snapshot Recorder                                                                                                     |
|    - Captures: step_idx, timestamp, input_tokens, output_tokens, tool_calls, tool_results, llm_response, latency_ms           |
|    - Immutable flight log storage indexed by session_id                                                                       |
+-------------------------------------------------------------------------------------------------------------------------------+
| 2. Flight Log Inspection & Replay Engine                                                                                      |
|    - get_flight_log(session_id): Returns complete step trajectory                                                             |
|    - replay_step(session_id, step_idx): Replays specific step input/output state                                              |
+-------------------------------------------------------------------------------------------------------------------------------+
```

### 2.1 Agent Flight Recorder (`AgentFlightRecorder`)
Records immutable step snapshots per session, tracking step indices, timestamps, tool calls, tool results, model output, latency, and token usage.

### 2.2 Replay Telemetry Engine (`FlightRecorderReplayEngine`)
Provides search and step replay capabilities allowing operators and UI flight recorders to inspect agent decision trajectories.

---

## 3. Verification Plan

1. **Unit Tests**: `tests/test_flight_recorder.py`
2. **Integration Verification**: Run `./scripts/check.sh` ensuring all tests pass.
