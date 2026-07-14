"""Durable, deduplicated, Task-only background research triggers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from hypertrade.agent.task_events import TaskEventService
from hypertrade.agent.tasks import TaskBudget
from hypertrade.config import Settings, get_settings
from hypertrade.db import (
    AgentSession,
    AgentTask,
    BitProPaperMonitorSnapshot,
    Database,
    MonitorRun,
    ResearchMandate,
    ResearchTrigger,
    ResearchTriggerControl,
    ResearchTriggerFire,
    new_id,
    utc_now,
)

TriggerType = Literal[
    "schedule",
    "regime_change",
    "strategy_drift",
    "data_quality",
    "evaluation_regression",
]


class TriggerCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(default="", max_length=96)
    operator: Literal["always", "eq", "ne", "gt", "gte", "lt", "lte"] = "always"
    value: str | int | float | bool | None = None


class TriggerSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["interval", "daily_utc"] = "interval"
    interval_seconds: int = Field(default=3600, ge=60, le=2_592_000)
    hour: int = Field(default=0, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class ResearchTriggerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=160)
    trigger_type: TriggerType
    mandate_id: str = Field(min_length=1, max_length=32)
    objective_template: str = Field(min_length=8, max_length=4000)
    enabled: bool = False
    condition: TriggerCondition = Field(default_factory=TriggerCondition)
    schedule: TriggerSchedule = Field(default_factory=TriggerSchedule)
    budget: TaskBudget = Field(
        default_factory=lambda: TaskBudget(
            max_tokens=50_000,
            max_model_calls=8,
            max_tool_calls=20,
            max_backtests=0,
            max_duration_seconds=900,
            max_concurrency=1,
        )
    )
    cooldown_seconds: int = Field(default=3600, ge=60, le=2_592_000)
    daily_quota: int = Field(default=2, ge=1, le=24)

    @model_validator(mode="after")
    def bounded_task(self) -> ResearchTriggerCreate:
        if not self.name.strip() or not self.objective_template.strip():
            raise ValueError("trigger name and objective must contain text")
        if self.budget.max_backtests != 0:
            raise ValueError("trigger-created tasks cannot receive backtest budget")
        if self.budget.max_tokens > 100_000 or self.budget.max_tool_calls > 40:
            raise ValueError("trigger task budget exceeds global bounds")
        return self


class TriggerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: TriggerType
    source_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime = Field(default_factory=utc_now)
    metrics: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    refs: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded_projection(self) -> TriggerEvent:
        if len(self.metrics) > 32 or len(self.refs) > 32:
            raise ValueError("trigger event projection exceeds 32 fields")
        for key, value in self.metrics.items():
            if not key.strip() or len(key) > 96:
                raise ValueError("trigger metric keys must be 1..96 characters")
            if isinstance(value, str) and len(value) > 512:
                raise ValueError("trigger metric string exceeds 512 characters")
        for key, value in self.refs.items():
            if not key.strip() or len(key) > 96 or len(value) > 256:
                raise ValueError("trigger refs exceed key/value bounds")
        return self


class TriggerControlUpdate(BaseModel):
    kill_switch: bool
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def non_empty_reason(self) -> TriggerControlUpdate:
        if not self.reason.strip():
            raise ValueError("reason must contain text")
        return self


class CommittedTriggerEventAdapter:
    """Normalize committed projections without calling their source systems."""

    @staticmethod
    def monitor_run(run: MonitorRun, *, source_type: TriggerType) -> TriggerEvent:
        if source_type not in {"regime_change", "data_quality"}:
            raise ValueError("MonitorRun supports regime_change or data_quality")
        metrics: dict[str, str | int | float | bool | None] = {
            "status": run.status,
            "alert_count": len(run.alerts_json or []),
            "data_gap_count": len(run.data_gaps_json or []),
        }
        metrics.update(_primitive_metrics("metric", run.metric_snapshot_json))
        return TriggerEvent(
            source_type=source_type,
            source_id=run.id,
            observed_at=run.completed_at or run.updated_at,
            metrics=metrics,
            refs={"monitor_run_id": run.id, "monitor_id": run.monitor_id},
        )

    @staticmethod
    def world_state(snapshot: dict[str, Any]) -> TriggerEvent:
        generated_at = _parse_datetime(snapshot.get("generated_at"))
        global_market = _object(snapshot.get("global_market"))
        metrics: dict[str, str | int | float | bool | None] = {
            "status": str(snapshot.get("status", "unknown")),
            "risk_regime": _primitive(global_market.get("risk_regime")),
            "volatility_regime": _primitive(global_market.get("volatility_regime")),
            "missing_data_count": len(snapshot.get("missing_data", [])),
        }
        source_id = str(snapshot.get("source_id", "world_model:unknown"))
        return TriggerEvent(
            source_type="regime_change",
            source_id=f"{source_id}:{generated_at.isoformat()}",
            observed_at=generated_at,
            metrics=metrics,
            refs={"world_state_source_id": source_id},
        )

    @staticmethod
    def paper_snapshot(snapshot: BitProPaperMonitorSnapshot) -> TriggerEvent:
        metrics: dict[str, str | int | float | bool | None] = {
            "status": snapshot.status,
            "strategy_id": snapshot.strategy_id,
        }
        metrics.update(_primitive_metrics("metric", snapshot.metrics_json))
        metrics.update(_primitive_metrics("drift", snapshot.drift_json))
        return TriggerEvent(
            source_type="strategy_drift",
            source_id=snapshot.id,
            observed_at=snapshot.updated_at,
            metrics=metrics,
            refs={"paper_snapshot_id": snapshot.id},
        )

    @staticmethod
    def eval_status(payload: dict[str, Any], *, observed_at: datetime) -> TriggerEvent:
        cases = payload.get("cases", [])
        failed = sum(
            isinstance(case, dict) and case.get("status") != "passed" for case in cases
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:20]
        return TriggerEvent(
            source_type="evaluation_regression",
            source_id=f"eval:{digest}",
            observed_at=observed_at,
            metrics={
                "status": str(payload.get("status", "unknown")),
                "case_count": int(payload.get("case_count", len(cases)) or 0),
                "failed_case_count": failed,
            },
            refs={"eval_digest": digest},
        )


class ResearchTriggerService:
    """Fail-closed trigger control plane with no external/write adapter imports."""

    def __init__(self, db: Database, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def create(self, payload: ResearchTriggerCreate, *, actor: str) -> dict[str, Any]:
        now = utc_now()
        try:
            with self.db.session() as session:
                mandate = session.get(ResearchMandate, payload.mandate_id)
                if mandate is None or mandate.status != "active":
                    raise ValueError("trigger requires an active research mandate")
                if session.scalar(
                    select(ResearchTrigger.id).where(
                        ResearchTrigger.name == payload.name.strip()
                    )
                ):
                    raise ValueError("trigger name already exists")
                row = ResearchTrigger(
                    name=payload.name.strip(),
                    trigger_type=payload.trigger_type,
                    enabled=payload.enabled,
                    mandate_id=payload.mandate_id,
                    objective_template=payload.objective_template.strip(),
                    condition_json=payload.condition.model_dump(mode="json"),
                    schedule_json=payload.schedule.model_dump(mode="json"),
                    task_budget_json=payload.budget.model_dump(mode="json"),
                    cooldown_seconds=payload.cooldown_seconds,
                    daily_quota=payload.daily_quota,
                    next_run_at=(
                        _next_run(payload.schedule, now)
                        if payload.trigger_type == "schedule"
                        else None
                    ),
                    audit_json=[
                        {
                            "event": "created",
                            "actor": actor,
                            "at": now.isoformat(),
                            "enabled": payload.enabled,
                        }
                    ],
                    created_by=actor,
                )
                session.add(row)
                session.flush()
                return trigger_to_dict(row)
        except IntegrityError as exc:
            raise ValueError("trigger name already exists") from exc

    def list_triggers(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(ResearchTrigger)
                .order_by(ResearchTrigger.created_at.desc())
                .limit(max(1, min(limit, 500)))
            ).all()
            return [trigger_to_dict(row) for row in rows]

    def get(self, trigger_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ResearchTrigger, trigger_id)
            if row is None:
                raise KeyError(trigger_id)
            return trigger_to_dict(row)

    def set_enabled(
        self,
        trigger_id: str,
        *,
        enabled: bool,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        if not reason.strip() or len(reason) > 1000:
            raise ValueError("reason must contain 1..1000 characters")
        with self.db.session() as session:
            row = session.get(ResearchTrigger, trigger_id)
            if row is None:
                raise KeyError(trigger_id)
            row.enabled = enabled
            row.version += 1
            audit = list(row.audit_json or [])
            audit.append(
                {
                    "event": "enabled" if enabled else "disabled",
                    "reason": reason.strip(),
                    "actor": actor,
                    "at": utc_now().isoformat(),
                }
            )
            row.audit_json = audit[-200:]
            return trigger_to_dict(row)

    def control(self) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ResearchTriggerControl, "global")
            if row is None:
                return {"kill_switch": False, "reason": "", "updated_by": "system"}
            return trigger_control_to_dict(row)

    def set_control(self, payload: TriggerControlUpdate, *, actor: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ResearchTriggerControl, "global")
            if row is None:
                row = ResearchTriggerControl(id="global")
                session.add(row)
            row.kill_switch = payload.kill_switch
            row.reason = payload.reason.strip()
            row.updated_by = actor
            session.flush()
            return trigger_control_to_dict(row)

    def list_fires(self, *, trigger_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        query = select(ResearchTriggerFire)
        if trigger_id:
            query = query.where(ResearchTriggerFire.trigger_id == trigger_id)
        query = query.order_by(ResearchTriggerFire.created_at.desc()).limit(
            max(1, min(limit, 500))
        )
        with self.db.session() as session:
            return [fire_to_dict(row) for row in session.scalars(query).all()]

    def claim_due(self, owner: str) -> dict[str, Any] | None:
        if not self.settings.research_triggers_enabled:
            return None
        now = utc_now()
        with self.db.session() as session:
            query = (
                select(ResearchTrigger)
                .where(
                    ResearchTrigger.enabled.is_(True),
                    ResearchTrigger.trigger_type == "schedule",
                    ResearchTrigger.next_run_at.is_not(None),
                    ResearchTrigger.next_run_at <= now,
                    or_(
                        ResearchTrigger.lease_expires_at.is_(None),
                        ResearchTrigger.lease_expires_at < now,
                    ),
                )
                .order_by(ResearchTrigger.next_run_at)
                .limit(1)
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = session.scalar(query)
            if row is None:
                return None
            row.lease_owner = owner
            row.lease_expires_at = now + timedelta(
                seconds=self.settings.research_trigger_lease_seconds
            )
            return trigger_to_dict(row)

    def run_claimed(self, trigger_id: str, owner: str) -> dict[str, Any]:
        trigger = self.get(trigger_id)
        if trigger.get("lease_owner") != owner:
            raise PermissionError("trigger lease owner mismatch")
        now = utc_now()
        schedule_bucket = _bucket(now, int(trigger["cooldown_seconds"]))
        event = TriggerEvent(
            source_type="schedule",
            source_id=f"schedule:{trigger_id}:{schedule_bucket.isoformat()}",
            observed_at=now,
        )
        result = self.fire(trigger_id, event, actor=f"trigger_worker:{owner}")
        with self.db.session() as session:
            row = session.get(ResearchTrigger, trigger_id)
            if row is not None and row.lease_owner == owner:
                schedule = TriggerSchedule.model_validate(row.schedule_json)
                row.next_run_at = _next_run(schedule, now)
                row.lease_owner = None
                row.lease_expires_at = None
        return result

    def fire(self, trigger_id: str, event: TriggerEvent, *, actor: str) -> dict[str, Any]:
        observed_at = _as_utc(event.observed_at)
        decision_at = utc_now()
        with self.db.session() as session:
            query = select(ResearchTrigger).where(ResearchTrigger.id == trigger_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            trigger = session.scalar(query)
            if trigger is None:
                raise KeyError(trigger_id)
            bucket = _bucket(observed_at, trigger.cooldown_seconds)
            fingerprint = _fingerprint(trigger.id, event, bucket)
            existing = session.scalar(
                select(ResearchTriggerFire).where(
                    ResearchTriggerFire.fingerprint == fingerprint
                )
            )
            if existing is not None:
                return {**fire_to_dict(existing), "deduplicated": True}
            reason = self._blocked_reason(session, trigger, event, decision_at)
            if not _condition_matches(trigger.condition_json, event.metrics):
                reason = reason or "condition_not_matched"
            fire = ResearchTriggerFire(
                id=new_id("rfire"),
                trigger_id=trigger.id,
                fingerprint=fingerprint,
                bucket_start=bucket,
                source_type=event.source_type,
                source_id=event.source_id,
                status="skipped" if reason else "created",
                reason=reason,
                event_ref_json={"metrics": dict(event.metrics), "refs": dict(event.refs)},
            )
            session.add(fire)
            try:
                # Persist the unique decision before any Task rows so concurrent
                # workers either own the fingerprint or replay its immutable result.
                session.flush()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(ResearchTriggerFire).where(
                        ResearchTriggerFire.fingerprint == fingerprint
                    )
                )
                if existing is None:
                    raise
                return {**fire_to_dict(existing), "deduplicated": True}
            if reason:
                return fire_to_dict(fire)
            task = self._create_task_in_session(session, trigger, fire, actor=actor)
            fire.task_id = task.id
            trigger.last_fired_at = decision_at
            session.flush()
            return fire_to_dict(fire)

    def _blocked_reason(
        self,
        session: Any,
        trigger: ResearchTrigger,
        event: TriggerEvent,
        now: datetime,
    ) -> str:
        if not self.settings.research_triggers_enabled:
            return "feature_disabled"
        control = session.get(ResearchTriggerControl, "global")
        if control is not None and control.kill_switch:
            return "global_kill_switch"
        if not trigger.enabled:
            return "trigger_disabled"
        if trigger.trigger_type != event.source_type:
            return "event_type_mismatch"
        mandate = session.get(ResearchMandate, trigger.mandate_id)
        if mandate is None or mandate.status != "active":
            return "mandate_inactive"
        try:
            budget = TaskBudget.model_validate(trigger.task_budget_json)
        except ValueError:
            return "task_budget_invalid"
        if (
            budget.max_backtests != 0
            or budget.max_tokens > 100_000
            or budget.max_tool_calls > 40
        ):
            return "task_budget_invalid"
        if trigger.last_fired_at is not None:
            last_fired = _as_utc(trigger.last_fired_at)
            if now < last_fired + timedelta(seconds=trigger.cooldown_seconds):
                return "cooldown_active"
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        trigger_count = session.scalar(
            select(func.count(ResearchTriggerFire.id)).where(
                ResearchTriggerFire.trigger_id == trigger.id,
                ResearchTriggerFire.status == "created",
                ResearchTriggerFire.created_at >= day_start,
            )
        )
        if int(trigger_count or 0) >= trigger.daily_quota:
            return "trigger_daily_quota"
        global_count = session.scalar(
            select(func.count(ResearchTriggerFire.id)).where(
                ResearchTriggerFire.status == "created",
                ResearchTriggerFire.created_at >= day_start,
            )
        )
        if int(global_count or 0) >= self.settings.research_trigger_global_daily_quota:
            return "global_daily_quota"
        return ""

    @staticmethod
    def _create_task_in_session(
        session: Any,
        trigger: ResearchTrigger,
        fire: ResearchTriggerFire,
        *,
        actor: str,
    ) -> AgentTask:
        agent_session = AgentSession(
            title=f"Triggered: {trigger.name}"[:200],
            surface="background",
            provider_config_json={},
            context_policy_json={
                "trigger_id": trigger.id,
                "fire_id": fire.id,
                "read_only": True,
            },
            created_by=actor,
        )
        session.add(agent_session)
        session.flush()
        task = AgentTask(
            session_id=agent_session.id,
            kind="triggered_research",
            objective=(
                f"{trigger.objective_template}\n\n"
                f"Trigger source: {fire.source_type}:{fire.source_id}. "
                f"Committed projection: "
                f"{json.dumps(fire.event_ref_json, ensure_ascii=False, sort_keys=True)}. "
                "Research only; preserve unknowns and do not perform write actions."
            ),
            resource_type="research_trigger_fire",
            resource_id=fire.id,
            budget_json=dict(trigger.task_budget_json),
            usage_json={
                "tokens": 0,
                "model_calls": 0,
                "tool_calls": 0,
                "backtests": 0,
                "duration_ms": 0,
            },
            control_json={"trigger_id": trigger.id, "fire_id": fire.id, "read_only": True},
            idempotency_key=f"trigger:{fire.fingerprint}",
        )
        session.add(task)
        session.flush()
        TaskEventService.append_in_session(
            session,
            task,
            "trigger_task_created",
            actor=actor,
            payload={
                "trigger_id": trigger.id,
                "fire_id": fire.id,
                "source_type": fire.source_type,
                "source_id": fire.source_id,
                "boundary": "task_only_read_only_no_direct_adapter",
            },
        )
        return task


def trigger_to_dict(row: ResearchTrigger) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "trigger_type": row.trigger_type,
        "enabled": row.enabled,
        "mandate_id": row.mandate_id,
        "objective_template": row.objective_template,
        "condition": dict(row.condition_json or {}),
        "schedule": dict(row.schedule_json or {}),
        "budget": dict(row.task_budget_json or {}),
        "cooldown_seconds": row.cooldown_seconds,
        "daily_quota": row.daily_quota,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_fired_at": row.last_fired_at.isoformat() if row.last_fired_at else None,
        "lease_owner": row.lease_owner,
        "lease_expires_at": row.lease_expires_at.isoformat() if row.lease_expires_at else None,
        "version": row.version,
        "audit": list(row.audit_json or []),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def fire_to_dict(row: ResearchTriggerFire) -> dict[str, Any]:
    return {
        "id": row.id,
        "trigger_id": row.trigger_id,
        "fingerprint": row.fingerprint,
        "bucket_start": row.bucket_start.isoformat(),
        "source_type": row.source_type,
        "source_id": row.source_id,
        "status": row.status,
        "reason": row.reason,
        "event_ref": dict(row.event_ref_json or {}),
        "task_id": row.task_id,
        "created_at": row.created_at.isoformat(),
    }


def trigger_control_to_dict(row: ResearchTriggerControl) -> dict[str, Any]:
    return {
        "kill_switch": row.kill_switch,
        "reason": row.reason,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat(),
    }


def _condition_matches(condition_raw: dict[str, Any], metrics: dict[str, Any]) -> bool:
    condition = TriggerCondition.model_validate(condition_raw or {})
    if condition.operator == "always":
        return True
    actual = metrics.get(condition.metric)
    expected = condition.value
    if condition.operator == "eq":
        return actual == expected
    if condition.operator == "ne":
        return actual != expected
    if not isinstance(actual, int | float) or not isinstance(expected, int | float):
        return False
    return {
        "gt": actual > expected,
        "gte": actual >= expected,
        "lt": actual < expected,
        "lte": actual <= expected,
    }[condition.operator]


def _fingerprint(trigger_id: str, event: TriggerEvent, bucket: datetime) -> str:
    canonical = json.dumps(
        {
            "trigger_id": trigger_id,
            "source_type": event.source_type,
            "source_id": event.source_id,
            "bucket": bucket.isoformat(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _bucket(value: datetime, seconds: int) -> datetime:
    aware = _as_utc(value)
    timestamp = int(aware.timestamp())
    return datetime.fromtimestamp(timestamp - timestamp % max(seconds, 60), tz=UTC)


def _next_run(schedule: TriggerSchedule, after: datetime) -> datetime:
    current = _as_utc(after)
    if schedule.mode == "interval":
        return current + timedelta(seconds=schedule.interval_seconds)
    candidate = current.replace(
        hour=schedule.hour,
        minute=schedule.minute,
        second=0,
        microsecond=0,
    )
    return candidate if candidate > current else candidate + timedelta(days=1)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("committed projection requires generated_at")
    return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _primitive(value: Any) -> str | int | float | bool | None:
    return value if isinstance(value, str | int | float | bool) or value is None else str(value)


def _primitive_metrics(prefix: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}.{key}": _primitive(value)
        for key, value in dict(payload or {}).items()
        if not isinstance(value, dict | list)
    }
