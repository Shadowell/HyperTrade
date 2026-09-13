"""Evolution readiness projection for BitPro running strategies (M0 Handoff).

Before a strategy can enter the evolution loop it must satisfy preconditions
that this projection makes explicit instead of discovering them mid-run:

1. HyperTrade holds settled BitPro evidence for the strategy
   (BitProStrategyEvidenceRecord rows whose source_id or summary names it).
2. The strategy maps to an internal immutable StrategyVersion lineage — without
   that mapping a Challenger has no parent to differ from. The mapping is
   resolved per BitPro strategy id: only internal records that name the id
   together with a manifest, version, or mandate/strategy-key pointer count, so
   another strategy's ledger can never vouch for this one. Legacy strategies
   that predate the ledger honestly report this gap.
3. At least two settled outcomes exist for the lineage (the decay assessor's
   own minimum).

The report never invents readiness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select

from hypertrade.db import (
    BitProStrategyEvidenceRecord,
    Database,
    PaperIncubationMember,
    PaperPromotion,
    ResearchExperimentEvidence,
    StrategyDiscoveryCandidate,
    StrategyLineage,
    StrategyOutcome,
    StrategyVersion,
)


@dataclass(frozen=True)
class EvolutionReadinessProjection:
    bitpro_strategy_id: str
    name: str
    status: str
    evidence_record_count: int
    latest_evidence_as_of: str | None
    outcome_count: int
    version_mapped: bool
    ready: bool
    gaps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "bitpro_strategy_id": self.bitpro_strategy_id,
            "name": self.name,
            "status": self.status,
            "evidence_record_count": self.evidence_record_count,
            "latest_evidence_as_of": self.latest_evidence_as_of,
            "outcome_count": self.outcome_count,
            "version_mapped": self.version_mapped,
            "ready": self.ready,
            "gaps": list(self.gaps),
        }


def _evidence_for_bitpro_id(db: Database, sid: str) -> list[BitProStrategyEvidenceRecord]:
    with db.session() as session:
        direct = list(
            session.scalars(
                select(BitProStrategyEvidenceRecord)
                .where(BitProStrategyEvidenceRecord.source_id == sid)
                .order_by(BitProStrategyEvidenceRecord.created_at.desc())
            )
        )
        if direct:
            return direct
        rows = session.scalars(select(BitProStrategyEvidenceRecord)).all()
        # Evidence payloads may name the BitPro strategy inside their summary;
        # checking both keeps undercounting impossible.
        return [
            row
            for row in rows
            if str((row.summary_json or {}).get("strategy_id") or "") == sid
        ]


def _mapped_lineage_ids(db: Database, sid: str) -> frozenset[str]:
    """Lineages one BitPro strategy id is provably bound to.

    Every accepted record type carries the BitPro id *and* an internal identity
    pointer: discovery candidates and incubation members name the manifest or
    version created for that exact BitPro strategy; promotions and legacy
    experiment evidence name the mandate/strategy-key pair whose lineage the
    BitPro strategy was created from. Anything looser — the global version or
    outcome ledger — would let one strategy's history vouch for another.
    """

    version_ids: set[str] = set()
    manifest_ids: set[str] = set()
    lineage_ids: set[str] = set()
    identity_keys: set[tuple[str, str]] = set()
    with db.session() as session:
        for candidate in session.scalars(
            select(StrategyDiscoveryCandidate).where(
                StrategyDiscoveryCandidate.bitpro_strategy_id == sid
            )
        ).all():
            if candidate.strategy_version_id:
                version_ids.add(candidate.strategy_version_id)
            if candidate.manifest_id:
                manifest_ids.add(candidate.manifest_id)
        for member in session.scalars(
            select(PaperIncubationMember).where(
                PaperIncubationMember.bitpro_strategy_id == sid,
                PaperIncubationMember.status != "rejected",
            )
        ).all():
            if member.manifest_id:
                manifest_ids.add(member.manifest_id)
        for promotion in session.scalars(
            select(PaperPromotion).where(PaperPromotion.bitpro_strategy_id == sid)
        ).all():
            identity_keys.add((promotion.mandate_id, promotion.strategy_key))
        for legacy in session.scalars(
            select(ResearchExperimentEvidence).where(
                ResearchExperimentEvidence.bitpro_strategy_id == sid
            )
        ).all():
            identity_keys.add((legacy.mandate_id, legacy.strategy_key))
        for mandate_id, strategy_key in identity_keys:
            if not mandate_id or not strategy_key:
                continue
            lineage_ids.update(
                lineage.id
                for lineage in session.scalars(
                    select(StrategyLineage).where(
                        StrategyLineage.mandate_id == mandate_id,
                        StrategyLineage.strategy_key == strategy_key,
                    )
                ).all()
            )
        if version_ids or manifest_ids:
            lineage_ids.update(
                version.lineage_id
                for version in session.scalars(
                    select(StrategyVersion).where(
                        or_(
                            StrategyVersion.id.in_(version_ids),
                            StrategyVersion.manifest_id.in_(manifest_ids),
                        )
                    )
                ).all()
            )
    return frozenset(lineage_ids)


def assess_running_strategy(
    db: Database,
    *,
    bitpro_strategy_id: int | str,
    name: str,
    status: str,
) -> EvolutionReadinessProjection:
    """Project evolution readiness for one BitPro running strategy."""

    sid = str(bitpro_strategy_id)
    gaps: list[str] = []

    evidence = _evidence_for_bitpro_id(db, sid)
    if not evidence:
        gaps.append("no_settled_bitpro_evidence")

    lineage_ids = _mapped_lineage_ids(db, sid)
    version_mapped = bool(lineage_ids)
    if not version_mapped:
        gaps.append("no_internal_strategy_version_mapping")

    outcome_count = 0
    if version_mapped:
        with db.session() as session:
            outcome_count = len(
                session.scalars(
                    select(StrategyOutcome).where(
                        StrategyOutcome.strategy_lineage_id.in_(lineage_ids)
                    )
                ).all()
            )
    if outcome_count < 2:
        gaps.append("fewer_than_two_settled_outcomes")

    latest = evidence[0].as_of.isoformat() if evidence and evidence[0].as_of else None
    return EvolutionReadinessProjection(
        bitpro_strategy_id=sid,
        name=name,
        status=status,
        evidence_record_count=len(evidence),
        latest_evidence_as_of=latest,
        outcome_count=outcome_count,
        version_mapped=version_mapped,
        ready=not gaps,
        gaps=gaps,
    )


def running_inventory_readiness(
    db: Database,
    adapter: Any,
    *,
    limit: int = 20,
) -> list[EvolutionReadinessProjection]:
    """Project readiness across the live running inventory."""
    payload = adapter.strategy_search(
        page=1, per_page=max(1, min(limit, 50)), status="running"
    )
    raw = payload.get("strategies")
    if isinstance(raw, dict):
        items = raw.get("items") or raw.get("strategies") or raw.get("results") or []
    else:
        items = raw if isinstance(raw, list) else []
    projections: list[EvolutionReadinessProjection] = []
    for row in items[:limit]:
        if not isinstance(row, dict):
            continue
        sid = row.get("id") or row.get("strategy_id")
        if sid is None:
            continue
        projections.append(
            assess_running_strategy(
                db,
                bitpro_strategy_id=sid,
                name=str(row.get("name") or row.get("strategy_name") or ""),
                status=str(row.get("status") or ""),
            )
        )
    projections.sort(key=lambda p: (-p.evidence_record_count, p.name))
    return projections
