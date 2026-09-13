"""Read-only evidence diagnostics; never repair or reset a Paper session."""

from datetime import datetime, timedelta
from typing import Any

from hypertrade.arc.feedback import _number, _time
from hypertrade.bitpro.strategy_evidence import _cost_model


def sampling_status(client: Any, snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    """One bounded recent read distinguishes sampling health from 14-day eligibility."""
    result: dict[str, Any] = {
        "state": "unavailable",
        "checked_at": now.isoformat(),
        "historical_window_verified": False,
    }
    instance_id = snapshot.get("instance_id")
    if not instance_id or not snapshot.get("strategy_id"):
        return {**result, "reason_code": "session_identity_missing"}
    try:
        start = max(now - timedelta(hours=6), _time(snapshot["session"]["started_at"]))
        if start >= now:
            raise ValueError("invalid_session_start")
        page = client.strategy_return_series(
            source_layer="paper",
            source_id=instance_id,
            start_at=start.isoformat(),
            end_at=now.isoformat(),
            bucket_seconds=3600,
            limit=500,
        )
        if (
            page.get("schema_version") != "strategy_return_series.v1"
            or page.get("source_layer") != "paper"
            or page.get("source_id") != instance_id
            or str(page.get("strategy_id")) != str(snapshot["strategy_id"])
            or not snapshot.get("strategy_version")
            or not snapshot.get("config_version")
            or page.get("strategy_version") != snapshot["strategy_version"]
            or page.get("config_version") != snapshot["config_version"]
            or page.get("bucket_seconds") != 3600
            or page.get("timezone") != "UTC"
            or not page.get("source_hash")
            or not page.get("content_hash")
            or not page.get("currency")
            or (page.get("pagination") or {}).get("next_cursor")
            or set(page.get("data_gaps", [])) - {"gross_return_unavailable"}
        ):
            raise ValueError("recent_series_contract_mismatch")
        _cost_model(page.get("cost_model"))
        points = page.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= 500:
            raise ValueError("recent_samples_missing")
        stamps = [_time(p["timestamp"]) for p in points]
        if any(_number(p["equity"]) <= 0 for p in points) or any(
            not start <= stamp <= now for stamp in stamps
        ):
            raise ValueError("recent_samples_invalid")
        gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:], strict=False)]
        if any(gap <= 0 for gap in gaps):
            raise ValueError("recent_samples_not_ordered")
        age = (now - stamps[-1]).total_seconds()
        max_gap = max([*gaps, (stamps[0] - start).total_seconds(), age])
        state = "stale" if age > 7200 else "gaps" if max_gap > 7200 else "current"
        return {
            **result,
            "state": state,
            "source_id": instance_id,
            "sample_count": len(points),
            "latest_sample_at": stamps[-1].isoformat(),
            "latest_sample_age_seconds": age,
            "max_gap_seconds": max_gap,
            "source_hash": page["source_hash"],
            "content_hash": page["content_hash"],
        }
    except Exception as exc:
        # Read failure is an observation, not evidence that the sampler itself failed.
        reason = (
            "cost_metadata_unavailable" if "cost model" in str(exc) else "recent_read_unavailable"
        )
        return {**result, "reason_code": reason}


def blocked_data_diagnostic(
    client: Any, snapshot: dict[str, Any], now: datetime, reason: str
) -> dict[str, Any]:
    sampling = sampling_status(client, snapshot, now)
    descriptions = {
        "current": "近期采样正常，仅代表最近6小时",
        "stale": "近期权益采样已超过2小时未更新",
        "gaps": "最近6小时权益采样仍有超过2小时的缺口",
        "unavailable": "近期采样状态尚无法确认",
    }
    action = "保留现有历史，继续积累满足条件的真实样本"
    if sampling.get("reason_code") == "session_identity_missing":
        action = "核对旧Paper的真实会话和版本映射，不重建会话或重置历史"
    elif sampling.get("reason_code") == "cost_metadata_unavailable":
        action = "核对原会话手续费、滑点与资金费元数据，不补造成本"
    elif sampling["state"] in {"stale", "gaps"}:
        action = "检查权益采样与持久化链路，保留原会话及全部历史"
    elif sampling["state"] == "unavailable":
        action = "检查只读数据接口及证据契约；读取失败不等于采样器已停止"
    label = {
        "duplicate_or_missing_samples": "14天权益曲线存在缺口或重复样本",
        "paper_session_younger_than_fourteen_days": "当前Paper会话不足14天",
        "incomplete_window_boundaries": "14天权益曲线边界不完整",
        "missing_week_boundary": "缺少两周之间的权益边界样本",
    }.get(reason, reason)
    return {
        "reason": f"{label}；{descriptions[sampling['state']]}",
        "data_readiness": {"blocking_reason": reason, "sampling": sampling, "next_action": action},
    }
