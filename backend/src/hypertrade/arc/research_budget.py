"""Shared automatic research admission. The ledger and mission commit atomically.

EvolutionCycle is the existing durable receipt envelope; budget.v1 rows require no
schema rewrite and never edit historical config or Paper records. PostgreSQL row
locking protects admission across worker processes; SQLite remains local-only.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from hypertrade.arc import store
from hypertrade.arc.controller import ARCController, ARCMissionProjection
from hypertrade.arc.evolution_models import EvolutionControl, EvolutionCycle
from hypertrade.arc.feedback import _feedback_child_active
from hypertrade.db import ArcMission, Database

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from hypertrade.arc.evolution import EvolutionConfig


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _stored_time(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value))


def _source_identity(goal: Any) -> tuple[str | None, int | None, str | None]:
    context, parent = goal.evolution_context or {}, goal.feedback_parent or {}
    if parent:
        evidence = parent.get("evidence") or {}
        source_value: Any
        strategy_value: Any
        trigger_value: Any
        source_value, strategy_value, trigger_value = (
            parent.get("instance_id"),
            evidence.get("strategy_id", context.get("source_strategy_id")),
            "degradation",
        )
    else:
        source_value = context.get("source_instance_id")
        strategy_value = context.get("source_strategy_id")
        trigger_value = context.get("trigger_source", "degradation")
    source = source_value.strip() if isinstance(source_value, str) else None
    if not source or len(source) > 128:
        source = None
    try:
        strategy_id = None if isinstance(strategy_value, bool) else int(strategy_value)
    except (TypeError, ValueError, OverflowError):
        strategy_id = None
    if strategy_id is not None and strategy_id <= 0:
        strategy_id = None
    trigger = trigger_value if trigger_value in {"degradation", "proactive"} else None
    return source, strategy_id, trigger


def usage(session: Session, config: EvolutionConfig, now: datetime) -> dict[str, Any]:
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    entries = {
        r.payload_json["mission_id"]: dict(r.payload_json)
        for r in session.scalars(
            select(EvolutionCycle).where(EvolutionCycle.status == "budget_admitted")
        )
    }
    active = 0
    sources: dict[str, Any] = {}
    for row in session.scalars(select(ArcMission)):
        projection = ARCMissionProjection.model_validate(row.projection_json)
        goal = projection.goal
        if goal is None:
            continue
        source, _, trigger = _source_identity(goal)
        if not source:
            continue
        # Pre-ledger missions count too: deployment/revision must never reset usage.
        entry = entries.setdefault(
            row.mission_id,
            {
                "mission_id": row.mission_id,
                "source_instance_id": source,
                "admitted_at": _utc(row.created_at).isoformat(),
                "trigger_source": trigger or "invalid",
                "legacy": True,
            },
        )
        when = _stored_time(entry["admitted_at"])
        ctrl = ARCController(mission_id=row.mission_id)
        ctrl.rebase(projection, row.revision)
        busy = bool(projection.avo.get("pending")) or _feedback_child_active(ctrl)
        if busy and (projection.state != "paper_observing" or projection.avo.get("pending")):
            active += 1
        cooldown_at = max(when, _utc(row.updated_at)) if not busy else when
        prior = sources.get(
            source,
            {
                "last_admitted_at": when.isoformat(),
                "busy": False,
                "cooldown_at": cooldown_at.isoformat(),
            },
        )
        prior["cooldown_at"] = max(prior["cooldown_at"], cooldown_at.isoformat())
        prior["last_admitted_at"] = max(prior["last_admitted_at"], when.isoformat())
        prior["busy"] = prior["busy"] or busy
        sources[source] = prior
    ordered = sorted(entries.values(), key=lambda r: (r["admitted_at"], r["mission_id"]))
    return {
        "schema_version": "research_budget.v1",
        "unit": "research_missions",
        "period": start.date().isoformat(),
        "period_end": (start + timedelta(days=1)).isoformat(),
        "period_used": sum(
            start <= _stored_time(r["admitted_at"]) < start + timedelta(days=1) for r in ordered
        ),
        "total_used": len(ordered),
        "active": active,
        "period_limit": config.max_research_per_day,
        "total_limit": config.max_research_total,
        "active_limit": config.max_active_research,
        "sources": sources,
        "recent_triggers": [r["trigger_source"] for r in ordered[-2:]],
        "fairness": ("eligible_degradation_first;least_recent_source_then_id"),
    }


def budget_status(db: Database, config: EvolutionConfig, now: datetime) -> dict[str, Any]:
    with db.session() as session:
        state = usage(session, config, now)
        reason: str | None = None
        next_run: str | None = now.isoformat()
        if not config.enabled:
            reason, next_run = "disabled", None
        elif (
            config.max_research_total is not None
            and state["total_used"] >= config.max_research_total
        ):
            reason, next_run = "total_budget_exhausted", None
        elif state["period_used"] >= config.max_research_per_day:
            reason, next_run = "period_budget_exhausted", state["period_end"]
        elif state["active"] >= config.max_active_research:
            reason, next_run = "concurrency_limit", None
        state.update(reason=reason, next_run_at=next_run)
        for source in state["sources"].values():
            until = datetime.fromisoformat(source["cooldown_at"]) + timedelta(
                hours=config.cooldown_hours
            )
            source["reason"] = (
                "source_active" if source["busy"] else ("source_cooldown" if now < until else None)
            )
            source["next_run_at"] = None if source["busy"] else max(now, until).isoformat()
        state["receipts"] = [
            dict(row.payload_json)
            for row in session.scalars(
                select(EvolutionCycle)
                .where(EvolutionCycle.status.in_(["budget_admitted", "budget_denied"]))
                .order_by(EvolutionCycle.updated_at.desc())
                .limit(20)
            )
        ]
        return state


def admit(
    ctrl: ARCController,
    *,
    now: datetime,
    revision: int | None = None,
    db: Database | None = None,
) -> dict[str, Any]:
    from hypertrade.arc.evolution import EvolutionConfig

    db = db or store._database
    if db is None:
        return {"accepted": False, "reason": "durable_budget_unavailable", "next_run_at": None}
    assert ctrl.projection.goal is not None
    goal = ctrl.projection.goal
    source, source_strategy_id, trigger = _source_identity(goal)
    with store.research_lock("automatic-research-budget") as owner:
        if owner is None:
            return {"accepted": False, "reason": "budget_busy", "next_run_at": now.isoformat()}
        with db.session() as session:
            # All automatic producers lock the same control row before reading usage.
            control = session.get(EvolutionControl, "global", with_for_update=True)
            config = EvolutionConfig.model_validate(control.config_json if control else {})
            state = usage(session, config, now)
            receipt = session.get(EvolutionCycle, "budget_" + ctrl.mission_id)
            if receipt and receipt.status == "budget_admitted":
                return {**state, **receipt.payload_json, "accepted": True, "replayed": True}
            reason, next_run = None, None
            if not config.enabled:
                reason = "disabled"
            elif revision is not None and (control is None or revision != control.revision):
                reason = "config_changed"
            elif source is None:
                reason = "invalid_source_identity"
            elif source_strategy_id is None:
                reason = "invalid_strategy_id"
            elif trigger is None:
                reason = "invalid_trigger_source"
            elif trigger == "proactive" and not config.proactive_enabled:
                reason = "proactive_disabled"
            elif config.strategy_ids and source_strategy_id not in config.strategy_ids:
                reason = "outside_strategy_scope"
            elif (
                config.max_research_total is not None
                and state["total_used"] >= config.max_research_total
            ):
                reason = "total_budget_exhausted"
            elif state["period_used"] >= config.max_research_per_day:
                reason, next_run = "period_budget_exhausted", state["period_end"]
            elif state["active"] >= config.max_active_research:
                reason = "concurrency_limit"
            elif source in state["sources"]:
                previous = state["sources"][source]
                until = datetime.fromisoformat(previous["cooldown_at"]) + timedelta(
                    hours=config.cooldown_hours
                )
                if previous["busy"]:
                    reason = "source_active"
                elif now < until:
                    reason, next_run = "source_cooldown", until.isoformat()
            result = {
                **{k: v for k, v in state.items() if k not in {"sources", "recent_triggers"}},
                "accepted": reason is None,
                "reason": reason,
                "next_run_at": next_run,
                "mission_id": ctrl.mission_id,
                "source_instance_id": source,
                "trigger_source": trigger,
                "revision": control.revision if control else 0,
                "checked_at": now.isoformat(),
            }
            if reason is None:
                receipt = EvolutionCycle(id="budget_" + ctrl.mission_id)
                session.add(receipt)
                owner()
                # No network effects occur here. Rollback removes both the task and debit.
                if session.get(ArcMission, ctrl.mission_id) is None:
                    session.add(
                        ArcMission(
                            mission_id=ctrl.mission_id,
                            state=ctrl.projection.state,
                            projection_json=ctrl.projection.model_dump(mode="json"),
                            revision=1,
                        )
                    )
                result.update(
                    admitted_at=now.isoformat(),
                    period_used=state["period_used"] + 1,
                    total_used=state["total_used"] + 1,
                    active=state["active"] + 1,
                    task_budget=goal.budget.model_dump(mode="json"),
                )
                receipt.status = "budget_admitted"
            else:
                # Keep refusals after a later admission; repeated identical checks do not
                # grow the ledger or erase the original refusal time.
                key = hashlib.sha256(
                    f"{ctrl.mission_id}/{state['period']}/{result['revision']}/{reason}".encode()
                ).hexdigest()[:32]
                receipt = session.get(EvolutionCycle, "budget_denied_" + key)
                if receipt is not None:
                    return result
                receipt = EvolutionCycle(id="budget_denied_" + key, status="budget_denied")
                session.add(receipt)
            receipt.payload_json = result
            return result
