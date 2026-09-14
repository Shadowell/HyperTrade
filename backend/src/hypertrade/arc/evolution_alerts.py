"""Operator-visible evolution alerts — silent stalls are defects.

The 2026-09 production lesson: an 8-hour data gap silently blocked every older
strategy's evidence for two weeks and nothing told the operator. These rules
surface (a) blockers that need a human or upstream fix, (b) evidence that
cannot be built at all and persists past the stall horizon, and (c)
consecutive failed scan cycles. Alert rows are the durable record whether or
not delivery is configured; delivery reuses the existing Feishu webhook.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from hypertrade.arc.evolution_continuation import blocker_resolution
from hypertrade.arc.evolution_models import EvolutionAlert, EvolutionCycle
from hypertrade.db import Database

ALERT_OPERATOR_BLOCKED = "evolution_blocked_needs_operator"
ALERT_STALLED = "evolution_evidence_stalled"
ALERT_CYCLES_ERRORING = "evolution_cycles_erroring"

STALL_AFTER_HOURS = 72
ERROR_STREAK = 3
RETRY_AFTER_HOURS = 6
RETRY_WINDOW_DAYS = 7

_LABELS = {
    ALERT_OPERATOR_BLOCKED: "存在需要人工处理的阻塞",
    ALERT_STALLED: "证据无法构建且已持续超过 72 小时",
    ALERT_CYCLES_ERRORING: "进化扫描周期连续报错",
}

Poster = Callable[[str, dict[str, Any]], None]


def alert_id(code: str, strategy_id: int | None = None) -> str:
    seed = f"{code}:{strategy_id if strategy_id is not None else 'global'}"
    return "evoalert_" + hashlib.sha256(seed.encode()).hexdigest()[:24]


def _row_strategies(payload: dict[str, Any]) -> int | None:
    value = payload.get("strategy_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _blocker_resolutions(payload: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    sampling_reason = (
        (payload.get("evidence_cursor") or {}).get("sampling") or {}
    ).get("reason_code")
    result = []
    for blocker in payload.get("blockers") or []:
        if not isinstance(blocker, dict):
            continue
        resolution = str(
            blocker.get("resolution")
            or blocker_resolution(str(blocker.get("code")), sampling_reason=sampling_reason)
        )
        result.append((blocker, resolution))
    return result


def _desired_alerts(
    continuations: list[dict[str, Any]], cycle_rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Deterministic id -> condition snapshot for every alert that should exist."""
    desired: dict[str, dict[str, Any]] = {}
    seen_strategies: set[int] = set()
    for row in continuations:
        strategy_id = _row_strategies(row)
        if strategy_id is None or strategy_id in seen_strategies:
            continue
        seen_strategies.add(strategy_id)
        pairs = _blocker_resolutions(row)
        operator_codes = sorted(
            {str(b.get("code")) for b, resolution in pairs if resolution == "operator"}
        )
        if operator_codes:
            key = alert_id(ALERT_OPERATOR_BLOCKED, strategy_id)
            desired[key] = {
                "code": ALERT_OPERATOR_BLOCKED,
                "severity": "warning",
                "strategy_id": strategy_id,
                "message": (
                    f"策略 {strategy_id} 存在需要人工处理的阻塞：{', '.join(operator_codes)}"
                ),
                "tracking_only": False,
                "signature": "|".join(operator_codes),
            }
            # The operator page already explains why this strategy is stuck;
            # a second stall-tracking alert for the same source is pure noise.
            continue
        stalled = [
            b
            for b, resolution in pairs
            if resolution == "time"
            and str(b.get("code")) == "evidence_recheck"
            and not row.get("next_eligible_at")
        ]
        if stalled:
            key = alert_id(ALERT_STALLED, strategy_id)
            desired[key] = {
                "code": ALERT_STALLED,
                "severity": "warning",
                "strategy_id": strategy_id,
                "message": (
                    f"策略 {strategy_id} 的证据窗口无法构建且没有可预计的资格时间"
                    "（数据缺口或上游读取失败），超过 72 小时仍未恢复"
                ),
                "tracking_only": True,
                "signature": "evidence_recheck",
            }
    if len(cycle_rows) >= ERROR_STREAK and all(
        str(row.get("status")) == "error" for row in cycle_rows[:ERROR_STREAK]
    ):
        desired[alert_id(ALERT_CYCLES_ERRORING)] = {
            "code": ALERT_CYCLES_ERRORING,
            "severity": "critical",
            "strategy_id": None,
            "message": f"进化扫描最近 {ERROR_STREAK} 个周期全部以 error 结束，请检查 worker 与上游",
            "tracking_only": False,
            "signature": ",".join(str(row.get("id")) for row in cycle_rows[:ERROR_STREAK]),
        }
    return desired


def _default_post(url: str, payload: dict[str, Any]) -> None:
    import httpx

    response = httpx.post(url, json=payload, timeout=10)
    response.raise_for_status()


def _deliver(
    block: dict[str, Any], now: datetime, *, post: Poster | None
) -> tuple[bool, str]:
    from hypertrade.config import get_settings

    webhook = str(getattr(get_settings(), "feishu_webhook_url", "") or "").strip()
    if not webhook:
        return False, "skipped_no_webhook"
    text = f"[HyperTrade 进化告警] {_LABELS.get(block['code'], block['code'])}\n{block['message']}"
    sender = post or _default_post
    try:
        sender(webhook, {"msg_type": "text", "content": {"text": text[:3900]}})
    except Exception as exc:  # noqa: BLE001 - delivery failure must never crash the loop
        return False, f"failed:{type(exc).__name__}"
    return True, "sent"


