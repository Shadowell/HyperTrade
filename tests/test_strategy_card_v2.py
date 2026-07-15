from __future__ import annotations

from decimal import Decimal
from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient
from hypertrade.cli import handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import (
    Database,
    PaperPromotion,
    ResearchExperimentEvidence,
    StrategyCardLifecycleDecision,
    StrategyCardSnapshot,
    StrategyLineage,
    StrategyVersion,
)
from hypertrade.main import create_app
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import ExperimentExecutionComplete, ExperimentRegister
from hypertrade.research.strategy_card_schemas import StrategyCardDecisionRequestV1
from hypertrade.research.strategy_cards import StrategyCardService
from sqlalchemy import func, select
from test_experiment_manifest import manifest


def _register(db: Database, *, fee: str = "10", key: str = "strategy-card-key-001") -> dict:
    return ExperimentLedgerService(db).register(
        ExperimentRegister(manifest=manifest(fee=fee), idempotency_key=key),
        actor="test",
    )


def test_manifest_immediately_creates_incomplete_card_without_paper() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    created = _register(db)

    cards = StrategyCardService(db).list()
    card = next(row for row in cards if row["schema_version"] == "strategy_card.v2")

    assert card["experiment_manifest_id"] == created["manifest"]["id"]
    assert card["lifecycle_status"] == "testing"
    assert card["paper_status"] == "not_started"
    assert "paper" in card["missing_fields"]
    assert Decimal(card["completeness_score"]) < 1
    assert card["source_refs"]["paper_promotion_ids"] == []
    with db.session() as session:
        assert session.scalar(select(func.count(PaperPromotion.id))) == 0


def test_semantic_manifests_share_lineage_and_receive_stable_versions() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _register(db, fee="10", key="strategy-card-key-001")
    _register(db, fee="11", key="strategy-card-key-002")

    cards = [
        row for row in StrategyCardService(db).list() if row["schema_version"] == "strategy_card.v2"
    ]

    assert len(cards) == 2
    assert len({row["lineage"]["id"] for row in cards}) == 1
    assert {row["version"]["version_number"] for row in cards} == {1, 2}
    assert len({row["version"]["manifest_fingerprint"] for row in cards}) == 2
    with db.session() as session:
        assert session.scalar(select(func.count(StrategyLineage.id))) == 1
        assert session.scalar(select(func.count(StrategyVersion.id))) == 2


def test_new_facts_append_snapshot_and_keep_previous_content_immutable() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    created = _register(db)
    execution_id = created["execution"]["id"]
    service = StrategyCardService(db)
    initial = service.list()[0]
    initial_hash = initial["snapshot_content_hash"]

    with db.session() as session:
        evidence = ResearchExperimentEvidence(
            job_id="rjob_card_v2",
            mandate_id="rmand_test",
            variant_id="baseline",
            status="evidence_recorded",
            strategy_key="btc_trend_v1",
            metrics_json={"capacity_usdt": "1000"},
            gate_results_json={"oos": True},
        )
        session.add(evidence)
        session.flush()
        evidence_id = evidence.id
    ledger = ExperimentLedgerService(db)
    ledger.start(execution_id)
    ledger.complete(
        execution_id,
        ExperimentExecutionComplete(
            evidence_ids=[evidence_id],
            evidence_kind="legacy_experiment",
        ),
        actor="test",
    )
    updated = service.reconcile_manifest(created["manifest"]["id"])
    snapshots = service.snapshots(updated["card_id"])

    assert len(snapshots) == 2
    assert snapshots[0]["snapshot_content_hash"] == initial_hash
    assert snapshots[0]["source_refs"]["evidence_ids"] == []
    assert snapshots[1]["source_refs"]["evidence_ids"] == [evidence_id]
    with db.session() as session:
        assert session.scalar(select(func.count(StrategyCardSnapshot.id))) == 2


