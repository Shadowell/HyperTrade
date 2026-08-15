"""Shaped evidence for an external console. A rendering, never a second store."""

from __future__ import annotations

from typing import Any

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCReflexionEventV1
from hypertrade.arc.controller import ARCMissionProjection
from hypertrade.arc.evidence import MIN_ADMISSIBLE_OOS_SHARPE
from hypertrade.arc.findings import MAX_ADMISSIBLE_DRAWDOWN

_SURVIVOR_STATES = {
    "validated",
    "paper_authorizing",
    "paper_observing",
    "live_canary",
}


def build_evidence_view(projection: ARCMissionProjection) -> dict[str, Any]:
    """Project ``ARCMissionProjection`` into a renderable evidence document.

    ``strategy_code`` is omitted on purpose: a mission of ninety candidates would
    otherwise become an unreadable megabyte payload. Source lives behind drill-down.
    """
    promoted = _promoted_attempt(projection)
    approval = projection.live_approval
    return {
        "mission": _mission_summary(projection),
        "candidates": [_candidate_row(item) for item in projection.attempts],
        "promotion": _promotion(projection, promoted),
        "approval": {
            "status": approval.status if approval is not None else None,
            "unknowns": list(approval.unknowns) if approval is not None else [],
            "recommendation": approval.recommendation if approval is not None else None,
            "package_hash": approval.package_hash if approval is not None else None,
        },
    }


def build_candidate_detail(
    projection: ARCMissionProjection, attempt_id: str
) -> dict[str, Any] | None:
    attempt = next(
        (item for item in projection.attempts if item.attempt_id == attempt_id),
        None,
    )
    if attempt is None:
        return None
    row = _candidate_row(attempt)
    row.update(
        {
            "strategy_code": attempt.strategy_code,
            "strategy_spec": dict(attempt.strategy_spec),
            "reflexion_events": [
                event.model_dump(mode="json") for event in attempt.reflexion_events
            ],
            "hypothesis": attempt.hypothesis,
        }
    )
    return row


def build_mission_summary(projection: ARCMissionProjection) -> dict[str, Any]:
    from hypertrade.arc.pipeline_view import build_pipeline_badge

    summary = _mission_summary(projection)
    summary["awaiting_approval"] = _awaiting_approval(projection)
    summary["survivor_count"] = sum(
        1 for item in projection.attempts if item.state in _SURVIVOR_STATES
    )
    summary["pipeline"] = build_pipeline_badge(projection)
    return summary


def _mission_summary(projection: ARCMissionProjection) -> dict[str, Any]:
    goal = projection.goal
    budget = goal.budget if goal is not None else None
    return {
        "mission_id": projection.mission_id,
        "state": projection.state,
        "objective": goal.objective if goal is not None else "",
        "symbol": (goal.symbols[0] if goal and goal.symbols else ""),
        "timeframe": (goal.timeframes[0] if goal and goal.timeframes else ""),
        "created_by": projection.created_by,
        "created_at": (
            projection.events[0].timestamp.isoformat()
            if projection.events
            else projection.updated_at.isoformat()
        ),
        "updated_at": projection.updated_at.isoformat(),
        "progress": {
            "candidates_used": len(projection.attempts),
            "max_candidates": budget.max_candidates if budget is not None else 0,
        },
    }


def _awaiting_approval(projection: ARCMissionProjection) -> bool:
    if projection.state == "live_approval_ready":
        return True
    package = projection.live_approval
    return package is not None and package.status == "ready"


def _candidate_row(attempt: ARCCandidateAttemptV1) -> dict[str, Any]:
    metrics = attempt.observed_metrics
    folds_total = _as_int(metrics.get("walk_forward_folds"))
    return {
        "attempt_id": attempt.attempt_id,
        "candidate_id": attempt.candidate_id,
        "state": attempt.state,
        "family": str(attempt.strategy_spec.get("family") or ""),
        "direction": str(attempt.strategy_spec.get("direction") or ""),
        "oos_sharpe": _as_float(
            metrics.get("out_of_sample_sharpe", metrics.get("ranking_sharpe"))
        ),
        "trades": _as_int(
            metrics.get("out_of_sample_trades", metrics.get("trades"))
        ),
        "win_rate": _as_float(metrics.get("win_rate", metrics.get("out_of_sample_win_rate"))),
        "folds_passed": _folds_passed(metrics),
        "folds_total": folds_total,
        "ranking_basis": metrics.get("ranking_basis"),
        "rejections": _rejections(attempt.reflexion_events),
    }


def _rejections(events: list[ARCReflexionEventV1]) -> list[dict[str, str]]:
    """Each objection with its own explanation.

    `negative_constraints` is deduped, sorted mutation guidance whose order has nothing
    to do with `reason_codes`; pairing them by index handed the operator a remediation
    string belonging to a different gate. The finding's own detail is authoritative, and
    the canonical remediation covers rows recorded before details were kept.
    """
    from hypertrade.arc.reflexion import constraint_for_reason_code

    rows: list[dict[str, str]] = []
    for event in events:
        codes = list(event.reason_codes) or [event.failure_class]
        for code in codes:
            key = str(code)
            text = event.reason_details.get(key) or constraint_for_reason_code(key)
            rows.append({"code": key, "text": text})
    return rows


def _folds_passed(metrics: dict[str, Any]) -> int | None:
    stored = metrics.get("walk_forward_surviving")
    if stored is not None:
        return _as_int(stored)
    sharpes = metrics.get("walk_forward_sharpes") or []
    drawdowns = metrics.get("walk_forward_drawdowns") or []
    if not isinstance(sharpes, list) or not sharpes:
        return None
    passed = 0
    for index, sharpe in enumerate(sharpes):
        drawdown = drawdowns[index] if index < len(drawdowns) else 0.0
        try:
            sharpe_ok = float(sharpe) >= MIN_ADMISSIBLE_OOS_SHARPE
            drawdown_ok = float(drawdown) <= MAX_ADMISSIBLE_DRAWDOWN
            if sharpe_ok and drawdown_ok:
                passed += 1
        except (TypeError, ValueError):
            continue
    return passed


def _promoted_attempt(projection: ARCMissionProjection) -> ARCCandidateAttemptV1 | None:
    observing = [item for item in projection.attempts if item.paper_instance_id]
    if observing:
        return observing[-1]
    survivors = [item for item in projection.attempts if item.state in _SURVIVOR_STATES]
    if survivors:
        return survivors[-1]
    return projection.attempts[-1] if projection.attempts else None


def _promotion(
    projection: ARCMissionProjection, attempt: ARCCandidateAttemptV1 | None
) -> dict[str, Any]:
    self_test = None
    if attempt is not None:
        matches = [
            record
            for record in projection.self_test_records
            if record.get("attempt_id") == attempt.attempt_id
        ]
        self_test = matches[-1] if matches else None
    return {
        "bitpro_strategy_id": attempt.bitpro_strategy_id if attempt else None,
        "bitpro_backtest_id": attempt.bitpro_backtest_id if attempt else None,
        "validation_id": attempt.validation_id if attempt else None,
        "paper_instance_id": attempt.paper_instance_id if attempt else None,
        "self_test": self_test,
        "paper_observation": dict(projection.paper_observation),
    }


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
