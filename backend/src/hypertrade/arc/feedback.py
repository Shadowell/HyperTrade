"""Paper-only degradation evidence and idempotent parameter research; never mutate the source."""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCGoalV1,
    PaperFeedbackPolicyV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.observation import paper_attempt
from hypertrade.arc.store import get_controller, research_lock
from hypertrade.arc.universe import candidate_symbols, declared_symbols
from hypertrade.bitpro.mcp import BitProToolAdapter
from hypertrade.bitpro.paced_reads import PacedReadClient
from hypertrade.targets.calendar import completed_session_window
from hypertrade.targets.ports import SessionCalendarEvidence
from hypertrade.targets.read_ports import BitProReadPorts, read_ports
from hypertrade.targets.schemas import TargetCalendarV1


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
    points: list[dict[str, Any]],
    end: datetime,
    policy: PaperFeedbackPolicyV1,
    *,
    benchmark: dict[str, Any] | None = None,
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
    basis, trig_drop, trig_inc = "absolute", drop, increase
    reason_drop, reason_inc = "return_drop", "drawdown_increase"
    benchmark_block = None
    relative_drop = relative_increase = None
    if benchmark is not None:
        benchmark_block = {k: v for k, v in benchmark.items() if k != "points"}
        if benchmark.get("status") == "observed" and policy.benchmark_relative:
            try:
                halves = _benchmark_halves(
                    benchmark["points"],
                    float(benchmark.get("tolerance_seconds") or 3600),
                    start,
                    middle,
                    end,
                )
                benchmark_block.update(halves)
                relative_drop = drop - _number(halves["return_drop_pp"])
                relative_increase = increase - _number(halves["drawdown_increase_pp"])
                basis = "benchmark_relative"
                trig_drop, trig_inc = relative_drop, relative_increase
                reason_drop, reason_inc = "relative_return_drop", "relative_drawdown_increase"
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                benchmark_block["status"] = str(exc) or "benchmark_misaligned"
    reasons = []
    if trig_drop >= policy.threshold_pp:
        reasons.append(reason_drop)
    if trig_inc >= policy.threshold_pp:
        reasons.append(reason_inc)
    result: dict[str, Any] = {
        "previous": previous,
        "recent": recent,
        "return_drop_pp": str(drop),
        "drawdown_increase_pp": str(increase),
        "degradation_basis": basis,
        "triggered": bool(reasons),
        "reasons": reasons,
        "threshold_pp": str(policy.threshold_pp),
        "end_at": end.isoformat(),
        "measurement": "hourly_sampled_paper_equity",
    }
    if benchmark_block is not None:
        result["benchmark"] = benchmark_block
    if relative_drop is not None and relative_increase is not None:
        result["relative_return_drop_pp"] = str(relative_drop)
        result["relative_drawdown_increase_pp"] = str(relative_increase)
    return result


_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}

# Upstream caps a single kline page at 1000 rows. Short strategy periods use
# closed hourly bars for the market benchmark; their own research period stays intact.
_KLINE_PAGE_LIMIT = 1000


def _timeframe_seconds(timeframe: str) -> int | None:
    return _TIMEFRAME_SECONDS.get(str(timeframe or "").strip().lower())


