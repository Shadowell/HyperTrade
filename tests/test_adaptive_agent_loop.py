from __future__ import annotations

from collections import deque

import pytest
from hypertrade.runtime.adapters.foundation import ReadOnlyCapabilityPolicy
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.models import (
    MissionBudgetV1,
    MissionCreate,
    MissionProjection,
    MissionStatus,
    PlanDiffV1,
    PlanStepV2,
    PlanV2,
    ReplanRequestV1,
    StepObservationV2,
    SuccessCriterionV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class ScenarioPlanner:
    async def plan(self, mission: MissionProjection) -> PlanV2:
        return self._plan(1)

    async def replan(
        self,
        mission: MissionProjection,
        previous: PlanV2,
        request: ReplanRequestV1,
    ) -> PlanV2:
        return self._plan(
            previous.version + 1,
            parent=previous.version,
            reason=request.trigger,
        )

    @staticmethod
    def _plan(version: int, parent: int | None = None, reason: str = "initial_plan") -> PlanV2:
        return PlanV2(
            plan_id=f"scenario_plan_{version}",
            version=version,
            parent_version=parent,
            goal_interpretation="Run a bounded scenario",
            completion_checks=("validated",),
            steps=(
                PlanStepV2(
                    step_id="inspect",
                    title="Inspect scenario input",
                    capability_id="runtime.objective_inspection",
                ),
            ),
            diff=PlanDiffV1(kept=("inspect",) if parent else (), reason_code=reason),
        )


class ScenarioExecutor:
    def __init__(self, observations: list[StepObservationV2]) -> None:
        self.observations = deque(observations)
        self.calls = 0

    async def execute(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> StepObservationV2:
        self.calls += 1
        return self.observations.popleft()


def success() -> StepObservationV2:
    return StepObservationV2(
        status="succeeded",
        summary="validated",
        source_refs=("scenario:fixture",),
        result={"validated": True},
        usage={"tool_calls": 1},
    )


def failure(category: str, *, retryable: bool) -> StepObservationV2:
    return StepObservationV2(
        status="failed",
        summary=f"{category} failure",
        error_category=category,  # type: ignore[arg-type]
        retryable=retryable,
        source_refs=("scenario:fixture",),
        usage={"tool_calls": 1},
    )


def payload(*, budget: MissionBudgetV1 | None = None) -> MissionCreate:
    return MissionCreate(
        objective="Execute the adaptive loop scenario",
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="validated",
                kind="all_steps_validated",
                description="The scenario step must validate.",
            ),
        ),
        budget=budget or MissionBudgetV1(),
    )


@pytest.mark.anyio
async def test_temporary_timeout_retries_inside_same_plan() -> None:
    store = InMemoryMissionStore()
    executor = ScenarioExecutor([failure("timeout", retryable=True), success()])
    runtime = MissionRuntime(store, ScenarioPlanner(), executor, ReadOnlyCapabilityPolicy())
    mission = await runtime.create(payload())

    result = await runtime.run(mission.mission_id)

    assert result.status == MissionStatus.COMPLETED
    assert result.active_plan_version == 1
    assert executor.calls == 2


@pytest.mark.anyio
async def test_permanent_capability_failure_replans_once() -> None:
    store = InMemoryMissionStore()
    executor = ScenarioExecutor([failure("source_unavailable", retryable=False), success()])
    runtime = MissionRuntime(store, ScenarioPlanner(), executor, ReadOnlyCapabilityPolicy())
    mission = await runtime.create(payload())

    replanned = await runtime.run(mission.mission_id)
    assert replanned.status == MissionStatus.RUNNING
    assert replanned.active_plan_version == 2
    completed = await runtime.run(mission.mission_id)

    assert completed.status == MissionStatus.COMPLETED
    assert executor.calls == 2


@pytest.mark.anyio
async def test_non_retryable_unsafe_request_fails_closed() -> None:
    store = InMemoryMissionStore()
    executor = ScenarioExecutor([failure("unsafe_request", retryable=False)])
    runtime = MissionRuntime(store, ScenarioPlanner(), executor, ReadOnlyCapabilityPolicy())
    mission = await runtime.create(payload())

    result = await runtime.run(mission.mission_id)

    assert result.status == MissionStatus.FAILED
    assert executor.calls == 1


@pytest.mark.anyio
async def test_tool_budget_stops_before_extra_dispatch() -> None:
    store = InMemoryMissionStore()
    executor = ScenarioExecutor([failure("timeout", retryable=True), success()])
    runtime = MissionRuntime(store, ScenarioPlanner(), executor, ReadOnlyCapabilityPolicy())
    mission = await runtime.create(payload(budget=MissionBudgetV1(max_tool_calls=1)))

    result = await runtime.run(mission.mission_id)

    assert result.status == MissionStatus.BUDGET_EXHAUSTED
    assert executor.calls == 1


@pytest.mark.anyio
async def test_plan_version_budget_stops_replan_loop() -> None:
    store = InMemoryMissionStore()
    executor = ScenarioExecutor([failure("source_unavailable", retryable=False)])
    runtime = MissionRuntime(store, ScenarioPlanner(), executor, ReadOnlyCapabilityPolicy())
    mission = await runtime.create(payload(budget=MissionBudgetV1(max_plan_versions=1)))

    result = await runtime.run(mission.mission_id)

    assert result.status == MissionStatus.BUDGET_EXHAUSTED
    assert executor.calls == 1
