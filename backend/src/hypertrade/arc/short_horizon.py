"""Observed short shocks can fund research; they never authorize adoption or live trading."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

MEASUREMENT = "short_paper_equity.v1"
LONG_MEASUREMENT = "observed_weekly_returns.v1"


def _time(value: Any) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("short_timestamp_timezone_missing")
    return stamp.astimezone(UTC)


def _seal(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "proof_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def verify_short_trigger(value: Any) -> bool:
    try:
        return bool(
            isinstance(value, dict)
            and value.get("measurement") == MEASUREMENT
            and value.get("triggered") is True
            and value.get("direct_adoption_allowed") is False
            and value.get("proof_hash") == _seal(value)
            and value.get("qualification") in {"elapsed_window", "trade_count"}
            and value.get("source_id")
            and value.get("strategy_id")
            and 1 <= value["observed_hours"] <= 120
            and value["coverage"] >= 0.8
            and value["max_missing_run"] <= 8
            and value["threshold_pp"] > 0
            and value["metrics"]["drawdown_pct"] >= value["threshold_pp"]
            and len(value["receipts"]) == 1
            and value["receipts"][0]["source_hash"]
            and value["receipts"][0]["content_hash"]
        )
    except (KeyError, TypeError, ValueError):
        return False


def collect_short_horizon(
    ports: Any,
    snapshot: dict[str, Any],
    now: datetime,
    *,
    days: int = 3,
    min_trades: int = 10,
    threshold_pp: float = 15.0,
) -> dict[str, Any]:
    """Use actual equity points. Filled display gaps never enter shock metrics."""
    try:
        return _collect(ports, snapshot, now, days, min_trades, threshold_pp)
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        OverflowError,
        InvalidOperation,
    ) as exc:
        reason = str(exc)
        return {
            "measurement": MEASUREMENT,
            "status": "unknown",
            "triggered": False,
            "direct_adoption_allowed": False,
            "reason": reason if reason.startswith("short_") else "short_read_unavailable",
        }
    except Exception:
        return {
            "measurement": MEASUREMENT,
            "status": "unknown",
            "triggered": False,
            "direct_adoption_allowed": False,
            "reason": "short_read_unavailable",
        }


def _collect(
    ports: Any,
    snapshot: dict[str, Any],
    now: datetime,
    days: int,
    min_trades: int,
    threshold_pp: float,
    *,
    allow_long: bool = False,
) -> dict[str, Any]:
    end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    begun = _time(snapshot["session"]["started_at"])
    if (
        not (3 <= days <= 5 or (allow_long and days == 14))
        or min_trades < 10
        or not 0 < threshold_pp <= 100
    ):
        raise ValueError("short_policy_invalid")
    if snapshot.get("status") != "running" or begun > end:
        raise ValueError("short_session_unavailable")
    start = max(end - timedelta(days=days), begun)
    if start.minute or start.second or start.microsecond:
        start = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    hours = int((end - start).total_seconds() / 3600)
    if hours < 1:
        return {
            "measurement": MEASUREMENT,
            "status": "cold_start",
            "triggered": False,
            "alert": False,
            "reason": "short_window_not_yet_observed",
            "direct_adoption_allowed": False,
        }
    instance = str(snapshot["instance_id"])
    sid = str(snapshot["strategy_id"])
    raw = (
        ports.read_equity_series(
            instance,
            start_ms=int(start.timestamp() * 1000),
            end_ms=int(end.timestamp() * 1000),
            bucket_seconds=3600,
            limit=500,
        ).raw
        or {}
    )
    if (
        raw.get("schema_version") != "strategy_return_series.v1"
        or raw.get("source_layer") != "paper"
        or raw.get("source_id") != instance
        or str(raw.get("strategy_id")) != sid
        or raw.get("bucket_seconds") != 3600
        or raw.get("timezone") != "UTC"
        or not raw.get("currency")
        or not raw.get("cost_model")
        or not raw.get("source_hash")
        or not raw.get("content_hash")
        or (raw.get("pagination") or {}).get("next_cursor")
        or set(raw.get("data_gaps") or ()) - {"gross_return_unavailable"}
    ):
        raise ValueError("short_series_contract_invalid")
    for key in ("strategy_version", "config_version"):
        if not snapshot.get(key) or raw.get(key) != snapshot[key]:
            raise ValueError("short_series_identity_mismatch")
    values: dict[datetime, Decimal] = {}
    for point in raw.get("points", []):
        stamp = _time(point["timestamp"])
        equity = Decimal(str(point["equity"]))
        if (
            not start <= stamp <= end
            or stamp.minute
            or stamp.second
            or stamp.microsecond
            or stamp in values
            or not equity.is_finite()
            or equity < 0
        ):
            raise ValueError("short_series_point_invalid")
        values[stamp] = equity
    stamps = sorted(values)
    if (
        len(stamps) < 2
        or stamps[0] - start > timedelta(hours=1)
        or end - stamps[-1] > timedelta(hours=1)
    ):
        raise ValueError("short_series_boundaries_missing")
    if values[stamps[0]] <= 0:
        raise ValueError("short_initial_equity_nonpositive")
    coverage = len(stamps) / (hours + 1)
    missing_run = max(
        int((b - a).total_seconds() / 3600) - 1 for a, b in zip(stamps, stamps[1:], strict=False)
    )
    if coverage < 0.8 or missing_run > 8:
        raise ValueError("short_series_coverage_insufficient")
    latest = ports.get_session_snapshot(instance_id=instance, strategy_id=sid).source or {}
    if any(
        str(latest.get(key)) != str(snapshot.get(key))
        for key in ("instance_id", "strategy_id", "strategy_version", "config_version", "status")
    ):
        raise ValueError("short_source_changed_during_read")
    if _time((latest.get("session") or {}).get("started_at")) != begun:
        raise ValueError("short_source_changed_during_read")
    peak, drawdown = values[stamps[0]], Decimal(0)
    for stamp in stamps:
        equity = values[stamp]
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak * 100)
    net_return = (values[stamps[-1]] / values[stamps[0]] - 1) * 100
    trades = snapshot.get("trade_count")
    if isinstance(trades, bool) or not isinstance(trades, int) or trades < 0:
        raise ValueError("short_trade_count_unknown")
    qualification = (
        "elapsed_window"
        if end - begun >= timedelta(days=days)
        else "trade_count"
        if trades >= min_trades
        else "cold_start"
    )
    alert = drawdown >= Decimal(str(threshold_pp))
    display = []
    previous = values[stamps[0]]
    stamp = stamps[0]
    while stamp <= stamps[-1]:
        previous = values.get(stamp, previous)
        display.append(
            {
                "timestamp": stamp.isoformat(),
                "equity": str(previous),
                "imputed": stamp not in values,
            }
        )
        stamp += timedelta(hours=1)
    result = {
        "measurement": MEASUREMENT,
        "status": "cold_start" if qualification == "cold_start" else "observed",
        "source_id": instance,
        "strategy_id": sid,
        "identity": {
            key: raw[key]
            for key in ("strategy_version", "config_version", "currency", "cost_model")
        },
        "horizon_days": days,
        "observed_hours": (stamps[-1] - stamps[0]).total_seconds() / 3600,
        "start_at": stamps[0].isoformat(),
        "end_at": stamps[-1].isoformat(),
        "requested_start_at": start.isoformat(),
        "requested_end_at": end.isoformat(),
        "trade_count": trades,
        "min_trades": min_trades,
        "qualification": qualification,
        "threshold_pp": float(threshold_pp),
        "coverage": coverage,
        "gap_hours": hours + 1 - len(stamps),
        "max_missing_run": missing_run,
        "alert": bool(alert),
        "triggered": bool(alert and qualification != "cold_start"),
        "metrics": {"return_pct": float(net_return), "drawdown_pct": float(drawdown)},
        "observed_points": [
            {"timestamp": stamp.isoformat(), "equity": str(values[stamp])} for stamp in stamps
        ],
        "display_points": display,
        "measurement_scope": "observed_points_only",
        "direct_adoption_allowed": False,
        "receipts": [
            {
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
                "source_hash": raw["source_hash"],
                "content_hash": raw["content_hash"],
            }
        ],
    }
    result["proof_hash"] = _seal(result)
    return result


def verify_long_trigger(value: Any) -> bool:
    try:
        return bool(
            isinstance(value, dict)
            and value.get("measurement") == LONG_MEASUREMENT
            and value.get("triggered") is True
            and value.get("proof_hash") == _seal(value)
            and value.get("direct_adoption_allowed") is False
            and value["coverage"] >= 0.95
            and value["max_missing_run"] <= 8
            and 334 <= value["observed_hours"] <= 336
            and value["trade_count"] >= value["min_trades"]
            and Decimal(value["return_drop_pp"]) >= Decimal(str(value["threshold_pp"]))
            and value["receipts"][0]["source_hash"]
            and value["receipts"][0]["content_hash"]
        )
    except (ValueError, KeyError, TypeError, InvalidOperation):
        return False


def collect_observed_long_window(
    ports: Any,
    snapshot: dict[str, Any],
    now: datetime,
    *,
    threshold_pp: float = 10,
    min_trades: int = 30,
) -> dict[str, Any]:
    """Fallback diagnostic: real 7+7 boundaries, bounded gaps, no inferred drawdown."""
    try:
        end = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        if (
            _time(snapshot["session"]["started_at"]) > end - timedelta(days=14)
            or snapshot.get("trade_count", 0) < min_trades
        ):
            raise ValueError("long_window_not_mature")
        result = _collect(ports, snapshot, end, 14, min_trades, threshold_pp, allow_long=True)
        if result.get("status") != "observed" or result["coverage"] < 0.95:
            raise ValueError("long_observed_coverage_insufficient")
        points = result["observed_points"]
        middle = end - timedelta(days=7)
        split = next(i for i, p in enumerate(points) if _time(p["timestamp"]) >= middle)
        if (
            split == 0
            or split == len(points) - 1
            or _time(points[split]["timestamp"]) - middle > timedelta(hours=1)
        ):
            raise ValueError("long_week_boundary_missing")
        a, b, c = (Decimal(points[index]["equity"]) for index in (0, split, -1))
        if a <= 0 or b <= 0:
            raise ValueError("long_nonpositive_boundary")
        previous_return, recent_return = b / a - 1, c / b - 1
        drop = (previous_return - recent_return) * 100
        result.update(
            measurement=LONG_MEASUREMENT,
            previous={
                "start_at": points[0]["timestamp"],
                "end_at": points[split]["timestamp"],
                "net_return": str(previous_return),
                "max_drawdown": None,
                "sample_count": split + 1,
            },
            recent={
                "start_at": points[split]["timestamp"],
                "end_at": points[-1]["timestamp"],
                "net_return": str(recent_return),
                "max_drawdown": None,
                "sample_count": len(points) - split,
            },
            return_drop_pp=str(drop),
            drawdown_increase_pp=None,
            degradation_basis="observed_boundary_returns",
            triggered=bool(drop >= Decimal(str(threshold_pp))),
            reasons=["observed_return_drop"] if drop >= Decimal(str(threshold_pp)) else [],
            drawdown_state="unknown_due_to_sampling_gaps",
            benchmark_state="not_used_in_gap_fallback",
        )
        result["proof_hash"] = _seal(result)
        return result
    except Exception:
        return {
            "measurement": LONG_MEASUREMENT,
            "status": "unknown",
            "triggered": False,
            "direct_adoption_allowed": False,
            "reason": "long_observed_window_unavailable",
        }
