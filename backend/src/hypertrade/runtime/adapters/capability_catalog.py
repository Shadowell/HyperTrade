from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hypertrade.db import (
    AgentCapabilityProposal,
    AgentCapabilityReview,
    AgentCapabilitySnapshot,
)
from hypertrade.runtime.adapters.sql_store import async_database_url
from hypertrade.runtime.domain.capabilities import (
    CapabilityDefinitionV1,
    CapabilityProposalV1,
    CapabilityReviewV1,
    CapabilitySnapshotV1,
    reviewed_snapshot,
)
from hypertrade.runtime.domain.models import PlanStepV2, utc_now


class CapabilityUnavailable(ValueError):
    pass


class InMemoryCapabilityCatalog:
    """Reviewed catalog projection; discovery proposals never enter the active map."""

    def __init__(self) -> None:
        self._active: dict[tuple[str, str], CapabilitySnapshotV1] = {}
        self._proposals: dict[str, CapabilityProposalV1] = {}
        self._review_keys: dict[str, CapabilityProposalV1] = {}

    async def bootstrap(self, definitions: Sequence[CapabilityDefinitionV1]) -> None:
        for definition in definitions:
            key = (definition.capability_id, definition.version)
            self._active[key] = reviewed_snapshot(
                definition,
                snapshot_id=f"caps_{sha256(':'.join(key).encode()).hexdigest()[:20]}",
            )

    def resolve_sync(self, capability_id: str, version: str) -> CapabilitySnapshotV1:
        try:
            snapshot = self._active[(capability_id, version)]
        except KeyError as exc:
            raise CapabilityUnavailable(
                f"capability not reviewed: {capability_id}@{version}"
            ) from exc
        if not snapshot.executable():
            raise CapabilityUnavailable(f"capability unavailable: {capability_id}@{version}")
        return snapshot

    async def list_active(self) -> Sequence[CapabilitySnapshotV1]:
        return sorted(
            self._active.values(),
            key=lambda item: (item.definition.capability_id, item.definition.version),
        )

    async def propose(self, proposal: CapabilityProposalV1) -> CapabilityProposalV1:
        canonical = proposal.definition.model_dump_json()
        discovery_hash = sha256(f"{proposal.discovered_from}:{canonical}".encode()).hexdigest()
        existing = next(
            (item for item in self._proposals.values() if item.discovery_hash == discovery_hash),
            None,
        )
        if existing is not None:
            return existing
        proposal_id = f"capp_{uuid4().hex[:20]}"
        row = proposal.model_copy(
            update={"proposal_id": proposal_id, "discovery_hash": discovery_hash}
        )
        self._proposals[proposal_id] = row
        return row

    async def list_proposals(self) -> Sequence[CapabilityProposalV1]:
        return sorted(self._proposals.values(), key=lambda item: item.created_at, reverse=True)

    async def review(self, proposal_id: str, review: CapabilityReviewV1) -> CapabilityProposalV1:
        if review.idempotency_key in self._review_keys:
            return self._review_keys[review.idempotency_key]
        try:
            proposal = self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(proposal_id) from exc
        if proposal.status != "pending_review":
            raise ValueError("capability proposal already reviewed")
        status = "approved" if review.decision == "approve" else "rejected"
        updated = proposal.model_copy(update={"status": status, "reason": review.reason})
        self._proposals[proposal_id] = updated
        self._review_keys[review.idempotency_key] = updated
        if review.decision == "approve":
            now = utc_now()
            definition = proposal.definition
            self._active[(definition.capability_id, definition.version)] = CapabilitySnapshotV1(
                snapshot_id=f"caps_{uuid4().hex[:20]}",
                definition=definition,
                review_status="reviewed",
                health="healthy",
                contract_hash=definition.contract_hash(),
                policy_hash=definition.policy_hash(),
                reviewed_by=review.actor,
                review_reason=review.reason,
                verified_at=now,
                fresh_until=now + timedelta(seconds=review.freshness_seconds),
            )
        return updated

    def set_health(
        self,
        capability_id: str,
        version: str,
        health: str,
        *,
        fresh_until: object | None = None,
    ) -> None:
        key = (capability_id, version)
        snapshot = self._active[key]
        updates: dict[str, object] = {"health": health}
        if fresh_until is not None:
            updates["fresh_until"] = fresh_until
        self._active[key] = snapshot.model_copy(update=updates)


