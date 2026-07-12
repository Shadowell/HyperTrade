"""Deterministic persistence and policy checks for Sprint 81 research work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import desc, select

from hypertrade.db import Database, ResearchJob, ResearchMandate
from hypertrade.research.schemas import (
    ResearchJobCreate,
    ResearchMandateCreate,
    StrategySpecDraft,
    strategy_key_from_prompt,
)

_TERMINAL_JOB_STATES = {"canceled", "completed", "failed", "rejected"}
_JOB_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"planning", "canceled"},
    "planning": {"completed", "failed", "rejected", "canceled"},
    "failed": {"queued", "canceled"},
    "rejected": set(),
    "completed": set(),
    "canceled": set(),
}


class ResearchProgramService:
    """Persist research mandates/jobs before later sprints add BitPro execution."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def create_mandate(self, payload: ResearchMandateCreate) -> dict[str, Any]:
        with self.db.session() as session:
            audit = [
                _audit_event(
                    event="mandate_validated",
                    trace_ref="research.mandate.validate",
                    detail="schema_valid",
                ),
                _audit_event(
                    event="mandate_created",
                    trace_ref="research.mandate.create",
                    detail="active",
                ),
            ]
            mandate = ResearchMandate(
                name=payload.name,
                status="active",
                market_type=payload.market_type,
                symbols_json=list(payload.symbols),
                timeframes_json=list(payload.timeframes),
                strategy_categories_json=list(payload.strategy_categories),
                budget_json=payload.budget.model_dump(mode="json"),
                validation_json=payload.validation.model_dump(mode="json"),
                paper_promotion_mode=payload.paper_promotion_mode,
                live_mode=payload.live_mode,
                audit_json=audit,
            )
            session.add(mandate)
            session.flush()
            return _mandate_to_dict(mandate)

    def list_mandates(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(ResearchMandate)
                .order_by(desc(ResearchMandate.created_at))
                .limit(_bounded_limit(limit))
            ).all()
            return [_mandate_to_dict(row) for row in rows]

    def get_mandate(self, mandate_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            mandate = _get_mandate(session, mandate_id)
            return _mandate_to_dict(mandate)

    def pause_mandate(self, mandate_id: str) -> dict[str, Any]:
        return self._set_mandate_status(mandate_id, target="paused")

    def resume_mandate(self, mandate_id: str) -> dict[str, Any]:
        return self._set_mandate_status(mandate_id, target="active")

    def _set_mandate_status(self, mandate_id: str, *, target: str) -> dict[str, Any]:
        with self.db.session() as session:
            mandate = _get_mandate(session, mandate_id)
            current = mandate.status
            allowed = (current == "active" and target == "paused") or (
                current == "paused" and target == "active"
            )
            if not allowed:
                raise ValueError(f"cannot transition mandate from {current} to {target}")
            mandate.status = target
            mandate.version += 1
            mandate.audit_json = [
                *list(mandate.audit_json),
                _audit_event(
                    event=f"mandate_{target}",
                    trace_ref="research.mandate.transition",
                    detail=f"{current}->{target}",
                ),
            ]
            session.flush()
            return _mandate_to_dict(mandate)

    def draft_strategy_spec(self, mandate_id: str, prompt: str) -> dict[str, Any]:
        with self.db.session() as session:
            mandate = _get_mandate(session, mandate_id)
            _require_active_mandate(mandate)
            spec = _draft_spec(mandate, prompt=prompt)
            return {
                "status": "draft",
                "source": "research_mandate",
                "mandate": _mandate_scope(mandate),
                "strategy_spec": spec.model_dump(mode="json"),
                "boundaries": [
                    "schema_valid_draft_only",
                    "no_bitpro_write",
                    "no_paper_or_live_action",
                ],
            }

    def queue_job(self, mandate_id: str, payload: ResearchJobCreate) -> dict[str, Any]:
        with self.db.session() as session:
            existing = session.scalar(
                select(ResearchJob).where(ResearchJob.idempotency_key == payload.idempotency_key)
            )
            if existing is not None:
                if existing.mandate_id != mandate_id or existing.prompt != payload.prompt:
                    raise ValueError("idempotency_key is already bound to a different research job")
                result = _job_to_dict(existing)
                result["idempotency_replayed"] = True
                return result

            mandate = _get_mandate(session, mandate_id)
            _require_active_mandate(mandate)
            spec = payload.strategy_spec or _draft_spec(mandate, prompt=payload.prompt)
            if spec.mandate_id != mandate.id:
                raise ValueError("strategy_spec mandate_id must match research job mandate")
            _validate_spec_scope(spec, mandate)
            transition = _transition_event(
                previous="",
                target="queued",
                reason="mandate_validated_and_job_queued",
                source_run_id=payload.source_run_id,
            )
            job = ResearchJob(
                mandate_id=mandate.id,
                status="queued",
                prompt=payload.prompt,
                strategy_spec_json=spec.model_dump(mode="json"),
                idempotency_key=payload.idempotency_key,
                source_run_id=payload.source_run_id,
                transition_json=[transition],
            )
            mandate.audit_json = [
                *list(mandate.audit_json),
                _audit_event(
                    event="job_queue_validated",
                    trace_ref="research.job.queue",
                    detail=f"idempotency_key={payload.idempotency_key}",
                    source_run_id=payload.source_run_id,
                ),
            ]
            session.add(job)
            session.flush()
            return _job_to_dict(job)

    def list_jobs(
        self,
        *,
        mandate_id: str = "",
        status: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.db.session() as session:
            statement = (
                select(ResearchJob)
                .order_by(desc(ResearchJob.created_at))
                .limit(_bounded_limit(limit))
            )
            if mandate_id:
                statement = statement.where(ResearchJob.mandate_id == mandate_id)
            if status:
                statement = statement.where(ResearchJob.status == status)
            rows = session.scalars(statement).all()
            return [_job_to_dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            job = _get_job(session, job_id)
            return _job_to_dict(job)

    def cancel_job(self, job_id: str, *, reason: str = "operator_canceled") -> dict[str, Any]:
        return self.transition_job(job_id, target="canceled", reason=reason)

    def transition_job(
        self,
        job_id: str,
        *,
        target: str,
        reason: str,
        source_run_id: str = "",
    ) -> dict[str, Any]:
        with self.db.session() as session:
            job = _get_job(session, job_id)
            current = job.status
            if target not in _JOB_TRANSITIONS.get(current, set()):
                raise ValueError(f"cannot transition research job from {current} to {target}")
            job.status = target
            if target == "planning":
                job.attempts += 1
            if target == "failed":
                job.last_error = reason
            job.transition_json = [
                *list(job.transition_json),
                _transition_event(
                    previous=current,
                    target=target,
                    reason=reason,
                    source_run_id=source_run_id or job.source_run_id,
                ),
            ]
            session.flush()
            return _job_to_dict(job)


def _draft_spec(mandate: ResearchMandate, *, prompt: str) -> StrategySpecDraft:
    cleaned_prompt = " ".join(prompt.split())
    if len(cleaned_prompt) < 3:
        raise ValueError("prompt must not be blank")
    category = mandate.strategy_categories_json[0]
    symbol = mandate.symbols_json[0]
    timeframe = mandate.timeframes_json[0]
    return StrategySpecDraft(
        mandate_id=mandate.id,
        strategy_key=strategy_key_from_prompt(
            category=category,
            symbol=symbol,
            timeframe=timeframe,
            prompt=cleaned_prompt,
        ),
        title=f"{symbol} {timeframe} {category} research draft",
        hypothesis=cleaned_prompt,
        symbols=list(mandate.symbols_json),
        timeframes=list(mandate.timeframes_json),
        strategy_category=category,
        entry_logic=(
            "Define an entry condition from the approved strategy category and real "
            "OHLCV only."
        ),
        exit_logic=(
            "Define deterministic exit, stop, and invalidation conditions before "
            "backtesting."
        ),
        risk_conditions=[
            "Respect the research mandate drawdown and data-coverage gates.",
            "Do not create paper or live orders from this draft.",
        ],
        data_requirements=[
            f"Real {mandate.market_type} OHLCV for {symbol} at {timeframe}.",
            "Declared fee, slippage, funding, and chronological validation windows.",
        ],
        parameter_bounds={
            "lookback": {"min": 2.0, "max": 120.0},
            "threshold": {"min": 0.0, "max": 0.1},
        },
        invalidation_conditions=[
            "Locked out-of-sample evidence is unavailable or fails the mandate gate.",
            "Required market data is stale, incomplete, or synthetic.",
        ],
    )


def _validate_spec_scope(spec: StrategySpecDraft, mandate: ResearchMandate) -> None:
    if set(spec.symbols) - set(mandate.symbols_json):
        raise ValueError("strategy_spec symbols exceed mandate allowlist")
    if set(spec.timeframes) - set(mandate.timeframes_json):
        raise ValueError("strategy_spec timeframes exceed mandate allowlist")
    if spec.strategy_category not in set(mandate.strategy_categories_json):
        raise ValueError("strategy_spec category exceeds mandate allowlist")


def _require_active_mandate(mandate: ResearchMandate) -> None:
    if mandate.status != "active":
        raise ValueError(f"research mandate is not active: {mandate.status}")
    if mandate.paper_promotion_mode != "manual_approval":
        raise ValueError("research mandate paper promotion mode must remain manual_approval")
    if mandate.live_mode != "disabled":
        raise ValueError("research mandate live mode must remain disabled")


def _get_mandate(session: Any, mandate_id: str) -> ResearchMandate:
    mandate = cast(ResearchMandate | None, session.get(ResearchMandate, mandate_id))
    if mandate is None:
        raise KeyError("Research mandate not found")
    return mandate


def _get_job(session: Any, job_id: str) -> ResearchJob:
    job = cast(ResearchJob | None, session.get(ResearchJob, job_id))
    if job is None:
        raise KeyError("Research job not found")
    return job


def _mandate_scope(mandate: ResearchMandate) -> dict[str, Any]:
    return {
        "id": mandate.id,
        "name": mandate.name,
        "status": mandate.status,
        "market_type": mandate.market_type,
        "symbols": list(mandate.symbols_json),
        "timeframes": list(mandate.timeframes_json),
        "strategy_categories": list(mandate.strategy_categories_json),
    }


def _mandate_to_dict(mandate: ResearchMandate) -> dict[str, Any]:
    return {
        **_mandate_scope(mandate),
        "budget": dict(mandate.budget_json),
        "validation": dict(mandate.validation_json),
        "paper_promotion_mode": mandate.paper_promotion_mode,
        "live_mode": mandate.live_mode,
        "version": mandate.version,
        "audit": list(mandate.audit_json),
        "created_at": mandate.created_at.isoformat(),
        "updated_at": mandate.updated_at.isoformat(),
    }


def _job_to_dict(job: ResearchJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "mandate_id": job.mandate_id,
        "status": job.status,
        "prompt": job.prompt,
        "strategy_spec": dict(job.strategy_spec_json),
        "idempotency_key": job.idempotency_key,
        "source_run_id": job.source_run_id,
        "attempts": job.attempts,
        "transitions": list(job.transition_json),
        "last_error": job.last_error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _audit_event(
    *,
    event: str,
    trace_ref: str,
    detail: str,
    source_run_id: str = "",
) -> dict[str, str]:
    return {
        "event": event,
        "trace_ref": trace_ref,
        "detail": detail,
        "source_run_id": source_run_id,
        "at": datetime.now(UTC).isoformat(),
    }


def _transition_event(
    *,
    previous: str,
    target: str,
    reason: str,
    source_run_id: str,
) -> dict[str, str]:
    return {
        "from": previous,
        "to": target,
        "reason": reason,
        "trace_ref": "research.job.transition",
        "source_run_id": source_run_id,
        "at": datetime.now(UTC).isoformat(),
    }


def _bounded_limit(value: int) -> int:
    return max(1, min(int(value), 100))
