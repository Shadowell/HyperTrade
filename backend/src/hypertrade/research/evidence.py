"""Append-only Research Evidence V2 ledger and lifecycle policy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hypertrade.db import (
    Database,
    MemoryItem,
    RagChunk,
    RagDocument,
    ResearchEvidence,
    ResearchEvidenceRelation,
    TraceEvent,
    utc_now,
)
from hypertrade.research.evidence_schemas import (
    CounterEvidenceInput,
    DataGapEvidenceInput,
    EvidenceInputBase,
    FactEvidenceInput,
    ResearchEvidenceInput,
    SourceType,
    canonical_evidence_payload,
    evidence_content_hash,
)


class EvidenceSourceUnavailable(ValueError):
    def __init__(self, sources: list[dict[str, str]]) -> None:
        super().__init__("evidence source is unavailable")
        self.sources = sources


class EvidenceService:
    """Trusted mutation boundary; Agents cannot alter persisted evidence content."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        payload: ResearchEvidenceInput,
        *,
        actor: str = "evidence_service",
    ) -> dict[str, Any]:
        content_hash = evidence_content_hash(payload)
        with self.db.session() as session:
            existing = session.scalar(
                select(ResearchEvidence).where(ResearchEvidence.content_hash == content_hash)
            )
            if existing is not None:
                result = self._to_dict(session, existing)
                result["idempotency_replayed"] = True
                return result

            self._validate_payload(session, payload)
            now = utc_now()
            status = "expired" if payload.valid_until and payload.valid_until <= now else "active"
            lifecycle = [
                _lifecycle_event(
                    status=status,
                    actor=actor,
                    reason="appended" if status == "active" else "appended_after_validity_window",
                    at=now,
                )
            ]
            canonical = canonical_evidence_payload(payload)
            row = ResearchEvidence(
                schema_version=payload.schema_version,
                evidence_type=payload.evidence_type,
                status=status,
                claim=payload.claim,
                task_id=payload.task_id,
                node_run_id=payload.node_run_id,
                role_key=payload.role_key,
                symbols_json=list(payload.scope.symbols),
                timeframes_json=list(payload.scope.timeframes),
                market_type=payload.scope.market_type,
                scope_json=canonical["scope"],
                sources_json=canonical["sources"],
                confidence=payload.confidence,
                as_of=payload.as_of,
                valid_until=payload.valid_until,
                content_hash=content_hash,
                payload_json=canonical,
                lifecycle_json=lifecycle,
                created_by=actor,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                raced = session.scalar(
                    select(ResearchEvidence).where(ResearchEvidence.content_hash == content_hash)
                )
                if raced is None:
                    raise
                result = self._to_dict(session, raced)
                result["idempotency_replayed"] = True
                return result
            self._append_payload_relations(session, row, payload, actor=actor)
            session.flush()
            return self._to_dict(session, row)

    def append_or_gap(
        self,
        payload: FactEvidenceInput,
        *,
        actor: str = "evidence_service",
        remediation: str = "Restore the expected source and rerun this evidence node.",
    ) -> dict[str, Any]:
        """Fail closed to a visible gap instead of fabricating a source-backed fact."""
        try:
            return self.append(payload, actor=actor)
        except EvidenceSourceUnavailable as exc:
            expected = sorted(
                {
                    cast(SourceType, item["source_type"])
                    for item in exc.sources
                    if item.get("source_type")
                }
            )
            if not expected:
                expected = ["tool"]
            gap = DataGapEvidenceInput(
                claim=f"Source unavailable for proposed fact: {payload.claim}",
                scope=payload.scope,
                sources=payload.sources,
                confidence=Decimal("0"),
                as_of=payload.as_of,
                valid_until=payload.valid_until,
                task_id=payload.task_id,
                node_run_id=payload.node_run_id,
                role_key=payload.role_key,
                expected_sources=expected,
                remediation=remediation,
            )
            result = self.append(gap, actor=actor)
            result["fact_rejected"] = True
            result["unavailable_sources"] = exc.sources
            return result

    def get(self, evidence_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ResearchEvidence, evidence_id)
            if row is None:
                raise KeyError(evidence_id)
            return self._to_dict(session, row)

    def query(
        self,
        *,
        task_id: str = "",
        evidence_type: str = "",
        status: str = "",
        symbol: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        statement = select(ResearchEvidence).order_by(desc(ResearchEvidence.created_at)).limit(
            max(1, min(limit * 4 if symbol or status else limit, 500))
        )
        if task_id:
            statement = statement.where(ResearchEvidence.task_id == task_id)
        if evidence_type:
            statement = statement.where(ResearchEvidence.evidence_type == evidence_type)
        with self.db.session() as session:
            rows = session.scalars(statement).all()
            result = [self._to_dict(session, row) for row in rows]
        if symbol:
            normalized_symbol = symbol.strip().upper()
            result = [row for row in result if normalized_symbol in row["scope"]["symbols"]]
        if status:
            result = [row for row in result if row["status"] == status]
        return result[: max(1, min(limit, 200))]

    def expire(
        self,
        evidence_id: str,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        return self._transition_status(
            evidence_id,
            target="expired",
            allowed={"active"},
            reason=reason,
            actor=actor,
        )

    def reject(
        self,
        evidence_id: str,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        return self._transition_status(
            evidence_id,
            target="rejected",
            allowed={"active", "expired"},
            reason=reason,
            actor=actor,
        )

    def expire_due(self, *, now: datetime | None = None) -> list[str]:
        cutoff = _aware_utc(now or utc_now())
        expired: list[str] = []
        with self.db.session() as session:
            rows = session.scalars(
                select(ResearchEvidence).where(
                    ResearchEvidence.status == "active",
                    ResearchEvidence.valid_until.is_not(None),
                    ResearchEvidence.valid_until <= cutoff,
                )
            ).all()
            for row in rows:
                row.status = "expired"
                row.lifecycle_json = [
                    *list(row.lifecycle_json),
                    _lifecycle_event(
                        status="expired",
                        actor="evidence_expiry",
                        reason="valid_until_elapsed",
                        at=cutoff,
                    ),
                ]
                expired.append(row.id)
        return expired

    def supersede(
        self,
        evidence_id: str,
        replacement: ResearchEvidenceInput,
        *,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        previous = self.get(evidence_id)
        if previous["status"] not in {"active", "expired"}:
            raise ValueError(f"cannot supersede evidence in status {previous['status']}")
        replacement_row = self.append(replacement, actor=actor)
        if replacement_row["id"] == evidence_id:
            raise ValueError("replacement evidence must have different canonical content")
        if replacement_row["status"] != "active":
            raise ValueError("replacement evidence must be active")
        with self.db.session() as session:
            old = session.get(ResearchEvidence, evidence_id)
            new = session.get(ResearchEvidence, replacement_row["id"])
            if old is None or new is None:
                raise KeyError(evidence_id)
            if old.status not in {"active", "expired"}:
                raise ValueError(f"cannot supersede evidence in status {old.status}")
            old.status = "superseded"
            old.superseded_by_id = new.id
            old.lifecycle_json = [
                *list(old.lifecycle_json),
                _lifecycle_event(
                    status="superseded",
                    actor=actor,
                    reason=reason,
                    at=utc_now(),
                ),
            ]
            new.supersedes_id = old.id
            self._add_relation(session, new.id, old.id, "supersedes", actor=actor)
            session.flush()
            return self._to_dict(session, new)

    def graph(self, evidence_id: str, *, depth: int = 2) -> dict[str, Any]:
        bounded_depth = max(0, min(depth, 5))
        with self.db.session() as session:
            root = session.get(ResearchEvidence, evidence_id)
            if root is None:
                raise KeyError(evidence_id)
            node_ids = {evidence_id}
            frontier = {evidence_id}
            edges: list[ResearchEvidenceRelation] = []
            for _ in range(bounded_depth):
                if not frontier:
                    break
                level_edges = session.scalars(
                    select(ResearchEvidenceRelation).where(
                        or_(
                            ResearchEvidenceRelation.from_evidence_id.in_(frontier),
                            ResearchEvidenceRelation.to_evidence_id.in_(frontier),
                        )
                    )
                ).all()
                next_frontier: set[str] = set()
                known_edge_ids = {edge.id for edge in edges}
                for edge in level_edges:
                    if edge.id not in known_edge_ids:
                        edges.append(edge)
                    next_frontier.update({edge.from_evidence_id, edge.to_evidence_id})
                next_frontier -= node_ids
                node_ids.update(next_frontier)
                frontier = next_frontier
            nodes = session.scalars(
                select(ResearchEvidence).where(ResearchEvidence.id.in_(node_ids))
            ).all()
            return {
                "root_id": evidence_id,
                "nodes": [self._to_dict(session, node) for node in nodes],
                "edges": [_relation_to_dict(edge) for edge in edges],
            }

    def report_block(self, evidence_id: str) -> dict[str, Any]:
        evidence = self.get(evidence_id)
        return {
            "schema_version": evidence["schema_version"],
            "id": evidence["id"],
            "type": evidence["evidence_type"],
            "status": evidence["status"],
            "claim": evidence["claim"],
            "confidence": evidence["confidence"],
            "as_of": evidence["as_of"],
            "valid_until": evidence["valid_until"],
            "source_refs": [
                {
                    "source_type": source["source_type"],
                    "source_id": source["source_id"],
                    "availability": source["availability"],
                }
                for source in evidence["source_health"]
            ],
            "warning": "Confidence is a declared research attribute, not a probability guarantee.",
        }

    def _transition_status(
        self,
        evidence_id: str,
        *,
        target: str,
        allowed: set[str],
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ResearchEvidence, evidence_id)
            if row is None:
                raise KeyError(evidence_id)
            if row.status == target:
                return self._to_dict(session, row)
            if row.status not in allowed:
                raise ValueError(f"cannot transition evidence from {row.status} to {target}")
            row.status = target
            row.lifecycle_json = [
                *list(row.lifecycle_json),
                _lifecycle_event(status=target, actor=actor, reason=reason, at=utc_now()),
            ]
            session.flush()
            return self._to_dict(session, row)

    def _validate_payload(self, session: Session, payload: EvidenceInputBase) -> None:
        unavailable = self._unavailable_sources(session, payload)
        if unavailable and payload.evidence_type != "data_gap":
            raise EvidenceSourceUnavailable(unavailable)
        if payload.evidence_type == "fact":
            qualifying = [
                source
                for source in payload.sources
                if source.source_type != "memory" and source.availability == "available"
            ]
            if not qualifying:
                raise ValueError("fact requires at least one available non-Memory source")
        related_ids = set(payload.supporting_evidence_ids) | set(payload.opposing_evidence_ids)
        if isinstance(payload, CounterEvidenceInput):
            related_ids.update(payload.challenged_evidence_ids)
        related = self._load_related(session, related_ids)
        if payload.evidence_type == "inference":
            stale = [
                evidence_id
                for evidence_id in payload.supporting_evidence_ids
                if self._effective_status(related[evidence_id]) != "active"
            ]
            if stale:
                raise ValueError(f"inference supporting evidence is not active: {stale}")

    def _load_related(
        self, session: Session, evidence_ids: set[str]
    ) -> dict[str, ResearchEvidence]:
        if not evidence_ids:
            return {}
        rows = session.scalars(
            select(ResearchEvidence).where(ResearchEvidence.id.in_(evidence_ids))
        ).all()
        by_id = {row.id: row for row in rows}
        missing = sorted(evidence_ids - set(by_id))
        if missing:
            raise ValueError(f"referenced evidence does not exist: {missing}")
        return by_id

    def _unavailable_sources(
        self, session: Session, payload: EvidenceInputBase
    ) -> list[dict[str, str]]:
        unavailable: list[dict[str, str]] = []
        for source in payload.sources:
            reason = ""
            if source.availability != "available":
                reason = f"declared_{source.availability}"
            elif source.source_type == "memory":
                memory = session.get(MemoryItem, source.source_id)
                if memory is None or memory.disabled:
                    reason = "memory_missing_or_disabled"
            elif source.source_type == "rag":
                if not self._rag_source_exists(session, source.source_id):
                    reason = "rag_source_missing"
            elif source.source_type == "tool":
                trace = session.get(TraceEvent, source.source_id)
                if trace is None:
                    reason = "tool_trace_missing"
                elif trace.tool_name != source.tool_name:
                    reason = "tool_name_mismatch"
            if reason:
                unavailable.append(
                    {
                        "source_type": source.source_type,
                        "source_id": source.source_id,
                        "reason": reason,
                    }
                )
        return unavailable

    def _append_payload_relations(
        self,
        session: Session,
        row: ResearchEvidence,
        payload: EvidenceInputBase,
        *,
        actor: str,
    ) -> None:
        for evidence_id in payload.supporting_evidence_ids:
            self._add_relation(session, row.id, evidence_id, "supported_by", actor=actor)
        for evidence_id in payload.opposing_evidence_ids:
            self._add_relation(session, row.id, evidence_id, "opposed_by", actor=actor)
        if isinstance(payload, CounterEvidenceInput):
            for evidence_id in payload.challenged_evidence_ids:
                self._add_relation(session, row.id, evidence_id, "challenges", actor=actor)

    @staticmethod
    def _add_relation(
        session: Session,
        from_id: str,
        to_id: str,
        relation_type: str,
        *,
        actor: str,
    ) -> None:
        existing = session.scalar(
            select(ResearchEvidenceRelation).where(
                ResearchEvidenceRelation.from_evidence_id == from_id,
                ResearchEvidenceRelation.to_evidence_id == to_id,
                ResearchEvidenceRelation.relation_type == relation_type,
            )
        )
        if existing is None:
            session.add(
                ResearchEvidenceRelation(
                    from_evidence_id=from_id,
                    to_evidence_id=to_id,
                    relation_type=relation_type,
                    created_by=actor,
                )
            )

    def _to_dict(self, session: Session, row: ResearchEvidence) -> dict[str, Any]:
        source_health = []
        for source in list(row.sources_json):
            source_payload = dict(source)
            source_payload["availability"] = self._current_source_availability(
                session, source_payload
            )
            source_health.append(source_payload)
        data_gaps = [
            {
                "expected_source": source["source_type"],
                "source_id": source["source_id"],
                "reason": "source_unavailable_after_evidence_append",
                "remediation": "Restore or replace the source, then append superseding evidence.",
            }
            for source in source_health
            if source["availability"] != "available"
        ]
        return {
            "id": row.id,
            "schema_version": row.schema_version,
            "evidence_type": row.evidence_type,
            "status": self._effective_status(row),
            "stored_status": row.status,
            "claim": row.claim,
            "scope": dict(row.scope_json),
            "sources": list(row.sources_json),
            "source_health": source_health,
            "data_gaps": data_gaps,
            "confidence": format(row.confidence.normalize(), "f"),
            "as_of": _aware_utc(row.as_of).isoformat(),
            "valid_until": (
                _aware_utc(row.valid_until).isoformat() if row.valid_until is not None else None
            ),
            "task_id": row.task_id,
            "node_run_id": row.node_run_id,
            "role_key": row.role_key,
            "content_hash": row.content_hash,
            "payload": dict(row.payload_json),
            "supersedes_id": row.supersedes_id,
            "superseded_by_id": row.superseded_by_id,
            "lifecycle": list(row.lifecycle_json),
            "created_by": row.created_by,
            "legacy": False,
            "created_at": _aware_utc(row.created_at).isoformat(),
            "updated_at": _aware_utc(row.updated_at).isoformat(),
        }

    @staticmethod
    def _effective_status(row: ResearchEvidence) -> str:
        if (
            row.status == "active"
            and row.valid_until is not None
            and _aware_utc(row.valid_until) <= utc_now()
        ):
            return "expired"
        return row.status

    @staticmethod
    def _current_source_availability(session: Session, source: dict[str, Any]) -> str:
        declared = str(source.get("availability", "unknown"))
        if declared != "available":
            return declared
        source_type = str(source.get("source_type", ""))
        source_id = str(source.get("source_id", ""))
        if source_type == "memory":
            row = session.get(MemoryItem, source_id)
            return "available" if row is not None and not row.disabled else "unavailable"
        if source_type == "rag":
            return (
                "available"
                if EvidenceService._rag_source_exists(session, source_id)
                else "unavailable"
            )
        if source_type == "tool":
            trace_row = session.get(TraceEvent, source_id)
            if trace_row is None or trace_row.tool_name != str(source.get("tool_name", "")):
                return "unavailable"
        return "available"

    @staticmethod
    def _rag_source_exists(session: Session, source_id: str) -> bool:
        if session.get(RagChunk, source_id) is not None:
            return True
        if session.get(RagDocument, source_id) is not None:
            return True
        if "#" not in source_id:
            return False
        source_path, raw_index = source_id.rsplit("#", 1)
        try:
            chunk_index = int(raw_index)
        except ValueError:
            return False
        return (
            session.scalar(
                select(RagChunk).where(
                    RagChunk.source_path == source_path,
                    RagChunk.chunk_index == chunk_index,
                )
            )
            is not None
        )


def _relation_to_dict(row: ResearchEvidenceRelation) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_evidence_id": row.from_evidence_id,
        "to_evidence_id": row.to_evidence_id,
        "relation_type": row.relation_type,
        "created_by": row.created_by,
        "created_at": _aware_utc(row.created_at).isoformat(),
    }


def _lifecycle_event(*, status: str, actor: str, reason: str, at: datetime) -> dict[str, str]:
    return {
        "status": status,
        "actor": actor,
        "reason": reason,
        "at": _aware_utc(at).isoformat(),
    }


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
