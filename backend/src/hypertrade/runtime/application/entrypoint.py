"""Server-side adapters for routing a bounded chat request into a Mission.

This module intentionally produces an operator-facing projection from Mission
facts. It does not create AgentTask/AgentRun compatibility rows, call legacy
AgentKernel, or ask a model to write the final completion status.
"""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from typing import Any

from hypertrade.runtime.domain.models import (
    MissionCreate,
    MissionEventV1,
    MissionProjection,
    StepAttemptV2,
    SuccessCriterionV1,
)
from hypertrade.runtime.ports import MissionStore


def mission_request_for_prompt(
    prompt: str,
    *,
    actor: str,
    idempotency_key: str,
) -> MissionCreate:
    """Normalize an untrusted chat prompt into a read-only Mission contract."""

    normalized = prompt.strip()
    return MissionCreate(
        objective=normalized,
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="validated_steps",
                kind="all_steps_validated",
                description="Every approved read-only plan step has a validated observation.",
            ),
            SuccessCriterionV1(
                criterion_id="provenance",
                kind="minimum_sources",
                description="The research result must retain at least one source reference.",
                expected=1,
            ),
        ),
        constraints=(
            "Research-only read scope.",
            "No paper, live, order or capital mutation.",
            "Completion requires validated observations and provenance.",
        ),
        permission_profile_ref="read_only.v1",
        created_by=actor,
        idempotency_key=idempotency_key,
    )


async def mission_run_projection(
    mission: MissionProjection,
    store: MissionStore,
) -> dict[str, Any]:
    """Return the existing chat response shape from canonical Mission facts."""

    plans = await store.plans(mission.mission_id)
    attempts = await store.attempts(mission.mission_id)
    events = await store.events(mission.mission_id, after=0, limit=1_000)
    return {
        "id": mission.mission_id,
        "mission_id": mission.mission_id,
        "runtime": "mission_v2",
        "status": mission.status.value,
        "report_markdown": _report_markdown(mission, attempts),
        "report_json": {
            "runtime": "mission_v2",
            "mission": mission.model_dump(mode="json"),
            "plans": [plan.model_dump(mode="json") for plan in plans],
            "attempts": [_attempt_summary(attempt) for attempt in attempts],
            "event_cursor": events[-1].sequence if events else 0,
        },
        "run_state_json": {
            "runtime": "mission_v2",
            "mission_id": mission.mission_id,
            "status": mission.status.value,
            "current_step_id": mission.current_step_id,
            "active_plan_version": mission.active_plan_version,
            "event_cursor": events[-1].sequence if events else 0,
        },
        "trace_events": [_event_trace(event) for event in events],
        "legacy_run": False,
    }


def is_mission_canary(
    *,
    enabled: bool,
    percent: int,
    idempotency_key: str,
) -> bool:
    """Choose a stable canary cohort; no random retry can change runtime."""

    if not enabled or percent <= 0:
        return False
    if percent >= 100:
        return True
    digest = sha256(idempotency_key.encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100 < percent


def _attempt_summary(attempt: StepAttemptV2) -> dict[str, Any]:
    observation = attempt.observation
    return {
        "attempt_id": attempt.attempt_id,
        "step_id": attempt.step_id,
        "attempt": attempt.attempt,
        "status": attempt.status,
        "capability_id": attempt.capability_id,
        "summary": observation.summary if observation else "",
        "source_refs": list(observation.source_refs) if observation else [],
        "artifact_refs": list(observation.artifact_refs) if observation else [],
        "unknowns": list(observation.unknowns) if observation else [],
        "error_category": observation.error_category if observation else "",
    }


def _event_trace(event: MissionEventV1) -> dict[str, Any]:
    payload = event.payload
    status = str(payload.get("status", "ok"))
    return {
        "id": f"{event.sequence}:{event.event_type}",
        "tool_name": event.event_type,
        "status": status,
        "input_json": {},
        "output_json": payload,
        "created_at": event.created_at.isoformat(),
    }


def _report_markdown(mission: MissionProjection, attempts: Sequence[StepAttemptV2]) -> str:
    lines = [
        "# Mission Research Result",
        "",
        f"- Mission: `{mission.mission_id}`",
        f"- Status: **{mission.status.value}**",
        f"- Plan version: {mission.active_plan_version}",
        f"- Tool calls: {mission.usage.tool_calls}",
        "",
        "## Validated observations",
    ]
    for attempt in attempts:
        observation = attempt.observation
        if observation is None:
            continue
        source_count = len(observation.source_refs) + len(observation.artifact_refs)
        lines.append(
            f"- `{attempt.step_id}` — {observation.status}; "
            f"sources: {source_count}; {observation.summary}"
        )
    if mission.unknowns:
        lines.extend(("", "## Explicit unknowns"))
        lines.extend(f"- {item}" for item in mission.unknowns)
    if mission.terminal_summary:
        lines.extend(("", "## Runtime conclusion", mission.terminal_summary))
    return "\n".join(lines)
