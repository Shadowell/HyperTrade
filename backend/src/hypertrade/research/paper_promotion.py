"""Explicit human approval and read-only observation for BitPro paper promotion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, cast

from sqlalchemy import desc, select

from hypertrade.db import (
    Database,
    ExperimentEvidenceLink,
    PaperPromotion,
    ResearchExperimentEvidence,
    ResearchMandate,
    RobustnessValidationRun,
)

PAPER_PROMOTION_STATES = frozenset(
    {
        "pending_paper_approval",
        "approving",
        "paper_observing",
        "paper_degraded",
        "paper_review_required",
        "paper_retired",
    }
)
OBSERVABLE_PAPER_STATES = frozenset({"paper_observing", "paper_degraded", "paper_review_required"})


class PaperPromotionAdapter(Protocol):
    def paper_configure(
        self,
        *,
        strategy_id: int,
        initial_equity: float = 10000.0,
        exchange: str = "okx",
        loop_interval_sec: int = 60,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def paper_start(self, *, strategy_id: int, idempotency_key: str) -> dict[str, Any]: ...

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]: ...


class PaperPromotionService:
    """Keeps approval separate from BitPro paper writes and from any live path."""

    def __init__(
        self, db: Database, *, bitpro_adapter: PaperPromotionAdapter | None = None
    ) -> None:
        self.db = db
        self.bitpro_adapter = bitpro_adapter

    def request(self, *, evidence_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("paper promotion request requires a reason")
        with self.db.session() as session:
            existing = session.scalar(
                select(PaperPromotion).where(PaperPromotion.evidence_id == evidence_id)
            )
            if existing is not None:
                return _promotion_dict(existing)
            evidence = _evidence(session, evidence_id)
            if evidence.status != "evidence_recorded" or not all(
                evidence.gate_results_json.values()
            ):
                raise ValueError(
                    "only fully passing validation evidence can request paper promotion"
                )
            experiment_link = session.scalar(
                select(ExperimentEvidenceLink).where(
                    ExperimentEvidenceLink.evidence_id == evidence.id
                )
            )
            if experiment_link is not None:
                robustness = session.scalar(
                    select(RobustnessValidationRun).where(
                        RobustnessValidationRun.experiment_execution_id
                        == experiment_link.execution_id
                    )
                )
                if robustness is None or robustness.final_status != "validated":
                    raise ValueError(
                        "paper promotion requires a validated robustness run"
                    )
            mandate = _mandate(session, evidence.mandate_id)
            if mandate.paper_promotion_mode != "manual_approval" or mandate.live_mode != "disabled":
                raise ValueError("mandate does not permit manual paper-only promotion")
            row = PaperPromotion(
                mandate_id=mandate.id,
                job_id=evidence.job_id,
                evidence_id=evidence.id,
                strategy_key=evidence.strategy_key,
                bitpro_strategy_id=evidence.bitpro_strategy_id,
                request_reason=reason.strip(),
                transition_json=[_transition("", "pending_paper_approval", "request_created")],
            )
            session.add(row)
            session.flush()
            return _promotion_dict(row)

    def approve(
        self, *, promotion_id: str, reason: str, idempotency_key: str, approved_by: str
    ) -> dict[str, Any]:
        if not reason.strip() or not idempotency_key.strip():
            raise ValueError("paper approval requires a reason and idempotency_key")
        if self.bitpro_adapter is None:
            raise RuntimeError("paper promotion adapter is unavailable")
        with self.db.session() as session:
            row = _promotion(session, promotion_id)
            if row.approval_idempotency_key == idempotency_key:
                return _promotion_dict(row)
            if row.status != "pending_paper_approval":
                raise ValueError(f"paper promotion cannot be approved from {row.status}")
            if session.scalar(
                select(PaperPromotion).where(
                    PaperPromotion.approval_idempotency_key == idempotency_key
                )
            ):
                raise ValueError("approval idempotency_key is already bound to another promotion")
            row.approval_reason = reason.strip()
            row.approval_idempotency_key = idempotency_key.strip()
            row.approved_by = approved_by
            row.status = "approving"
            row.transition_json = [
                *row.transition_json,
                _transition("pending_paper_approval", "approving", "operator_approved"),
            ]
            strategy_id = int(row.bitpro_strategy_id)
            session.flush()

        try:
            configured = self.bitpro_adapter.paper_configure(
                strategy_id=strategy_id,
                idempotency_key=f"{idempotency_key}:configure"[:128],
            )
            paper = _dict(configured.get("paper"))
            instance_id = paper.get("instance_id") or paper.get("id") or strategy_id
            started = self.bitpro_adapter.paper_start(
                strategy_id=int(instance_id),
                idempotency_key=f"{idempotency_key}:start"[:128],
            )
        except Exception as exc:  # noqa: BLE001 - preserve failed external approval audit
            return self._fail_approval(promotion_id, str(exc))

        with self.db.session() as session:
            row = _promotion(session, promotion_id)
            row.status = "paper_observing"
            row.paper_refs_json = {
                "bitpro_strategy_id": strategy_id,
                "paper_instance_id": str(instance_id),
                "configure_tool_calls": _tool_calls(configured),
                "start_tool_calls": _tool_calls(started),
            }
            row.transition_json = [
                *row.transition_json,
                _transition("approving", "paper_observing", "paper_started"),
            ]
            session.flush()
            return _promotion_dict(row)

    def observe(self, promotion_id: str) -> dict[str, Any]:
        if self.bitpro_adapter is None:
            raise RuntimeError("paper promotion adapter is unavailable")
        with self.db.session() as session:
            row = _promotion(session, promotion_id)
            if row.status not in OBSERVABLE_PAPER_STATES:
                raise ValueError(f"paper promotion cannot be observed from {row.status}")
            strategy_id = int(row.bitpro_strategy_id)
        paper = self.bitpro_adapter.paper_snapshot(strategy_id=strategy_id)
        snapshot = _dict(paper.get("snapshot"))
        gaps, alerts = _snapshot_health(snapshot)
        drift = {"mode": "bitpro_paper_snapshot", "data_gaps": gaps, "alerts": alerts}
        next_status = (
            "paper_review_required" if alerts else "paper_degraded" if gaps else "paper_observing"
        )
        with self.db.session() as session:
            row = _promotion(session, promotion_id)
            previous = row.status
            row.status = next_status
            observation = {
                "snapshot_id": str(snapshot.get("instance_id", "")),
                "metrics": _snapshot_metrics(snapshot),
                "drift": drift,
                "paper_snapshot": snapshot,
                "recommended_next_action": "operator_review"
                if next_status != "paper_observing"
                else "continue_read_only_observation",
            }
            history = list(row.observation_json.get("history", []))
            row.observation_json = {**observation, "history": [*history[-19:], observation]}
            row.transition_json = [
                *row.transition_json,
                _transition(previous, next_status, "monitor_evidence"),
            ]
            session.flush()
            return _promotion_dict(row)

    def list(self, *, status: str = "") -> list[dict[str, Any]]:
        with self.db.session() as session:
            statement = select(PaperPromotion).order_by(desc(PaperPromotion.created_at))
            if status:
                statement = statement.where(PaperPromotion.status == status)
            return [_promotion_dict(row) for row in session.scalars(statement).all()]

    def get(self, promotion_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            return _promotion_dict(_promotion(session, promotion_id))

    def _fail_approval(self, promotion_id: str, detail: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = _promotion(session, promotion_id)
            row.status = "paper_review_required"
            row.observation_json = {
                "approval_error": detail[:500],
                "recommended_next_action": "operator_review",
            }
            row.transition_json = [
                *row.transition_json,
                _transition("approving", "paper_review_required", "paper_start_failed"),
            ]
            session.flush()
            return _promotion_dict(row)


def _promotion(session: Any, promotion_id: str) -> PaperPromotion:
    row = cast(PaperPromotion | None, session.get(PaperPromotion, promotion_id))
    if row is None:
        raise KeyError("Paper promotion not found")
    return row


def _evidence(session: Any, evidence_id: str) -> ResearchExperimentEvidence:
    row = cast(
        ResearchExperimentEvidence | None, session.get(ResearchExperimentEvidence, evidence_id)
    )
    if row is None:
        raise KeyError("Research evidence not found")
    return row


def _mandate(session: Any, mandate_id: str) -> ResearchMandate:
    row = cast(ResearchMandate | None, session.get(ResearchMandate, mandate_id))
    if row is None:
        raise KeyError("Research mandate not found")
    return row


def _promotion_dict(row: PaperPromotion) -> dict[str, Any]:
    return {
        "id": row.id,
        "mandate_id": row.mandate_id,
        "job_id": row.job_id,
        "evidence_id": row.evidence_id,
        "strategy_key": row.strategy_key,
        "bitpro_strategy_id": row.bitpro_strategy_id,
        "status": row.status,
        "request_reason": row.request_reason,
        "approval_reason": row.approval_reason,
        "approval_idempotency_key": row.approval_idempotency_key or "",
        "approved_by": row.approved_by,
        "paper_refs": dict(row.paper_refs_json),
        "observation": dict(row.observation_json),
        "transitions": list(row.transition_json),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _transition(previous: str, target: str, reason: str) -> dict[str, str]:
    return {
        "from": previous,
        "to": target,
        "reason": reason,
        "trace_ref": "research.paper_promotion",
        "at": datetime.now(UTC).isoformat(),
    }


def _dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tool_calls")
    return (
        [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    )


def _snapshot_health(snapshot: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    gaps = [
        f"missing {field}"
        for field in ("instance_id", "strategy_version", "config_version", "generated_at")
        if not snapshot.get(field)
    ]
    coverage = _dict(snapshot.get("data_coverage"))
    if not coverage.get("equity_sample_count"):
        gaps.append("missing equity sample coverage")
    alerts: list[dict[str, str]] = []
    if str(snapshot.get("status", "")) != "running":
        alerts.append({"level": "warning", "code": "paper_not_running"})
    if int(snapshot.get("error_count", 0) or 0) > 0:
        alerts.append({"level": "warning", "code": "paper_errors"})
    return gaps, alerts


def _snapshot_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in (
            "equity",
            "pnl",
            "cumulative_return_pct",
            "max_drawdown_pct",
            "sharpe_ratio",
            "trade_count",
            "error_count",
        )
        if snapshot.get(key) is not None
    }
