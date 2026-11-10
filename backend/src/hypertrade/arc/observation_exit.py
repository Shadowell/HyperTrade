"""Close an observing mission once what it observes has ended.

A reviewed candidate races its parent in BitPro, and BitPro alone decides how that race ends.
HyperTrade's race judge records every finished lane in the forward outcome ledger, keyed by
(target, parent strategy, challenger strategy). This module reads that row, and when there is
none the Paper session state BitPro last reported, and closes the mission with one reducer
event. It never writes to BitPro and never decides a verdict of its own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.controller import ARCController, ARCMissionProjection
from hypertrade.arc.evolution_models import ArcForwardOutcome
from hypertrade.arc.forward_outcomes import ForwardOutcomeLedger, outcome_id
from hypertrade.arc.store import get_configured_database
from hypertrade.db import Database

# A session BitPro reports over is only a fallback signal. The race judge records a finished
# lane within minutes and that row carries the verdict, so wait before closing without one.
SESSION_ENDED_GRACE = timedelta(hours=1)
_FINAL_OBSERVATION_KEYS = (
    "observed_at",
    "ok",
    "status",
    "trades",
    "equity",
    "net_return",
    "max_drawdown",
    "sharpe",
    "error_count",
    "bitpro_health",
)


def parse_moment(value: Any) -> datetime | None:
    """An ISO timestamp as an aware UTC time; anything unreadable is unknown, not now."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def lane_key(
    projection: ARCMissionProjection, attempt: ARCCandidateAttemptV1
) -> tuple[str, str, str] | None:
    """(target, parent, challenger) of the lane this mission's candidate races in, if it races.

    Only a mission the evolution loop created names a parent. Any other observed strategy is
    nobody's challenger, however many races it appears in as a parent.
    """
    goal = projection.goal
    context = (goal.evolution_context if goal is not None else None) or {}
    target, parent = context.get("target_id"), context.get("source_strategy_id")
    challenger = attempt.bitpro_strategy_id
    if not target or parent is None or not challenger:
        return None
    return str(target), str(parent), str(challenger)


def finished_lane(
    db: Database, key: tuple[str, str, str], *, since: datetime | None
) -> dict[str, Any] | None:
    """The ledger row of this lane, unless it was written before the Paper session began."""
    with db.session() as session:
        row = session.get(ArcForwardOutcome, outcome_id(*key))
        if row is None:
            return None
        recorded = parse_moment(row.created_at)
        if since is not None and recorded is not None and recorded < since:
            # The ledger keeps the first verdict of a pair; an older one is another race.
            return None
        return ForwardOutcomeLedger.view(row)


def reported_session_end(
    projection: ARCMissionProjection, attempt: ARCCandidateAttemptV1
) -> datetime | None:
    """When BitPro said the observed Paper session ended, from the last confirmed observation."""
    observation = projection.paper_observation
    if observation.get("instance_matched") is not True:
        return None
    if str(observation.get("instance_id")) != str(attempt.paper_instance_id):
        return None
    return parse_moment(observation.get("session_ended_at"))


def end_observation(
    controller: ARCController,
    attempt: ARCCandidateAttemptV1,
    *,
    db: Database | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Close the mission when its lane has a verdict or its session is over; None otherwise."""
    projection = controller.projection
    goal = projection.goal
    if projection.state != "paper_observing" or goal is None or not goal.paper_review_required:
        return None
    if not attempt.paper_instance_id:
        return None
    clock = now or datetime.now(UTC)
    database = db or get_configured_database()
    payload: dict[str, Any] = {
        "schema_version": "paper_observation_ended.v1",
        "attempt_id": attempt.attempt_id,
        "paper_instance_id": attempt.paper_instance_id,
        "strategy_id": str(attempt.bitpro_strategy_id),
    }
    key = lane_key(projection, attempt)
    lane = (
        finished_lane(database, key, since=parse_moment(projection.paper_started_at))
        if database is not None and key is not None
        else None
    )
    if lane is not None:
        payload.update(
            reason="race_finished",
            verdict=lane["verdict"],
            verdict_source=lane["verdict_source"],
            outcome_id=lane["id"],
            parent_strategy_id=lane["parent_strategy_id"],
            challenger_strategy_id=lane["challenger_strategy_id"],
            ended_at=lane["ended_at"],
            metrics=lane["metrics"],
        )
    else:
        ended = reported_session_end(projection, attempt)
        if ended is None or clock - ended < SESSION_ENDED_GRACE:
            return None
        payload.update(reason="paper_session_ended", session_ended_at=ended.isoformat())
    final = projection.paper_observation
    payload["final_observation"] = {name: final.get(name) for name in _FINAL_OBSERVATION_KEYS}
    try:
        controller.apply_event("paper_observation_ended", payload)
    except PermissionError as exc:
        # The mission moved on between the read and the write; the reducer refused.
        return {"status": "skipped", "reason": str(exc)}
    return {
        "status": "completed",
        "reason": payload["reason"],
        "verdict": payload.get("verdict"),
    }