def _benchmark_series(
    client: Any, symbols: list[str], timeframe: str, start: datetime, end: datetime
) -> dict[str, Any]:
    """Buy-and-hold benchmark from closes known at each hourly boundary.

    One symbol uses its own closes; a portfolio benchmark is the equal-weight
    composite of every member's normalized closes (base 100), aligned on the
    shared bar grid. Any member that cannot be built fails the whole benchmark
    (annotated fallback), never a silently partial basket.
    """
    if not symbols:
        return {"status": "unsupported_symbols"}
    strategy_seconds = _timeframe_seconds(timeframe)
    if strategy_seconds is None:
        return {"status": "unsupported_timeframe", "symbols": list(symbols), "timeframe": timeframe}
    benchmark_timeframe = "1h" if strategy_seconds <= 3600 else timeframe.strip().lower()
    seconds = _timeframe_seconds(benchmark_timeframe)
    assert seconds is not None
    span = (end - start).total_seconds()
    if span <= 0 or span % seconds:
        return {
            "status": "window_misaligned",
            "symbols": list(symbols),
            "timeframe": timeframe,
            "benchmark_timeframe": benchmark_timeframe,
        }
    needed = int(span // seconds) + 1
    if needed > _KLINE_PAGE_LIMIT:
        return {
            "status": "insufficient_coverage",
            "symbols": list(symbols),
            "timeframe": timeframe,
            "benchmark_timeframe": benchmark_timeframe,
        }
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    step_ms = seconds * 1000
    # OHLCV timestamps mark bar OPEN. The value at boundary B is the close of
    # [B-period, B), never the close of a bar opening at B.
    expected_opens = list(range(start_ms - step_ms, end_ms, step_ms))
    normalized: list[dict[str, float]] = []
    for symbol in symbols:
        try:
            payload = client.market_klines(
                symbol=symbol,
                timeframe=benchmark_timeframe,
                limit=needed,
                start_ms=start_ms - step_ms,
                end_ms=end_ms - 1,
            )
        except Exception:  # noqa: BLE001 - benchmark absence must not stall the strategy read
            return {
                "status": "unavailable",
                "symbols": list(symbols),
                "timeframe": timeframe,
                "benchmark_timeframe": benchmark_timeframe,
            }
        candles = payload.get("candles") if isinstance(payload, dict) else None
        if not isinstance(candles, list) or len(candles) != needed:
            return {
                "status": "incomplete_grid",
                "symbols": list(symbols),
                "timeframe": timeframe,
                "benchmark_timeframe": benchmark_timeframe,
            }
        closes: dict[int, float] = {}
        for row in candles:
            if not isinstance(row, dict):
                return {
                    "status": "invalid_candle",
                    "symbols": list(symbols),
                    "timeframe": timeframe,
                    "benchmark_timeframe": benchmark_timeframe,
                }
            stamp = row.get("timestamp") or row.get("ts") or row.get("time")
            try:
                if stamp is None or isinstance(stamp, bool):
                    raise ValueError("missing or boolean timestamp")
                stamp_number = float(stamp)
                if not math.isfinite(stamp_number) or not stamp_number.is_integer():
                    raise ValueError("nonintegral timestamp")
                ms = int(stamp_number)
                if ms < 10_000_000_000:
                    ms = ms * 1000
                if isinstance(row["close"], bool):
                    raise ValueError("boolean close")
                close = float(row["close"])
            except (TypeError, ValueError, KeyError, OverflowError):
                return {
                    "status": "invalid_candle",
                    "symbols": list(symbols),
                    "timeframe": timeframe,
                    "benchmark_timeframe": benchmark_timeframe,
                }
            if not math.isfinite(close) or close <= 0 or ms in closes:
                return {
                    "status": "invalid_candle",
                    "symbols": list(symbols),
                    "timeframe": timeframe,
                    "benchmark_timeframe": benchmark_timeframe,
                }
            closes[ms] = close
        if list(closes) != expected_opens:
            return {
                "status": "incomplete_grid",
                "symbols": list(symbols),
                "timeframe": timeframe,
                "benchmark_timeframe": benchmark_timeframe,
            }
        base = closes[expected_opens[0]]
        normalized.append(
            {
                datetime.fromtimestamp((ms + step_ms) / 1000, UTC).isoformat(): closes[ms]
                / base
                * 100.0
                for ms in expected_opens
            }
        )
    merged: dict[str, list[float]] = {}
    for series in normalized:
        for stamp, value in series.items():
            merged.setdefault(stamp, []).append(value)
    points = [
        {"timestamp": stamp, "equity": sum(values) / len(values)}
        for stamp, values in sorted(merged.items())
    ]
    if len(points) < 3:
        return {"status": "unavailable", "symbols": list(symbols), "timeframe": timeframe}
    block: dict[str, Any] = {
        "status": "observed",
        "symbols": list(symbols),
        "timeframe": timeframe,
        "benchmark_timeframe": benchmark_timeframe,
        "price_time_semantics": "close_of_bar_ending_at_boundary",
        "tolerance_seconds": seconds,
        "points": points,
    }
    if len(symbols) == 1:
        block["symbol"] = symbols[0]
    return block


def _benchmark_halves(
    points: list[dict[str, Any]],
    tolerance_seconds: float,
    start: datetime,
    middle: datetime,
    end: datetime,
) -> dict[str, str]:
    samples = sorted((_time(p["timestamp"]), _number(p["equity"])) for p in points)
    if len(samples) < 3:
        raise ValueError("benchmark_insufficient")

    def boundary(target: datetime) -> None:
        nearest = min(samples, key=lambda s: abs((s[0] - target).total_seconds()))
        if abs((nearest[0] - target).total_seconds()) > tolerance_seconds:
            raise ValueError("benchmark_misaligned")

    for target in (start, middle, end):
        boundary(target)

    def half(rows: list[tuple[datetime, Decimal]]) -> dict[str, Decimal]:
        if not rows:
            raise ValueError("benchmark_insufficient")
        peak, drawdown = rows[0][1], Decimal(0)
        for _, value in rows:
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak)
        return {
            "net_return": rows[-1][1] / rows[0][1] - 1,
            "max_drawdown": drawdown,
        }

    previous = half([s for s in samples if start <= s[0] <= middle])
    recent = half([s for s in samples if middle <= s[0] <= end])
    return {
        "previous_net_return": str(previous["net_return"]),
        "recent_net_return": str(recent["net_return"]),
        "return_drop_pp": str((previous["net_return"] - recent["net_return"]) * 100),
        "drawdown_increase_pp": str((recent["max_drawdown"] - previous["max_drawdown"]) * 100),
    }


