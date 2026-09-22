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

from sqlalchemy import case, select

from hypertrade.arc.evolution_continuation import blocker_resolution
from hypertrade.arc.evolution_models import EvolutionAlert, EvolutionControl, EvolutionCycle
from hypertrade.arc.provenance import alert_codes
from hypertrade.db import Database

ALERT_OPERATOR_BLOCKED = "evolution_blocked_needs_operator"
ALERT_STALLED = "evolution_evidence_stalled"
ALERT_CYCLES_ERRORING = "evolution_cycles_erroring"

STALL_AFTER_HOURS = 72
ERROR_STREAK = 3
RETRY_AFTER_HOURS = 6
REMIND_AFTER_HOURS = 24
DELIVERY_RECEIPT_VERSION = "feishu_webhook.v1"
# A continuation older than this belongs to a strategy the scan no longer
# updates (paused/removed); its stale blockers are not an alert condition.
STALE_CONTINUATION_HOURS = 3

_LABELS = {
    ALERT_OPERATOR_BLOCKED: "存在需要人工处理的阻塞",
    ALERT_STALLED: "证据无法构建且已持续超过 72 小时",
    ALERT_CYCLES_ERRORING: "进化扫描周期连续报错",
}

Poster = Callable[[str, dict[str, Any]], None]

_BLOCKER_TEXT = {
    "session_identity": "会话身份或版本无法核对",
    "session_start": "缺少原会话起点",
    "running_state": "原模拟盘运行状态待核对",
    "evidence_recheck": "证据读取或校验未通过",
}
_SOURCE_TEXT = {
    "historical_cost_metadata_missing": "历史成本绑定缺失",
    "invalid_research_costs": "历史成本记录无效",
    "historical_code_version_missing": "历史源码版本缺失",
    "execution_version_unverified": "执行版本未核验",
    "review_binding_invalid": "原会话审核绑定无效",
    "started_at_missing": "原会话起点缺失",
    "source_provenance_unavailable": "来源核验暂不可用",
}
_SAMPLING_TEXT = {
    "source_point_limit_exceeded": (
        "高频采样点数超过上游读取上限",
        "修复上游分桶读取，保留原始采样",
    ),
    "cost_metadata_unavailable": (
        "历史费用或成本身份缺失",
        "核对原会话成本证据，禁止用当前费率补造历史",
    ),
    "session_identity_missing": ("缺少可核验的原会话身份", "核对原实例和版本，禁止重建会话"),
    "recent_series_contract_mismatch": (
        "返回的证据身份或格式不符合契约",
        "核对来源、版本、分页和数据覆盖",
    ),
    "recent_read_unavailable": (
        "上游近期证据读取失败",
        "检查只读接口、认证和数据契约；不代表采样器停机",
    ),
}


class WebhookRejected(RuntimeError):
    """Only a fixed reason/code, never a provider message or webhook URL."""


def _operator_message(row: dict[str, Any], strategy_id: int, codes: list[str]) -> str:
    sampling = (row.get("evidence_cursor") or {}).get("sampling") or {}
    reason = str(sampling.get("reason_code") or "")
    detail, action = _SAMPLING_TEXT.get(
        reason,
        (
            "、".join(
                _SOURCE_TEXT.get(code, _BLOCKER_TEXT.get(code, "需要人工核对的证据阻塞"))
                for code in codes
            ),
            "在自主研究页面核对原会话与数据来源，保留原模拟盘历史",
        ),
    )
    source_details = [_SOURCE_TEXT[code] for code in codes if code in _SOURCE_TEXT]
    if source_details:
        if reason in _SAMPLING_TEXT:
            detail += "；" + "、".join(source_details)
        action += "；核对原会话冻结成本、源码及审核绑定，缺失历史保持未知，禁止补造或重置"
    message = f"策略 {strategy_id}：{detail}\n下一步：{action}"
    if row.get("next_eligible_at"):
        message += f"\n最早时间条件：{row['next_eligible_at']}（还需证据完整）"
    return message


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
    sampling_reason = ((payload.get("evidence_cursor") or {}).get("sampling") or {}).get(
        "reason_code"
    )
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


def _continuation_stale(row: dict[str, Any], now: datetime) -> bool:
    observed = row.get("observed_at")
    if not isinstance(observed, str):
        return False
    try:
        seen_at = datetime.fromisoformat(observed)
    except ValueError:
        return False
    if seen_at.tzinfo is None:
        seen_at = seen_at.replace(tzinfo=UTC)
    return now - seen_at > timedelta(hours=STALE_CONTINUATION_HOURS)


