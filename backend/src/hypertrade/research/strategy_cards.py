"""Stable StrategyCard V2 identity and immutable lifecycle projections."""

from __future__ import annotations

import builtins
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    BitProPaperMonitorSnapshot,
    Database,
    ExperimentEvidenceLink,
    ExperimentExecution,
    ExperimentManifest,
    PaperPromotion,
    ResearchExperimentEvidence,
    ResearchMandate,
    RobustnessValidationRun,
    StrategyCardLifecycleDecision,
    StrategyCardSnapshot,
    StrategyLineage,
    StrategyVersion,
    UnifiedStrategyValidation,
)
from hypertrade.memory.governance import MemoryAssertionService
from hypertrade.research.strategy_card_schemas import (
    StrategyCardDecisionRequestV1,
    StrategyCardV2,
    StrategyLineageV1,
    StrategyVersionV1,
)


class StrategyCardService:
    """Rebuild Card snapshots from facts; never changes BitPro, paper, or risk state."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def reconcile_all(self, *, actor: str = "strategy_card_reconcile") -> dict[str, Any]:
        with self.db.session() as session:
            manifest_ids = list(
                session.scalars(
                    select(ExperimentManifest.id).order_by(ExperimentManifest.created_at)
                ).all()
            )
        snapshots = [
            self.reconcile_manifest(manifest_id, actor=actor) for manifest_id in manifest_ids
        ]
        return {
            "schema_version": "strategy_card_reconcile.v2",
            "manifest_count": len(manifest_ids),
            "card_count": len(snapshots),
            "items": snapshots,
            "mutation_boundary": {
                "projection_tables_only": True,
                "bitpro_writes": False,
                "paper_writes": False,
                "live_writes": False,
                "capital_writes": False,
            },
        }

    def reconcile_manifest(
        self, manifest_id: str, *, actor: str = "strategy_card_reconcile"
    ) -> dict[str, Any]:
        version_id = self._ensure_identity(manifest_id, actor=actor)
        return self._append_snapshot(version_id, actor=actor)

    def list(self) -> list[dict[str, Any]]:
        # Reconciliation is idempotent and writes only derived projection tables.
        self.reconcile_all()
        with self.db.session() as session:
            versions = session.scalars(
                select(StrategyVersion).order_by(
                    StrategyVersion.lineage_id, desc(StrategyVersion.version_number)
                )
            ).all()
            cards = [self._latest_snapshot(session, row.id) for row in versions]
        represented = {
            (str(card.get("mandate_id", "")), str(card.get("strategy_key", ""))) for card in cards
        }
        return cards + self._legacy_cards(exclude=represented)

    def funnel(self) -> dict[str, Any]:
        cards = [card for card in self.list() if card.get("schema_version") == "strategy_card.v2"]
        stages = {
            "task": 0,
            "spec": 0,
            "manifest": len(cards),
            "evidence": 0,
            "validation": 0,
            "paper": 0,
            "card": len(cards),
        }
        items: list[dict[str, Any]] = []
        for card in cards:
            refs = dict(card.get("source_refs", {}))
            reached = {
                "task": bool(refs.get("task_ids") or refs.get("research_job_ids")),
                "spec": bool(card.get("title") and card.get("hypothesis")),
                "manifest": bool(refs.get("manifest_id")),
                "evidence": bool(refs.get("evidence_ids")),
                "validation": bool(refs.get("validation_ids")),
                "paper": bool(refs.get("paper_promotion_ids")),
                "card": True,
            }
            for stage, present in reached.items():
                stages[stage] += int(present) if stage not in {"manifest", "card"} else 0
            items.append(
                {
                    "card_id": card["card_id"],
                    "version_id": card["version"]["id"],
                    "manifest_id": refs.get("manifest_id", ""),
                    "lifecycle_status": card["lifecycle_status"],
                    "reached": reached,
                    "missing_fields": list(card.get("missing_fields", [])),
                }
            )
        return {
            "schema_version": "research_funnel.v2",
            "denominator": len(cards),
            "denominator_unit": "experiment_manifest",
            "stages": stages,
            "items": items,
        }

    def snapshots(self, card_id: str) -> builtins.list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(StrategyCardSnapshot)
                .where(StrategyCardSnapshot.card_id == card_id)
                .order_by(StrategyCardSnapshot.created_at)
            ).all()
            if not rows:
                raise KeyError(card_id)
            return [_snapshot_to_dict(row) for row in rows]

    def decide(
        self,
        card_id: str,
        payload: StrategyCardDecisionRequestV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        request_hash = _hash(
            {
                "card_id": card_id,
                "target_status": payload.target_status,
                "decision": payload.decision,
                "reason": payload.reason,
            }
        )
        with self.db.session() as session:
            existing = session.scalar(
                select(StrategyCardLifecycleDecision).where(
                    StrategyCardLifecycleDecision.idempotency_key == payload.idempotency_key
                )
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ValueError("idempotency key is bound to another lifecycle decision")
                decision = _decision_to_dict(existing)
                version_id = existing.version_id
            else:
                snapshot = session.scalar(
                    select(StrategyCardSnapshot)
                    .where(StrategyCardSnapshot.card_id == card_id)
                    .order_by(desc(StrategyCardSnapshot.created_at))
                    .limit(1)
                )
                if snapshot is None:
                    raise KeyError(card_id)
                row = StrategyCardLifecycleDecision(
                    card_id=card_id,
                    lineage_id=snapshot.lineage_id,
                    version_id=snapshot.version_id,
                    snapshot_id=snapshot.id,
                    target_status=payload.target_status,
                    decision=payload.decision,
                    reason=payload.reason,
                    request_hash=request_hash,
                    idempotency_key=payload.idempotency_key,
                    decided_by=actor,
                )
                session.add(row)
                session.flush()
                decision = _decision_to_dict(row)
                version_id = row.version_id
        card = self._append_snapshot(version_id, actor="strategy_card_decision")
        return {
            "schema_version": "strategy_card_decision.v1",
            "decision": decision,
            "card": card,
            "execution_authorized": False,
        }

    def _legacy_cards(
        self, *, exclude: set[tuple[str, str]]
    ) -> builtins.list[dict[str, Any]]:
        """Keep pre-ledger PaperPromotion records visible without guessing a Manifest."""

        with self.db.session() as session:
            promotions = session.scalars(
                select(PaperPromotion).order_by(desc(PaperPromotion.updated_at))
            ).all()
            cards: builtins.list[dict[str, Any]] = []
            for promotion in promotions:
                identity = (promotion.mandate_id, promotion.strategy_key)
                if identity in exclude:
                    continue
                evidence = session.get(ResearchExperimentEvidence, promotion.evidence_id)
                mandate = session.get(ResearchMandate, promotion.mandate_id)
                if evidence is None or mandate is None:
                    continue
                monitor = session.scalar(
                    select(BitProPaperMonitorSnapshot)
                    .where(
                        BitProPaperMonitorSnapshot.scope_key == str(promotion.bitpro_strategy_id)
                    )
                    .order_by(desc(BitProPaperMonitorSnapshot.created_at))
                    .limit(1)
                )
                flags = list(dict(promotion.observation_json).get("drift", {}).get("data_gaps", []))
                if promotion.status in {"paper_degraded", "paper_review_required"}:
                    flags.append(promotion.status)
                passed = (
                    evidence.status == "evidence_recorded"
                    and bool(evidence.gate_results_json)
                    and all(evidence.gate_results_json.values())
                )
                cards.append(
                    {
                        "schema_version": "strategy_card.v1_compat",
                        "card_id": f"scard_{promotion.id.removeprefix('ppr_')}",
                        "promotion_id": promotion.id,
                        "mandate_id": mandate.id,
                        "job_id": evidence.job_id,
                        "evidence_id": evidence.id,
                        "strategy_key": evidence.strategy_key,
                        "bitpro_strategy_id": evidence.bitpro_strategy_id,
                        "strategy_category": list(mandate.strategy_categories_json),
                        "allowed_symbols": list(mandate.symbols_json),
                        "allowed_timeframes": list(mandate.timeframes_json),
                        "declared_regime_fit": _regime_fit(
                            str(mandate.strategy_categories_json[0])
                            if mandate.strategy_categories_json
                            else "unknown"
                        ),
                        "direction_exposure": "unknown",
                        "validation_status": "passed" if passed else "not_passed",
                        "robustness_validation_id": "",
                        "robustness_status": "legacy_not_available",
                        "evidence_freshness": _freshness(evidence.updated_at),
                        "paper_status": promotion.status,
                        "monitor_snapshot_id": monitor.id if monitor is not None else "",
                        "drawdown": (
                            dict(monitor.metrics_json).get("max_drawdown_pct", "unknown")
                            if monitor is not None
                            else "unknown"
                        ),
                        "capacity": dict(evidence.metrics_json).get("capacity_usdt", "unknown"),
                        "liquidity": dict(evidence.metrics_json).get("liquidity_status", "unknown"),
                        "monitor_drift": (
                            dict(monitor.drift_json or {}) if monitor is not None else {}
                        ),
                        "memory_assertion_ids": [],
                        "coverage_flags": list(dict.fromkeys(flags)),
                        "retirement_reason": "",
                        "qualified_for_paper_review": (
                            passed and promotion.status == "paper_observing"
                        ),
                        "source_refs": {
                            "validation_evidence_id": evidence.id,
                            "paper_promotion_id": promotion.id,
                            "monitor_snapshot_id": monitor.id if monitor is not None else "",
                            "experiment_manifest_id": "",
                        },
                        "unknowns": ["strategy_card.manifest_unavailable"],
                        "missing_fields": ["manifest"],
                        "completeness_score": "unknown",
                    }
                )
            return cards

    def _ensure_identity(self, manifest_id: str, *, actor: str) -> str:
        try:
            with self.db.session() as session:
                manifest = session.get(ExperimentManifest, manifest_id)
                if manifest is None:
                    raise KeyError(manifest_id)
                lineage_key = _hash(
                    {"mandate_id": manifest.mandate_id, "strategy_key": manifest.strategy_key}
                )
                lineage = session.scalar(
                    select(StrategyLineage).where(StrategyLineage.lineage_key == lineage_key)
                )
                if lineage is None:
                    lineage = StrategyLineage(
                        lineage_key=lineage_key,
                        mandate_id=manifest.mandate_id,
                        strategy_key=manifest.strategy_key,
                        created_by=actor,
                    )
                    session.add(lineage)
                    session.flush()
                version = session.scalar(
                    select(StrategyVersion).where(StrategyVersion.manifest_id == manifest.id)
                )
                if version is None:
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        session.scalar(
                            select(StrategyLineage)
                            .where(StrategyLineage.id == lineage.id)
                            .with_for_update()
                        )
                    latest_number = session.scalar(
                        select(func.max(StrategyVersion.version_number)).where(
                            StrategyVersion.lineage_id == lineage.id
                        )
                    )
                    spec = dict(manifest.canonical_json).get("strategy_spec", {})
                    version = StrategyVersion(
                        lineage_id=lineage.id,
                        version_number=int(latest_number or 0) + 1,
                        manifest_id=manifest.id,
                        manifest_fingerprint=manifest.fingerprint,
                        strategy_spec_hash=_hash(spec),
                        created_by=actor,
                    )
                    session.add(version)
                    session.flush()
                return version.id
        except IntegrityError:
            with self.db.session() as session:
                version = session.scalar(
                    select(StrategyVersion).where(StrategyVersion.manifest_id == manifest_id)
                )
                if version is None:
                    raise
                return version.id

    def _append_snapshot(self, version_id: str, *, actor: str) -> dict[str, Any]:
        card = self._project(version_id)
        content_hash = _hash(card)
        try:
            with self.db.session() as session:
                existing = session.scalar(
                    select(StrategyCardSnapshot).where(
                        StrategyCardSnapshot.version_id == version_id,
                        StrategyCardSnapshot.content_hash == content_hash,
                    )
                )
                if existing is None:
                    row = StrategyCardSnapshot(
                        card_id=card["card_id"],
                        lineage_id=card["lineage"]["id"],
                        version_id=version_id,
                        schema_version="strategy_card.v2",
                        lifecycle_status=card["lifecycle_status"],
                        completeness_score=Decimal(card["completeness_score"]),
                        content_hash=content_hash,
                        card_json=card,
                        created_by=actor,
                    )
                    session.add(row)
                    session.flush()
                    return _snapshot_to_dict(row)
                return _snapshot_to_dict(existing)
        except IntegrityError:
            # Concurrent ledger reconciliation can project identical card content.
            # The unique key is the serialization point; return the committed winner.
            with self.db.session() as session:
                winner = session.scalar(
                    select(StrategyCardSnapshot).where(
                        StrategyCardSnapshot.version_id == version_id,
                        StrategyCardSnapshot.content_hash == content_hash,
                    )
                )
                if winner is None:
                    raise
                return _snapshot_to_dict(winner)

    def _project(self, version_id: str) -> dict[str, Any]:
        assertions = MemoryAssertionService(self.db).active_for_prompt(limit=100)
        with self.db.session() as session:
            version = session.get(StrategyVersion, version_id)
            if version is None:
                raise KeyError(version_id)
            lineage = cast(StrategyLineage, session.get(StrategyLineage, version.lineage_id))
            manifest = cast(
                ExperimentManifest,
                session.get(ExperimentManifest, version.manifest_id),
            )
            executions = session.scalars(
                select(ExperimentExecution)
                .where(ExperimentExecution.manifest_id == manifest.id)
                .order_by(desc(ExperimentExecution.attempt))
            ).all()
            execution_ids = [row.id for row in executions]
            links = (
                session.scalars(
                    select(ExperimentEvidenceLink).where(
                        ExperimentEvidenceLink.execution_id.in_(execution_ids)
                    )
                ).all()
                if execution_ids
                else []
            )
            evidence_ids = sorted({row.evidence_id for row in links})
            legacy_evidence = [
                row
                for evidence_id in evidence_ids
                if (row := session.get(ResearchExperimentEvidence, evidence_id)) is not None
            ]
            validations = (
                session.scalars(
                    select(RobustnessValidationRun)
                    .where(RobustnessValidationRun.experiment_execution_id.in_(execution_ids))
                    .order_by(desc(RobustnessValidationRun.created_at))
                ).all()
                if execution_ids
                else []
            )
            unified_validations = (
                session.scalars(
                    select(UnifiedStrategyValidation)
                    .where(
                        UnifiedStrategyValidation.experiment_execution_id.in_(
                            execution_ids
                        )
                    )
                    .order_by(desc(UnifiedStrategyValidation.created_at))
                ).all()
                if execution_ids
                else []
            )
            promotion = session.scalar(
                select(PaperPromotion)
                .where(
                    and_(
                        PaperPromotion.mandate_id == manifest.mandate_id,
                        or_(
                            PaperPromotion.evidence_id.in_(evidence_ids or ["__none__"]),
                            PaperPromotion.strategy_key == manifest.strategy_key,
                        ),
                    )
                )
                .order_by(desc(PaperPromotion.updated_at))
                .limit(1)
            )
            bitpro_strategy_id = next(
                (row.bitpro_strategy_id for row in legacy_evidence if row.bitpro_strategy_id), ""
            )
            if promotion is not None and promotion.bitpro_strategy_id:
                bitpro_strategy_id = promotion.bitpro_strategy_id
            monitor = (
                session.scalar(
                    select(BitProPaperMonitorSnapshot)
                    .where(BitProPaperMonitorSnapshot.scope_key == str(bitpro_strategy_id))
                    .order_by(desc(BitProPaperMonitorSnapshot.created_at))
                    .limit(1)
                )
                if bitpro_strategy_id
                else None
            )
            decision = session.scalar(
                select(StrategyCardLifecycleDecision)
                .where(StrategyCardLifecycleDecision.version_id == version.id)
                .order_by(desc(StrategyCardLifecycleDecision.created_at))
                .limit(1)
            )

            canonical = dict(manifest.canonical_json)
            spec = dict(canonical.get("strategy_spec", {}))
            symbols = [str(value) for value in spec.get("symbols", [])]
            category = str(spec.get("strategy_category", "unknown"))
            matching_assertions = [
                str(assertion["id"])
                for assertion in assertions
                if _assertion_matches(assertion, symbols, manifest.strategy_key)
            ]
            validation = validations[0] if validations else None
            unified_validation = unified_validations[0] if unified_validations else None
            evidence = legacy_evidence[0] if legacy_evidence else None
            latest_execution = executions[0] if executions else None
            lifecycle = _lifecycle(
                latest_execution=latest_execution,
                validation=validation,
                promotion=promotion,
                decision=decision,
            )
            if unified_validation is not None and promotion is None and decision is None:
                lifecycle = (
                    "validated"
                    if unified_validation.status == "validated"
                    else "validation_rejected"
                )
            present = {
                "identity": True,
                "manifest": True,
                "execution": latest_execution is not None,
                "evidence": bool(evidence_ids),
                "validation": validation is not None or unified_validation is not None,
                "paper": promotion is not None,
                "monitor": monitor is not None,
                "memory": bool(matching_assertions),
            }
            missing_fields = [key for key, value in present.items() if not value]
            score = Decimal(sum(present.values())) / Decimal(len(present))
            paper_status = promotion.status if promotion is not None else "not_started"
            robustness_status = validation.final_status if validation is not None else "unknown"
            effective_validation_status = (
                unified_validation.status
                if unified_validation is not None
                else validation.final_status
                if validation is not None
                else "unknown"
            )
            validation_status = (
                "passed"
                if effective_validation_status == "validated"
                else "not_passed"
                if effective_validation_status != "unknown"
                else "unknown"
            )
            freshness = _freshness(evidence.updated_at) if evidence is not None else "unknown"
            metrics = dict(evidence.metrics_json or {}) if evidence is not None else {}
            latest_decision = _decision_to_dict(decision) if decision is not None else {}
            card = StrategyCardV2(
                card_id=f"scard_{version.id.removeprefix('sver_')}",
                lineage=StrategyLineageV1(
                    id=lineage.id,
                    lineage_key=lineage.lineage_key,
                    mandate_id=lineage.mandate_id,
                    strategy_key=lineage.strategy_key,
                ),
                version=StrategyVersionV1(
                    id=version.id,
                    lineage_id=version.lineage_id,
                    version_number=version.version_number,
                    manifest_id=version.manifest_id,
                    manifest_fingerprint=version.manifest_fingerprint,
                    strategy_spec_hash=version.strategy_spec_hash,
                ),
                lifecycle_status=lifecycle,
                completeness_score=format(score.quantize(Decimal("0.00001")), "f"),
                missing_fields=missing_fields,
                unknowns=[f"strategy_card.{key}_unavailable" for key in missing_fields],
                strategy_key=manifest.strategy_key,
                title=str(spec.get("title", manifest.strategy_key)),
                hypothesis=str(spec.get("hypothesis", "unknown")),
                mandate_id=manifest.mandate_id,
                allowed_symbols=symbols,
                allowed_timeframes=[str(value) for value in spec.get("timeframes", [])],
                strategy_category=[category],
                validation_status=validation_status,
                robustness_status=robustness_status,
                paper_status=paper_status,
                evidence_freshness=freshness,
                drawdown=(
                    str(dict(monitor.metrics_json).get("max_drawdown_pct", "unknown"))
                    if monitor is not None
                    else "unknown"
                ),
                capacity=str(metrics.get("capacity_usdt", "unknown")),
                liquidity=str(metrics.get("liquidity_status", "unknown")),
                memory_assertion_ids=matching_assertions,
                coverage_flags=[f"missing:{key}" for key in missing_fields],
                qualified_for_paper_review=(
                    validation_status == "passed"
                    and paper_status in {"not_started", "paper_pending"}
                ),
                source_refs={
                    "manifest_id": manifest.id,
                    "manifest_fingerprint": manifest.fingerprint,
                    "execution_ids": execution_ids,
                    "task_ids": sorted({row.task_id for row in executions if row.task_id}),
                    "research_job_ids": sorted(
                        {row.research_job_id for row in executions if row.research_job_id}
                    ),
                    "evidence_ids": evidence_ids,
                    "validation_ids": [row.id for row in unified_validations]
                    + [row.id for row in validations],
                    "paper_promotion_ids": [promotion.id] if promotion is not None else [],
                    "monitor_snapshot_ids": [monitor.id] if monitor is not None else [],
                    "memory_assertion_ids": matching_assertions,
                },
                latest_decision=latest_decision,
                promotion_id=promotion.id if promotion is not None else "",
                job_id=evidence.job_id if evidence is not None else "",
                evidence_id=evidence.id if evidence is not None else "",
                bitpro_strategy_id=bitpro_strategy_id,
                declared_regime_fit=_regime_fit(category),
                monitor_snapshot_id=monitor.id if monitor is not None else "",
                monitor_drift=dict(monitor.drift_json or {}) if monitor is not None else {},
                retirement_reason=(
                    decision.reason
                    if decision is not None
                    and decision.decision == "accept"
                    and decision.target_status == "retired"
                    else ""
                ),
                robustness_validation_id=validation.id if validation is not None else "",
                experiment_manifest_id=manifest.id,
            )
            return card.model_dump(mode="json")

    @staticmethod
    def _latest_snapshot(session: Any, version_id: str) -> dict[str, Any]:
        row = session.scalar(
            select(StrategyCardSnapshot)
            .where(StrategyCardSnapshot.version_id == version_id)
            .order_by(desc(StrategyCardSnapshot.created_at))
            .limit(1)
        )
        if row is None:
            raise KeyError(version_id)
        return _snapshot_to_dict(row)


def _lifecycle(
    *,
    latest_execution: ExperimentExecution | None,
    validation: RobustnessValidationRun | None,
    promotion: PaperPromotion | None,
    decision: StrategyCardLifecycleDecision | None,
) -> str:
    if decision is not None and decision.decision == "accept":
        return decision.target_status
    if promotion is not None:
        if promotion.status == "paper_degraded":
            return "degraded"
        if promotion.status == "paper_review_required":
            return "review_required"
        if promotion.status == "paper_observing":
            return "observing"
        return "paper_pending"
    if validation is not None:
        return "validated" if validation.final_status == "validated" else "validation_rejected"
    if latest_execution is not None:
        return "testing"
    return "researching"


def _snapshot_to_dict(row: StrategyCardSnapshot) -> dict[str, Any]:
    result = dict(row.card_json)
    result.update(
        {
            "snapshot_id": row.id,
            "snapshot_content_hash": row.content_hash,
            "snapshot_created_at": row.created_at.isoformat(),
        }
    )
    return result


def _decision_to_dict(row: StrategyCardLifecycleDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "card_id": row.card_id,
        "version_id": row.version_id,
        "snapshot_id": row.snapshot_id,
        "target_status": row.target_status,
        "decision": row.decision,
        "reason": row.reason,
        "idempotency_key": row.idempotency_key,
        "decided_by": row.decided_by,
        "created_at": row.created_at.isoformat(),
    }


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _freshness(value: datetime) -> str:
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return "fresh" if (datetime.now(UTC) - current).days <= 7 else "stale"


def _regime_fit(category: str) -> list[str]:
    normalized = category.upper()
    if normalized in {"TREND", "CTA"}:
        return ["risk_on", "mixed"]
    if normalized == "MEAN_REVERSION":
        return ["mixed"]
    return ["unknown"]


def _assertion_matches(assertion: dict[str, Any], symbols: list[str], strategy_key: str) -> bool:
    scope = dict(assertion.get("scope", {}))
    scoped_symbols = {str(value).upper() for value in scope.get("symbols", [])}
    scoped_tags = {str(value).casefold() for value in scope.get("tags", [])}
    return bool(
        scoped_symbols.intersection(str(value).upper() for value in symbols)
        or strategy_key.casefold() in scoped_tags
    )