class SqlCapabilityCatalog(InMemoryCapabilityCatalog):
    """Async SQL catalog with a reviewed in-process pre-dispatch projection."""

    def __init__(self, database_url: str) -> None:
        super().__init__()
        self.engine = create_async_engine(async_database_url(database_url), pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def bootstrap(self, definitions: Sequence[CapabilityDefinitionV1]) -> None:
        now = utc_now()
        async with self.sessions.begin() as session:
            for definition in definitions:
                row = await session.scalar(
                    select(AgentCapabilitySnapshot)
                    .where(AgentCapabilitySnapshot.capability_id == definition.capability_id)
                    .where(AgentCapabilitySnapshot.version == definition.version)
                    .with_for_update()
                )
                snapshot = reviewed_snapshot(
                    definition,
                    snapshot_id=(row.id if row is not None else f"caps_{uuid4().hex[:20]}"),
                )
                if row is None:
                    row = AgentCapabilitySnapshot(
                        id=snapshot.snapshot_id,
                        capability_id=definition.capability_id,
                        version=definition.version,
                    )
                    session.add(row)
                row.review_status = snapshot.review_status
                row.health = snapshot.health
                row.contract_hash = snapshot.contract_hash
                row.policy_hash = snapshot.policy_hash
                row.definition_json = definition.model_dump(mode="json")
                row.reviewed_by = snapshot.reviewed_by
                row.review_reason = snapshot.review_reason
                row.verified_at = now
                row.fresh_until = snapshot.fresh_until
                self._active[(definition.capability_id, definition.version)] = snapshot

    async def load(self) -> None:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentCapabilitySnapshot).where(
                        AgentCapabilitySnapshot.review_status == "reviewed"
                    )
                )
            ).all()
            self._active = {
                (row.capability_id, row.version): _snapshot_from_row(row) for row in rows
            }

    async def list_active(self) -> Sequence[CapabilitySnapshotV1]:
        await self.load()
        return await super().list_active()

    async def propose(self, proposal: CapabilityProposalV1) -> CapabilityProposalV1:
        canonical = proposal.definition.model_dump_json()
        discovery_hash = sha256(f"{proposal.discovered_from}:{canonical}".encode()).hexdigest()
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(AgentCapabilityProposal).where(
                    AgentCapabilityProposal.discovery_hash == discovery_hash
                )
            )
            if existing is not None:
                return _proposal_from_row(existing)
            row = AgentCapabilityProposal(
                capability_id=proposal.definition.capability_id,
                version=proposal.definition.version,
                discovered_from=proposal.discovered_from,
                discovery_hash=discovery_hash,
                definition_json=proposal.definition.model_dump(mode="json"),
                status="pending_review",
                reason="",
                created_by=proposal.created_by,
            )
            session.add(row)
            await session.flush()
            return _proposal_from_row(row)

    async def list_proposals(self) -> Sequence[CapabilityProposalV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentCapabilityProposal).order_by(
                        desc(AgentCapabilityProposal.created_at)
                    )
                )
            ).all()
            return [_proposal_from_row(row) for row in rows]

    async def review(self, proposal_id: str, review: CapabilityReviewV1) -> CapabilityProposalV1:
        async with self.sessions.begin() as session:
            replay = await session.scalar(
                select(AgentCapabilityReview).where(
                    AgentCapabilityReview.idempotency_key == review.idempotency_key
                )
            )
            if replay is not None:
                proposal = await session.get(AgentCapabilityProposal, replay.proposal_id)
                if proposal is None:
                    raise KeyError(replay.proposal_id)
                return _proposal_from_row(proposal)
            proposal = await session.get(
                AgentCapabilityProposal,
                proposal_id,
                with_for_update=True,
            )
            if proposal is None:
                raise KeyError(proposal_id)
            if proposal.status != "pending_review":
                raise ValueError("capability proposal already reviewed")
            proposal.status = "approved" if review.decision == "approve" else "rejected"
            proposal.reason = review.reason
            session.add(
                AgentCapabilityReview(
                    proposal_id=proposal_id,
                    decision=review.decision,
                    reason=review.reason,
                    actor=review.actor,
                    idempotency_key=review.idempotency_key,
                )
            )
            if review.decision == "approve":
                definition = CapabilityDefinitionV1.model_validate(proposal.definition_json)
                existing = await session.scalar(
                    select(AgentCapabilitySnapshot)
                    .where(AgentCapabilitySnapshot.capability_id == definition.capability_id)
                    .where(AgentCapabilitySnapshot.version == definition.version)
                    .with_for_update()
                )
                now = utc_now()
                snapshot = CapabilitySnapshotV1(
                    snapshot_id=(
                        existing.id if existing is not None else f"caps_{uuid4().hex[:20]}"
                    ),
                    definition=definition,
                    review_status="reviewed",
                    health="healthy",
                    contract_hash=definition.contract_hash(),
                    policy_hash=definition.policy_hash(),
                    reviewed_by=review.actor,
                    review_reason=review.reason,
                    verified_at=now,
                    fresh_until=now + timedelta(seconds=review.freshness_seconds),
                )
                if existing is None:
                    existing = AgentCapabilitySnapshot(
                        id=snapshot.snapshot_id,
                        capability_id=definition.capability_id,
                        version=definition.version,
                    )
                    session.add(existing)
                existing.review_status = "reviewed"
                existing.health = "healthy"
                existing.contract_hash = snapshot.contract_hash
                existing.policy_hash = snapshot.policy_hash
                existing.definition_json = definition.model_dump(mode="json")
                existing.reviewed_by = review.actor
                existing.review_reason = review.reason
                existing.verified_at = now
                existing.fresh_until = snapshot.fresh_until
                self._active[(definition.capability_id, definition.version)] = snapshot
            await session.flush()
            return _proposal_from_row(proposal)


