"""Durable eligibility and acceptance evidence, without owning research execution."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from hypertrade.arc.controller import ARCMissionProjection
from hypertrade.arc.evolution_models import EvolutionAcceptance, EvolutionContinuation
from hypertrade.arc.provenance import alert_codes
from hypertrade.db import Database

if TYPE_CHECKING:
    from hypertrade.arc.evolution import EvolutionConfig
    from hypertrade.targets.schemas import MarketTargetProfileV1


def key(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def continuation_source_id(target_id: str, strategy_id: int | str, instance_id: str) -> str:
    """Retain BitPro's historic key while isolating other market targets."""
    if target_id == "bitpro":
        return key([int(strategy_id), instance_id])
    return key([target_id, str(strategy_id), instance_id])


def utc(value: str | datetime) -> datetime:
    stamp = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def window_timezone(profile: MarketTargetProfileV1 | None) -> tzinfo:
    """Evidence windows align to the market target's calendar timezone."""
    name = (profile.calendar.timezone if profile is not None else "UTC").strip() or "UTC"
    if name.upper() in {"UTC", "Z", "GMT"}:
        return UTC
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - an unknown tz must not stall eligibility
        return UTC


def window_days(profile: MarketTargetProfileV1 | None) -> int:
    return profile.calendar.evidence_window_days if profile is not None else 14


# time = waiting clears it (window rolls, trades accumulate, budget resets);
# operator = a human or upstream fix is required (identity, source down, costs).
_OPERATOR_BLOCKERS = {"session_identity", "session_start", "running_state"}
_OPERATOR_SAMPLING_REASONS = {
    "source_point_limit_exceeded",
    "recent_series_contract_mismatch",
    "recent_read_unavailable",
    "cost_metadata_unavailable",
    "session_identity_missing",
}


def blocker_resolution(code: str, *, sampling_reason: str | None = None) -> str:
    """Classify whether a blocker self-heals with time or needs an operator."""
    if code in _OPERATOR_BLOCKERS:
        return "operator"
    if code == "evidence_recheck":
        return "operator" if sampling_reason in _OPERATOR_SAMPLING_REASONS else "time"
    return "time"


