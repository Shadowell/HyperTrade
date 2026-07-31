"""
Agent Flight Recorder & Replay Telemetry Subsystem

Provides immutable step snapshots, flight log recording,
and step-by-step decision replay capabilities.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StepSnapshot:
    session_id: str
    step_idx: int
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    llm_response: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentFlightRecorder:
    """
    Immutable flight log recorder capturing agent decision trajectories per session.
    """

    def __init__(self) -> None:
        # session_id -> list of StepSnapshot
        self._flight_logs: dict[str, list[StepSnapshot]] = {}

    def record_step(self, snapshot: StepSnapshot) -> None:
        logs = self._flight_logs.setdefault(snapshot.session_id, [])
        logs.append(snapshot)
        logger.debug(
            "AgentFlightRecorder recorded step %d for session '%s'",
            snapshot.step_idx,
            snapshot.session_id,
        )

    def get_flight_log(self, session_id: str) -> list[StepSnapshot]:
        return list(self._flight_logs.get(session_id, []))

    def replay_step(self, session_id: str, step_idx: int) -> StepSnapshot | None:
        logs = self._flight_logs.get(session_id, [])
        for snap in logs:
            if snap.step_idx == step_idx:
                return snap
        return None

    def export_flight_log_json(self, session_id: str) -> str:
        logs = self.get_flight_log(session_id)
        raw = [snap.to_dict() for snap in logs]
        return json.dumps(raw, indent=2)
