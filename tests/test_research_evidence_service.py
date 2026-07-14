from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database, MemoryItem, ResearchExperimentEvidence, TraceEvent
from hypertrade.main import create_app
from hypertrade.rag.service import RagHit
from hypertrade.research.evidence import EvidenceService, EvidenceSourceUnavailable
from hypertrade.research.evidence_schemas import (
    CounterEvidenceInput,
    EvidenceScope,
    EvidenceSourceRef,
    FactEvidenceInput,
    InferenceEvidenceInput,
)
from hypertrade.research.legacy_evidence import LegacyEvidenceAdapter
from hypertrade.research.source_refs import (
    source_ref_from_bitpro_result,
    source_ref_from_paper_snapshot,
    source_ref_from_rag_hit,
    source_refs_from_experiment,
)
from hypertrade.strategy.evidence import StrategyEvidence


def _db_with_trace() -> tuple[Database, str]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        trace = TraceEvent(
            run_id="run_evidence",
            tool_name="market_ticker",
            status="completed",
            input_json={"symbol": "BTC"},
            output_json={"last": "70000"},
        )
        session.add(trace)
        session.flush()
        trace_id = trace.id
    return db, trace_id


def _fact(trace_id: str, *, claim: str = "BTC last price is 70000") -> FactEvidenceInput:
    return FactEvidenceInput(
        claim=claim,
        scope=EvidenceScope(symbols=["BTC"], timeframes=["1H"], market_type="SWAP"),
        sources=[
            EvidenceSourceRef(
                source_type="tool",
                source_id=trace_id,
                tool_name="market_ticker",
                observed_at=datetime(2026, 7, 14, 8, tzinfo=UTC),
            )
        ],
        confidence=Decimal("0.8"),
        as_of=datetime(2026, 7, 14, 8, tzinfo=UTC),
        valid_until=datetime(2026, 7, 15, 8, tzinfo=UTC),
        task_id="task_evidence",
        node_run_id="tnode_data",
        role_key="data_quality",
    )


def test_append_is_deduplicated_and_fact_requires_non_memory_source() -> None:
    db, trace_id = _db_with_trace()
    service = EvidenceService(db)
    first = service.append(_fact(trace_id))
    replay = service.append(_fact(trace_id))

    assert first["id"] == replay["id"]
    assert replay["idempotency_replayed"] is True
    assert first["status"] == "active"
    assert first["source_health"][0]["availability"] == "available"

    with db.session() as session:
        memory = MemoryItem(kind="observation", content="context only")
        session.add(memory)
        session.flush()
        memory_id = memory.id
    memory_only = _fact(trace_id).model_copy(
        update={
            "claim": "Memory says price is 70000",
            "sources": [
                EvidenceSourceRef(
                    source_type="memory",
                    source_id=memory_id,
                    observed_at=datetime.now(UTC),
                )
            ],
        }
    )
    with pytest.raises(ValueError, match="non-Memory"):
        service.append(memory_only)


def test_unavailable_source_fails_closed_or_creates_data_gap() -> None:
    db, trace_id = _db_with_trace()
    service = EvidenceService(db)
    missing = _fact(trace_id).model_copy(
        update={
            "claim": "Missing trace fact",
            "sources": [
                EvidenceSourceRef(
                    source_type="tool",
                    source_id="evt_missing",
                    tool_name="market_ticker",
                    observed_at=datetime.now(UTC),
                )
            ],
        }
    )
    with pytest.raises(EvidenceSourceUnavailable):
        service.append(missing)

    gap = service.append_or_gap(missing)
    assert gap["evidence_type"] == "data_gap"
    assert gap["fact_rejected"] is True
    assert gap["confidence"] == "0"


def test_inference_counter_graph_expiry_and_supersede_are_explicit() -> None:
    db, trace_id = _db_with_trace()
    service = EvidenceService(db)
    fact = service.append(_fact(trace_id))
    inference = service.append(
        InferenceEvidenceInput(
            claim="The short-term structure is supportive",
            scope=EvidenceScope(symbols=["BTC"], timeframes=["1H"]),
            sources=[],
            confidence=Decimal("0.6"),
            as_of=datetime(2026, 7, 14, 8, tzinfo=UTC),
            task_id="task_evidence",
            node_run_id="tnode_regime",
            role_key="market_regime",
            supporting_evidence_ids=[fact["id"]],
            inference_method="bounded synthesis of source-backed facts",
        )
    )
    counter = service.append(
        CounterEvidenceInput(
            claim="The observation window is too short for persistence",
            scope=EvidenceScope(symbols=["BTC"], timeframes=["1H"]),
            sources=[],
            confidence=Decimal("0.7"),
            as_of=datetime(2026, 7, 14, 8, tzinfo=UTC),
            task_id="task_evidence",
            node_run_id="tnode_bear",
            role_key="bear_case",
            challenged_evidence_ids=[inference["id"]],
            rationale="One observation cannot establish regime persistence.",
        )
    )
    graph = service.graph(inference["id"])
    assert {edge["relation_type"] for edge in graph["edges"]} == {
        "supported_by",
        "challenges",
    }
    assert counter["status"] == "active"

    original_hash = fact["content_hash"]
    expired = service.expire(fact["id"], reason="observation stale", actor="operator")
    assert expired["status"] == "expired"
    with pytest.raises(ValueError, match="not active"):
        service.append(
            InferenceEvidenceInput(
                claim="Stale support must be rejected",
                scope=EvidenceScope(symbols=["BTC"]),
                sources=[],
                confidence=Decimal("0.5"),
                as_of=datetime.now(UTC),
                role_key="market_regime",
                supporting_evidence_ids=[fact["id"]],
                inference_method="invalid stale synthesis",
            )
        )
    replacement = service.supersede(
        fact["id"],
        _fact(trace_id, claim="BTC last price is 70100"),
        reason="newer observation",
        actor="operator",
    )
    assert replacement["supersedes_id"] == fact["id"]
    assert service.get(fact["id"])["status"] == "superseded"
    assert service.get(fact["id"])["content_hash"] == original_hash