def _first_seen(payload: dict[str, Any], *, fallback: datetime) -> datetime:
    """Episode anchor: when the loop first observed this condition.

    Horizons are measured against the loop's own clock (payload first_seen_at),
    never the DB insert clock: production writes both from the same clock, and
    the anchor must survive clock skew and a resolve-then-reappear cycle
    starting a fresh episode.
    """
    value = payload.get("first_seen_at")
    if isinstance(value, str):
        try:
            seen_at = datetime.fromisoformat(value)
        except ValueError:
            return fallback
        return seen_at if seen_at.tzinfo else seen_at.replace(tzinfo=UTC)
    return fallback


def _desired_alerts(
    continuations: list[dict[str, Any]], cycle_rows: list[dict[str, Any]], now: datetime
) -> dict[str, dict[str, Any]]:
    """Deterministic id -> condition snapshot for every alert that should exist."""
    desired: dict[str, dict[str, Any]] = {}
    seen_strategies: set[int] = set()
    for row in continuations:
        strategy_id = _row_strategies(row)
        if strategy_id is None or strategy_id in seen_strategies:
            continue
        seen_strategies.add(strategy_id)
        if _continuation_stale(row, now):
            continue
        pairs = _blocker_resolutions(row)
        operator_codes = sorted(
            {str(b.get("code")) for b, resolution in pairs if resolution == "operator"}
            | set(alert_codes((row.get("evidence_cursor") or {}).get("source_provenance")))
        )
        if operator_codes:
            key = alert_id(ALERT_OPERATOR_BLOCKED, strategy_id)
            desired[key] = {
                "code": ALERT_OPERATOR_BLOCKED,
                "severity": "warning",
                "strategy_id": strategy_id,
                "message": _operator_message(row, strategy_id, operator_codes),
                "tracking_only": False,
                "signature": "|".join(
                    [
                        *operator_codes,
                        str(
                            ((row.get("evidence_cursor") or {}).get("sampling") or {}).get(
                                "reason_code"
                            )
                            or ""
                        ),
                    ]
                ),
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
            "signature": ALERT_CYCLES_ERRORING,
        }
    return desired


def _default_post(url: str, payload: dict[str, Any]) -> None:
    import httpx

    response = httpx.post(url, json=payload, timeout=10)
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise WebhookRejected("invalid_receipt") from exc
    if not isinstance(body, dict):
        raise WebhookRejected("invalid_receipt")
    codes = [body[key] for key in ("code", "StatusCode") if key in body]
    if not codes or any(type(code) is not int for code in codes):
        raise WebhookRejected("invalid_receipt")
    rejected = next((code for code in codes if code != 0), None)
    if rejected is not None:
        raise WebhookRejected(f"business_code_{rejected}")


def _deliver(block: dict[str, Any], now: datetime, *, post: Poster | None) -> tuple[bool, str]:
    from hypertrade.config import get_settings

    webhook = str(getattr(get_settings(), "feishu_webhook_url", "") or "").strip()
    if not webhook:
        return False, "skipped_no_webhook"
    text = f"[HyperTrade 进化告警] {_LABELS.get(block['code'], block['code'])}\n{block['message']}"
    text += (
        f"\n首次发现：{block.get('first_seen_at', now.isoformat())}"
        f"\n最近检查：{block.get('last_seen_at', now.isoformat())}"
        "\n未解决且未确认将每天提醒；请在 BitPro 自主研究页面查看和确认。"
    )
    sender = post or _default_post
    try:
        sender(webhook, {"msg_type": "text", "content": {"text": text[:3900]}})
    except WebhookRejected as exc:
        return False, f"failed:{exc}"
    except Exception as exc:  # noqa: BLE001 - delivery failure must never crash the loop
        return False, f"failed:{type(exc).__name__}"
    return True, "sent"


def _alert_continuations(db: Database, now: datetime) -> list[dict[str, Any]]:
    """A fresh preview may refresh alerts, never research admission or its ledger."""
    from hypertrade.arc.evolution_continuation import ContinuationLedger

    rows = ContinuationLedger(db).view()
    with db.session() as session:
        control = session.get(EvolutionControl, "global")
        preview = session.scalar(
            select(EvolutionCycle)
            .where(EvolutionCycle.status == "preview_complete")
            .order_by(EvolutionCycle.created_at.desc())
            .limit(1)
        )
        if (
            control is None
            or preview is None
            or not control.config_json.get("enabled", True)
            or preview.payload_json.get("revision") != control.revision
        ):
            return rows
        diagnostics = (preview.payload_json or {}).get("diagnostics") or []

    latest: dict[int, datetime] = {}
    for row in rows:
        sid = _row_strategies(row)
        try:
            observed = _aware(datetime.fromisoformat(row["observed_at"]))
        except (KeyError, ValueError, TypeError):
            continue
        if sid is not None and (sid not in latest or observed > latest[sid]):
            latest[sid] = observed
    overrides = []
    for diagnostic in diagnostics:
        sid = _row_strategies(diagnostic)
        state = diagnostic.get("continuation")
        if sid is None or not isinstance(state, dict):
            continue
        try:
            observed = _aware(datetime.fromisoformat(state["observed_at"]))
        except (KeyError, ValueError, TypeError):
            continue
        if not timedelta(0) <= now - observed <= timedelta(hours=STALE_CONTINUATION_HOURS) or (
            sid in latest and observed <= latest[sid]
        ):
            continue
        overrides.append({**state, "strategy_id": sid})
        latest[sid] = observed
    replaced = {_row_strategies(row) for row in overrides}
    return overrides + [row for row in rows if _row_strategies(row) not in replaced]


