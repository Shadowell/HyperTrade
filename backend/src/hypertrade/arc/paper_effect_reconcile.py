"""Adopt a Paper session BitPro actually started although the start receipt never arrived.

A reviewed candidate is provisioned with two external writes: BitPro configures a version-bound
session, then HyperTrade asks BitPro to start it. When the start request fails or its receipt
cannot be confirmed, the mission parks in `effect_unknown` and the write is never replayed:
repeating a write whose outcome is unknown is not allowed. BitPro may nevertheless have started
(or auto-started) that exact session. Reading BitPro's own state is safe, so this module
reconciles instead of retrying: the start is adopted by one reducer event only when the live
session matches, field for field, what HyperTrade configured and the approved review bound.
Anything else stays parked.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from hypertrade.arc.controller import ARCController, ARCEventV1
from hypertrade.arc.store import (
    committed_revisions,
    get_controller,
    is_parked,
    list_mission_ids,
    park,
    peek_controller,
    research_lock,
)
from hypertrade.bitpro.mcp import BitProToolAdapter
from hypertrade.targets.read_ports import SnapshotContractError, read_ports

logger = logging.getLogger(__name__)

# Messages `ARCPaperIncubationResolver` returns when the failure happened at or after the start
# request. A failure while configuring leaves no session to adopt and is not reconciled here.
START_STAGE_FAILURES = (
    "bitpro_paper_start_failed",
    "bitpro_paper_start_rejected",
    "bitpro_paper_start_identity_unconfirmed",
    "bitpro_started_review_binding_unconfirmed",
)
CONFIGURED_RECEIPT_KEYS = (
    "paper_instance_id",
    "strategy_id",
    "guard_version",
    "review_hash",
    "code_sha256",
    "strategy_version",
    "config_version",
)
# A session that did not verify is looked at again after this long, not every sweep.
RECHECK_SECONDS = 600.0
_last_checked: dict[str, float] = {}


def _last_event(projection: Any, event_type: str, package_hash: str) -> ARCEventV1 | None:
    return next(
        (
            event
            for event in reversed(projection.events)
            if event.event_type == event_type and event.payload.get("package_hash") == package_hash
        ),
        None,
    )


def session_mismatch(snapshot: Any, configured: dict[str, Any]) -> list[str]:
    """Machine reasons why a live BitPro session is not the one HyperTrade configured."""
    reasons: list[str] = []
    if str(snapshot.strategy_id) != str(configured["strategy_id"]):
        reasons.append("strategy_id_mismatch")
    if snapshot.instance_id != configured["paper_instance_id"]:
        reasons.append("instance_id_mismatch")
    if snapshot.status != "running":
        reasons.append(f"session_status_{snapshot.status or 'unknown'}")
    if snapshot.strategy_version != configured["strategy_version"]:
        reasons.append("strategy_version_mismatch")
    if snapshot.config_version != configured["config_version"]:
        reasons.append("config_version_mismatch")
    if snapshot.session_started_at is None:
        reasons.append("session_not_started")
    session = (snapshot.source or {}).get("session") or {}
    if session.get("ended_at"):
        reasons.append("session_ended")
    # BitPro keeps a session it failed to restore as `running` but marks it critical and does not
    # trade it; that is not a started candidate.
    if session.get("error_level") == "critical":
        reasons.append("session_error_level_critical")
    return reasons


def reconcile_paper_start(
    controller: ARCController, client: Any = None, *, apply: bool = True
) -> dict[str, Any]:
    """Adopt the started session of one parked mission, or say why it cannot be adopted."""
    projection = controller.projection
    review = projection.paper_review
    if projection.state != "needs_operator" or review.get("status") != "effect_unknown":
        return {"status": "skipped", "reason": "no_unknown_paper_effect"}
    package_hash = review.get("package_hash")
    if not package_hash or (review.get("decision") or {}).get("decision") != "approve":
        return {"status": "skipped", "reason": "review_not_approved"}
    effect = _last_event(projection, "paper_review_effect", package_hash)
    if effect is None or effect.payload.get("ok"):
        return {"status": "skipped", "reason": "no_failed_effect_receipt"}
    message = str(effect.payload.get("message") or "")
    if not message.startswith(START_STAGE_FAILURES):
        return {"status": "skipped", "reason": "failure_not_at_start_stage"}
    configured_event = _last_event(projection, "paper_review_configured", package_hash)
    configured = configured_event.payload if configured_event is not None else {}
    if configured.get("ok") is not True or not all(
        configured.get(key) for key in CONFIGURED_RECEIPT_KEYS
    ):
        return {"status": "skipped", "reason": "configure_receipt_missing"}
    attempt = next(
        (a for a in projection.attempts if a.attempt_id == review.get("attempt_id")), None
    )
    if attempt is None or str(attempt.bitpro_strategy_id) != str(configured["strategy_id"]):
        return {"status": "skipped", "reason": "candidate_identity_mismatch"}
    try:
        snapshot = read_ports(client or BitProToolAdapter()).get_session_snapshot(
            strategy_id=str(configured["strategy_id"]), instance_id=configured["paper_instance_id"]
        )
    except SnapshotContractError:
        return {"status": "unverified", "reasons": ["snapshot_identity_mismatch"]}
    except Exception as exc:  # BitPro unreachable or erroring: look again later, change nothing.
        return {"status": "unverified", "reasons": [f"snapshot_read_failed:{type(exc).__name__}"]}
    reasons = session_mismatch(snapshot, configured)
    if reasons:
        return {"status": "unverified", "reasons": reasons}
    payload = {
        "schema_version": "paper_review_receipt.v1",
        "package_hash": package_hash,
        "ok": True,
        "paper_instance_id": configured["paper_instance_id"],
        "strategy_name": effect.payload.get("strategy_name"),
        "message": "reconciled_from_bitpro_session",
        "previous_message": message,
        "source": "bitpro_paper_snapshot",
        **{k: configured[k] for k in CONFIGURED_RECEIPT_KEYS if k != "paper_instance_id"},
        "session_started_at": snapshot.session_started_at.isoformat(),
        "observed_status": snapshot.status,
    }
    if not apply:
        return {"status": "verified", "payload": payload}
    try:
        controller.apply_event("paper_review_effect_reconciled", payload)
    except PermissionError:
        # Another worker resolved it first, or the mission moved on since this read.
        return {"status": "skipped", "reason": "reducer_rejected"}
    return {
        "status": "reconciled",
        "paper_instance_id": payload["paper_instance_id"],
        "session_started_at": payload["session_started_at"],
    }


def reconcile_paper_effects_once(client: Any = None, *, now: float | None = None) -> dict[str, Any]:
    """One sweep over parked missions; read-only against BitPro, one ARC event per adoption."""
    clock = time.monotonic() if now is None else now
    results: list[dict[str, Any]] = []
    mission_ids = list_mission_ids(state="needs_operator")
    revisions = committed_revisions(mission_ids)
    for mission_id in mission_ids:
        previous = _last_checked.get(mission_id)
        if previous is not None and clock - previous < RECHECK_SECONDS:
            continue
        if is_parked("paper_effect", mission_id, revisions.get(mission_id)):
            continue
        # Looking is not keeping: missions that wait for the operator pile up, and every one of
        # them stayed resident, journal and all, for no reason but to be told it is not unknown.
        controller = peek_controller(mission_id)
        if controller is None:
            continue
        if controller.projection.paper_review.get("status") != "effect_unknown":
            park("paper_effect", mission_id, controller.revision)  # until it changes
            continue
        _last_checked[mission_id] = clock
        with research_lock(f"paper-effect-reconcile/{mission_id}") as owner:
            if owner is None:
                continue
            controller = get_controller(mission_id) or controller
            result = reconcile_paper_start(controller, client)
        if result["status"] == "reconciled":
            _last_checked.pop(mission_id, None)
            logger.info(
                "paper effect reconciled mission=%s instance=%s",
                mission_id,
                result["paper_instance_id"],
            )
        results.append({"mission_id": mission_id, **result})
    return {
        "checked": len(results),
        "reconciled": sum(1 for row in results if row["status"] == "reconciled"),
        "results": results,
    }
