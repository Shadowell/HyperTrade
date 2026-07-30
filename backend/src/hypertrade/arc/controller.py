"""
ARC Controller Engine and State Machine
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCReflexionEventV1,
)

ARCMissionState = Literal[
    "created",
    "compiling_goal",
    "exploring_candidates",
    "mutating",
    "red_team_testing",
    "validating",
    "paper_authorizing",
    "paper_observing",
    "needs_operator",
    "completed",
    "failed",
]


class ARCEventV1(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    mission_id: str
    event_type: str
    payload: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ARCMissionProjection(BaseModel):
    mission_id: str
    state: ARCMissionState = "created"
    goal: ARCGoalV1 | None = None
    attempts: list[ARCCandidateAttemptV1] = Field(default_factory=list)
    current_attempt_id: str | None = None
    reflexion_history: list[ARCReflexionEventV1] = Field(default_factory=list)
    events: list[ARCEventV1] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ARCController:
    """
    Universal Agent Kernel Controller managing the state machine,
    event reduction, and autonomous exploration loop.
    """

    def __init__(self, mission_id: str | None = None, goal: ARCGoalV1 | None = None):
        self.mission_id = mission_id or f"arc_{uuid.uuid4().hex[:12]}"
        self.projection = ARCMissionProjection(mission_id=self.mission_id, goal=goal)

    def apply_event(self, event_type: str, payload: dict[str, Any]) -> ARCEventV1:
        evt = ARCEventV1(
            mission_id=self.mission_id,
            event_type=event_type,
            payload=payload,
        )
        self.projection.events.append(evt)
        self._reduce(evt)
        return evt

    def _reduce(self, evt: ARCEventV1) -> None:
        p = self.projection
        p.updated_at = evt.timestamp
        et = evt.event_type
        payload = evt.payload

        if et == "goal_compiled":
            p.goal = ARCGoalV1(**payload["goal"])
            p.state = "exploring_candidates"

        elif et == "candidate_proposed":
            attempt = ARCCandidateAttemptV1(**payload["attempt"])
            p.attempts.append(attempt)
            p.current_attempt_id = attempt.attempt_id
            if p.goal:
                p.goal.budget.candidates_used += 1

        elif et == "candidate_mutated":
            attempt_id = payload["attempt_id"]
            for att in p.attempts:
                if att.attempt_id == attempt_id or att.candidate_id == attempt_id:
                    att.state = "mutated"
                    att.strategy_code = payload.get("strategy_code", att.strategy_code)
                    break
            p.state = "mutating"

        elif et == "red_team_tested":
            attempt_id = payload["attempt_id"]
            passed = payload.get("passed", False)
            for att in p.attempts:
                if att.attempt_id == attempt_id or att.candidate_id == attempt_id:
                    att.state = "red_team_testing"
                    att.observed_metrics.update(payload.get("metrics", {}))
                    break
            p.state = "red_team_testing" if not passed else "validating"

        elif et == "candidate_validated":
            attempt_id = payload["attempt_id"]
            for att in p.attempts:
                if att.attempt_id == attempt_id or att.candidate_id == attempt_id:
                    att.state = "validated"
                    att.validation_id = payload.get("validation_id")
                    break
            p.state = "paper_authorizing"

        elif et == "reflexion_recorded":
            reflexion = ARCReflexionEventV1(**payload["reflexion"])
            p.reflexion_history.append(reflexion)
            target_id = reflexion.candidate_id
            for att in p.attempts:
                if att.attempt_id == target_id or att.candidate_id == target_id:
                    att.state = "rejected"
                    att.reflexion_events.append(reflexion)
                    break
            if p.goal and p.goal.budget.is_exhausted():
                p.state = "needs_operator"
            else:
                p.state = "exploring_candidates"

        elif et == "paper_started":
            attempt_id = payload["attempt_id"]
            paper_instance_id = payload.get("paper_instance_id")
            for att in p.attempts:
                if att.attempt_id == attempt_id or att.candidate_id == attempt_id:
                    att.state = "paper_observing"
                    att.paper_instance_id = paper_instance_id
                    break
            p.state = "paper_observing"

        elif et == "operator_needed":
            p.state = "needs_operator"

        elif et == "mission_completed":
            p.state = "completed"

        elif et == "mission_failed":
            p.state = "failed"