def evolution_alerts_once(
    db: Database, *, now: datetime | None = None, post: Poster | None = None
) -> dict[str, Any]:
    """Evaluate alert conditions, update the ledger, then deliver new alerts."""
    now = now or datetime.now(UTC)
    continuations = _alert_continuations(db, now)
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
    desired = _desired_alerts(continuations, cycle_rows, now)

    opened = resolved = tracking = delivered = failed = 0
    with db.session() as session:
        existing = {
            row.id: row for row in session.scalars(select(EvolutionAlert).with_for_update()).all()
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
                changed = payload.get("signature") != block["signature"]
                payload["last_seen_at"] = now.isoformat()
                payload["signature"] = block["signature"]
                row.payload_json = payload
                if not block["tracking_only"]:
                    row.message = block["message"]
                if row.status == "resolved" or (row.status == "acknowledged" and changed):
                    # A reappearing condition is a new episode: reset the anchor
                    # so horizons are not inherited from the old episode.
                    payload["first_seen_at"] = now.isoformat()
                    for field in (
                        "last_attempt_at",
                        "acknowledged_at",
                        "acknowledged_by",
                        "delivery_count",
                        "delivery_receipt_version",
                        "delivery_business_code",
                    ):
                        payload.pop(field, None)
                    row.payload_json = dict(payload)
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
                elif row.status == "tracking" and block["tracking_only"]:
                    since = _first_seen(payload, fallback=_aware(row.created_at))
                    hours = int((now - since).total_seconds() // 3600)
                    if hours >= STALL_AFTER_HOURS:
                        row.status = "open"
                        row.message = f"{block['message']}（已持续约 {hours} 小时）"
                        opened += 1
        for key, row in existing.items():
            if key not in desired and row.status in {"open", "tracking", "acknowledged"}:
                row.status = "resolved"
                resolved += 1
        session.flush()
        # A provider receipt proves acceptance, not that the operator saw it.
        # Keep reminding until acknowledgement/recovery, including after restarts.
        open_rows = session.scalars(
            select(EvolutionAlert).where(EvolutionAlert.status == "open").with_for_update()
        ).all()
        for row in open_rows:
            payload = dict(row.payload_json or {})
            if row.delivered_at and now - _aware(row.delivered_at) < timedelta(
                hours=REMIND_AFTER_HOURS
            ):
                continue
            # "Webhook not configured" is a configuration state, not a failed
            # attempt: once the webhook appears, delivery must not wait out the
            # retry cadence. Applies to rows written before this distinction.
            previously_skipped = str(row.delivery_result or "") == "skipped_no_webhook"
            last_attempt = payload.get("last_attempt_at")
            if isinstance(last_attempt, str) and not previously_skipped:
                try:
                    attempt_at = _aware(datetime.fromisoformat(last_attempt))
                    if now - attempt_at < timedelta(hours=RETRY_AFTER_HOURS):
                        continue
                except ValueError:
                    pass
            ok, result = _deliver(
                {
                    "code": row.code,
                    "message": row.message,
                    "first_seen_at": _first_seen(
                        payload, fallback=_aware(row.created_at)
                    ).isoformat(),
                    "last_seen_at": payload.get("last_seen_at"),
                },
                now,
                post=post,
            )
            row.delivery_result = result
            if ok:
                row.delivered_at = now
                delivered += 1
                payload["last_attempt_at"] = now.isoformat()
                payload["delivery_count"] = int(payload.get("delivery_count") or 0) + 1
                payload["delivery_receipt_version"] = DELIVERY_RECEIPT_VERSION
                payload["delivery_business_code"] = 0
            elif result.startswith("failed"):
                failed += 1
                payload["last_attempt_at"] = now.isoformat()
            row.payload_json = payload
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
            .order_by(
                case(
                    (EvolutionAlert.status == "open", 0),
                    (EvolutionAlert.status == "tracking", 1),
                    (EvolutionAlert.status == "acknowledged", 2),
                    else_=3,
                ),
                EvolutionAlert.created_at.desc(),
            )
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
                "delivery_verified": (
                    (row.payload_json or {}).get("delivery_receipt_version")
                    == DELIVERY_RECEIPT_VERSION
                    and row.delivery_result == "sent"
                ),
                "reminder_interval_hours": REMIND_AFTER_HOURS,
            }
            for row in rows
        ]


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