def test_paper_projection_never_crosses_mandate_scope() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    created = _register(db)
    with db.session() as session:
        evidence = ResearchExperimentEvidence(
            job_id="rjob_other_mandate",
            mandate_id="rmand_other",
            variant_id="baseline",
            status="evidence_recorded",
            strategy_key="btc_trend_v1",
            metrics_json={},
            gate_results_json={"oos": True},
        )
        session.add(evidence)
        session.flush()
        session.add(
            PaperPromotion(
                mandate_id="rmand_other",
                job_id=evidence.job_id,
                evidence_id=evidence.id,
                strategy_key=evidence.strategy_key,
                bitpro_strategy_id="bitpro_other",
                status="paper_observing",
            )
        )

    card = StrategyCardService(db).reconcile_manifest(created["manifest"]["id"])

    assert card["paper_status"] == "not_started"
    assert card["source_refs"]["paper_promotion_ids"] == []
    assert card["bitpro_strategy_id"] == ""


def test_lifecycle_decision_is_idempotent_audit_fact_without_execution_authority() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _register(db)
    service = StrategyCardService(db)
    card = service.list()[0]
    payload = StrategyCardDecisionRequestV1(
        target_status="retired",
        decision="accept",
        reason="Operator ended this research branch",
        idempotency_key="strategy-card-decision-001",
    )

    first = service.decide(card["card_id"], payload, actor="admin")
    replay = service.decide(card["card_id"], payload, actor="admin")

    assert first["execution_authorized"] is False
    assert first["card"]["lifecycle_status"] == "retired"
    assert replay["decision"]["id"] == first["decision"]["id"]
    with db.session() as session:
        assert session.scalar(select(func.count(StrategyCardLifecycleDecision.id))) == 1
        assert session.scalar(select(func.count(PaperPromotion.id))) == 0

    conflicting = payload.model_copy(update={"reason": "A different decision reason"})
    try:
        service.decide(card["card_id"], conflicting, actor="admin")
    except ValueError as exc:
        assert "idempotency key" in str(exc)
    else:
        raise AssertionError("decision idempotency must bind the canonical request")


def test_funnel_uses_manifest_denominator_and_api_projects_same_state() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _register(db)
    service = StrategyCardService(db)
    funnel = service.funnel()

    assert funnel["denominator"] == 1
    assert funnel["denominator_unit"] == "experiment_manifest"
    assert funnel["stages"]["manifest"] == funnel["stages"]["card"] == 1
    assert funnel["stages"]["paper"] == 0

    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="strategy-card-v2-test",
            ),
            db=db,
        )
    )
    assert client.get("/api/research/strategy-cards/funnel").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code
        == 200
    )
    assert client.get("/api/research/strategy-cards/funnel").json() == funnel
    card = client.get("/api/research/strategy-cards").json()["items"][0]
    snapshots = client.get(f"/api/research/strategy-cards/{card['card_id']}/snapshots")
    assert snapshots.status_code == 200
    decision = client.post(
        f"/api/research/strategy-cards/{card['card_id']}/decisions",
        json={
            "target_status": "review_required",
            "decision": "hold",
            "reason": "Need additional evidence",
            "idempotency_key": "strategy-card-api-decision-001",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["execution_authorized"] is False


def test_cli_projects_cards_and_funnel_without_client_lifecycle_logic() -> None:
    class CardClient:
        def list_strategy_cards(self) -> list[dict]:
            return [
                {
                    "card_id": "scard_1",
                    "strategy_key": "btc_trend_v1",
                    "version": {"version_number": 2},
                    "lifecycle_status": "testing",
                    "completeness_score": "0.50000",
                    "missing_fields": ["paper"],
                }
            ]

        def get_research_funnel(self) -> dict:
            return {
                "denominator": 1,
                "denominator_unit": "experiment_manifest",
                "stages": {"manifest": 1, "paper": 0, "card": 1},
            }

    output = StringIO()
    handle_slash_command("/cards", client=CardClient(), output=output)  # type: ignore[arg-type]

    rendered = output.getvalue()
    assert "denominator=1" in rendered
    assert "btc_trend_v1 v2 status=testing complete=0.50000" in rendered
    assert "missing=paper" in rendered


def test_strategy_card_projection_has_no_execution_adapter_imports() -> None:
    source = (
        Path(__file__).parents[1]
        / "backend"
        / "src"
        / "hypertrade"
        / "research"
        / "strategy_cards.py"
    ).read_text(encoding="utf-8")

    assert "hypertrade.bitpro" not in source
    assert "hypertrade.paper.service" not in source
    assert "hypertrade.live" not in source
    assert "live_order" not in source
    assert "capital_allocation" not in source
