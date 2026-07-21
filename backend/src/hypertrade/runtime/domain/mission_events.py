"""Canonical append-only Mission events and deterministic projection reducer."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, model_validator

from hypertrade.runtime.domain.models import (
    CompletionProofV1,
    MissionEventV1,
    MissionProjection,
    MissionReplayStatus,
    MissionStatus,
    MissionUsageV1,
    PlanV2,
    StepAttemptV2,
    StepObservationV2,
    StrictModel,
)
from hypertrade.runtime.domain.state_machine import require_transition

MISSION_SCHEMA_VERSION = 2
MISSION_REDUCER_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


def mission_content_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return sha256(encoded).hexdigest()


class MissionEventV2(StrictModel):
    event_id: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=3, max_length=96)
    aggregate_type: Literal["mission"] = "mission"
    aggregate_id: str = Field(min_length=1, max_length=64)
    aggregate_version: int = Field(ge=1)
    sequence: int = Field(ge=1)
    schema_version: int = MISSION_SCHEMA_VERSION
    reducer_version: int = MISSION_REDUCER_VERSION
    causation_id: str = Field(default="", max_length=64)
    correlation_id: str = Field(default="", max_length=64)
    actor: str = Field(default="runtime", min_length=1, max_length=128)
    policy_snapshot_hash: str = Field(default="", max_length=64)
    payload_hash: str = Field(min_length=64, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    fencing_token: int = Field(default=0, ge=0)
    occurred_at: datetime = Field(default_factory=utc_now)
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_envelope(self) -> MissionEventV2:
        if self.aggregate_version != self.sequence:
            raise ValueError("mission aggregate version must equal event sequence")
        if self.schema_version != MISSION_SCHEMA_VERSION:
            raise ValueError("unsupported mission event schema version")
        if self.reducer_version != MISSION_REDUCER_VERSION:
            raise ValueError("unsupported mission reducer version")
        if mission_content_hash(self.payload) != self.payload_hash:
            raise ValueError("mission event payload hash mismatch")
        return self


class MissionSnapshotV2(StrictModel):
    mission: MissionProjection | None = None
    plans: tuple[PlanV2, ...] = ()
    attempts: tuple[StepAttemptV2, ...] = ()
    replay_status: MissionReplayStatus = MissionReplayStatus.CANONICAL
    quarantine_reason: str = ""


class MissionProtocolError(ValueError):
    """A Mission event violates the canonical state or envelope contract."""


class MissionVersionGap(MissionProtocolError):
    pass


class MissionStaleFencingToken(MissionProtocolError):
    pass


class MissionCompletionRejected(MissionProtocolError):
    pass


def make_mission_event(
    *,
    event_id: str,
    event_type: str,
    mission_id: str,
    sequence: int,
    payload: dict[str, Any],
    actor: str,
    causation_id: str = "",
    correlation_id: str = "",
    policy_snapshot_hash: str = "",
    fencing_token: int = 0,
    occurred_at: datetime | None = None,
) -> MissionEventV2:
    happened = occurred_at or utc_now()
    return MissionEventV2(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=mission_id,
        aggregate_version=sequence,
        sequence=sequence,
        causation_id=causation_id,
        correlation_id=correlation_id or mission_id,
        actor=actor,
        policy_snapshot_hash=policy_snapshot_hash,
        payload_hash=mission_content_hash(payload),
        payload=payload,
        fencing_token=fencing_token,
        occurred_at=happened,
        recorded_at=happened,
    )


def mission_projection_hash(snapshot: MissionSnapshotV2) -> str:
    return mission_content_hash(snapshot.model_dump(mode="json"))


def reduce_mission_events(
    events: Iterable[MissionEventV2 | MissionEventV1 | dict[str, Any]],
) -> MissionSnapshotV2:
    snapshot = MissionSnapshotV2()
    seen: dict[int, tuple[str, str]] = {}
    for raw in events:
        if isinstance(raw, MissionEventV1):
            return MissionSnapshotV2(
                replay_status=MissionReplayStatus.LEGACY_NON_REPLAYABLE,
                quarantine_reason="legacy Mission events do not contain rebuildable payloads",
            )
        try:
            event = raw if isinstance(raw, MissionEventV2) else MissionEventV2.model_validate(raw)
        except (TypeError, ValueError) as exc:
            return _quarantined(snapshot, f"invalid event envelope: {exc}")
        previous = seen.get(event.aggregate_version)
        signature = (event.event_type, event.payload_hash)
        if previous is not None:
            if previous == signature:
                continue
            return _quarantined(snapshot, "conflicting duplicate aggregate version")
        seen[event.aggregate_version] = signature
        try:
            snapshot = apply_mission_event(snapshot, event)
        except MissionProtocolError as exc:
            return _quarantined(snapshot, str(exc))
    return snapshot


def apply_mission_event(
    snapshot: MissionSnapshotV2,
    event: MissionEventV2,
) -> MissionSnapshotV2:
    mission = snapshot.mission
    expected = 1 if mission is None else mission.event_cursor + 1
    if event.aggregate_version != expected:
        raise MissionVersionGap(
            f"mission event version gap: expected {expected}, got {event.aggregate_version}"
        )
    if mission is not None and event.aggregate_id != mission.mission_id:
        raise MissionProtocolError("event aggregate does not match mission")
    if snapshot.replay_status == MissionReplayStatus.QUARANTINED:
        raise MissionProtocolError("quarantined Mission is read-only")
    if (
        mission is not None
        and event.fencing_token
        and event.fencing_token < mission.fencing_token
    ):
        raise MissionStaleFencingToken("stale Mission worker fencing token")

    normalized_type = {
        "mission_created": "mission.created",
        "mission_transitioned": "mission.transitioned",
        "plan_activated": "plan.activated",
        "step_started": "attempt.started",
        "step_observed": "attempt.completed",
        "mission_steered": "mission.steered",
        "mission_lease_claimed": "mission.lease_claimed",
        "mission_lease_heartbeat": "mission.lease_heartbeat",
        "mission_lease_released": "mission.lease_released",
        "mission_worker_failed": "mission.worker_failed",
    }.get(event.event_type, event.event_type)

    if normalized_type == "mission.created":
        if mission is not None:
            raise MissionProtocolError("Mission already exists")
        mission = MissionProjection.model_validate(event.payload["projection"]).model_copy(
            update={
                "event_cursor": event.sequence,
                "event_protocol_version": MISSION_SCHEMA_VERSION,
                "replay_status": MissionReplayStatus.CANONICAL,
                "updated_at": event.occurred_at,
            }
        )
        if mission.mission_id != event.aggregate_id:
            raise MissionProtocolError("created Mission id does not match aggregate")
        return MissionSnapshotV2(mission=mission)
    if mission is None:
        raise MissionProtocolError("first Mission event must be mission.created")

    plans = {row.version: row for row in snapshot.plans}
    attempts = {row.attempt_id: row for row in snapshot.attempts}
    event_type = normalized_type
    payload = event.payload
    state_updates: dict[str, Any] = {}
    state_changed = False

    if event_type == "mission.transitioned":
        current = MissionStatus(str(payload["from"]))
        target = MissionStatus(str(payload["to"]))
        if mission.status != current:
            raise MissionProtocolError("Mission transition source does not match projection")
        require_transition(current, target)
        if target == MissionStatus.COMPLETED:
            proof = mission.completion_proof
            if proof is None or not proof.passed or proof.mission_version != mission.version:
                raise MissionCompletionRejected(
                    "Mission completion requires a current passing CompletionProofV1"
                )
        state_updates.update(
            status=target,
            current_step_id=str(payload.get("current_step_id", mission.current_step_id)),
            terminal_summary=str(payload.get("terminal_summary", mission.terminal_summary)),
            control_requested=str(payload.get("control_requested", mission.control_requested)),
        )
        state_changed = True
    elif event_type == "mission.usage_updated":
        usage_values = mission.usage.model_dump()
        delta = dict(payload.get("delta") or {})
        for key, amount in delta.items():
            if key not in usage_values or not isinstance(amount, int) or amount < 0:
                raise MissionProtocolError(f"invalid usage delta: {key}")
            usage_values[key] += amount
        state_updates["usage"] = MissionUsageV1.model_validate(usage_values)
        state_changed = True
    elif event_type == "mission.current_step_set":
        state_updates["current_step_id"] = str(payload["step_id"])
        state_changed = True
    elif event_type == "plan.activated":
        plan = PlanV2.model_validate(payload["plan"])
        if plan.version != mission.active_plan_version + 1:
            raise MissionProtocolError("plan versions must be contiguous and append-only")
        if plan.version > mission.budget.max_plan_versions:
            raise MissionProtocolError("plan version budget exceeded")
        if len(plan.steps) > mission.budget.max_steps_per_plan:
            raise MissionProtocolError("plan step budget exceeded")
        plans[plan.version] = plan
        state_updates.update(
            active_plan_version=plan.version,
            usage=mission.usage.model_copy(update={"plan_versions": plan.version}),
        )
        state_changed = True
    elif event_type == "attempt.started":
        attempt = StepAttemptV2.model_validate(payload["attempt"])
        if attempt.attempt_id in attempts:
            raise MissionProtocolError("attempt already exists")
        attempts[attempt.attempt_id] = attempt
    elif event_type == "attempt.completed":
        attempt_id = str(payload["attempt_id"])
        try:
            attempt = attempts[attempt_id]
        except KeyError as exc:
            raise MissionProtocolError("unknown attempt") from exc
        if attempt.status != "running":
            raise MissionProtocolError("attempt is already terminal")
        observation = StepObservationV2.model_validate(payload["observation"])
        attempts[attempt_id] = attempt.model_copy(
            update={
                "status": observation.status,
                "observation": observation,
                "completed_at": event.occurred_at,
            }
        )
    elif event_type == "mission.steered":
        state_updates["objective"] = str(payload["objective"])
        state_changed = True
    elif event_type == "mission.completion_proof_recorded":
        proof = CompletionProofV1.model_validate(payload["proof"])
        if proof.mission_id != mission.mission_id or proof.mission_version != mission.version:
            raise MissionProtocolError("CompletionProofV1 is not bound to current Mission version")
        state_updates["completion_proof"] = proof
    elif event_type == "mission.lease_claimed":
        if event.fencing_token <= mission.fencing_token:
            raise MissionStaleFencingToken("Mission lease claim did not advance fencing token")
        state_updates["fencing_token"] = event.fencing_token
    elif event_type in {
        "mission.lease_heartbeat",
        "mission.lease_released",
        "context.compiled",
        "mission.worker_failed",
        "team.completed",
    }:
        pass
    else:
        raise MissionProtocolError(f"unknown Mission event type: {event_type}")

    if state_changed:
        state_updates["version"] = mission.version + 1
        if (
            mission.completion_proof is not None
            and event_type != "mission.completion_proof_recorded"
            and not (
                event_type == "mission.transitioned"
                and (
                    state_updates.get("status") == MissionStatus.COMPLETED
                    or (
                        state_updates.get("status") == MissionStatus.WAITING_INPUT
                        and payload.get("reason") == "completion_evidence_missing"
                    )
                )
            )
        ):
            state_updates["completion_proof"] = None
    state_updates.update(
        event_cursor=event.sequence,
        event_protocol_version=MISSION_SCHEMA_VERSION,
        replay_status=MissionReplayStatus.CANONICAL,
        quarantine_reason="",
        updated_at=event.occurred_at,
    )
    mission = mission.model_copy(update=state_updates)
    return MissionSnapshotV2(
        mission=mission,
        plans=tuple(plans[key] for key in sorted(plans)),
        attempts=tuple(
            sorted(attempts.values(), key=lambda row: (row.started_at, row.attempt_id))
        ),
    )


def _quarantined(snapshot: MissionSnapshotV2, reason: str) -> MissionSnapshotV2:
    mission = snapshot.mission
    if mission is not None:
        mission = mission.model_copy(
            update={
                "replay_status": MissionReplayStatus.QUARANTINED,
                "quarantine_reason": reason[:1_000],
            }
        )
    return snapshot.model_copy(
        update={
            "mission": mission,
            "replay_status": MissionReplayStatus.QUARANTINED,
            "quarantine_reason": reason[:1_000],
        }
    )
