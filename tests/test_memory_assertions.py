from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database, MemoryItem, ResearchEvidence, TraceEvent, utc_now
from hypertrade.main import create_app
from hypertrade.memory.governance import (
    AssertionScope,
    MemoryAssertionRelationV1,
    MemoryAssertionReviewV1,
    MemoryAssertionService,
    MemoryAssertionV1,
)
from hypertrade.memory.service import MemoryService
from hypertrade.research.evidence import EvidenceService
from hypertrade.research.evidence_schemas import (
    EvidenceScope,
    EvidenceSourceRef,
    FactEvidenceInput,
)
from sqlalchemy import select


def _db_and_evidence(*, claim: str = "BTC volatility regime is elevated") -> tuple[Database, str]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    now = datetime.now(UTC)
    with db.session() as session:
        trace = TraceEvent(
            run_id="run_memory_governance",
            tool_name="world_model_snapshot",
            status="completed",
            input_json={},
            output_json={"volatility_regime": "high"},
        )
        session.add(trace)
        session.flush()
        trace_id = trace.id
    evidence = EvidenceService(db).append(
        FactEvidenceInput(
            claim=claim,
            scope=EvidenceScope(symbols=["BTC"], timeframes=["1H"], market_type="SWAP"),
            sources=[
                EvidenceSourceRef(
                    source_type="tool",
                    source_id=trace_id,
                    tool_name="world_model_snapshot",
                    observed_at=now,
                )
            ],
            confidence=Decimal("0.8"),
            as_of=now,
            valid_until=now + timedelta(days=2),
            role_key="market_regime",
        )
    )
    return db, str(evidence["id"])


def _proposal(evidence_id: str, *, key: str, claim: str) -> MemoryAssertionV1:
    return MemoryAssertionV1(
        claim=claim,
        scope=AssertionScope(symbols=["BTC"], timeframes=["1H"], tags=["regime"]),
        source_evidence_ids=[evidence_id],
        confidence=Decimal("0.75"),
        valid_until=utc_now() + timedelta(days=1),
        idempotency_key=key,
    )


def _approve(service: MemoryAssertionService, assertion_id: str, *, key: str) -> dict:
    return service.review(
        assertion_id,
        MemoryAssertionReviewV1(
            decision="approve",
            reason="source and scope reviewed",
            idempotency_key=key,
        ),
        actor="admin",
    )


def test_assertion_requires_evidence_and_review_before_legacy_memory_use() -> None:
    db, evidence_id = _db_and_evidence()
    service = MemoryAssertionService(db)
    payload = _proposal(
        evidence_id,
        key="memory-proposal-001",
        claim="Elevated volatility invalidates narrow stop assumptions.",
    )

    proposed = service.propose(payload, actor="agent")
    replay = service.propose(payload, actor="agent")

    assert proposed["status"] == "proposed"
    assert proposed["usable"] is False
    assert replay["id"] == proposed["id"]
    assert replay["idempotent"] is True
    with db.session() as session:
        assert session.scalars(select(MemoryItem)).all() == []

    active = _approve(service, str(proposed["id"]), key="memory-review-001")
    assert active["status"] == "active"
    assert active["usable"] is True
    assert active["linked_memory_id"]
    assert service.active_for_prompt()[0]["id"] == proposed["id"]
    with db.session() as session:
        memory = session.get(MemoryItem, str(active["linked_memory_id"]))
        assert memory is not None and memory.disabled is False
        assert memory.source_tool == "memory_assertion_review"


def test_conflicts_are_visible_and_neither_assertion_silently_wins() -> None:
    db, evidence_id = _db_and_evidence()
    service = MemoryAssertionService(db)
    left = service.propose(
        _proposal(
            evidence_id,
            key="memory-conflict-left",
            claim="High volatility favors wider invalidation bands.",
        ),
        actor="agent",
    )
    right = service.propose(
        _proposal(
            evidence_id,
            key="memory-conflict-right",
            claim="High volatility favors narrower invalidation bands.",
        ),
        actor="agent",
    )
    _approve(service, str(left["id"]), key="memory-conflict-review-left")
    _approve(service, str(right["id"]), key="memory-conflict-review-right")

    relation = service.add_relation(
        MemoryAssertionRelationV1(
            from_assertion_id=str(left["id"]),
            to_assertion_id=str(right["id"]),
            relation_type="conflicts",
            reason="opposing operational conclusions from the same regime fact",
            idempotency_key="memory-conflict-edge-001",
        ),
        actor="admin",
    )

    assert relation["relation_type"] == "conflicts"
    rows = service.list_assertions()
    assert {row["status"] for row in rows} == {"disputed"}
    assert all(row["usable"] is False for row in rows)
    assert service.active_for_prompt() == []
    assert all(row["relations"] for row in rows)


