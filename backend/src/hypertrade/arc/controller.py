"""
ARC Controller Engine and State Machine
"""

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCReflexionEventV1,
    LiveApprovalPackageV1,
    ResearchWindowsV1,
)

ARCMissionState = Literal[
    "created",
    "compiling_goal",
    "exploring_candidates",
    "mutating",
    "red_team_testing",
    "validating",
    "paper_authorizing",
    "paper_review_ready",
    "paper_provisioning",
    "paper_observing",
    "live_approval_ready",
    "approved_pending_effect",
    "live_canary",
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
    live_approval: LiveApprovalPackageV1 | None = None
    paper_review: dict[str, Any] = Field(default_factory=dict)
    avo: dict[str, Any] = Field(default_factory=dict)
    paper_observation: dict[str, Any] = Field(default_factory=dict)
    paper_feedback: dict[str, Any] = Field(default_factory=dict)
    paper_started_at: datetime | None = None
    self_test_records: list[dict[str, Any]] = Field(default_factory=list)
    created_by: str = "operator"
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ARCController:
    """
    Universal Agent Kernel Controller managing the state machine,
    event reduction, and autonomous exploration loop.
    """

    def __init__(self, mission_id: str | None = None, goal: ARCGoalV1 | None = None):
        self.mission_id = mission_id or f"arc_{uuid.uuid4().hex[:12]}"
        if goal is not None and goal.paper_review_required and goal.research_id is None:
            goal.research_id = self.mission_id
        if goal is not None and goal.research_mode == "avo":
            if not goal.paper_review_required:
                raise ValueError("AVO requires version-bound Paper review")
            if goal.research_windows is None:
                goal.research_windows = ResearchWindowsV1()
        self.projection = ARCMissionProjection(mission_id=self.mission_id, goal=goal)
        # Storage revision this projection was read at. The store compares it against
        # the committed row to tell a stale cache from the current mission.
        self.revision = 0

    def apply_event(self, event_type: str, payload: dict[str, Any]) -> ARCEventV1:
        """Apply one event to the newest committed projection.

        The reduction happens inside the store's per-mission lock rather than here,
        because api and worker each hold their own controller for the same mission.
        Reducing against a stale local snapshot and writing it back whole is how one
        process silently erases the other's progress.
        """
        if event_type == "budget_extended":
            # Persist the operator directive in new events; never invent it during old replay.
            payload = {
                **payload,
                "resume_message": (
                    "The operator explicitly resumed this research. The prior stop is historical, "
                    "not a summary request. Re-read available tools; capabilities "
                    "may have changed. Continue from recorded experiments using remaining server "
                    "budgets and the original objective. Choose a research tool now."
                ),
            }
        evt = ARCEventV1(
            mission_id=self.mission_id,
            event_type=event_type,
            payload=payload,
        )
        from hypertrade.arc.store import commit_event

        commit_event(self, evt)
        return evt

    def absorb(self, evt: ARCEventV1) -> None:
        """Append and reduce. The store calls this while holding the mission row."""
        self._reduce(evt)
        self.projection.events.append(evt)

    def rebase(self, projection: ARCMissionProjection, revision: int) -> None:
        """Adopt the committed projection before replaying a local event onto it."""
        self.projection = projection
        self.revision = revision

    def _reduce(self, evt: ARCEventV1) -> None:
        p = self.projection
        p.updated_at = evt.timestamp
        et = evt.event_type
        payload = evt.payload

        if et.startswith("avo_"):
            from hypertrade.arc.avo import reduce_avo_event

            reduce_avo_event(p, evt)
            return

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

        elif et == "bitpro_self_tested":
            attempt_id = payload.get("attempt_id")
            record = dict(payload)
            p.self_test_records.append(record)
            for att in p.attempts:
                if att.attempt_id == attempt_id or att.candidate_id == attempt_id:
                    att.bitpro_strategy_id = (
                        payload.get("bitpro_strategy_id") or att.bitpro_strategy_id
                    )
                    att.bitpro_backtest_id = payload.get("backtest_id") or att.bitpro_backtest_id
                    if payload.get("validation_id"):
                        att.validation_id = payload.get("validation_id")
                    att.observed_metrics.update(payload.get("metrics") or {})
                    if payload.get("passed"):
                        att.state = "validated"
                    break
            if payload.get("passed"):
                p.state = "paper_authorizing"

        elif et == "candidate_validated":
            attempt_id = payload["attempt_id"]
            for att in p.attempts:
                if att.attempt_id == attempt_id or att.candidate_id == attempt_id:
                    att.state = "validated"
                    att.validation_id = payload.get("validation_id") or att.validation_id
                    if payload.get("bitpro_strategy_id"):
                        att.bitpro_strategy_id = payload.get("bitpro_strategy_id")
                    if payload.get("backtest_id"):
                        att.bitpro_backtest_id = payload.get("backtest_id")
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

        elif et == "paper_review_requested":
            p.paper_review = dict(payload["package"])
            p.state = (
                "paper_review_ready" if p.paper_review["status"] == "ready" else "needs_operator"
            )

        elif et == "paper_review_decided":
            from hypertrade.arc.paper_review import build_paper_review

            review_package = build_paper_review(p)
            if (
                p.state != "paper_review_ready"
                or review_package["unknowns"]
                or review_package["package_hash"] != payload["package_hash"]
                or p.paper_review.get("package_hash") != payload["package_hash"]
                or p.paper_review.get("decision")
            ):
                raise PermissionError("review changed or already claimed")
            p.paper_review["decision"] = dict(payload)
            p.paper_review["status"] = (
                "approved_pending_effect" if payload["decision"] == "approve" else "rejected"
            )
            p.state = "paper_provisioning" if payload["decision"] == "approve" else "needs_operator"

        elif et == "paper_review_effect":
            if (
                p.state != "paper_provisioning"
                or p.paper_review.get("package_hash") != payload["package_hash"]
            ):
                raise PermissionError("paper effect is not bound to an approved review")
            p.paper_review.update(payload)
            p.paper_review["status"] = "paper_observing" if payload["ok"] else "effect_unknown"
            p.state = "paper_observing" if payload["ok"] else "needs_operator"
            if payload["ok"]:
                for att in p.attempts:
                    if att.attempt_id == p.paper_review["attempt_id"]:
                        att.paper_instance_id = payload["paper_instance_id"]
                        att.state = "paper_observing"
                p.paper_started_at = evt.timestamp

        elif et == "paper_started":
            attempt_id = payload["attempt_id"]
            paper_instance_id = payload.get("paper_instance_id")
            for att in p.attempts:
                if att.attempt_id == attempt_id or att.candidate_id == attempt_id:
                    att.state = "paper_observing"
                    att.paper_instance_id = paper_instance_id
                    break
            p.paper_started_at = evt.timestamp
            p.state = "paper_observing"

        elif et == "paper_feedback_checked":
            p.paper_feedback.update(payload)

        elif et == "paper_observed":
            p.paper_observation = dict(payload.get("observation") or {})
            p.state = "paper_observing"

        elif et == "live_approval_ready":
            package = LiveApprovalPackageV1(**payload["package"])
            p.live_approval = package
            p.state = "live_approval_ready" if package.status == "ready" else "needs_operator"

        elif et == "live_decided":
            decision = str(payload.get("decision") or "")
            if p.live_approval is not None:
                p.live_approval.decision = dict(payload)
                if decision == "approved":
                    p.live_approval.status = "approved"
                elif decision == "rejected":
                    p.live_approval.status = "rejected"
            p.state = "approved_pending_effect" if decision == "approved" else "needs_operator"

        elif et == "live_promoted":
            attempt_id = payload.get("attempt_id")
            live_instance_id = payload.get("live_instance_id")
            for att in p.attempts:
                if attempt_id and (att.attempt_id == attempt_id or att.candidate_id == attempt_id):
                    att.state = "live_canary"
                    att.live_instance_id = live_instance_id
                    break
                if att.paper_instance_id and live_instance_id and att.live_instance_id is None:
                    att.state = "live_canary"
                    att.live_instance_id = live_instance_id
            if p.live_approval is not None:
                p.live_approval.status = "promoted"
            p.state = "live_canary"

        elif et == "live_revoked":
            if p.live_approval is not None:
                revoked = dict(p.live_approval.decision or {})
                revoked.update({"revoked": True, **payload})
                p.live_approval.decision = revoked
            p.state = "needs_operator"

        elif et == "budget_extended":
            fields = {
                "extra_candidates": "max_candidates",
                "extra_model_calls": "max_model_calls",
                "extra_tool_calls": "max_tool_calls",
                "extra_backtests": "max_backtests",
                "extra_wall_seconds": "max_wall_seconds",
            }
            key = payload.get("idempotency_key")
            previous = next(
                (
                    event.payload
                    for event in p.events
                    if event.event_type == et
                    and key
                    and event.payload.get("idempotency_key") == key
                ),
                None,
            )
            if previous is not None:
                if any(previous.get(name, 0) != payload.get(name, 0) for name in fields) or any(
                    previous.get(name) != payload.get(name)
                    for name in ("operator_id", "provider_name", "model_name")
                ):
                    raise PermissionError("budget extension key is bound to another request")
                payload["idempotent"] = True
                return
            if p.goal is not None:
                provider = payload.get("provider_name")
                model = payload.get("model_name")
                if model and (provider or p.goal.provider_name) not in {"codex", "vide_coding"}:
                    raise PermissionError("task model overrides require codex or vide_coding")
                if (provider and provider != p.goal.provider_name) or (
                    model and model != p.goal.model_name
                ):
                    if (
                        p.attempts
                        or p.state != "needs_operator"
                        or (p.avo.get("pending") or {}).get("kind") == "tool"
                    ):
                        raise PermissionError(
                            "provider can change only on a stopped task without candidates"
                        )
                    abandoned = list(p.avo.get("awaiting", []))
                    for call in abandoned:
                        p.avo.setdefault("messages", []).append(
                            {
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": json.dumps(
                                    {
                                        "status": "not_executed",
                                        "reason": "operator_changed_provider",
                                    }
                                ),
                            }
                        )
                    p.avo["awaiting"] = []
                    payload["discarded_tool_ids"] = [call["id"] for call in abandoned]
                    if provider and provider != p.goal.provider_name:
                        p.goal.model_name = None
                        p.goal.provider_name = str(provider)
                    if model:
                        p.goal.model_name = str(model)
                for field, target in fields.items():
                    extra = int(payload.get(field) or 0)
                    if extra > 0:
                        setattr(p.goal.budget, target, getattr(p.goal.budget, target) + extra)
            if p.state == "needs_operator":
                if (
                    p.goal is not None
                    and p.goal.research_mode == "avo"
                    and p.avo.get("messages")
                    and not p.avo.get("awaiting")
                    and isinstance(payload.get("resume_message"), str)
                ):
                    p.avo["messages"].append({"role": "user", "content": payload["resume_message"]})
                    p.avo["empty_action_streak"] = 0
                p.state = "exploring_candidates"

        elif et == "operator_needed":
            p.state = "needs_operator"

        elif et == "mission_completed":
            p.state = "completed"

        elif et == "mission_failed":
            p.state = "failed"