def complete_receipt_chain(receipts: list[Any], end_at: Any) -> bool:
    """Verify that the source receipts cover one exact, contiguous 7+7 window."""
    try:
        end = utc(end_at)
        if len(receipts) != 56:
            return False
        expected = end - timedelta(days=14)
        for receipt in receipts:
            if (
                not isinstance(receipt, dict)
                or utc(receipt["start_at"]) != expected
                or utc(receipt["end_at"]) != expected + timedelta(hours=6)
                or not receipt.get("source_hash")
                or not receipt.get("content_hash")
            ):
                return False
            expected += timedelta(hours=6)
        return expected == end
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def complete_session_receipt_chain(receipts: list[Any], feedback: dict[str, Any]) -> bool:
    calendar = feedback.get("calendar") or {}
    dates = calendar.get("trading_dates") or []
    baseline = feedback.get("baseline_receipt") or {}
    try:
        if (
            feedback.get("measurement") != "session_paper_equity"
            or not calendar.get("source_hash")
            or not calendar.get("timezone")
            or len(dates) != 14
            or len(receipts) != 14
            or dates != sorted(set(dates))
            or not isinstance(baseline, dict)
            or baseline.get("trading_day") != calendar.get("baseline_trading_day")
            or not baseline.get("source_hash")
            or not baseline.get("content_hash")
            or calendar["baseline_trading_day"] >= dates[0]
        ):
            return False
        tz = ZoneInfo(calendar["timezone"])
        if (
            utc(baseline["start_at"]) >= utc(baseline["end_at"])
            or utc(baseline["end_at"]) >= utc(receipts[0]["start_at"])
            or utc(baseline["start_at"]).astimezone(tz).date().isoformat()
            != calendar["baseline_trading_day"]
            or utc(baseline["end_at"]).astimezone(tz).date().isoformat()
            != calendar["baseline_trading_day"]
            or utc(baseline["end_at"]) != utc(feedback["previous"]["start_at"])
            or utc(receipts[6]["end_at"]) != utc(feedback["recent"]["start_at"])
        ):
            return False
        for day, receipt in zip(dates, receipts, strict=True):
            if (
                receipt.get("trading_day") != day
                or not receipt.get("source_hash")
                or not receipt.get("content_hash")
                or utc(receipt["start_at"]) >= utc(receipt["end_at"])
                or utc(receipt["start_at"]).astimezone(tz).date().isoformat() != day
                or utc(receipt["end_at"]).astimezone(tz).date().isoformat() != day
            ):
                return False
        return utc(receipts[-1]["end_at"]) == utc(feedback["end_at"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def readiness(
    snapshot: dict[str, Any],
    diagnostic: dict[str, Any],
    config: EvolutionConfig,
    now: datetime,
    profile: MarketTargetProfileV1 | None = None,
) -> dict[str, Any]:
    """Known lower bounds are not promises: all evidence is re-read when due."""
    now = utc(now)
    tz = window_timezone(profile)
    days = window_days(profile)
    end = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    blockers: list[dict[str, Any]] = []
    next_eligible = None
    cursor = {
        k: snapshot.get(k)
        for k in ("instance_id", "strategy_id", "strategy_version", "config_version", "trade_count")
    }
    session = snapshot.get("session")
    start = session.get("started_at") if isinstance(session, dict) else None
    cursor["session_started_at"] = start
    sessions = profile is not None and profile.calendar.mode == "sessions"
    window = diagnostic.get("window") or {}
    receipts = window.get("receipts") or []
    baseline_receipt = window.get("baseline_receipt") or {}
    cursor["requested_window_start"] = (
        baseline_receipt.get("end_at")
        if sessions and baseline_receipt
        else (end - timedelta(days=days)).isoformat()
        if not sessions
        else None
    )
    cursor["requested_window_end"] = (
        receipts[-1].get("end_at")
        if sessions and receipts
        else end.isoformat()
        if not sessions
        else None
    )
    cursor["window_receipt_hash"] = diagnostic.get("window_receipt_hash")
    provenance = (diagnostic.get("attribution_report") or {}).get("provenance")
    source_alerts = alert_codes(provenance)
    if provenance is not None:
        # These metadata gaps need operator visibility even while the time gate is pending.
        # This projection does not change research admission or reconstruct historical evidence.
        cursor["source_provenance"] = {
            "status": provenance.get("status") if isinstance(provenance, dict) else "unavailable",
            "blocking_reasons": source_alerts,
        }
    if not all(cursor.get(k) for k in ("instance_id", "strategy_version", "config_version")):
        blockers.append(
            {"code": "session_identity", "condition": "verify original session and versions"}
        )
    if snapshot and snapshot.get("status") != "running":
        blockers.append(
            {
                "code": "running_state",
                "observed": snapshot.get("status"),
                "condition": "original Paper must be running; do not restart or reconfigure",
            }
        )
    if snapshot:
        trades = snapshot.get("trade_count")
        try:
            observed = int(trades) if trades is not None and not isinstance(trades, bool) else None
        except (TypeError, ValueError, OverflowError):
            observed = None
        if observed is None or observed < config.min_trades:
            blockers.append(
                {
                    "code": "minimum_trades",
                    "observed": observed,
                    "required": config.min_trades,
                    "condition": "same-session trade_count >= required",
                }
            )
    try:
        if not start:
            raise ValueError("missing start")
        if sessions:
            if not complete_session_receipt_chain(receipts, window):
                blockers.append(
                    {
                        "code": "trading_calendar_evidence",
                        "condition": "14 complete sessions with timezone and source receipts",
                        "resolution": "operator",
                    }
                )
        else:
            minimum = utc(start) + timedelta(days=days)
            eligible = minimum.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            if eligible < minimum:
                eligible += timedelta(days=1)
            if end < minimum:
                next_eligible = eligible.isoformat()
                calendar_name = tz.tzname(None) or "UTC"
                blockers.append(
                    {
                        "code": "completed_utc_window",
                        "eligible_at": next_eligible,
                        "condition": (
                            f"{days} complete {calendar_name} days within original session"
                        ),
                    }
                )
    except (ValueError, TypeError, OverflowError):
        blockers.append(
            {
                "code": "session_start",
                "condition": "verify original session started_at; never recreate",
            }
        )
    data = diagnostic.get("data_readiness") or {}
    sampling = data.get("sampling") or {}
    cursor["sampling"] = {
        k: sampling.get(k)
        for k in ("latest_sample_at", "sample_count", "source_hash", "content_hash", "reason_code")
    }
    reason = data.get("blocking_reason") or diagnostic.get("reason")
    if diagnostic.get("status") == "unavailable":
        blockers.append(
            {
                "code": "evidence_recheck",
                "reason": reason,
                "condition": (
                    "fresh identity/cost-bound 7+7 series; "
                    "complete boundaries, no gaps or pagination"
                ),
            }
        )
    if diagnostic.get("status") == "stable":
        blockers.append(
            {
                "code": "degradation_threshold",
                "required_pp": str(config.threshold_pp),
                "condition": "return_drop_pp or drawdown_increase_pp >= required_pp",
            }
        )
    # Poll unknown/trade/data conditions; a date is only the known minimum time gate.
    sampling_reason = (cursor.get("sampling") or {}).get("reason_code")
    for blocker in blockers:
        blocker.setdefault(
            "resolution",
            blocker_resolution(str(blocker.get("code")), sampling_reason=sampling_reason),
        )
    return {
        "schema_version": "evolution_continuation.v1",
        "observed_at": now.isoformat(),
        "next_eligible_at": next_eligible,
        "next_check_at": datetime.fromtimestamp(
            (int(now.timestamp()) // (config.interval_minutes * 60) + 1)
            * config.interval_minutes
            * 60,
            UTC,
        ).isoformat(),
        "blockers": blockers,
        "evidence_cursor": cursor,
        "check_result": diagnostic.get("status", "unavailable"),
        "window": diagnostic.get("window"),
        "automatic_resume": True,
        "attention_required": bool(source_alerts)
        or any(b.get("resolution") == "operator" for b in blockers),
    }


class ContinuationLedger:
    def __init__(self, db: Database):
        self.db = db

    def view(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            return [
                {"id": row.id, "target_id": "bitpro", **row.payload_json}
                for row in session.scalars(
                    select(EvolutionContinuation)
                    .order_by(EvolutionContinuation.updated_at.desc())
                    .limit(100)
                )
            ]

    def record_check(
        self,
        cycle_id: str,
        diagnostics: list[dict[str, Any]],
        budget: dict[str, Any] | None = None,
    ) -> None:
        from hypertrade.arc.research_budget import source_key

        # The caller holds the distributed evolution scanner lock. Each checkpoint and
        # immutable receipt commit together; replay uses deterministic receipt IDs.
        with self.db.session() as session:
            for diagnostic in diagnostics:
                state = diagnostic.get("continuation")
                if not state or not diagnostic.get("strategy_id"):
                    continue
                state = dict(state)
                instance = state["evidence_cursor"].get("instance_id")
                target_id = str(diagnostic.get("target_id") or "bitpro")
                strategy_id = diagnostic["strategy_id"]
                if budget:
                    source_budget = budget.get("sources", {}).get(
                        source_key(target_id, strategy_id, instance), {}
                    )
                    state["dispatch_condition"] = {
                        "schema_version": budget.get("schema_version"),
                        "source_reason": source_budget.get("reason"),
                        "source_next_run_at": source_budget.get("next_run_at"),
                        "global_reason": budget.get("reason"),
                        "global_next_run_at": budget.get("next_run_at"),
                    }
                    state["blockers"] = list(state["blockers"])
                    eligibility_times = (
                        [state["next_eligible_at"]] if state["next_eligible_at"] else []
                    )
                    conditional_dispatch = False
                    for reason, eligible_at in (
                        (source_budget.get("reason"), source_budget.get("next_run_at")),
                        (budget.get("reason"), budget.get("next_run_at")),
                    ):
                        if reason:
                            if eligible_at:
                                eligibility_times.append(eligible_at)
                            else:
                                conditional_dispatch = True
                            state["blockers"].append(
                                {
                                    "code": reason,
                                    "eligible_at": eligible_at,
                                    "condition": "budget admission must recheck",
                                    "resolution": "time",
                                }
                            )
                    state["next_eligible_at"] = (
                        None
                        if conditional_dispatch
                        else max(eligibility_times, key=utc)
                        if eligibility_times
                        else None
                    )
                source_id = continuation_source_id(target_id, strategy_id, instance)
                row = session.get(EvolutionContinuation, source_id, with_for_update=True)
                if row is None:
                    row = EvolutionContinuation(id=source_id, payload_json={})
                    session.add(row)
                if row.payload_json.get("observed_at", "") > state["observed_at"]:
                    continue
                row.payload_json = {
                    **row.payload_json,
                    **state,
                    "strategy_id": strategy_id,
                    "target_id": target_id,
                    "cycle_id": cycle_id,
                }
                entry_id = key([cycle_id, source_id, state])
                if session.get(EvolutionAcceptance, entry_id) is None:
                    session.add(
                        EvolutionAcceptance(
                            id=entry_id,
                            source_id=source_id,
                            payload_json={
                                "stage": "eligibility_checked",
                                "cycle_id": cycle_id,
                                "target_id": target_id,
                                **state,
                            },
                        )
                    )

    def refresh(self, now: datetime) -> None:
        from hypertrade.arc.store import research_lock
        from hypertrade.db import ArcMission

        with research_lock("evolution-acceptance") as owner:
            if owner is None:
                return
            with self.db.session() as session:
                missions = session.scalars(
                    select(ArcMission).order_by(ArcMission.created_at)
                ).yield_per(20)
                for mission in missions:
                    projection = ARCMissionProjection.model_validate(mission.projection_json)
                    goal = projection.goal
                    context = (goal.feedback_parent or goal.evolution_context) if goal else None
                    if not goal or not context:
                        continue
                    instance = context.get("source_instance_id") or context.get("instance_id")
                    sid = (
                        context.get("source_strategy_id")
                        or context.get("strategy_id")
                        or (context.get("evidence") or {}).get("strategy_id")
                    )
                    if not instance or not sid:
                        continue
                    target_id = str(
                        context.get("target_id")
                        or (goal.evolution_context or {}).get("target_id")
                        or "bitpro"
                    )
                    if target_id == "bitpro":
                        try:
                            sid = int(sid)
                        except (ValueError, TypeError, OverflowError):
                            continue
                    elif not isinstance(sid, str) or not sid.strip():
                        continue
                    source_id = continuation_source_id(target_id, sid, instance)
                    checkpoint = session.get(EvolutionContinuation, source_id, with_for_update=True)
                    if checkpoint is None:
                        checkpoint = EvolutionContinuation(
                            id=source_id,
                            payload_json={
                                "strategy_id": sid,
                                "target_id": target_id,
                                "evidence_cursor": {"instance_id": instance},
                            },
                        )
                        session.add(checkpoint)
                    known = set(
                        session.scalars(
                            select(EvolutionAcceptance.id).where(
                                EvolutionAcceptance.source_id == source_id
                            )
                        )
                    )
                    entries = acceptance_entries(projection, now)
                    for entry in entries:
                        entry_id = key(
                            [
                                mission.mission_id,
                                entry["reference_id"],
                                entry["stage"],
                                entry["result"],
                                entry["payload"],
                            ]
                        )
                        if entry_id not in known:
                            session.add(
                                EvolutionAcceptance(
                                    id=entry_id,
                                    source_id=source_id,
                                    payload_json={"mission_id": mission.mission_id, **entry},
                                )
                            )
                    passed = {e["stage"] for e in entries if e["result"] == "passed"}
                    required = {
                        "trigger_7_plus_7",
                        "budgeted_avo",
                        "same_window_comparison",
                        "final_validation",
                        "agent_policy_review",
                        "reviewed_configure",
                        "reviewed_start",
                    }
                    missing = sorted(required - passed)
                    review = projection.paper_review
                    unknown = review.get("status") == "effect_unknown" or (
                        projection.state == "needs_operator" and bool(projection.avo.get("pending"))
                    )
                    last_stop = next(
                        (
                            e.payload.get("reason", "")
                            for e in reversed(projection.events)
                            if e.event_type == "operator_needed"
                        ),
                        "",
                    )
                    unknown = (
                        unknown
                        or projection.state == "paper_provisioning"
                        or (
                            projection.state == "needs_operator"
                            and "effect_unknown" in str(last_stop)
                        )
                    )
                    reasons = [
                        e["payload"].get("reason")
                        for e in entries
                        if e["stage"] == "terminal" or e["result"] == "rejected"
                    ]
                    status = (
                        "reconciliation_required"
                        if unknown
                        else "accepted"
                        if not missing
                        else "evidence_incomplete"
                        if projection.state == "paper_observing"
                        else "terminal_with_gaps"
                        if projection.state in {"needs_operator", "failed", "completed"}
                        else "in_progress"
                    )
                    checkpoint.payload_json = {
                        **checkpoint.payload_json,
                        "acceptance": {
                            "mission_id": mission.mission_id,
                            "status": status,
                            "checked_at": utc(now).isoformat(),
                            "missing_stages": missing,
                            "terminal_reasons": [r for r in reasons if r],
                            "stages": entries[-100:],
                            "event_cursor": projection.events[-1].event_id
                            if projection.events
                            else None,
                            "pending_effect": bool(unknown),
                            "automatic_resume": not unknown,
                        },
                    }
                    if status in {
                        "terminal_with_gaps",
                        "reconciliation_required",
                        "evidence_incomplete",
                        "accepted",
                    }:
                        summary = checkpoint.payload_json["acceptance"]
                        summary_id = key(
                            [
                                mission.mission_id,
                                "acceptance_summary",
                                summary["event_cursor"],
                                status,
                            ]
                        )
                        if summary_id not in known:
                            session.add(
                                EvolutionAcceptance(
                                    id=summary_id,
                                    source_id=source_id,
                                    payload_json={"stage": "acceptance_summary", **summary},
                                )
                            )
                    owner()


def acceptance_entries(projection: ARCMissionProjection, now: datetime) -> list[dict[str, Any]]:
    """Audit source events, not inferred state transitions or synthetic production proof."""
    goal = projection.goal
    if goal is None:
        return []
    context = goal.feedback_parent or goal.evolution_context or {}
    feedback = (
        context.get("paper_feedback") or context.get("evidence") or context.get("window") or {}
    )
    if not isinstance(feedback, dict):
        feedback = {}
    receipts = feedback.get("receipts")
    if not isinstance(receipts, list):
        receipts = []
    budget = goal.budget.model_dump(mode="json")
    bounded_budget = (
        goal.research_mode == "avo"
        and all(
            isinstance(budget.get(limit), int)
            and not isinstance(budget.get(limit), bool)
            and budget[limit] > 0
            for limit in (
                "max_candidates",
                "max_model_calls",
                "max_tool_calls",
                "max_backtests",
                "max_wall_seconds",
            )
        )
        and all(
            isinstance(budget.get(used), int)
            and not isinstance(budget.get(used), bool)
            and 0 <= budget[used] <= budget[limit]
            for limit, used in (
                ("max_candidates", "candidates_used"),
                ("max_model_calls", "model_calls_used"),
                ("max_tool_calls", "tool_calls_used"),
                ("max_backtests", "backtests_used"),
            )
        )
    )
    entries: list[dict[str, Any]] = [
        {
            "stage": "budgeted_avo",
            "reference_id": projection.mission_id,
            "observed_at": utc(now).isoformat(),
            "result": "passed" if bounded_budget else "missing",
            "payload": {"budget": budget},
        },
        {
            "stage": "trigger_7_plus_7",
            "reference_id": projection.mission_id,
            "observed_at": utc(now).isoformat(),
            "result": "passed"
            if feedback.get("triggered") is True
            and (
                complete_session_receipt_chain(receipts, feedback)
                if feedback.get("measurement") == "session_paper_equity"
                else complete_receipt_chain(receipts, feedback.get("end_at"))
            )
            and feedback.get("source_id")
            == (context.get("source_instance_id") or context.get("instance_id"))
            else "missing",
            "payload": {
                "window_end": feedback.get("end_at"),
                "baseline_receipt": feedback.get("baseline_receipt"),
                "receipts": [
                    {k: r.get(k) for k in ("start_at", "end_at", "source_hash", "content_hash")}
                    for r in receipts
                    if isinstance(r, dict)
                ],
            },
        },
    ]
    for event_index, event in enumerate(projection.events):
        payload = event.payload
        stage: str | None = None
        result = "recorded"
        if event.event_type == "bitpro_self_tested":
            selected = payload.get("attempt_id") == projection.paper_review.get(
                "attempt_id"
            ) and payload.get("backtest_id") == (projection.paper_review.get("backtest") or {}).get(
                "backtest_id"
            )
            entries.append(
                {
                    "stage": "final_validation",
                    "reference_id": event.event_id,
                    "observed_at": utc(event.timestamp).isoformat(),
                    "result": "passed"
                    if selected
                    and payload.get("passed") is True
                    and payload.get("backtest_id")
                    and payload.get("validation_id")
                    else "failed"
                    if selected
                    else "pending_review_binding",
                    "payload": {
                        "backtest_id": payload.get("backtest_id"),
                        "validation_id": payload.get("validation_id"),
                    },
                }
            )
            comparison = (payload.get("metrics") or {}).get("baseline_comparison") or {}
            if comparison:
                stage = "same_window_comparison"
                result = (
                    "passed"
                    if selected
                    and comparison.get("passed") is True
                    and payload.get("backtest_id")
                    and comparison.get("backtest_id")
                    == (projection.avo.get("baseline_final") or {}).get("backtest_id")
                    and comparison.get("backtest_id") is not None
                    else "failed"
                    if selected
                    else "pending_review_binding"
                )
        elif event.event_type == "paper_review_decided":
            stage = "agent_policy_review"
            prior_agent_review = next(
                (
                    item
                    for item in reversed(projection.events[:event_index])
                    if item.event_type == "paper_auto_review_evaluated"
                    and item.payload.get("package_hash") == payload.get("package_hash")
                ),
                None,
            )
            result = (
                "passed"
                if (
                    payload.get("identity_source") == "agent_policy"
                    and payload.get("decision") == "approve"
                    and payload.get("package_hash") == projection.paper_review.get("package_hash")
                    and prior_agent_review is not None
                    and prior_agent_review.payload.get("decision") == "approve"
                )
                else "rejected"
            )
        elif event.event_type in {"paper_review_configured", "paper_review_started"}:
            stage = (
                "reviewed_configure"
                if event.event_type.endswith("configured")
                else "reviewed_start"
            )
            valid = (
                payload.get("schema_version") == "paper_review_receipt.v1"
                and payload.get("ok") is True
                and payload.get("guard_version") == "paper_review_binding.v1"
                and payload.get("review_hash") == payload.get("package_hash")
                and payload.get("package_hash") == projection.paper_review.get("package_hash")
                and payload.get("paper_instance_id")
                != (context.get("source_instance_id") or context.get("instance_id"))
                and all(
                    payload.get(k)
                    for k in (
                        "package_hash",
                        "strategy_id",
                        "paper_instance_id",
                        "code_sha256",
                        "config_version",
                    )
                )
            )
            valid = valid and bool(payload.get("strategy_version"))
            if stage == "reviewed_start":
                prior: dict[str, Any] = next(
                    (
                        e.payload
                        for e in reversed(projection.events[:event_index])
                        if e.event_type == "paper_review_configured"
                    ),
                    {},
                )
                valid = valid and all(
                    payload.get(k) == prior.get(k)
                    for k in (
                        "package_hash",
                        "strategy_id",
                        "paper_instance_id",
                        "code_sha256",
                        "strategy_version",
                        "config_version",
                    )
                )
            result = "passed" if valid else "unknown"
        elif event.event_type in {"operator_needed", "mission_failed", "mission_completed"}:
            stage = "terminal"
        elif event.event_type in {"avo_unknown_result", "paper_review_effect"}:
            stage = "external_effect"
            result = "passed" if payload.get("ok") is True else "unknown"
        elif event.event_type in {
            "avo_development_result",
            "avo_baseline_result",
            "paper_auto_review_evaluated",
        }:
            stage = event.event_type
        if stage:
            # References lead to the canonical immutable ARC event. Never duplicate raw
            # model text, source code or external responses into the public ledger.
            safe = {
                k: payload.get(k)
                for k in (
                    "reason",
                    "reasons",
                    "backtest_id",
                    "validation_id",
                    "package_hash",
                    "identity_source",
                    "decision",
                    "strategy_id",
                    "paper_instance_id",
                    "guard_version",
                    "review_hash",
                    "code_sha256",
                    "strategy_version",
                    "config_version",
                )
                if k in payload
            }
            entries.append(
                {
                    "stage": stage,
                    "reference_id": event.event_id,
                    "observed_at": utc(event.timestamp).isoformat(),
                    "result": result,
                    "payload": safe,
                }
            )
    return entries
