from __future__ import annotations

from opentelemetry import trace

from hypertrade.runtime.application.completion import MissionCompletionVerifier
from hypertrade.runtime.application.evaluation_fixtures import failure_from_constraints
from hypertrade.runtime.application.safety_intent import classify_objective_safety
from hypertrade.runtime.domain.context import ContextBudgetExceeded
from hypertrade.runtime.domain.models import (
    TERMINAL_STATUSES,
    MissionCreate,
    MissionProjection,
    MissionStatus,
    PlanV2,
    ReplanRequestV1,
    SteeringEventV1,
    StepAttemptV2,
)
from hypertrade.runtime.ports import (
    CapabilityPolicy,
    MissionContextEngine,
    MissionPlanner,
    MissionStore,
    StepExecutor,
)

_TRACER = trace.get_tracer("hypertrade.runtime")


class MissionRuntime:
    """Adaptive, bounded Mission loop over strict ports.

    Completion is derived from validated observations, never from model prose.
    Every loop edge checks control and budget before another dispatch.
    """

    def __init__(
        self,
        store: MissionStore,
        planner: MissionPlanner,
        executor: StepExecutor,
        policy: CapabilityPolicy,
        context_engine: MissionContextEngine | None = None,
        completion_verifier: MissionCompletionVerifier | None = None,
    ) -> None:
        self.store = store
        self.planner = planner
        self.executor = executor
        self.policy = policy
        self.context_engine = context_engine
        self.completion_verifier = completion_verifier or MissionCompletionVerifier()

    async def create(self, payload: MissionCreate) -> MissionProjection:
        return await self.store.create(payload)

    async def run(self, mission_id: str, *, fencing_token: int = 0) -> MissionProjection:
        with _TRACER.start_as_current_span("mission.run") as span:
            span.set_attribute("mission.id", mission_id)
            mission = await self.store.get(mission_id)
            if mission.status in TERMINAL_STATUSES:
                return mission
            mission = await self._apply_safe_point(mission, fencing_token=fencing_token)
            if mission.status in {MissionStatus.PAUSED, MissionStatus.CANCELED}:
                return mission
            if mission.status == MissionStatus.DRAFT:
                safety = classify_objective_safety(mission.objective)
                if safety.disposition == "blocked":
                    return await self.store.transition(
                        mission_id,
                        expected_version=mission.version,
                        target=MissionStatus.CANCELED,
                        actor="mission_safety",
                        reason=safety.reason,
                        terminal_summary="A governed safety boundary blocked this request.",
                        fencing_token=fencing_token,
                    )
                if safety.disposition == "needs_review":
                    return await self.store.transition(
                        mission_id,
                        expected_version=mission.version,
                        target=MissionStatus.WAITING_APPROVAL,
                        actor="mission_safety",
                        reason=safety.reason,
                        fencing_token=fencing_token,
                    )
                if safety.disposition == "needs_data":
                    return await self.store.transition(
                        mission_id,
                        expected_version=mission.version,
                        target=MissionStatus.WAITING_INPUT,
                        actor="mission_safety",
                        reason=safety.reason,
                        fencing_token=fencing_token,
                    )
                if failure := failure_from_constraints(mission.constraints):
                    return await self.store.transition(
                        mission_id,
                        expected_version=mission.version,
                        target=MissionStatus.FAILED,
                        actor="operator_eval",
                        reason=f"evaluation_fixture_{failure}",
                        terminal_summary=(
                            "An isolated evaluation fixture withheld required evidence."
                        ),
                        fencing_token=fencing_token,
                    )
            if mission.status == MissionStatus.DRAFT:
                mission = await self.store.transition(
                    mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.PLANNING,
                    actor="runtime",
                    reason="initial_plan_requested",
                    fencing_token=fencing_token,
                )
                plan = await self.planner.plan(mission)
                self._validate_plan(mission, plan)
                await self.store.save_plan(mission_id, plan, fencing_token=fencing_token)
                mission = await self.store.get(mission_id)
                mission = await self.store.transition(
                    mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.RUNNING,
                    actor="runtime",
                    reason="plan_validated",
                    fencing_token=fencing_token,
                )
            elif mission.status == MissionStatus.PAUSED or mission.status not in {
                MissionStatus.RUNNING,
                MissionStatus.RETRY_WAIT,
            }:
                return mission
            if mission.status == MissionStatus.RETRY_WAIT:
                mission = await self.store.transition(
                    mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.RUNNING,
                    actor="runtime",
                    reason="retry_window_opened",
                    fencing_token=fencing_token,
                )
            return await self._execute(mission, fencing_token=fencing_token)

    async def _execute(
        self, mission: MissionProjection, *, fencing_token: int = 0
    ) -> MissionProjection:
        while mission.status == MissionStatus.RUNNING:
            mission = await self._apply_safe_point(mission, fencing_token=fencing_token)
            if mission.status != MissionStatus.RUNNING:
                return mission
            if self._budget_exhausted(mission):
                return await self.store.transition(
                    mission.mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.BUDGET_EXHAUSTED,
                    actor="runtime",
                    reason="mission_budget_exhausted",
                    terminal_summary="Mission stopped at a hard runtime budget.",
                    fencing_token=fencing_token,
                )
            plans = await self.store.plans(mission.mission_id)
            plan = plans[-1]
            attempts = await self.store.attempts(mission.mission_id)
            completed = {
                row.step_id
                for row in attempts
                if row.status == "succeeded" and self._attempt_plan_version(row, plan)
            }
            if len(completed) == len(plan.steps):
                observations = [
                    row.observation
                    for row in attempts
                    if row.status == "succeeded" and row.observation is not None
                ]
                context_valid = (
                    self.context_engine is None
                    or await self.context_engine.validate_completion(mission, observations)
                )
                proof = self.completion_verifier.verify(
                    mission,
                    plan,
                    attempts,
                    context_valid=context_valid,
                )
                mission = await self.store.record_completion_proof(
                    mission.mission_id,
                    proof,
                    fencing_token=fencing_token,
                )
                if proof.passed:
                    return await self.store.transition(
                        mission.mission_id,
                        expected_version=mission.version,
                        target=MissionStatus.COMPLETED,
                        actor="runtime",
                        reason="validated_completion_criteria",
                        current_step_id="",
                        terminal_summary="All structured completion criteria passed.",
                        fencing_token=fencing_token,
                    )
                return await self.store.transition(
                    mission.mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.WAITING_INPUT,
                    actor="runtime",
                    reason="completion_evidence_missing",
                    current_step_id="",
                    fencing_token=fencing_token,
                )
            ready = next(
                (
                    step
                    for step in plan.steps
                    if step.step_id not in completed and set(step.depends_on).issubset(completed)
                ),
                None,
            )
            if ready is None:
                return await self.store.transition(
                    mission.mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.FAILED,
                    actor="runtime",
                    reason="no_executable_step",
                    terminal_summary="Plan has no executable completion path.",
                    fencing_token=fencing_token,
                )
            count = sum(1 for row in attempts if row.step_id == ready.step_id) + 1
            if count > mission.budget.max_attempts_per_step:
                return await self._request_replan(
                    mission,
                    plan,
                    ReplanRequestV1(
                        trigger="dependency_failed",
                        summary="Step attempt budget exhausted.",
                        failed_step_id=ready.step_id,
                    ),
                    fencing_token=fencing_token,
                )
            self.policy.validate_step(ready, mission.permission_profile_ref)
            mission = await self.store.set_current_step(
                mission.mission_id,
                expected_version=mission.version,
                step_id=ready.step_id,
                fencing_token=fencing_token,
            )
            if self.context_engine is not None:
                try:
                    context_pack = await self.context_engine.prepare(
                        mission,
                        plan,
                        ready,
                        count,
                        attempts,
                    )
                except ContextBudgetExceeded:
                    return await self.store.transition(
                        mission.mission_id,
                        expected_version=mission.version,
                        target=MissionStatus.BUDGET_EXHAUSTED,
                        actor="runtime",
                        reason="context_budget_exhausted",
                        terminal_summary="Required context exceeded the hard context budget.",
                        fencing_token=fencing_token,
                    )
                await self.store.append_event(
                    mission.mission_id,
                    "context.compiled",
                    actor="runtime",
                    payload={
                        "context_pack_id": context_pack.context_pack_id,
                        "manifest_hash": context_pack.manifest_hash,
                        "used_tokens": context_pack.ledger.used_tokens,
                        "budget_tokens": context_pack.ledger.budget_tokens,
                    },
                    fencing_token=fencing_token,
                )
            attempt = await self.store.start_attempt(
                mission.mission_id,
                plan.version,
                ready,
                count,
                fencing_token=fencing_token,
            )
            with _TRACER.start_as_current_span("mission.step") as span:
                span.set_attribute("mission.id", mission.mission_id)
                span.set_attribute("plan.version", plan.version)
                span.set_attribute("step.id", ready.step_id)
                span.set_attribute("capability.id", ready.capability_id)
                observation = await self.executor.execute(mission, plan, ready, count)
            await self.store.complete_attempt(
                attempt.attempt_id,
                observation,
                fencing_token=fencing_token,
            )
            mission = await self.store.get(mission.mission_id)
            mission = await self.store.update_usage(
                mission.mission_id,
                expected_version=mission.version,
                delta={
                    "step_attempts": 1,
                    "tool_calls": int(observation.usage.get("tool_calls", 0)),
                    "model_calls": int(observation.usage.get("model_calls", 0)),
                    "tokens": int(observation.usage.get("tokens", 0)),
                    "duration_ms": int(observation.usage.get("duration_ms", 0)),
                },
                fencing_token=fencing_token,
            )
            if observation.status == "succeeded":
                continue
            if observation.status == "waiting_approval":
                return await self.store.transition(
                    mission.mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.WAITING_APPROVAL,
                    actor="runtime",
                    reason="capability_requires_approval",
                    fencing_token=fencing_token,
                )
            if observation.retryable and count < mission.budget.max_attempts_per_step:
                mission = await self.store.transition(
                    mission.mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.RETRY_WAIT,
                    actor="runtime",
                    reason=observation.error_category or "retryable_failure",
                    fencing_token=fencing_token,
                )
                mission = await self.store.transition(
                    mission.mission_id,
                    expected_version=mission.version,
                    target=MissionStatus.RUNNING,
                    actor="runtime",
                    reason="bounded_retry",
                    fencing_token=fencing_token,
                )
                continue
            if observation.error_category in {"source_unavailable", "contract_mismatch"}:
                return await self._request_replan(
                    mission,
                    plan,
                    ReplanRequestV1(
                        trigger="capability_unavailable",
                        summary=observation.summary,
                        failed_step_id=ready.step_id,
                    ),
                    fencing_token=fencing_token,
                )
            return await self.store.transition(
                mission.mission_id,
                expected_version=mission.version,
                target=MissionStatus.FAILED,
                actor="runtime",
                reason=observation.error_category or "step_failed",
                terminal_summary=observation.summary,
                fencing_token=fencing_token,
            )
        return mission

    async def pause(self, mission_id: str, *, actor: str = "operator") -> MissionProjection:
        mission = await self.store.get(mission_id)
        return await self.store.transition(
            mission_id,
            expected_version=mission.version,
            target=MissionStatus.PAUSE_REQUESTED,
            actor=actor,
            reason="operator_pause",
            control_requested="pause",
        )

    async def cancel(self, mission_id: str, *, actor: str = "operator") -> MissionProjection:
        mission = await self.store.get(mission_id)
        target = (
            MissionStatus.CANCELED
            if mission.status == MissionStatus.DRAFT
            else MissionStatus.CANCEL_REQUESTED
        )
        return await self.store.transition(
            mission_id,
            expected_version=mission.version,
            target=target,
            actor=actor,
            reason="operator_cancel",
            control_requested="cancel",
        )

    async def resume(self, mission_id: str, *, actor: str = "operator") -> MissionProjection:
        mission = await self.store.get(mission_id)
        return await self.store.transition(
            mission_id,
            expected_version=mission.version,
            target=MissionStatus.RUNNING,
            actor=actor,
            reason="operator_resume",
            control_requested="",
        )

    async def steer(self, mission_id: str, steer: SteeringEventV1) -> MissionProjection:
        mission = await self.store.get(mission_id)
        await self.store.append_steer(mission_id, steer)
        mission = await self.store.get(mission_id)
        if mission.status == MissionStatus.RUNNING:
            mission = await self.store.transition(
                mission_id,
                expected_version=mission.version,
                target=MissionStatus.REPLANNING,
                actor=steer.actor,
                reason="user_steer",
            )
            plans = await self.store.plans(mission_id)
            return await self._activate_replan(
                mission,
                plans[-1],
                ReplanRequestV1(trigger="user_steer", summary=steer.instruction),
            )
        return mission

    async def _apply_safe_point(
        self, mission: MissionProjection, *, fencing_token: int = 0
    ) -> MissionProjection:
        if mission.status == MissionStatus.PAUSE_REQUESTED:
            return await self.store.transition(
                mission.mission_id,
                expected_version=mission.version,
                target=MissionStatus.PAUSED,
                actor="runtime",
                reason="safe_point_pause",
                fencing_token=fencing_token,
            )
        if mission.status == MissionStatus.CANCEL_REQUESTED:
            return await self.store.transition(
                mission.mission_id,
                expected_version=mission.version,
                target=MissionStatus.CANCELED,
                actor="runtime",
                reason="safe_point_cancel",
                fencing_token=fencing_token,
            )
        return mission

    async def _request_replan(
        self,
        mission: MissionProjection,
        previous: PlanV2,
        request: ReplanRequestV1,
        *,
        fencing_token: int = 0,
    ) -> MissionProjection:
        if mission.active_plan_version >= mission.budget.max_plan_versions:
            return await self.store.transition(
                mission.mission_id,
                expected_version=mission.version,
                target=MissionStatus.BUDGET_EXHAUSTED,
                actor="runtime",
                reason="plan_version_budget_exhausted",
                fencing_token=fencing_token,
            )
        mission = await self.store.transition(
            mission.mission_id,
            expected_version=mission.version,
            target=MissionStatus.REPLANNING,
            actor="runtime",
            reason=request.trigger,
            fencing_token=fencing_token,
        )
        return await self._activate_replan(
            mission,
            previous,
            request,
            fencing_token=fencing_token,
        )

    async def _activate_replan(
        self,
        mission: MissionProjection,
        previous: PlanV2,
        request: ReplanRequestV1,
        *,
        fencing_token: int = 0,
    ) -> MissionProjection:
        plan = await self.planner.replan(mission, previous, request)
        self._validate_plan(mission, plan)
        await self.store.save_plan(
            mission.mission_id,
            plan,
            fencing_token=fencing_token,
        )
        mission = await self.store.get(mission.mission_id)
        return await self.store.transition(
            mission.mission_id,
            expected_version=mission.version,
            target=MissionStatus.RUNNING,
            actor="runtime",
            reason="replan_validated",
            fencing_token=fencing_token,
        )

    def _validate_plan(self, mission: MissionProjection, plan: PlanV2) -> None:
        if len(plan.steps) > mission.budget.max_steps_per_plan:
            raise ValueError("plan exceeds approved step budget")
        if plan.version > mission.budget.max_plan_versions:
            raise ValueError("plan exceeds approved version budget")
        for step in plan.steps:
            self.policy.validate_step(step, mission.permission_profile_ref)

    @staticmethod
    def _attempt_plan_version(
        attempt: StepAttemptV2,
        plan: PlanV2,
    ) -> bool:
        # Attempts from superseded plans share step ids only when the replanner
        # explicitly keeps them. Plan diffs define that reuse contract.
        return attempt.plan_version == plan.version or (
            attempt.plan_version < plan.version and attempt.step_id in plan.diff.kept
        )

    @staticmethod
    def _budget_exhausted(mission: MissionProjection) -> bool:
        return (
            mission.usage.tool_calls >= mission.budget.max_tool_calls
            or mission.usage.tokens >= mission.budget.max_tokens
        )
