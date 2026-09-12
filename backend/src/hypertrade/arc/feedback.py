"""Paper-only degradation evidence and idempotent parameter research; never mutate the source."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCGoalV1,
    PaperFeedbackPolicyV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.observation import paper_attempt
from hypertrade.arc.store import get_controller, research_lock, save_mission
from hypertrade.arc.universe import candidate_symbol
from hypertrade.bitpro.mcp import BitProToolAdapter


def _time(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("timestamp_missing_timezone")
    return timestamp.astimezone(UTC)


def _number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("invalid_equity")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite_equity")
    return result


def evaluate_windows(
    points: list[dict[str, Any]], end: datetime, policy: PaperFeedbackPolicyV1
) -> dict[str, Any]:
    start, middle = end - timedelta(days=14), end - timedelta(days=7)
    samples = [(_time(p["timestamp"]), _number(p["equity"])) for p in points]
    if len(samples) < 3 or samples[0][0] < start or samples[-1][0] > end:
        raise ValueError("invalid_window")
    if any(v <= 0 for _, v in samples):
        raise ValueError("nonpositive_equity_requires_operator")
    if (samples[0][0] - start).total_seconds() > 3600 or (
        end - samples[-1][0]
    ).total_seconds() > 3600:
        raise ValueError("incomplete_window_boundaries")
    if any(
        not 0 < (b[0] - a[0]).total_seconds() <= policy.max_gap_seconds
        for a, b in zip(samples, samples[1:], strict=False)
    ):
        raise ValueError("duplicate_or_missing_samples")
    split = next((i for i, p in enumerate(samples) if p[0] >= middle), None)
    if (
        split is None
        or split == 0
        or split == len(samples) - 1
        or (samples[split][0] - middle).total_seconds() > 3600
    ):
        raise ValueError("missing_week_boundary")

    def metrics(window: list[tuple[datetime, Decimal]]) -> dict[str, Any]:
        peak, drawdown = window[0][1], Decimal(0)
        for _, value in window:
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak)
        return {
            "start_at": window[0][0].isoformat(),
            "end_at": window[-1][0].isoformat(),
            "net_return": str(window[-1][1] / window[0][1] - 1),
            "max_drawdown": str(drawdown),
            "sample_count": len(window),
        }

    previous, recent = metrics(samples[: split + 1]), metrics(samples[split:])
    drop = (_number(previous["net_return"]) - _number(recent["net_return"])) * 100
    increase = (_number(recent["max_drawdown"]) - _number(previous["max_drawdown"])) * 100
    reasons = []
    if drop >= policy.threshold_pp:
        reasons.append("return_drop")
    if increase >= policy.threshold_pp:
        reasons.append("drawdown_increase")
    return {
        "previous": previous,
        "recent": recent,
        "return_drop_pp": str(drop),
        "drawdown_increase_pp": str(increase),
        "triggered": bool(reasons),
        "reasons": reasons,
        "threshold_pp": str(policy.threshold_pp),
        "end_at": end.isoformat(),
        "measurement": "hourly_sampled_paper_equity",
    }


def collect_windows(
    client: Any, instance_id: str, strategy_id: str, end: datetime, policy: PaperFeedbackPolicyV1
) -> dict[str, Any]:
    raw = client.paper_snapshot(instance_id=instance_id, strategy_id=int(strategy_id))
    snapshot = raw.get("snapshot", raw)
    if (
        snapshot.get("instance_id") != instance_id
        or str(snapshot.get("strategy_id")) != strategy_id
        or snapshot.get("status") != "running"
    ):
        raise ValueError("paper_identity_or_running_state_mismatch")
    start = end - timedelta(days=14)
    session_start = (snapshot.get("session") or {}).get("started_at")
    if not session_start or _time(session_start) > start:
        raise ValueError("paper_session_younger_than_fourteen_days")
    points: dict[str, dict[str, Any]] = {}
    identity, receipts = None, []
    # The upstream caps RAW samples at 500. Six-hour reads cover minute sampling;
    # denser sources fail closed rather than silently truncating a weekly window.
    for chunk in range(56):
        left = start + timedelta(hours=chunk * 6)
        right = left + timedelta(hours=6)
        page = client.strategy_return_series(
            source_layer="paper",
            source_id=instance_id,
            start_at=left.isoformat(),
            end_at=right.isoformat(),
            bucket_seconds=3600,
            limit=500,
        )
        if (
            page.get("schema_version") != "strategy_return_series.v1"
            or page.get("source_layer") != "paper"
            or page.get("source_id") != instance_id
            or str(page.get("strategy_id")) != strategy_id
            or page.get("bucket_seconds") != 3600
            or page.get("timezone") != "UTC"
            or (page.get("pagination") or {}).get("next_cursor")
            or not page.get("source_hash")
            or not page.get("content_hash")
            or set(page.get("data_gaps", [])) - {"gross_return_unavailable"}
        ):
            raise ValueError("incomplete_or_mismatched_series_contract")
        stamp = {
            k: page.get(k) for k in ("strategy_version", "config_version", "currency", "cost_model")
        }
        if (
            not all(stamp.values())
            or stamp["strategy_version"] != snapshot.get("strategy_version")
            or stamp["config_version"] != snapshot.get("config_version")
            or (identity and stamp != identity)
        ):
            raise ValueError("paper_version_or_cost_changed")
        identity = stamp
        receipts.append(
            {
                "start_at": left.isoformat(),
                "end_at": right.isoformat(),
                "source_hash": page["source_hash"],
                "content_hash": page["content_hash"],
            }
        )
        for point in page.get("points", []):
            if not left <= _time(point["timestamp"]) <= right:
                raise ValueError("point_outside_requested_window")
            point = {"timestamp": point["timestamp"], "equity": point["equity"]}
            old = points.get(point["timestamp"])
            if old is not None and old != point:
                raise ValueError("conflicting_boundary_sample")
            points[point["timestamp"]] = point
    latest_raw = client.paper_snapshot(instance_id=instance_id, strategy_id=int(strategy_id))
    latest = latest_raw.get("snapshot", latest_raw)
    if any(
        latest.get(k) != snapshot.get(k)
        for k in ("instance_id", "strategy_id", "status", "strategy_version", "config_version")
    ):
        raise ValueError("paper_changed_during_collection")
    result = evaluate_windows(
        sorted(points.values(), key=lambda p: _time(p["timestamp"])), end, policy
    )
    return {
        **result,
        "source_id": instance_id,
        "strategy_id": strategy_id,
        "identity": identity,
        "receipts": receipts,
    }


def _negative_experiment_finished(record: dict[str, Any], goal: ARCGoalV1) -> bool:
    from hypertrade.arc.self_test import apply_success_criteria

    if record.get("passed") is not False or not record.get("backtest_id"):
        return False
    metrics = record.get("metrics") or {}
    passed, reasons = apply_success_criteria(metrics, goal.success_criteria)
    if not passed:
        # Missing or invalid evidence is an operator problem, not a settled rejection.
        return bool(reasons) and all("success_criteria." in reason for reason in reasons)
    comparison = metrics.get("baseline_comparison") or {}
    return (
        comparison.get("passed") is False
        and bool(comparison.get("backtest_id"))
        and not comparison.get("reason")
    )


def _feedback_child_active(child: ARCController) -> bool:
    projection = child.projection
    if (
        projection.state in {"failed", "completed"}
        or projection.paper_review.get("status") == "rejected"
    ):
        return False
    if (
        projection.state != "needs_operator"
        or projection.goal is None
        or projection.avo.get("pending")
    ):
        return True
    reason = next(
        (
            event.payload.get("reason")
            for event in reversed(projection.events)
            if event.event_type == "operator_needed"
        ),
        None,
    )
    if reason == "avo_final_validation_failed" and projection.avo.get("final_window_consumed"):
        return not any(
            _negative_experiment_finished(record, projection.goal)
            for record in projection.self_test_records[-1:]
        )
    if (
        reason == "avo_no_candidate"
        and projection.attempts
        and projection.goal.budget.candidates_used >= projection.goal.budget.max_candidates
    ):
        development = projection.avo.get("development", {})
        return not all(
            _negative_experiment_finished(development.get(attempt.attempt_id, {}), projection.goal)
            for attempt in projection.attempts
        )
    return True


def check_paper_feedback(
    mission_id: str, client: Any = None, now: datetime | None = None
) -> dict[str, Any]:
    parent = get_controller(mission_id)
    if parent is None or parent.projection.goal is None:
        return {"status": "missing"}
    goal = parent.projection.goal
    attempt = paper_attempt(parent)
    if (
        not goal.feedback.enabled
        or not goal.paper_review_required
        or parent.projection.state != "paper_observing"
        or attempt is None
    ):
        return {"status": "skipped"}
    instance_id = str(attempt.paper_instance_id)
    end = (
        (now or datetime.now(UTC))
        .astimezone(UTC)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    with research_lock(f"paper-feedback/{instance_id}") as owner:
        if owner is None:
            return {"status": "busy"}
        parent = get_controller(mission_id)
        assert parent is not None and parent.projection.goal is not None
        state = parent.projection.paper_feedback
        child = get_controller(str(state.get("child_mission_id", "")))
        if child and _feedback_child_active(child):
            return {"status": "child_active", "child_mission_id": child.mission_id}
        if state.get("checked_end_at") == end.isoformat():
            return dict(state)
        try:
            evidence = collect_windows(
                client or BitProToolAdapter(),
                instance_id,
                str(attempt.bitpro_strategy_id),
                end,
                goal.feedback,
            )
        except Exception as exc:
            result: dict[str, Any] = {
                "status": "data_unavailable",
                "reason": str(exc)[:200],
                "checked_end_at": end.isoformat(),
            }
            parent.apply_event("paper_feedback_checked", result)
            return result
        owner()
        result = {
            "status": "degraded" if evidence["triggered"] else "stable",
            "checked_end_at": end.isoformat(),
            "evidence": evidence,
        }
        if evidence["triggered"]:
            key = hashlib.sha256(f"{instance_id}/{end.isoformat()}".encode()).hexdigest()[:24]
            child_id = f"arc_feedback_{key}"
            # Stable child identity repairs a crash after child creation but before parent linking.
            if get_controller(child_id) is None:
                baseline = attempt.model_copy(deep=True)
                baseline.paper_instance_id = None
                baseline.live_instance_id = None
                baseline.observed_metrics = {}
                baseline.bitpro_strategy_id = baseline.bitpro_backtest_id = (
                    baseline.validation_id
                ) = None
                baseline.attempt_id = f"baseline_{key}"
                baseline.candidate_id = f"baseline_{key}"
                baseline.state = "proposed"
                child_goal = goal.model_copy(deep=True)
                child_goal.symbols = [candidate_symbol(baseline.strategy_spec, goal.symbols)]
                child_goal.research_id = child_id
                child_goal.research_mode = "avo"
                child_goal.research_windows = ResearchWindowsV1(
                    as_of=end.date() - timedelta(days=1)
                )
                child_goal.budget = ARCBudgetV1(
                    max_candidates=goal.feedback.research_max_candidates,
                    max_model_calls=goal.feedback.research_max_model_calls,
                    max_backtests=goal.feedback.research_max_backtests,
                )
                child_goal.paper_authorization = None
                child_goal.feedback_parent = {
                    "mission_id": mission_id,
                    "instance_id": instance_id,
                    "evidence": evidence,
                    "baseline": baseline.model_dump(mode="json"),
                }
                child_goal.objective = (
                    "根据原策略最近两周模拟盘退化证据，仅调整同策略族和方向的参数；"
                    "开发回测后提交最终同窗对比，等待人工审核。"
                )
                new = ARCController(
                    mission_id=child_id, goal=ARCGoalV1.model_validate(child_goal.model_dump())
                )
                new.projection.created_by = "paper-feedback-worker"
                save_mission(new)
            result["child_mission_id"] = child_id
        parent.apply_event("paper_feedback_checked", result)
        return result


def compare_backtests(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Same-window Pareto gate; baseline failure does not waive evidence completeness."""
    try:
        old = baseline["metrics"]
        if metrics["evaluation_window"] != old["evaluation_window"]:
            raise ValueError("comparison_window_mismatch")

        def read(row: dict[str, Any], ratio: str, pct: str) -> Decimal:
            return _number(row[ratio]) if ratio in row else _number(row[pct]) / 100

        new_return = read(metrics, "net_return", "total_return_pct")
        old_return = read(old, "net_return", "total_return_pct")
        new_dd = read(metrics, "max_drawdown", "max_drawdown_pct")
        old_dd = read(old, "max_drawdown", "max_drawdown_pct")
        passed = (
            new_return >= old_return
            and new_dd <= old_dd
            and (new_return > old_return or new_dd < old_dd)
        )
        return {
            "passed": passed,
            "backtest_id": baseline["backtest_id"],
            "net_return": str(old_return),
            "max_drawdown": str(old_dd),
        }
    except (KeyError, ValueError, ArithmeticError):
        return {
            "passed": False,
            "backtest_id": baseline.get("backtest_id"),
            "reason": "comparison_evidence_invalid",
        }