def collect_windows(
    client: Any,
    instance_id: str,
    strategy_id: str,
    end: datetime,
    policy: PaperFeedbackPolicyV1,
    *,
    benchmark_symbols: list[str] | None = None,
    timeframe: str | None = None,
    calendar: TargetCalendarV1 | None = None,
) -> dict[str, Any]:
    if calendar is not None and calendar.mode == "sessions":
        return _collect_session_windows(
            read_ports(client), instance_id, strategy_id, end, policy, calendar
        )
    ports = read_ports(client)
    snapshot = (
        ports.get_session_snapshot(instance_id=instance_id, strategy_id=strategy_id).source or {}
    )
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
        page_record = ports.read_equity_series(
            instance_id,
            start_ms=int(left.timestamp() * 1000),
            end_ms=int(right.timestamp() * 1000),
            bucket_seconds=3600,
            limit=500,
        )
        page = page_record.raw or {}
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
    latest = (
        ports.get_session_snapshot(instance_id=instance_id, strategy_id=strategy_id).source or {}
    )
    if any(
        latest.get(k) != snapshot.get(k)
        for k in ("instance_id", "strategy_id", "status", "strategy_version", "config_version")
    ):
        raise ValueError("paper_changed_during_collection")
    benchmark = None
    if policy.benchmark_relative and benchmark_symbols:
        if timeframe:
            benchmark_client = ports.client if isinstance(ports, BitProReadPorts) else client
            benchmark = _benchmark_series(
                benchmark_client, benchmark_symbols, timeframe, start, end
            )
        else:
            benchmark = {"status": "unknown_timeframe", "symbols": list(benchmark_symbols)}
    result = evaluate_windows(
        sorted(points.values(), key=lambda p: _time(p["timestamp"])),
        end,
        policy,
        benchmark=benchmark,
    )
    return {
        **result,
        "source_id": instance_id,
        "strategy_id": strategy_id,
        "identity": identity,
        "receipts": receipts,
    }


