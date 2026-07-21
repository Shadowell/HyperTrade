from __future__ import annotations

from io import StringIO

from evolution_fixtures import NOW, evolution_request, seeded_evolution_db
from fastapi.testclient import TestClient
from hypertrade.cli import handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import ExperimentManifest, StrategyEvolutionCandidate, StrategyVersion
from hypertrade.main import create_app
from hypertrade.research.evolution import StrategyEvolutionService
from hypertrade.research.evolution_schemas import CandidateProposalV1, EvolutionRequestV1
from sqlalchemy import func, select


class PassingValidator:
    def validate(self, *, code_ref: str, code_sha256: str) -> dict[str, object]:
        return {"valid": True, "sandbox_passed": True, "dependency_status": "approved"}


class FailingValidator:
    def validate(self, *, code_ref: str, code_sha256: str) -> dict[str, object]:
        return {"valid": True, "sandbox_passed": False, "dependency_status": "unknown"}


def test_candidate_creates_new_immutable_version_and_keeps_parent_unchanged() -> None:
    db, refs = seeded_evolution_db()
    with db.session() as session:
        parent = session.get(StrategyVersion, refs["parent_version_id"])
        assert parent is not None
        before = (parent.manifest_id, parent.manifest_fingerprint, parent.strategy_spec_hash)

    result = StrategyEvolutionService(db).evolve(
        evolution_request(refs), actor="evolution-test", now=NOW
    )
    accepted = result["candidates"][0]
    with db.session() as session:
        parent = session.get(StrategyVersion, refs["parent_version_id"])
        candidate = session.get(StrategyVersion, accepted["candidate_version_id"])
        assert parent is not None and candidate is not None
        assert (
            parent.manifest_id,
            parent.manifest_fingerprint,
            parent.strategy_spec_hash,
        ) == before
        assert candidate.id != parent.id
        assert candidate.lineage_id == parent.lineage_id
        manifest = session.get(ExperimentManifest, candidate.manifest_id)
        assert manifest is not None
        assert manifest.canonical_json["parameters"]["fast"] == "8"


def test_candidate_fingerprint_prevents_duplicate_physical_experiment() -> None:
    db, refs = seeded_evolution_db()
    service = StrategyEvolutionService(db)
    first = service.evolve(evolution_request(refs), actor="evolution-test", now=NOW)
    second = service.evolve(
        evolution_request(refs, key="evolution-request-002"),
        actor="evolution-test",
        now=NOW,
    )

    assert second["candidates"][0]["id"] == first["candidates"][0]["id"]
    assert second["usage"]["reused_candidate_ids"] == [first["candidates"][0]["id"]]
    with db.session() as session:
        assert session.scalar(select(func.count(StrategyEvolutionCandidate.id))) == 1
        assert session.scalar(select(func.count(ExperimentManifest.id))) == 2


def test_rule_candidate_requires_declared_slot_and_sandbox_dependency_pass() -> None:
    db, refs = seeded_evolution_db()
    proposal = CandidateProposalV1(
        proposal_kind="rule",
        rule_changes={"entry": "Enter only after two independently confirmed trend bars."},
        strategy_code_sha256="6" * 64,
        strategy_code_ref="artifact:strategy-candidate:entry-v2",
        proposal_reason="Reduce false breakouts observed in settled windows.",
    )
    rejected = StrategyEvolutionService(db, rule_validator=FailingValidator()).evolve(
        evolution_request(refs, proposals=[proposal]), actor="evolution-test", now=NOW
    )
    assert rejected["candidates"][0]["status"] == "rejected"
    assert set(rejected["candidates"][0]["rejection_reasons"]) == {
        "strategy_dependency_unapproved",
        "strategy_sandbox_failed",
    }

    db, refs = seeded_evolution_db()
    accepted = StrategyEvolutionService(db, rule_validator=PassingValidator()).evolve(
        evolution_request(refs, proposals=[proposal]), actor="evolution-test", now=NOW
    )
    assert accepted["candidates"][0]["status"] == "accepted"

    payload = evolution_request(refs).model_dump(mode="python")
    payload["proposals"][0]["account"] = "mainnet"
    try:
        EvolutionRequestV1.model_validate(payload)
    except ValueError as exc:
        assert "extra" in str(exc).lower()
    else:
        raise AssertionError("candidate must not expand account or permission scope")


def test_api_and_cli_expose_read_only_candidate_queue() -> None:
    db, refs = seeded_evolution_db()
    run = StrategyEvolutionService(db).evolve(
        evolution_request(refs), actor="evolution-test", now=NOW
    )
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="strategy-evolution-api-test",
            ),
            db=db,
        )
    )
    assert client.get("/api/research/evolution-runs").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
        .status_code
        == 200
    )
    listed = client.get("/api/research/evolution-runs").json()["items"]
    detail = client.get(f"/api/research/evolution-runs/{run['id']}").json()
    assert listed[0]["id"] == run["id"]
    assert detail["candidates"][0]["candidate_version_id"]
    assert detail["execution_authorized"] is False

    class EvolutionClient:
        def list_strategy_evolution_runs(self) -> list[dict]:
            return listed

        def get_strategy_evolution_run(self, run_id: str) -> dict:
            assert run_id == run["id"]
            return detail

    output = StringIO()
    handle_slash_command(
        f"/evolution show {run['id']}",
        client=EvolutionClient(),  # type: ignore[arg-type]
        output=output,
    )
    assert "execution_authorized=false" in output.getvalue()
    assert "version=sver_" in output.getvalue()
