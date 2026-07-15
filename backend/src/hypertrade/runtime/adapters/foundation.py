from __future__ import annotations

from hashlib import sha256

from hypertrade.runtime.domain.models import (
    MissionProjection,
    PlanDiffV1,
    PlanStepV2,
    PlanV2,
    ReplanRequestV1,
    StepObservationV2,
)


class ReadOnlyCapabilityPolicy:
    """Sprint-111 fail-closed policy before the versioned catalog lands."""

    def __init__(self, allowed: set[str] | None = None) -> None:
        self.allowed = allowed or {"runtime.objective_inspection"}

    def validate_step(self, step: PlanStepV2, permission_profile_ref: str) -> None:
        if permission_profile_ref != "read_only.v1":
            raise ValueError("Sprint 111 only accepts read_only.v1 missions")
        if step.capability_id not in self.allowed:
            raise ValueError(f"unregistered capability: {step.capability_id}")
        if not step.read_only or step.requires_approval:
            raise ValueError("foundation runtime cannot dispatch write or approval capabilities")


class FoundationPlanner:
    """Strict bootstrap planner for the first canary path.

    It intentionally performs no model call. Sprint 112 replaces capability
    resolution and later planners may use providers behind the same port.
    """

    async def plan(self, mission: MissionProjection) -> PlanV2:
        return PlanV2(
            plan_id=f"plan_{sha256(mission.mission_id.encode()).hexdigest()[:20]}",
            version=1,
            goal_interpretation=mission.objective,
            completion_checks=tuple(item.criterion_id for item in mission.success_criteria),
            steps=(
                PlanStepV2(
                    step_id="inspect_objective",
                    title="Validate and normalize the mission objective",
                    capability_id="runtime.objective_inspection",
                    arguments={"objective": mission.objective},
                    expected_output_schema={"type": "object", "required": ["objective_hash"]},
                ),
            ),
        )

    async def replan(
        self,
        mission: MissionProjection,
        previous: PlanV2,
        request: ReplanRequestV1,
    ) -> PlanV2:
        version = previous.version + 1
        return PlanV2(
            plan_id=f"plan_{sha256(f'{mission.mission_id}:{version}'.encode()).hexdigest()[:20]}",
            version=version,
            parent_version=previous.version,
            goal_interpretation=mission.objective,
            assumptions=(f"Replan trigger: {request.trigger}",),
            completion_checks=previous.completion_checks,
            steps=previous.steps,
            diff=PlanDiffV1(
                kept=tuple(step.step_id for step in previous.steps),
                reason_code=request.trigger,
            ),
        )


class FoundationExecutor:
    """No-side-effect executor proving the new Mission vertical slice."""

    async def execute(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> StepObservationV2:
        if step.capability_id != "runtime.objective_inspection":
            return StepObservationV2(
                status="failed",
                summary="Capability is unavailable in the foundation runtime.",
                error_category="source_unavailable",
                retryable=False,
                source_refs=("runtime:capability-policy",),
            )
        objective_hash = sha256(mission.objective.encode()).hexdigest()
        return StepObservationV2(
            status="succeeded",
            summary="Mission objective and safety boundaries are structurally valid.",
            result={
                "objective_hash": objective_hash,
                "constraint_count": len(mission.constraints),
                "plan_version": plan.version,
                "attempt": attempt,
            },
            source_refs=(f"mission:{mission.mission_id}", "runtime:foundation-v2"),
            usage={"tool_calls": 1, "tokens": 0, "model_calls": 0},
        )