def test_deleted_source_remains_referenced_but_projects_unavailable() -> None:
    db, trace_id = _db_with_trace()
    service = EvidenceService(db)
    fact = service.append(_fact(trace_id))
    with db.session() as session:
        trace = session.get(TraceEvent, trace_id)
        assert trace is not None
        session.delete(trace)

    reread = service.get(fact["id"])
    assert reread["sources"][0]["source_id"] == trace_id
    assert reread["source_health"][0]["availability"] == "unavailable"
    assert reread["data_gaps"][0]["expected_source"] == "tool"


def test_expire_due_uses_valid_until_without_deleting_content() -> None:
    db, trace_id = _db_with_trace()
    service = EvidenceService(db)
    payload = _fact(trace_id).model_copy(
        update={"valid_until": datetime.now(UTC) + timedelta(minutes=1)}
    )
    row = service.append(payload)
    expired = service.expire_due(now=datetime.now(UTC) + timedelta(minutes=2))
    assert expired == [row["id"]]
    assert service.get(row["id"])["status"] == "expired"


def test_legacy_adapter_does_not_promote_old_records_to_v2() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        experiment = ResearchExperimentEvidence(
            job_id="rjob_legacy",
            mandate_id="rman_legacy",
            variant_id="v1",
            status="evidence_recorded",
            strategy_key="legacy_strategy",
        )
        memory = MemoryItem(
            kind="strategy_knowledge",
            content=StrategyEvidence(
                strategy_key="legacy_strategy", passed=True
            ).to_memory_content(),
        )
        session.add_all([experiment, memory])
        session.flush()
        experiment_id = experiment.id
        memory_id = memory.id

    assert LegacyEvidenceAdapter(db).get(experiment_id)["legacy"] is True
    projected = LegacyEvidenceAdapter(db).get(memory_id)
    assert projected["schema_version"] == "strategy_evidence.v1"
    assert projected["warning"].startswith("Memory is context")
    assert EvidenceService(db).query() == []


def test_evidence_api_has_public_reads_and_admin_only_mutation() -> None:
    db, trace_id = _db_with_trace()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="evidence-api-session",
        ),
        db=db,
    )
    client = TestClient(app)
    payload = _fact(trace_id).model_dump(mode="json")

    assert client.post("/api/research/evidence", json=payload).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "secret"}
    ).status_code == 200
    created = client.post("/api/research/evidence", json=payload)
    assert created.status_code == 200
    evidence_id = created.json()["id"]

    client.cookies.clear()
    assert client.get(f"/api/research/evidence/{evidence_id}").status_code == 200
    listed = client.get("/api/research/evidence?symbol=BTC&type=fact").json()["items"]
    assert [item["id"] for item in listed] == [evidence_id]
    assert client.get(f"/api/research/evidence/{evidence_id}/graph").status_code == 200


def test_existing_artifact_adapters_emit_bounded_hashed_source_refs() -> None:
    observed_at = datetime.now(UTC)
    rag = source_ref_from_rag_hit(
        RagHit(
            source_path="docs/knowledge/risk.md",
            title="Risk",
            chunk_index=2,
            content="Risk control comes before signal strength.",
            score=1.0,
            content_preview="Risk control",
        ),
        observed_at=observed_at,
    )
    result = source_ref_from_bitpro_result(
        result_id="result-1",
        result_projection={"return_pct": "3.2"},
        observed_at=observed_at,
    )
    snapshot = source_ref_from_paper_snapshot(
        snapshot_id="paper-1",
        snapshot_projection={"status": "running"},
        observed_at=observed_at,
    )
    assert rag.source_id == "docs/knowledge/risk.md#2"
    assert len(result.content_hash) == 64
    assert len(snapshot.content_hash) == 64

    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        experiment = ResearchExperimentEvidence(
            job_id="rjob_sources",
            mandate_id="rman_sources",
            variant_id="v1",
            status="evidence_recorded",
            strategy_key="source_strategy",
            result_refs_json={
                "locked_out_of_sample": {"job_id": "bt-1", "result_id": "result-1"}
            },
            metrics_json={"locked_out_of_sample": {"return_pct": "3.2"}},
        )
        session.add(experiment)
        session.flush()
        refs = source_refs_from_experiment(experiment)
    assert [ref.source_id for ref in refs] == ["result-1"]