def evolution_alerts_once(
    db: Database, *, now: datetime | None = None, post: Poster | None = None
) -> dict[str, Any]:
    """Evaluate alert conditions, update the ledger, then deliver new alerts."""
    now = now or datetime.now(UTC)
    from hypertrade.arc.evolution_continuation import ContinuationLedger

    continuations = ContinuationLedger(db).view()
    with db.session() as session:
        cycle_rows = [
            {"id": row.id, "status": row.status}
            for row in session.scalars(
                select(EvolutionCycle)
                .where(EvolutionCycle.status.not_in(["budget_admitted", "budget_denied"]))
                .order_by(EvolutionCycle.created_at.desc())
                .limit(ERROR_STREAK)
            )
        ]
    desired = _desired_alerts(continuations, cycle_rows)

    opened = resolved = tracking = delivered = failed = 0
    with db.session() as session:
        existing = {
            row.id: row
            for row in session.scalars(
                select(EvolutionAlert).with_for_update()
            ).all()
        }
        for key, block in desired.items():
            row = existing.get(key)
            if row is None:
                status = "tracking" if block["tracking_only"] else "open"
                session.add(
                    EvolutionAlert(
                        id=key,
                        code=block["code"],
                        severity=block["severity"],
                        strategy_id=block["strategy_id"],
                        message=block["message"],
                        status=status,
                        payload_json={
                            "first_seen_at": now.isoformat(),
                            "last_seen_at": now.isoformat(),
                            "signature": block["signature"],
                        },
                    )
                )
                if status == "open":
                    opened += 1
                else:
                    tracking += 1
            else:
                payload = dict(row.payload_json or {})
                payload["last_seen_at"] = now.isoformat()
                payload["signature"] = block["signature"]
                row.payload_json = payload
                if row.status in {"resolved"}:
                    row.status = "open" if not block["tracking_only"] else "tracking"
                    row.delivered_at = None
                    row.delivery_result = ""
                    if row.status == "open":
                        opened += 1
                    else:
                        tracking += 1
                elif row.status == "tracking" and not block["tracking_only"]:
                    row.status = "open"
                    opened += 1
                elif (
                    row.status == "tracking"
                    and block["tracking_only"]
                    and now - _aware(row.created_at) >= timedelta(hours=STALL_AFTER_HOURS)
                ):
                    row.status = "open"
                    hours = int((now - _aware(row.created_at)).total_seconds() // 3600)
                    row.message = f"{block['message']}（已持续约 {hours} 小时）"
                    opened += 1
        for key, row in existing.items():
            if key not in desired and row.status in {"open", "tracking", "acknowledged"}:
                row.status = "resolved"
                resolved += 1
        session.flush()
        # Deliver any open, not-yet-delivered alert (new or retried), bounded by
        # a retry cadence and a give-up window.
        open_rows = session.scalars(
            select(EvolutionAlert)
            .where(EvolutionAlert.status == "open", EvolutionAlert.delivered_at.is_(None))
            .with_for_update()
        ).all()
        for row in open_rows:
            payload = dict(row.payload_json or {})
            if now - _aware(row.created_at) > timedelta(days=RETRY_WINDOW_DAYS):
                continue
            last_attempt = payload.get("last_attempt_at")
            if isinstance(last_attempt, str):
                try:
                    attempt_at = datetime.fromisoformat(last_attempt)
                    if now - attempt_at < timedelta(hours=RETRY_AFTER_HOURS):
                        continue
                except ValueError:
                    pass
            payload["last_attempt_at"] = now.isoformat()
            ok, result = _deliver({"code": row.code, "message": row.message}, now, post=post)
            row.payload_json = payload
            row.delivery_result = result
            if ok:
                row.delivered_at = now
                delivered += 1
            elif result.startswith("failed"):
                failed += 1
    return {
        "status": "ok",
        "opened": opened,
        "resolved": resolved,
        "tracking": tracking,
        "delivered": delivered,
        "failed": failed,
    }


def acknowledge_alert(db: Database, alert_id: str, *, actor: str) -> dict[str, Any]:
    with db.session() as session:
        row = session.get(EvolutionAlert, alert_id, with_for_update=True)
        if row is None:
            raise KeyError(alert_id)
        payload = dict(row.payload_json or {})
        payload["acknowledged_by"] = actor
        payload["acknowledged_at"] = datetime.now(UTC).isoformat()
        row.payload_json = payload
        if row.status in {"open", "tracking"}:
            row.status = "acknowledged"
        session.flush()
        return {
            "id": row.id,
            "code": row.code,
            "status": row.status,
            "strategy_id": row.strategy_id,
        }


def list_alerts(db: Database, *, limit: int = 50) -> list[dict[str, Any]]:
    with db.session() as session:
        rows = session.scalars(
            select(EvolutionAlert)
            .order_by(EvolutionAlert.created_at.desc())
            .limit(max(1, min(limit, 200)))
        ).all()
        return [
            {
                "id": row.id,
                "code": row.code,
                "severity": row.severity,
                "strategy_id": row.strategy_id,
                "message": row.message,
                "status": row.status,
                "delivery_result": row.delivery_result,
                "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
                "created_at": _aware(row.created_at).isoformat(),
                **(row.payload_json or {}),
            }
            for row in rows
        ]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
