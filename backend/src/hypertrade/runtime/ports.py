from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from hypertrade.runtime.domain.context import ContextPackV1
from hypertrade.runtime.domain.models import (
    MissionCreate,
    MissionEventV1,
    MissionProjection,
    MissionStatus,
    PlanStepV2,
    PlanV2,
    ReplanRequestV1,
    SteeringEventV1,
    StepAttemptV2,
    StepObservationV2,
)


class MissionStore(Protocol):
    async def create(self, payload: MissionCreate) -> MissionProjection: ...

    async def get(self, mission_id: str) -> MissionProjection: ...

    async def list(self, *, limit: int = 50) -> Sequence[MissionProjection]: ...

    async def transition(
        self,
        mission_id: str,
        *,
        expected_version: int,
        target: MissionStatus,
        actor: str,
        reason: str,
        current_step_id: str | None = None,
        terminal_summary: str | None = None,
        control_requested: str | None = None,
    ) -> MissionProjection: ...

    async def update_usage(
        self, mission_id: str, *, expected_version: int, delta: dict[str, int]
    ) -> MissionProjection: ...

    async def set_current_step(
        self, mission_id: str, *, expected_version: int, step_id: str
    ) -> MissionProjection: ...

    async def save_plan(self, mission_id: str, plan: PlanV2) -> None: ...

    async def plans(self, mission_id: str) -> Sequence[PlanV2]: ...

    async def start_attempt(
        self, mission_id: str, plan_version: int, step: PlanStepV2, attempt: int
    ) -> StepAttemptV2: ...

    async def complete_attempt(
        self, attempt_id: str, observation: StepObservationV2
    ) -> StepAttemptV2: ...

    async def attempts(self, mission_id: str) -> Sequence[StepAttemptV2]: ...

    async def append_event(
        self, mission_id: str, event_type: str, *, actor: str, payload: dict[str, object]
    ) -> MissionEventV1: ...

    async def events(
        self, mission_id: str, *, after: int = 0, limit: int = 500
    ) -> Sequence[MissionEventV1]: ...

    async def append_steer(self, mission_id: str, steer: SteeringEventV1) -> None: ...


class MissionPlanner(Protocol):
    async def plan(self, mission: MissionProjection) -> PlanV2: ...

    async def replan(
        self,
        mission: MissionProjection,
        previous: PlanV2,
        request: ReplanRequestV1,
    ) -> PlanV2: ...


class StepExecutor(Protocol):
    async def execute(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> StepObservationV2: ...


class CapabilityPolicy(Protocol):
    def validate_step(self, step: PlanStepV2, permission_profile_ref: str) -> None: ...


class MissionContextEngine(Protocol):
    async def prepare(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
        prior_attempts: Sequence[StepAttemptV2],
    ) -> ContextPackV1: ...

    async def validate_completion(
        self,
        mission: MissionProjection,
        observations: Sequence[StepObservationV2],
    ) -> bool: ...