def test_expiry_and_source_lifecycle_fail_closed_and_disable_legacy_item() -> None:
    db, evidence_id = _db_and_evidence()
    service = MemoryAssertionService(db)
    proposed = service.propose(
        _proposal(
            evidence_id,
            key="memory-expiry-proposal",
            claim="This assertion must stop loading after its evidence expires.",
        ),
        actor="agent",
    )
    active = _approve(service, str(proposed["id"]), key="memory-expiry-review")
    with db.session() as session:
        evidence = session.get(ResearchEvidence, evidence_id)
        assert evidence is not None
        evidence.status = "expired"

    refreshed = service.get(str(proposed["id"]))

    assert refreshed["status"] == "expired"
    assert refreshed["source_valid"] is False
    assert refreshed["usable"] is False
    assert service.active_for_prompt() == []
    # A source lifecycle change does not rewrite assertion history, but prompt use fails closed.
    with db.session() as session:
        memory = session.get(MemoryItem, str(active["linked_memory_id"]))
        assert memory is not None and memory.disabled is True


def test_memory_search_refreshes_governed_source_lifecycle() -> None:
    db, evidence_id = _db_and_evidence()
    service = MemoryAssertionService(db)
    proposed = service.propose(
        _proposal(
            evidence_id,
            key="memory-search-expiry",
            claim="Governed memory must fail closed during normal search.",
        ),
        actor="agent",
    )
    _approve(service, str(proposed["id"]), key="memory-search-review")
    assert MemoryService(db).search(query="fail closed")

    with db.session() as session:
        evidence = session.get(ResearchEvidence, evidence_id)
        assert evidence is not None
        evidence.status = "expired"

    assert MemoryService(db).search(query="fail closed") == []
    assert service.get(str(proposed["id"]))["status"] == "expired"


def test_invalid_or_expired_sources_cannot_be_proposed_or_approved() -> None:
    db, evidence_id = _db_and_evidence()
    service = MemoryAssertionService(db)
    with pytest.raises(ValueError, match="Evidence V2"):
        service.propose(
            _proposal(
                "evi_missing",
                key="memory-missing-source",
                claim="Missing source must fail closed.",
            ),
            actor="agent",
        )
    proposed = service.propose(
        _proposal(
            evidence_id,
            key="memory-source-expires",
            claim="Approval must revalidate source lifecycle.",
        ),
        actor="agent",
    )
    with db.session() as session:
        evidence = session.get(ResearchEvidence, evidence_id)
        assert evidence is not None
        evidence.status = "expired"
    with pytest.raises(ValueError, match="Evidence V2"):
        _approve(service, str(proposed["id"]), key="memory-expired-review")


def test_memory_assertion_api_is_admin_governed() -> None:
    db, evidence_id = _db_and_evidence()
    app = create_app(
        settings=Settings(ADMIN_USERNAME="admin", ADMIN_PASSWORD="secret"),
        db=db,
    )
    client = TestClient(app)
    payload = _proposal(
        evidence_id,
        key="memory-api-proposal",
        claim="API assertion remains proposed until an administrator reviews it.",
    ).model_dump(mode="json")

    assert client.post("/api/memory/assertions", json=payload).status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    proposed = client.post("/api/memory/assertions", json=payload)
    assert proposed.status_code == 200
    assertion_id = proposed.json()["id"]
    reviewed = client.post(
        f"/api/memory/assertions/{assertion_id}/review",
        json={
            "decision": "approve",
            "reason": "reviewed through API",
            "idempotency_key": "memory-api-review-001",
        },
    )
    assert reviewed.json()["status"] == "active"
    assert client.get("/api/memory/assertions").json()["items"][0]["usable"] is True
