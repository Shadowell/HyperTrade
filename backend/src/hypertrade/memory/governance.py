"""Source-bound Memory Assertion lifecycle layered over legacy MemoryItem."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    Database,
    MemoryAssertion,
    MemoryAssertionRelation,
    MemoryAssertionReview,
    MemoryItem,
    ResearchEvidence,
    utc_now,
)


class AssertionScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(default_factory=list, max_length=20)
    timeframes: list[str] = Field(default_factory=list, max_length=20)
    market_type: str = Field(default="", max_length=32)
    tags: list[str] = Field(default_factory=list, max_length=20)


class MemoryAssertionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=3, max_length=4_000)
    scope: AssertionScope = Field(default_factory=AssertionScope)
    source_evidence_ids: list[str] = Field(min_length=1, max_length=32)
    confidence: Decimal = Field(ge=0, le=1)
    valid_until: datetime | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def normalized_and_future_bound(self) -> MemoryAssertionV1:
        if not self.claim.strip():
            raise ValueError("claim must contain text")
        if len(set(self.source_evidence_ids)) != len(self.source_evidence_ids):
            raise ValueError("source evidence ids must be unique")
        if self.valid_until is not None and _as_utc(self.valid_until) <= utc_now():
            raise ValueError("valid_until must be in the future")
        return self


class MemoryAssertionReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "dispute"]
    reason: str = Field(min_length=1, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class MemoryAssertionRelationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_assertion_id: str = Field(min_length=1, max_length=32)
    to_assertion_id: str = Field(min_length=1, max_length=32)
    relation_type: Literal["supports", "conflicts", "supersedes"]
    reason: str = Field(min_length=1, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def distinct_nodes(self) -> MemoryAssertionRelationV1:
        if self.from_assertion_id == self.to_assertion_id:
            raise ValueError("assertion relation cannot be self-referential")
        if not self.reason.strip():
            raise ValueError("relation reason must contain text")
        return self


class MemoryAssertionService:
    """Govern claim usability without replacing or silently trusting MemoryItem."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def propose(self, payload: MemoryAssertionV1, *, actor: str) -> dict[str, Any]:
        canonical = _assertion_canonical(payload)
        content_hash = _hash(canonical)
        with self.db.session() as session:
            replay = session.scalar(
                select(MemoryAssertion).where(
                    MemoryAssertion.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.content_hash != content_hash:
                    raise ValueError("idempotency key is bound to another assertion")
                return {**self._projection_in_session(session, replay), "idempotent": True}
            duplicate = session.scalar(
                select(MemoryAssertion).where(MemoryAssertion.content_hash == content_hash)
            )
            if duplicate is not None:
                return {**self._projection_in_session(session, duplicate), "deduplicated": True}
            self._require_valid_evidence(session, payload.source_evidence_ids)
            row = MemoryAssertion(
                claim=payload.claim.strip(),
                scope_json=payload.scope.model_dump(mode="json"),
                source_evidence_ids_json=list(payload.source_evidence_ids),
                confidence=payload.confidence.quantize(Decimal("0.00000001")),
                valid_until=_as_utc(payload.valid_until) if payload.valid_until else None,
                status="proposed",
                content_hash=content_hash,
                idempotency_key=payload.idempotency_key,
                created_by=actor,
                audit_json=[
                    {"event": "proposed", "actor": actor, "at": utc_now().isoformat()}
                ],
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                raced = session.scalar(
                    select(MemoryAssertion).where(
                        MemoryAssertion.content_hash == content_hash
                    )
                )
                if raced is None:
                    raise
                return {**self._projection_in_session(session, raced), "deduplicated": True}
            return self._projection_in_session(session, row)

    def review(
        self,
        assertion_id: str,
        payload: MemoryAssertionReviewV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            replay = session.scalar(
                select(MemoryAssertionReview).where(
                    MemoryAssertionReview.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.assertion_id != assertion_id or replay.decision != payload.decision:
                    raise ValueError("review idempotency key is bound to another decision")
                row = session.get(MemoryAssertion, assertion_id)
                if row is None:
                    raise KeyError(assertion_id)
                return {**self._projection_in_session(session, row), "idempotent": True}
            assertion_query = select(MemoryAssertion).where(
                MemoryAssertion.id == assertion_id
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                assertion_query = assertion_query.with_for_update()
            row = session.scalar(assertion_query)
            if row is None:
                raise KeyError(assertion_id)
            if row.status not in {"proposed", "disputed"}:
                raise ValueError(f"assertion cannot be reviewed from {row.status}")
            reason = payload.reason.strip()
            if not reason:
                raise ValueError("review reason must contain text")
            if payload.decision == "approve":
                self._require_valid_evidence(session, row.source_evidence_ids_json)
                if row.valid_until is not None and _as_utc(row.valid_until) <= utc_now():
                    raise ValueError("expired assertion cannot be approved")
                row.status = "active"
                self._sync_legacy_memory(session, row)
                self._apply_outgoing_relations(session, row)
            elif payload.decision == "reject":
                row.status = "rejected"
                self._disable_linked_memory(session, row)
            else:
                row.status = "disputed"
                self._disable_linked_memory(session, row)
            row.reviewed_by = actor
            row.review_reason = reason
            audit = list(row.audit_json or [])
            audit.append(
                {
                    "event": payload.decision,
                    "actor": actor,
                    "reason": reason,
                    "at": utc_now().isoformat(),
                }
            )
            row.audit_json = audit[-200:]
            session.add(
                MemoryAssertionReview(
                    assertion_id=row.id,
                    decision=payload.decision,
                    reason=reason,
                    idempotency_key=payload.idempotency_key,
                    decided_by=actor,
                )
            )
            session.flush()
            return self._projection_in_session(session, row)

    def add_relation(
        self,
        payload: MemoryAssertionRelationV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            replay = session.scalar(
                select(MemoryAssertionRelation).where(
                    MemoryAssertionRelation.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if (
                    replay.from_assertion_id != payload.from_assertion_id
                    or replay.to_assertion_id != payload.to_assertion_id
                    or replay.relation_type != payload.relation_type
                ):
                    raise ValueError("relation idempotency key is bound to another edge")
                return {**relation_to_dict(replay), "idempotent": True}
            source = session.get(MemoryAssertion, payload.from_assertion_id)
            target = session.get(MemoryAssertion, payload.to_assertion_id)
            if source is None:
                raise KeyError(payload.from_assertion_id)
            if target is None:
                raise KeyError(payload.to_assertion_id)
            existing = session.scalar(
                select(MemoryAssertionRelation).where(
                    MemoryAssertionRelation.from_assertion_id == source.id,
                    MemoryAssertionRelation.to_assertion_id == target.id,
                    MemoryAssertionRelation.relation_type == payload.relation_type,
                )
            )
            if existing is None:
                existing = MemoryAssertionRelation(
                    from_assertion_id=source.id,
                    to_assertion_id=target.id,
                    relation_type=payload.relation_type,
                    reason=payload.reason.strip(),
                    idempotency_key=payload.idempotency_key,
                    created_by=actor,
                )
                session.add(existing)
                session.flush()
            if payload.relation_type == "conflicts" and (
                source.status == "active" or target.status == "active"
            ):
                source.status = "disputed"
                target.status = "disputed"
                self._disable_linked_memory(session, source)
                self._disable_linked_memory(session, target)
            if payload.relation_type == "supersedes" and source.status == "active":
                target.status = "superseded"
                self._disable_linked_memory(session, target)
            return relation_to_dict(existing)

    def list_assertions(
        self,
        *,
        query: str = "",
        status: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.refresh_lifecycle()
        normalized_query = query.strip().casefold()
        with self.db.session() as session:
            statement = select(MemoryAssertion).order_by(MemoryAssertion.created_at.desc())
            if status:
                statement = statement.where(MemoryAssertion.status == status)
            if normalized_query:
                statement = statement.where(
                    or_(
                        MemoryAssertion.claim.ilike(f"%{normalized_query}%"),
                        MemoryAssertion.content_hash == normalized_query,
                    )
                )
            rows = session.scalars(statement.limit(max(1, min(limit, 500)))).all()
            return [self._projection_in_session(session, row) for row in rows]

    def get(self, assertion_id: str) -> dict[str, Any]:
        self.refresh_lifecycle()
        with self.db.session() as session:
            row = session.get(MemoryAssertion, assertion_id)
            if row is None:
                raise KeyError(assertion_id)
            return self._projection_in_session(session, row)

    def active_for_prompt(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            item
            for item in self.list_assertions(status="active", limit=limit)
            if item["usable"]
        ]

    def refresh_lifecycle(self) -> list[str]:
        now = utc_now()
        expired: list[str] = []
        with self.db.session() as session:
            rows = session.scalars(
                select(MemoryAssertion).where(
                    MemoryAssertion.status.in_(["proposed", "active", "disputed"]),
                )
            ).all()
            for row in rows:
                past_validity = (
                    row.valid_until is not None and _as_utc(row.valid_until) <= now
                )
                source_invalid = not self._evidence_is_valid(
                    session, row.source_evidence_ids_json
                )
                if not past_validity and not source_invalid:
                    continue
                row.status = "expired"
                self._disable_linked_memory(session, row)
                expired.append(row.id)
        return expired

    def _projection_in_session(
        self,
        session: Any,
        row: MemoryAssertion,
    ) -> dict[str, Any]:
        relations = session.scalars(
            select(MemoryAssertionRelation).where(
                or_(
                    MemoryAssertionRelation.from_assertion_id == row.id,
                    MemoryAssertionRelation.to_assertion_id == row.id,
                )
            )
        ).all()
        source_valid = self._evidence_is_valid(session, row.source_evidence_ids_json)
        return {
            "id": row.id,
            "schema_version": row.schema_version,
            "claim": row.claim,
            "scope": dict(row.scope_json or {}),
            "source_evidence_ids": list(row.source_evidence_ids_json or []),
            "confidence": str(row.confidence),
            "valid_until": row.valid_until.isoformat() if row.valid_until else None,
            "status": row.status,
            "content_hash": row.content_hash,
            "linked_memory_id": row.linked_memory_id,
            "source_valid": source_valid,
            "usable": row.status == "active" and source_valid,
            "relations": [relation_to_dict(item) for item in relations],
            "created_by": row.created_by,
            "reviewed_by": row.reviewed_by,
            "review_reason": row.review_reason,
            "audit": list(row.audit_json or []),
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        }

    @staticmethod
    def _require_valid_evidence(session: Any, evidence_ids: list[str]) -> None:
        if not MemoryAssertionService._evidence_is_valid(session, evidence_ids):
            raise ValueError("assertion requires active, unexpired Evidence V2 sources")

    @staticmethod
    def _evidence_is_valid(session: Any, evidence_ids: list[str]) -> bool:
        if not evidence_ids:
            return False
        rows = session.scalars(
            select(ResearchEvidence).where(ResearchEvidence.id.in_(evidence_ids))
        ).all()
        if len(rows) != len(set(evidence_ids)):
            return False
        now = utc_now()
        return all(
            row.status == "active"
            and (row.valid_until is None or _as_utc(row.valid_until) > now)
            for row in rows
        )

    @staticmethod
    def _sync_legacy_memory(session: Any, row: MemoryAssertion) -> None:
        item = session.scalar(
            select(MemoryItem).where(
                MemoryItem.kind == "governed_assertion",
                MemoryItem.content == row.claim,
            )
        )
        if item is None:
            scope = dict(row.scope_json or {})
            tags = sorted(
                {
                    "governed_assertion",
                    *[str(value).casefold() for value in scope.get("tags", [])],
                    *[str(value).casefold() for value in scope.get("symbols", [])],
                }
            )
            item = MemoryItem(
                kind="governed_assertion",
                content=row.claim,
                source_run_id="",
                source_tool="memory_assertion_review",
                disabled=False,
                importance=Decimal("0.5000"),
                confidence=Decimal(row.confidence).quantize(Decimal("0.0001")),
                tags=tags,
                usage_count=0,
            )
            session.add(item)
            session.flush()
        else:
            item.disabled = False
        row.linked_memory_id = item.id

    @staticmethod
    def _disable_linked_memory(session: Any, row: MemoryAssertion) -> None:
        if not row.linked_memory_id:
            return
        item = session.get(MemoryItem, row.linked_memory_id)
        if item is not None:
            item.disabled = True

    def _apply_outgoing_relations(self, session: Any, row: MemoryAssertion) -> None:
        relations = session.scalars(
            select(MemoryAssertionRelation).where(
                MemoryAssertionRelation.from_assertion_id == row.id
            )
        ).all()
        for relation in relations:
            target = session.get(MemoryAssertion, relation.to_assertion_id)
            if target is None:
                continue
            if relation.relation_type == "conflicts":
                row.status = "disputed"
                target.status = "disputed"
                self._disable_linked_memory(session, row)
                self._disable_linked_memory(session, target)
            elif relation.relation_type == "supersedes":
                target.status = "superseded"
                self._disable_linked_memory(session, target)


def relation_to_dict(row: MemoryAssertionRelation) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_assertion_id": row.from_assertion_id,
        "to_assertion_id": row.to_assertion_id,
        "relation_type": row.relation_type,
        "reason": row.reason,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


def _assertion_canonical(payload: MemoryAssertionV1) -> str:
    return json.dumps(
        {
            "schema_version": "memory_assertion.v1",
            "claim": payload.claim.strip(),
            "scope": payload.scope.model_dump(mode="json"),
            "source_evidence_ids": sorted(payload.source_evidence_ids),
            "confidence": str(payload.confidence.normalize()),
            "valid_until": (
                _as_utc(payload.valid_until).isoformat() if payload.valid_until else None
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
