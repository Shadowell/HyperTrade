from __future__ import annotations

import pytest
from hypertrade.runtime.domain.mission_events import (
    MissionSnapshotV2,
    apply_mission_event,
    make_mission_event,
)
from hypertrade.runtime.domain.models import (
    MissionBudgetV1,
    MissionProjection,
    MissionStatus,
    SuccessCriterionV1,
    utc_now,
)
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError


def _created() -> tuple[MissionSnapshotV2, object]:
    now = utc_now()
    projection = MissionProjection(
        mission_id="mis_domain",
        objective="Verify canonical Mission events",
        original_objective="Verify canonical Mission events",
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="validated",
                kind="all_steps_validated",
                description="Every step validates",
            ),
        ),
        constraints=(),
        status=MissionStatus.DRAFT,
        budget=MissionBudgetV1(),
        permission_profile_ref="read_only.v1",
        context_policy_ref="mission_context.v1",
        created_by="test",
        event_protocol_version=2,
        replay_status="canonical",
        created_at=now,
        updated_at=now,
    )
    event = make_mission_event(
        event_id="mevt_created",
        event_type="mission_created",
        mission_id=projection.mission_id,
        sequence=1,
        actor="test",
        causation_id="cmd_create",
        correlation_id="turn_domain",
        policy_snapshot_hash="a" * 64,
        payload={"projection": projection.model_dump(mode="json")},
    )
    return apply_mission_event(MissionSnapshotV2(), event), event


def test_mission_event_envelope_binds_payload_and_audit_context() -> None:
    _, event = _created()

    assert event.aggregate_type == "mission"
    assert event.aggregate_version == event.sequence == 1
    assert event.schema_version == 2
    assert event.reducer_version == 1
    assert event.causation_id == "cmd_create"
    assert event.correlation_id == "turn_domain"
    assert event.policy_snapshot_hash == "a" * 64
    with pytest.raises(ValidationError, match="payload hash mismatch"):
        event.model_copy(update={"payload": {"tampered": True}}).__class__.model_validate(
            event.model_dump(mode="python") | {"payload": {"tampered": True}}
        )


@given(st.lists(st.integers(min_value=0, max_value=20), min_size=0, max_size=30))
def test_legal_usage_event_sequences_never_produce_negative_budget_state(
    deltas: list[int],
) -> None:
    snapshot, _ = _created()
    for index, amount in enumerate(deltas, start=2):
        event = make_mission_event(
            event_id=f"mevt_usage_{index}",
            event_type="mission.usage_updated",
            mission_id="mis_domain",
            sequence=index,
            actor="runtime",
            payload={"delta": {"tokens": amount}},
        )
        snapshot = apply_mission_event(snapshot, event)

    assert snapshot.mission is not None
    assert snapshot.mission.usage.tokens == sum(deltas)
    assert snapshot.mission.usage.tokens >= 0
    assert snapshot.mission.event_cursor == len(deltas) + 1
    assert snapshot.mission.status == MissionStatus.DRAFT