def _collect_session_windows(
    ports: Any,
    instance_id: str,
    strategy_id: str,
    now: datetime,
    policy: PaperFeedbackPolicyV1,
    calendar: TargetCalendarV1,
) -> dict[str, Any]:
    """Require a complete exchange calendar and per-point trading-day evidence."""
    if not callable(getattr(ports, "list_trading_sessions", None)):
        raise ValueError("session_calendar_evidence_missing")
    tz = ZoneInfo(calendar.timezone)
    local_end = now.astimezone(tz).date()
    requested_start = local_end - timedelta(days=90)
    calendar_evidence: SessionCalendarEvidence = ports.list_trading_sessions(
        start_date=requested_start.isoformat(), end_date=local_end.isoformat()
    )
    if (
        calendar_evidence.start_date != requested_start.isoformat()
        or calendar_evidence.end_date != local_end.isoformat()
    ):
        raise ValueError("session_calendar_coverage_missing")
    window = completed_session_window(calendar, calendar_evidence, now)
    baseline_open, _ = window.bounds(window.baseline_day)
    initial = ports.get_session_snapshot(strategy_id=strategy_id, instance_id=instance_id)
    if (
        initial.strategy_id != strategy_id
        or initial.instance_id != instance_id
        or initial.status != "running"
        or not initial.strategy_version
        or not initial.config_version
        or initial.session_started_at is None
        or initial.session_started_at.tzinfo is None
        or initial.session_started_at.astimezone(UTC) > baseline_open
    ):
        raise ValueError("paper_identity_or_session_window_mismatch")
    receipts: list[dict[str, Any]] = []
    day_points: list[list[tuple[datetime, Decimal]]] = []
    baseline_points: list[tuple[datetime, Decimal]] | None = None
    baseline_receipt: dict[str, Any] | None = None
    currency = cost_model = None
    for day in (window.baseline_day, *window.dates):
        opening, closing = window.bounds(day)
        page = ports.read_equity_series(
            instance_id,
            start_ms=int(opening.timestamp() * 1000),
            end_ms=int(closing.timestamp() * 1000),
            bucket_seconds=calendar.evidence_bucket_seconds,
            limit=500,
        )
        if (
            not page.complete
            or page.next_cursor
            or not page.source_hash
            or not page.content_hash
            or page.data_gaps
            or page.strategy_id != strategy_id
            or page.strategy_version != initial.strategy_version
            or page.config_version != initial.config_version
            or page.timezone != calendar.timezone
            or not page.currency
            or not page.cost_model
        ):
            raise ValueError("incomplete_or_mismatched_series_contract")
        if currency is None:
            currency, cost_model = page.currency, page.cost_model
        elif (page.currency, page.cost_model) != (currency, cost_model):
            raise ValueError("paper_version_or_cost_changed")
        samples: list[tuple[datetime, Decimal]] = []
        for point in page.points:
            stamp = datetime.fromtimestamp(point.ts_ms / 1000, UTC)
            if (
                point.trading_day != day.isoformat()
                or stamp.astimezone(tz).date() != day
                or not opening <= stamp <= closing
            ):
                raise ValueError("trading_day_evidence_mismatch")
            samples.append((stamp, _number(point.equity)))
        if (
            len(samples) < 2
            or samples != sorted(samples)
            or len({stamp for stamp, _ in samples}) != len(samples)
            or samples[0][0] != opening
            or samples[-1][0] != closing
            or any(value <= 0 for _, value in samples)
        ):
            raise ValueError("incomplete_session_boundaries")
        if any(
            not 0 < (right[0] - left[0]).total_seconds() <= policy.max_gap_seconds
            for left, right in zip(samples, samples[1:], strict=False)
        ):
            raise ValueError("duplicate_or_missing_samples")
        receipt = {
            "trading_day": day.isoformat(),
            "start_at": opening.isoformat(),
            "end_at": closing.isoformat(),
            "source_hash": page.source_hash,
            "content_hash": page.content_hash,
        }
        if day == window.baseline_day:
            baseline_points, baseline_receipt = samples, receipt
        else:
            day_points.append(samples)
            receipts.append(receipt)
    latest = ports.get_session_snapshot(strategy_id=strategy_id, instance_id=instance_id)
    if any(
        getattr(latest, field) != getattr(initial, field)
        for field in ("instance_id", "strategy_id", "status", "strategy_version", "config_version")
    ):
        raise ValueError("paper_changed_during_collection")

    def metrics(samples: list[tuple[datetime, Decimal]]) -> dict[str, Any]:
        peak, drawdown = samples[0][1], Decimal(0)
        for _, value in samples:
            peak = max(peak, value)
            drawdown = max(drawdown, (peak - value) / peak)
        return {
            "start_at": samples[0][0].isoformat(),
            "end_at": samples[-1][0].isoformat(),
            "net_return": str(samples[-1][1] / samples[0][1] - 1),
            "max_drawdown": str(drawdown),
            "sample_count": len(samples),
        }

    if not baseline_points or not baseline_receipt:
        raise ValueError("session_baseline_close_missing")
    half = len(day_points) // 2
    previous_points = [baseline_points[-1]] + [
        point for points in day_points[:half] for point in points
    ]
    recent_points = [day_points[half - 1][-1]] + [
        point for points in day_points[half:] for point in points
    ]
    previous, recent = metrics(previous_points), metrics(recent_points)
    drop = (_number(previous["net_return"]) - _number(recent["net_return"])) * 100
    increase = (_number(recent["max_drawdown"]) - _number(previous["max_drawdown"])) * 100
    reasons = [
        name
        for name, value in (("return_drop", drop), ("drawdown_increase", increase))
        if value >= policy.threshold_pp
    ]
    return {
        "previous": previous,
        "recent": recent,
        "return_drop_pp": str(drop),
        "drawdown_increase_pp": str(increase),
        "degradation_basis": "absolute",
        "triggered": bool(reasons),
        "reasons": reasons,
        "threshold_pp": str(policy.threshold_pp),
        "end_at": receipts[-1]["end_at"],
        "measurement": "session_paper_equity",
        "source_id": instance_id,
        "strategy_id": strategy_id,
        "identity": {
            "strategy_version": initial.strategy_version,
            "config_version": initial.config_version,
            "currency": currency,
            "cost_model": cost_model,
        },
        "calendar": {
            "timezone": calendar.timezone,
            "source_hash": window.source_hash,
            "baseline_trading_day": window.baseline_day.isoformat(),
            "trading_dates": [day.isoformat() for day in window.dates],
        },
        **(
            {"benchmark": {"status": "unsupported_sessions_market_data"}}
            if policy.benchmark_relative
            else {}
        ),
        "receipts": receipts,
        "baseline_receipt": baseline_receipt,
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


_EPOCH_END_REASONS = frozenset(
    {
        "avo_model_budget_exhausted",
        "avo_tool_budget_exhausted",
        "avo_wall_budget_exhausted",
        "avo_context_budget_exhausted",
        "avo_provider_unavailable",
        "avo_no_candidate",
    }
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
    if reason in _EPOCH_END_REASONS:
        # A bounded automatic epoch ends normally; the next eligible window/cooldown may retry.
        # Human review gates Paper approval, not endings that precede any review package;
        # holding the slot for them froze all evolution. The pending-effect check above still
        # prevents unsafe recovery by duplication.
        return False
    if reason == "avo_final_validation_failed" and projection.avo.get("final_window_consumed"):
        return not any(
            _negative_experiment_finished(record, projection.goal)
            for record in projection.self_test_records[-1:]
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
            spec = attempt.strategy_spec if isinstance(attempt.strategy_spec, dict) else {}
            try:
                spec_symbols = candidate_symbols(spec, goal.symbols)
            except ValueError:
                spec_symbols = None
            spec_timeframe = spec.get("timeframe")
            evidence = collect_windows(
                client or BitProToolAdapter(PacedReadClient()),
                instance_id,
                str(attempt.bitpro_strategy_id),
                end,
                goal.feedback,
                benchmark_symbols=spec_symbols,
                timeframe=spec_timeframe if isinstance(spec_timeframe, str) else None,
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
            from hypertrade.arc import store
            from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
            from hypertrade.arc.research_budget import admit

            if store._database is None:
                result.update(status="no_action", reason="durable_budget_unavailable")
                parent.apply_event("paper_feedback_checked", result)
                return result
            # Stable child identity repairs a crash after child creation but before parent linking.
            if get_controller(child_id) is None:
                service = EvolutionService(store._database, client)
                policy = service.status()
                config = EvolutionConfig.model_validate(policy["config"])
                if not config.enabled:
                    result.update(status="no_action", reason="disabled")
                    parent.apply_event("paper_feedback_checked", result)
                    return result
                if (
                    config.strategy_ids
                    and int(attempt.bitpro_strategy_id or 0) not in config.strategy_ids
                ):
                    result.update(status="no_action", reason="outside_strategy_scope")
                    parent.apply_event("paper_feedback_checked", result)
                    return result
                # The legacy feedback producer consumes the same source eligibility contract:
                # session/version/cost/coverage and current-session fills, all read-only.
                diagnostics, context = service._scan(
                    config.model_copy(
                        update={
                            "strategy_ids": [int(attempt.bitpro_strategy_id or 0)],
                            "threshold_pp": goal.feedback.threshold_pp,
                            "proactive_enabled": False,
                        }
                    ),
                    now or datetime.now(UTC),
                )
                if context is None or context["source_instance_id"] != instance_id:
                    result.update(status="no_action", reason="needs_data", diagnostics=diagnostics)
                    parent.apply_event("paper_feedback_checked", result)
                    return result
                if context["source_code_sha256"] != hashlib.sha256(
                    attempt.strategy_code.encode()
                ).hexdigest() or set(declared_symbols(context["baseline"]["strategy_spec"])) != set(
                    candidate_symbols(attempt.strategy_spec, goal.symbols)
                ):
                    result.update(status="no_action", reason="approved_source_changed")
                    parent.apply_event("paper_feedback_checked", result)
                    return result
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
                child_goal.symbols = candidate_symbols(baseline.strategy_spec, goal.symbols)
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
                    "开发回测后提交最终同窗对比，再由配置的审核模式决定是否启动新模拟盘。"
                )
                context["memory"] = service._memory(context, now or datetime.now(UTC))
                child_goal.evolution_context = context
                new = ARCController(mission_id=child_id, goal=child_goal)
                new.projection.created_by = "paper-feedback-worker"
                admission = admit(new, now=now or datetime.now(UTC), revision=policy["revision"])
                result["budget"] = admission
                if not admission["accepted"]:
                    result.update(status="deferred", reason=admission["reason"])
                    parent.apply_event("paper_feedback_checked", result)
                    return result
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
        new_dd = abs(read(metrics, "max_drawdown", "max_drawdown_pct"))
        old_dd = abs(read(old, "max_drawdown", "max_drawdown_pct"))
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
