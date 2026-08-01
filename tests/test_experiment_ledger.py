from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from hypertrade.cli import handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import Database, ResearchExperimentEvidence
from hypertrade.main import create_app
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import (
    ArtifactReference,
    ExperimentExecutionComplete,
    ExperimentRegister,
    experiment_fingerprint,
)
from test_experiment_manifest import manifest


def register(db: Database, *, key: str = "experiment-key-0001") -> dict[str, object]:
    return ExperimentLedgerService(db).register(
        ExperimentRegister(
            manifest=manifest(),
            idempotency_key=key,
            task_id="task_test",
            research_job_id="rjob_test",
        ),
        actor="test",
    )


def test_completed_fingerprint_is_reused_without_new_execution() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    first = register(db)
    execution = dict(first["execution"])  # type: ignore[arg-type]
    service = ExperimentLedgerService(db)
    service.start(str(execution["id"]))
    service.complete(
        str(execution["id"]),
        ExperimentExecutionComplete(metrics={"return": Decimal("1.20")}),
        actor="test",
    )

    replay = register(db, key="experiment-key-0002")

    assert replay["reused"] is True
    assert dict(replay["execution"])["id"] == execution["id"]  # type: ignore[arg-type]
    assert len(service.executions(experiment_fingerprint(manifest()))) == 1


def test_concurrent_registration_creates_one_physical_execution(tmp_path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'experiment-race.db'}")
    db.create_all()
    barrier = Barrier(2)

    def submit(index: int) -> dict[str, object]:
        barrier.wait()
        return ExperimentLedgerService(db).register(
            ExperimentRegister(
                manifest=manifest(),
                idempotency_key=f"experiment-concurrent-{index}",
            ),
            actor=f"thread:{index}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))

    execution_ids = {
        str(dict(item["execution"])["id"])
        for item in results  # type: ignore[arg-type]
    }
    assert len(execution_ids) == 1
    assert len(ExperimentLedgerService(db).executions(experiment_fingerprint(manifest()))) == 1


def test_failed_execution_requires_audited_force_rerun() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    first = register(db)
    first_execution = dict(first["execution"])  # type: ignore[arg-type]
    service = ExperimentLedgerService(db)
    service.fail(str(first_execution["id"]), error={"code": "upstream"})

    with pytest.raises(ValueError, match="requires force_rerun"):
        register(db, key="experiment-key-0002")

    retried = service.register(
        ExperimentRegister(
            manifest=manifest(),
            idempotency_key="experiment-key-0003",
            force_rerun=True,
            force_reason="operator approved retry",
        ),
        actor="test",
    )
    retry = dict(retried["execution"])  # type: ignore[arg-type]
    assert retry["attempt"] == 2
    assert retry["retry_of_id"] == first_execution["id"]
    assert first_execution["id"] != retry["id"]


def test_artifact_contract_and_evidence_reference_are_verified() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        evidence = ResearchExperimentEvidence(
            job_id="rjob_test",
            mandate_id="rmand_test",
            variant_id="baseline",
            status="evidence_recorded",
            strategy_key="btc_trend_v1",
        )
        session.add(evidence)
        session.flush()
        evidence_id = evidence.id
    created = register(db)
    execution_id = str(dict(created["execution"])["id"])  # type: ignore[arg-type]
    service = ExperimentLedgerService(db)
    service.start(execution_id)

    with pytest.raises(ValueError, match="artifact contract mismatch"):
        service.complete(
            execution_id,
            ExperimentExecutionComplete(
                artifacts=[
                    ArtifactReference(
                        artifact_id="bt-1",
                        artifact_ref="bitpro:backtest:1",
                        content_hash="f" * 64,
                        contract_version="bitpro-mcp-v2",
                    )
                ]
            ),
            actor="test",
        )

    completed = service.complete(
        execution_id,
        ExperimentExecutionComplete(
            evidence_ids=[evidence_id],
            evidence_kind="legacy_experiment",
            artifacts=[
                ArtifactReference(
                    artifact_id="bt-1",
                    artifact_ref="bitpro:backtest:1",
                    content_hash="f" * 64,
                    contract_version="bitpro-mcp-v1",
                )
            ],
        ),
        actor="test",
    )
    assert completed["status"] == "completed"
    assert service.executions(experiment_fingerprint(manifest()))[0]["evidence"] == [
        {"evidence_id": evidence_id, "evidence_kind": "legacy_experiment"}
    ]


def test_diff_explains_semantic_category() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = ExperimentLedgerService(db)
    first = service.register(
        ExperimentRegister(manifest=manifest(), idempotency_key="experiment-key-0001"),
        actor="test",
    )
    second = service.register(
        ExperimentRegister(manifest=manifest(fee="11"), idempotency_key="experiment-key-0002"),
        actor="test",
    )

    diff = service.diff(
        str(dict(first["manifest"])["fingerprint"]),  # type: ignore[arg-type]
        str(dict(second["manifest"])["fingerprint"]),  # type: ignore[arg-type]
    )
    assert diff["equal"] is False
    assert {row["category"] for row in diff["changes"]} == {"costs"}


def test_experiment_api_requires_admin_to_register_but_reads_publicly() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="experiment-ledger-test",
            ),
            db=db,
        )
    )
    payload = ExperimentRegister(
        manifest=manifest(), idempotency_key="experiment-api-key-0001"
    ).model_dump(mode="json")

    assert client.post("/api/research/experiments", json=payload).status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code
        == 200
    )
    created = client.post("/api/research/experiments", json=payload)
    fingerprint = created.json()["manifest"]["fingerprint"]

    assert created.status_code == 200
    assert client.get(f"/api/research/experiments/{fingerprint}").status_code == 200
    assert (
        client.get(f"/api/research/experiments/{fingerprint}/executions").json()["items"][0][
            "status"
        ]
        == "queued"
    )


def test_cli_projects_manifest_execution_and_categorized_diff() -> None:
    class LedgerClient:
        def list_experiment_manifests(self):
            return [{"id": "expm_1", "fingerprint": "a" * 64, "strategy_key": "btc"}]

        def get_experiment_manifest(self, fingerprint: str):
            return {
                "manifest": {"fingerprint": fingerprint, "strategy_key": "btc"},
                "executions": [
                    {"id": "exex_1", "attempt": 1, "status": "completed", "evidence": []}
                ],
            }

        def diff_experiment_manifests(self, left: str, right: str):
            return {
                "equal": False,
                "changes": [
                    {"category": "costs", "path": "costs.maker_fee_bps", "left": 1, "right": 2}
                ],
            }

    output = StringIO()
    client = LedgerClient()
    handle_slash_command("/ledger list", client=client, output=output)  # type: ignore[arg-type]
    handle_slash_command(f"/ledger show {'a' * 64}", client=client, output=output)  # type: ignore[arg-type]
    handle_slash_command(f"/ledger diff {'a' * 64} {'b' * 64}", client=client, output=output)  # type: ignore[arg-type]

    rendered = output.getvalue()
    assert "Experiment manifests" in rendered
    assert "attempt=1 [completed]" in rendered
    assert "[costs] costs.maker_fee_bps" in rendered
