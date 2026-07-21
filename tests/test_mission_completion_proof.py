from __future__ import annotations

import pytest
from hypertrade.runtime.adapters.foundation import (
    FoundationExecutor,
    FoundationPlanner,
    ReadOnlyCapabilityPolicy,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.application.completion import MissionCompletionVerifier
from hypertrade.runtime.application.entrypoint import mission_request_for_prompt
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.mission_events import MissionCompletionRejected
from hypertrade.runtime.domain.models import (
    MissionCreate,
    MissionStatus,
    StepAttemptV2,
    StepObservationV2,
    SuccessCriterionV1,
)


@pytest.mark.anyio
async def test_runtime_requires_and_persists_passing_completion_proof() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = await runtime.create(
        mission_request_for_prompt(
            "研究 BTC 当前市场状态",
            actor="test",
            idempotency_key="completion-proof-pass",
        )
    )

    completed = await runtime.run(mission.mission_id)

    assert completed.status == MissionStatus.COMPLETED
    assert completed.completion_proof is not None
    assert completed.completion_proof.passed
    assert completed.completion_proof.mission_version + 1 == completed.version
    assert completed.completion_proof.evidence_refs
    event_types = [row.event_type for row in await store.events(mission.mission_id)]
    assert event_types.count("mission.completion_proof_recorded") == 1


@pytest.mark.anyio
async def test_provider_or_runtime_cannot_complete_without_current_proof() -> None:
    store = InMemoryMissionStore()
    planner = FoundationPlanner()
    runtime = MissionRuntime(
        store,
        planner,
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = await runtime.create(
        mission_request_for_prompt(
            "研究 ETH 当前市场状态",
            actor="test",
            idempotency_key="completion-proof-reject",
        )
    )
    mission = await store.transition(
        mission.mission_id,
        expected_version=mission.version,
        target=MissionStatus.PLANNING,
        actor="runtime",
        reason="test",
    )
    await store.save_plan(mission.mission_id, await planner.plan(mission))
    mission = await store.get(mission.mission_id)
    mission = await store.transition(
        mission.mission_id,
        expected_version=mission.version,
        target=MissionStatus.RUNNING,
        actor="runtime",
        reason="test",
    )

    with pytest.raises(MissionCompletionRejected):
        await store.transition(
            mission.mission_id,
            expected_version=mission.version,
            target=MissionStatus.COMPLETED,
            actor="provider",
            reason="model_said_done",
        )

    quarantined = await store.get(mission.mission_id)
    assert quarantined.replay_status == "quarantined"
    assert quarantined.status == MissionStatus.RUNNING


@pytest.mark.anyio
async def test_failed_completion_proof_persists_gaps_at_waiting_input() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = await runtime.create(
        MissionCreate(
            objective="Require a report artifact before completion",
            success_criteria=(
                SuccessCriterionV1(
                    criterion_id="report",
                    kind="artifact_kind_exists",
                    description="A report artifact is required",
                    expected="report",
                ),
            ),
            idempotency_key="completion-proof-failed",
        )
    )

    waiting = await runtime.run(mission.mission_id)

    assert waiting.status == MissionStatus.WAITING_INPUT
    assert waiting.completion_proof is not None
    assert not waiting.completion_proof.passed
    assert "artifact kind report missing" in waiting.completion_proof.gaps


@pytest.mark.anyio
async def test_completion_proof_lists_pending_unknown_and_evidence_gaps() -> None:
    store = InMemoryMissionStore()
    planner = FoundationPlanner()
    mission = await store.create(
        mission_request_for_prompt(
            "研究 SOL 当前市场状态",
            actor="test",
            idempotency_key="completion-proof-gaps",
        )
    )
    plan = await planner.plan(mission)
    pending = StepAttemptV2(
        attempt_id="sat_pending",
        plan_version=plan.version,
        step_id=plan.steps[0].step_id,
        attempt=1,
        status="running",
        capability_id=plan.steps[0].capability_id,
    )
    unknown = StepAttemptV2(
        attempt_id="sat_unknown",
        plan_version=plan.version,
        step_id=plan.steps[0].step_id,
        attempt=2,
        status="unknown",
        capability_id=plan.steps[0].capability_id,
        observation=StepObservationV2(
            status="unknown",
            summary="effect is unknown",
            error_category="unknown_failure",
        ),
    )

    proof = MissionCompletionVerifier().verify(
        mission,
        plan,
        (pending, unknown),
        context_valid=False,
    )

    assert not proof.passed
    assert proof.pending_attempt_ids == ("sat_pending",)
    assert proof.effect_unknown
    assert "unfinished tool/step attempts remain" in proof.gaps
    assert "one or more attempts have unknown effect/result state" in proof.gaps
    assert "no valid Evidence or Artifact binding exists" in proof.gaps
