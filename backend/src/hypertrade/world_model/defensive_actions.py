"""Narrow defensive action executor for world-model automation.

Sprint 73 keeps automation disabled by default. When explicitly enabled, only
allowlisted defensive handlers can run, every attempt needs an idempotency key,
and all outcomes are persisted as trace-backed audit records.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select

from hypertrade.config import Settings, get_settings
from hypertrade.db import Database, MonitorAlertEvent, TraceEvent, utc_now
from hypertrade.risk.governance import RiskGovernancePolicy

TRACE_TOOL_NAME = "world_model.defensive_action"
SUPPORTED_ACTIONS = {
    "raise_human_confirmation_alert": "Raise an internal alert requesting operator review.",
    "urgent_monitor_capture": "Record an urgent monitor-capture request for operators.",
}
OFFENSIVE_ACTIONS = {
    "open_position",
    "increase_risk",
    "add_leverage",
    "move_funds",
    "live_order_intent",
}


class DefensiveActionEngine:
    def __init__(self, db: Database, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.governance = RiskGovernancePolicy()

    def status(self) -> dict[str, Any]:
        attempts = self.list_attempts(limit=5)
        return {
            "enabled": self._enabled(),
            "allowlist": self._allowlist(),
            "supported_actions": [
                {"action_id": key, "description": value}
                for key, value in sorted(SUPPORTED_ACTIONS.items())
            ],
            "recent_attempt_count": len(attempts),
            "recent_attempts": attempts,
        }

    def execute(
        self,
        *,
        action_id: str,
        idempotency_key: str,
        world_state: dict[str, Any],
    ) -> dict[str, Any]:
        action_id = action_id.strip()
        idempotency_key = idempotency_key.strip()
        duplicate = self._find_attempt_by_idempotency_key(idempotency_key)
        if duplicate is not None:
            return {
                **duplicate,
                "status": "duplicate",
                "execution_result": {
                    "duplicate_of": duplicate["action_attempt_id"],
                    "executed": False,
                },
            }
        if not idempotency_key:
            return self._record_attempt(
                action_id=action_id,
                idempotency_key=idempotency_key,
                world_state=world_state,
                status="rejected",
                reason="missing_idempotency_key",
                policy_decision=self.governance.evaluate(
                    "world_model_defensive_action",
                    {},
                ).as_trace_payload(),
                execution_result={"executed": False},
            )

        policy_decision = self.governance.evaluate(
            "world_model_defensive_action",
            {"idempotency_key": idempotency_key},
        )
        if not policy_decision.allowed:
            return self._record_attempt(
                action_id=action_id,
                idempotency_key=idempotency_key,
                world_state=world_state,
                status="rejected",
                reason=policy_decision.denial_reason or "policy_denied",
                policy_decision=policy_decision.as_trace_payload(),
                execution_result={"executed": False},
            )
        risk_check = self._risk_check(action_id=action_id, world_state=world_state)
        if risk_check["status"] != "passed":
            return self._record_attempt(
                action_id=action_id,
                idempotency_key=idempotency_key,
                world_state=world_state,
                status="rejected",
                reason=str(risk_check["reason"]),
                policy_decision=policy_decision.as_trace_payload(),
                execution_result={"executed": False, "risk_check": risk_check},
            )
        if not self._enabled():
            return self._record_attempt(
                action_id=action_id,
                idempotency_key=idempotency_key,
                world_state=world_state,
                status="skipped",
                reason="defensive_actions_disabled",
                policy_decision=policy_decision.as_trace_payload(),
                execution_result={"executed": False},
            )
        if action_id not in self._allowlist():
            return self._record_attempt(
                action_id=action_id,
                idempotency_key=idempotency_key,
                world_state=world_state,
                status="rejected",
                reason="action_not_allowlisted",
                policy_decision=policy_decision.as_trace_payload(),
                execution_result={"executed": False},
            )

        execution_result = self._execute_handler(
            action_id=action_id,
            idempotency_key=idempotency_key,
            world_state=world_state,
        )
        return self._record_attempt(
            action_id=action_id,
            idempotency_key=idempotency_key,
            world_state=world_state,
            status="executed",
            reason="executed",
            policy_decision=policy_decision.as_trace_payload(),
            execution_result=execution_result,
        )

    def list_attempts(self, *, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self.db.session() as session:
            rows = session.scalars(
                select(TraceEvent)
                .where(TraceEvent.tool_name == TRACE_TOOL_NAME)
                .order_by(desc(TraceEvent.created_at))
                .limit(safe_limit)
            ).all()
            return [
                dict(row.output_json)
                for row in rows
                if isinstance(row.output_json, dict)
            ]

    def _execute_handler(
        self,
        *,
        action_id: str,
        idempotency_key: str,
        world_state: dict[str, Any],
    ) -> dict[str, Any]:
        if action_id == "raise_human_confirmation_alert":
            alert_id = _attempt_id(idempotency_key, prefix="alrt")
            with self.db.session() as session:
                session.add(
                    MonitorAlertEvent(
                        id=alert_id,
                        monitor_id="world_model_defensive_action",
                        run_id=str(world_state.get("source_id", "world_model:latest")),
                        level="warning",
                        code="world_model_human_confirmation_required",
                        message="World model defensive automation requested operator review.",
                        source_id=str(world_state.get("source_id", "world_model:latest")),
                        threshold_json={"idempotency_key": idempotency_key},
                        metric_json={
                            "decision": world_state.get("decision", {}),
                            "missing_data_count": len(_list_value(world_state.get("missing_data"))),
                        },
                    )
                )
            return {"executed": True, "alert_created": True, "alert_id": alert_id}
        return {
            "executed": True,
            "capture_requested": True,
            "note": "Operator-facing urgent monitor capture request recorded.",
        }

    def _record_attempt(
        self,
        *,
        action_id: str,
        idempotency_key: str,
        world_state: dict[str, Any],
        status: str,
        reason: str,
        policy_decision: dict[str, Any],
        execution_result: dict[str, Any],
    ) -> dict[str, Any]:
        attempt = {
            "action_attempt_id": _attempt_id(idempotency_key or action_id),
            "status": status,
            "reason": reason,
            "action_id": action_id,
            "idempotency_key": idempotency_key,
            "world_state_id": str(world_state.get("source_id", "world_model:latest")),
            "world_state_hash": str(
                world_state.get("decision", {}).get("world_state_hash", "")
            ),
            "decision_id": str(world_state.get("decision", {}).get("decision_id", "")),
            "selected_scenario": world_state.get("decision", {}),
            "policy_decision": policy_decision,
            "execution_result": execution_result,
            "review_after": str(world_state.get("decision", {}).get("review_after", "PT5M")),
            "rollback_or_follow_up": _follow_up(status),
            "created_at": utc_now().isoformat(),
        }
        with self.db.session() as session:
            session.add(
                TraceEvent(
                    run_id=str(attempt["decision_id"] or attempt["world_state_id"]),
                    tool_name=TRACE_TOOL_NAME,
                    status=status,
                    input_json={
                        "action_id": action_id,
                        "idempotency_key": idempotency_key,
                        "world_state_id": attempt["world_state_id"],
                    },
                    output_json=attempt,
                )
            )
        return attempt

    def _risk_check(self, *, action_id: str, world_state: dict[str, Any]) -> dict[str, str]:
        if action_id in OFFENSIVE_ACTIONS:
            return {"status": "rejected", "reason": "offensive_action_blocked"}
        if action_id not in SUPPORTED_ACTIONS:
            return {"status": "rejected", "reason": "unsupported_defensive_action"}
        if _is_stale(world_state) and action_id != "raise_human_confirmation_alert":
            return {"status": "rejected", "reason": "stale_world_state"}
        policy_status = str(world_state.get("decision", {}).get("policy_status", ""))
        if (
            policy_status == "blocked_risk_increasing_until_confirmed"
            and action_id != "raise_human_confirmation_alert"
        ):
            return {"status": "rejected", "reason": "scenario_policy_blocked"}
        return {"status": "passed", "reason": "defensive_action_allowed"}

    def _find_attempt_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        for attempt in self.list_attempts(limit=200):
            if attempt.get("idempotency_key") == idempotency_key:
                return attempt
        return None

    def _enabled(self) -> bool:
        return bool(self.settings.world_model_defensive_actions_enabled)

    def _allowlist(self) -> list[str]:
        raw = self.settings.world_model_defensive_action_allowlist
        return [item.strip() for item in raw.split(",") if item.strip()]


def _attempt_id(value: str, *, prefix: str = "wma") -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _follow_up(status: str) -> str:
    if status == "executed":
        return "Review alert/trace outcome before any further action."
    if status == "skipped":
        return "Enable a specific allowlist entry before automation can execute."
    return "Keep action blocked and request operator review."


def _is_stale(world_state: dict[str, Any]) -> bool:
    generated_at = world_state.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        return False
    try:
        parsed = datetime.fromisoformat(generated_at)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return utc_now() - parsed > timedelta(minutes=30)


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