class CatalogCapabilityPolicy:
    def __init__(self, catalog: InMemoryCapabilityCatalog) -> None:
        self.catalog = catalog

    def validate_step(self, step: PlanStepV2, permission_profile_ref: str) -> None:
        snapshot = self.catalog.resolve_sync(step.capability_id, step.capability_version)
        definition = snapshot.definition
        if permission_profile_ref == "read_only.v1" and definition.scope != "read":
            raise CapabilityUnavailable("read-only Mission cannot use write capability")
        if definition.approval != "none" and not step.requires_approval:
            raise CapabilityUnavailable("capability approval requirement missing from plan")
        if definition.side_effect != "none" and step.read_only:
            raise CapabilityUnavailable("plan side-effect classification mismatches capability")


def builtin_capabilities() -> tuple[CapabilityDefinitionV1, ...]:
    return (
        CapabilityDefinitionV1(
            capability_id="runtime.objective_inspection",
            title="Objective inspection",
            description=(
                "Validate and fingerprint a Mission objective without external side effects."
            ),
            source_owner="hypertrade.runtime",
            handler_key="runtime.objective_inspection",
            input_schema={
                "type": "object",
                "properties": {"objective": {"type": "string", "minLength": 3}},
                "required": ["objective"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "objective_hash": {"type": "string"},
                    "constraint_count": {"type": "integer"},
                    "plan_version": {"type": "integer"},
                    "attempt": {"type": "integer"},
                },
                "required": ["objective_hash", "constraint_count", "plan_version", "attempt"],
                "additionalProperties": False,
            },
        ),
        CapabilityDefinitionV1(
            capability_id="market.summary",
            title="Market summary",
            description="Read a bounded latest OKX SWAP market summary from HyperTrade storage.",
            source_owner="hypertrade.market",
            handler_key="market.summary",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "inst_id": {"type": "string", "minLength": 5, "maxLength": 64},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                    "count": {"type": "integer"},
                    "requested_inst_id": {"type": "string"},
                    "found": {"type": "boolean"},
                },
                "required": ["items", "count"],
            },
        ),
        CapabilityDefinitionV1(
            capability_id="rag.search",
            title="RAG search",
            description="Search curated knowledge and return source-bound bounded hits.",
            source_owner="hypertrade.rag",
            handler_key="rag.search",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"hits": {"type": "array"}, "count": {"type": "integer"}},
                "required": ["hits", "count"],
            },
        ),
        CapabilityDefinitionV1(
            capability_id="memory.search",
            title="Memory search",
            description="Search governed active Memory with bounded previews.",
            source_owner="hypertrade.memory",
            handler_key="memory.search",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"items": {"type": "array"}, "count": {"type": "integer"}},
                "required": ["items", "count"],
            },
        ),
    )


def _snapshot_from_row(row: AgentCapabilitySnapshot) -> CapabilitySnapshotV1:
    return CapabilitySnapshotV1(
        snapshot_id=row.id,
        definition=CapabilityDefinitionV1.model_validate(row.definition_json),
        review_status=row.review_status,
        health=row.health,
        contract_hash=row.contract_hash,
        policy_hash=row.policy_hash,
        reviewed_by=row.reviewed_by,
        review_reason=row.review_reason,
        verified_at=row.verified_at,
        fresh_until=row.fresh_until,
        created_at=row.created_at,
    )


def _proposal_from_row(row: AgentCapabilityProposal) -> CapabilityProposalV1:
    return CapabilityProposalV1(
        proposal_id=row.id,
        definition=CapabilityDefinitionV1.model_validate(row.definition_json),
        discovered_from=row.discovered_from,
        discovery_hash=row.discovery_hash,
        status=row.status,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
    )
