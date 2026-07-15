from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MissionStatus(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    RUNNING = "running"
    REPLANNING = "replanning"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    RETRY_WAIT = "retry_wait"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELED = "canceled"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


TERMINAL_STATUSES = {
    MissionStatus.CANCELED,
    MissionStatus.COMPLETED,
    MissionStatus.FAILED,
    MissionStatus.BUDGET_EXHAUSTED,
}


class MissionBudgetV1(StrictModel):
    max_plan_versions: int = Field(default=3, ge=1, le=5)
    max_steps_per_plan: int = Field(default=12, ge=1, le=24)
    max_attempts_per_step: int = Field(default=2, ge=1, le=3)
    max_model_calls_per_step: int = Field(default=4, ge=0, le=8)
    max_tool_calls: int = Field(default=48, ge=1, le=100)
    max_tokens: int = Field(default=120_000, ge=1_000, le=1_000_000)
    max_duration_seconds: int = Field(default=900, ge=10, le=14_400)


class MissionUsageV1(StrictModel):
    plan_versions: int = 0
    step_attempts: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    duration_ms: int = 0


class SuccessCriterionV1(StrictModel):
    criterion_id: str = Field(min_length=1, max_length=96)
    kind: Literal[
        "all_steps_validated",
        "minimum_sources",
        "artifact_kind_exists",
        "observation_field",
    ]
    description: str = Field(min_length=3, max_length=500)
    expected: int | str | bool = True


class MissionCreate(StrictModel):
    objective: str = Field(min_length=3, max_length=8_000)
    success_criteria: tuple[SuccessCriterionV1, ...] = Field(min_length=1, max_length=12)
    constraints: tuple[str, ...] = Field(default=(), max_length=24)
    budget: MissionBudgetV1 = Field(default_factory=MissionBudgetV1)
    permission_profile_ref: str = Field(default="read_only.v1", max_length=128)
    context_policy_ref: str = Field(default="mission_context.v1", max_length=128)
    created_by: str = Field(default="operator", min_length=1, max_length=128)
    idempotency_key: str = Field(default="", max_length=128)
    deadline: datetime | None = None

    @model_validator(mode="after")
    def require_verifiable_criterion(self) -> MissionCreate:
        if not any(
            item.kind != "observation_field" or item.expected is not None
            for item in self.success_criteria
        ):
            raise ValueError("at least one verifiable success criterion is required")
        if self.deadline is not None and self.deadline <= utc_now():
            raise ValueError("deadline must be in the future")
        return self


class PlanStepV2(StrictModel):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=3, max_length=240)
    depends_on: tuple[str, ...] = ()
    capability_id: str = Field(min_length=3, max_length=160)
    capability_version: str = Field(default="1", min_length=1, max_length=32)
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True
    requires_approval: bool = False


class PlanDiffV1(StrictModel):
    kept: tuple[str, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    replaced: dict[str, str] = Field(default_factory=dict)
    reason_code: str = Field(default="initial_plan", max_length=96)


class PlanV2(StrictModel):
    plan_id: str = Field(min_length=3, max_length=64)
    version: int = Field(ge=1, le=5)
    parent_version: int | None = Field(default=None, ge=1, le=5)
    goal_interpretation: str = Field(min_length=3, max_length=2_000)
    assumptions: tuple[str, ...] = ()
    completion_checks: tuple[str, ...] = Field(min_length=1)
    steps: tuple[PlanStepV2, ...] = Field(min_length=1, max_length=24)
    diff: PlanDiffV1 = Field(default_factory=PlanDiffV1)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_dag(self) -> PlanV2:
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step ids must be unique")
        known = set(ids)
        for step in self.steps:
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(f"step {step.step_id} has unknown dependencies: {sorted(unknown)}")
            if step.step_id in step.depends_on:
                raise ValueError(f"step {step.step_id} cannot depend on itself")
        visiting: set[str] = set()
        visited: set[str] = set()
        edges = {step.step_id: set(step.depends_on) for step in self.steps}

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan step graph must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in edges[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ids:
            visit(step_id)
        return self


class StepObservationV2(StrictModel):
    schema_version: Literal["step_observation.v2"] = "step_observation.v2"
    status: Literal["succeeded", "failed", "unknown", "waiting_approval"]
    summary: str = Field(min_length=1, max_length=4_000)
    result: dict[str, Any] = Field(default_factory=dict)
    source_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    error_category: Literal[
        "",
        "invalid_input",
        "permission_denied",
        "source_unavailable",
        "timeout",
        "rate_limited",
        "contract_mismatch",
        "partial_result",
        "unsafe_request",
        "unknown_failure",
    ] = ""
    retryable: bool = False
    usage: dict[str, int] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_provenance_for_success(self) -> StepObservationV2:
        if self.status == "succeeded" and not self.source_refs and not self.artifact_refs:
            raise ValueError("successful observation requires a source or artifact reference")
        if self.status == "failed" and not self.error_category:
            raise ValueError("failed observation requires an error category")
        return self


class StepAttemptV2(StrictModel):
    attempt_id: str
    step_id: str
    attempt: int = Field(ge=1, le=3)
    status: Literal["running", "succeeded", "failed", "unknown", "waiting_approval"]
    capability_id: str
    observation: StepObservationV2 | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class SteeringEventV1(StrictModel):
    instruction: str = Field(min_length=2, max_length=4_000)
    reason: str = Field(min_length=2, max_length=1_000)
    actor: str = Field(default="operator", min_length=1, max_length=128)


class MissionEventV1(StrictModel):
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=2, max_length=96)
    actor: str = Field(default="runtime", max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class MissionProjection(StrictModel):
    mission_id: str
    objective: str
    original_objective: str
    success_criteria: tuple[SuccessCriterionV1, ...]
    constraints: tuple[str, ...]
    status: MissionStatus
    budget: MissionBudgetV1
    usage: MissionUsageV1 = Field(default_factory=MissionUsageV1)
    permission_profile_ref: str
    context_policy_ref: str
    active_plan_version: int = 0
    current_step_id: str = ""
    version: int = 1
    control_requested: str = ""
    terminal_summary: str = ""
    unknowns: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    created_by: str
    idempotency_key: str = ""
    deadline: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ReplanRequestV1(StrictModel):
    trigger: Literal[
        "capability_unavailable",
        "observation_invalid",
        "assumption_invalidated",
        "user_steer",
        "budget_degraded",
        "dependency_failed",
    ]
    summary: str = Field(min_length=2, max_length=2_000)
    failed_step_id: str = ""
