"""Read-only lifecycle projections for regime-aware portfolio review."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import (
    BitProPaperMonitorSnapshot,
    Database,
    ExperimentEvidenceLink,
    PaperPromotion,
    ResearchExperimentEvidence,
    ResearchMandate,
    RobustnessValidationRun,
)


class StrategyCardService:
    """Join research and paper evidence; never changes BitPro or risk state."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            promotions = session.scalars(
                select(PaperPromotion).order_by(desc(PaperPromotion.updated_at))
            ).all()
            cards: list[dict[str, Any]] = []
            for promotion in promotions:
                evidence = session.get(ResearchExperimentEvidence, promotion.evidence_id)
                mandate = session.get(ResearchMandate, promotion.mandate_id)
                if evidence is None or mandate is None:
                    continue
                snapshot = session.scalars(
                    select(BitProPaperMonitorSnapshot)
                    .where(
                        BitProPaperMonitorSnapshot.scope_key == str(promotion.bitpro_strategy_id)
                    )
                    .order_by(desc(BitProPaperMonitorSnapshot.created_at))
                    .limit(1)
                ).first()
                experiment_link = session.scalar(
                    select(ExperimentEvidenceLink).where(
                        ExperimentEvidenceLink.evidence_id == evidence.id
                    )
                )
                robustness = (
                    session.scalar(
                        select(RobustnessValidationRun).where(
                            RobustnessValidationRun.experiment_execution_id
                            == experiment_link.execution_id
                        )
                    )
                    if experiment_link is not None
                    else None
                )
                cards.append(_card(promotion, evidence, mandate, snapshot, robustness))
            return cards


def _card(
    promotion: PaperPromotion,
    evidence: ResearchExperimentEvidence,
    mandate: ResearchMandate,
    snapshot: BitProPaperMonitorSnapshot | None,
    robustness: RobustnessValidationRun | None,
) -> dict[str, Any]:
    observation = dict(promotion.observation_json)
    raw_drift = observation.get("drift")
    drift: dict[str, Any] = raw_drift if isinstance(raw_drift, dict) else {}
    flags = list(drift.get("data_gaps", [])) + [
        str(alert.get("code", "monitor_alert"))
        for alert in drift.get("alerts", [])
        if isinstance(alert, dict)
    ]
    passed = (
        evidence.status == "evidence_recorded"
        and bool(evidence.gate_results_json)
        and all(evidence.gate_results_json.values())
        and (robustness is None or robustness.final_status == "validated")
    )
    freshness = _freshness(evidence.updated_at)
    if freshness != "fresh":
        flags.append("validation_evidence_stale")
    if promotion.status in {"paper_degraded", "paper_review_required"}:
        flags.append(promotion.status)
    symbols = list(mandate.symbols_json)
    return {
        "card_id": f"scard_{promotion.id.removeprefix('ppr_')}",
        "promotion_id": promotion.id,
        "mandate_id": mandate.id,
        "job_id": evidence.job_id,
        "evidence_id": evidence.id,
        "strategy_key": evidence.strategy_key,
        "bitpro_strategy_id": evidence.bitpro_strategy_id,
        "strategy_category": list(mandate.strategy_categories_json),
        "allowed_symbols": symbols,
        "allowed_timeframes": list(mandate.timeframes_json),
        "declared_regime_fit": _regime_fit(mandate.strategy_categories_json),
        "validation_status": "passed" if passed else "not_passed",
        "robustness_validation_id": robustness.id if robustness is not None else "",
        "robustness_status": (
            robustness.final_status if robustness is not None else "legacy_not_available"
        ),
        "evidence_freshness": freshness,
        "paper_status": promotion.status,
        "monitor_snapshot_id": snapshot.id if snapshot is not None else "",
        "drawdown": dict(snapshot.metrics_json).get("max_drawdown_pct") if snapshot else "unknown",
        "coverage_flags": _dedupe(flags),
        "retirement_reason": "",
        "qualified_for_paper_review": passed and promotion.status == "paper_observing",
        "source_refs": {
            "validation_evidence_id": evidence.id,
            "paper_promotion_id": promotion.id,
            "monitor_snapshot_id": snapshot.id if snapshot is not None else "",
            "robustness_validation_id": robustness.id if robustness is not None else "",
        },
    }


def _freshness(value: datetime) -> str:
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return "fresh" if (datetime.now(UTC) - current).days <= 7 else "stale"


def _regime_fit(categories: list[str]) -> list[str]:
    normalized = {str(item).upper() for item in categories}
    if "TREND" in normalized or "CTA" in normalized:
        return ["risk_on", "mixed"]
    if "MEAN_REVERSION" in normalized:
        return ["mixed"]
    return ["unknown"]


def _dedupe(values: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))
