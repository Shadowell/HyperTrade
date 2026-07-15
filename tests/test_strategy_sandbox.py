from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.runtime.adapters.sandbox import (
    DockerSandboxRunner,
    InMemorySandboxStore,
    SqlSandboxStore,
    StrategySandbox,
    is_pinned_oci_image,
)
from hypertrade.runtime.domain.sandbox import ImportReviewV1, SandboxRequestV1


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def files(*, passing: bool = True) -> dict[str, str]:
    expected = "[0, 0, 0]" if passing else "[1, 1, 1]"
    return {
        "strategies/candidate.py": (
            "def generate_signals(prices: list[float]) -> list[int]:\n"
            "    return [0 for _ in prices]\n"
        ),
        "tests/test_candidate.py": (
            "from strategies.candidate import generate_signals\n\n"
            "def test_signals():\n"
            f"    assert generate_signals([1.0, 2.0, 3.0]) == {expected}\n"
        ),
    }


def request(**updates: object) -> SandboxRequestV1:
    values: dict[str, object] = {
        "assignment_ref": "assignment:asgn_sandbox",
        "context_pack_refs": ("context:ctxp_sandbox@" + "a" * 64,),
        "files": files(),
        "commands": (
            {"name": "ruff"},
            {"name": "pytest"},
            {"name": "limited_backtest"},
        ),
        "idempotency_key": "sandbox-run-001",
    }
    values.update(updates)
    return SandboxRequestV1.model_validate(values)


@pytest.mark.anyio
async def test_strategy_patch_passes_lint_test_and_limited_backtest() -> None:
    store = InMemorySandboxStore()
    sandbox = StrategySandbox(store)
    result = await sandbox.run("mis_sandbox", request())
    replay = await sandbox.run("mis_sandbox", request())

    assert result.status == "validated"
    assert [row.status for row in result.commands] == ["passed", "passed", "passed"]
    assert "no orders dispatched" in result.commands[-1].output_preview
    assert result.patch.patch_hash == replay.patch.patch_hash
    assert result.artifact_hash == replay.artifact_hash
    assert all(path.startswith(("strategies/", "tests/")) for path in result.patch.file_hashes)
    assert result.artifacts
    assert {row.kind for row in result.artifacts} >= {
        "source_file",
        "patch",
        "command_output",
        "manifest",
    }


@pytest.mark.anyio
async def test_failed_test_never_produces_validated_manifest() -> None:
    sandbox = StrategySandbox(InMemorySandboxStore())
    result = await sandbox.run("mis_sandbox", request(files=files(passing=False)))

    assert result.status == "failed"
    assert result.commands[-1].name == "pytest"
    assert result.commands[-1].status == "failed"


@pytest.mark.anyio
async def test_review_is_hash_bound_idempotent_and_never_imports() -> None:
    store = InMemorySandboxStore()
    run = await StrategySandbox(store).run("mis_sandbox", request())
    review = ImportReviewV1(
        decision="accept",
        reason="Exact patch and isolated test ledger reviewed",
        patch_hash=run.patch.patch_hash,
        artifact_hash=run.artifact_hash,
        idempotency_key="sandbox-review-001",
    )
    first = await store.review(run, review, "admin")
    replay = await store.review(run, review, "admin")

    assert first == replay
    assert first.external_write_performed is False
    with pytest.raises(ValueError, match="hash mismatch"):
        await store.review(
            run,
            review.model_copy(
                update={
                    "artifact_hash": "0" * 64,
                    "idempotency_key": "sandbox-review-tampered",
                }
            ),
            "admin",
        )
    with pytest.raises(ValueError, match="idempotency key"):
        await store.review(
            run,
            review.model_copy(
                update={"reason": "different decision context"}
            ),
            "admin",
        )


@pytest.mark.anyio
async def test_production_rejects_host_subprocess_fallback() -> None:
    sandbox = StrategySandbox(InMemorySandboxStore(), production=True)
    with pytest.raises(RuntimeError, match="rootless Docker"):
        await sandbox.run("mis_production", request())


def test_production_sandbox_image_requires_an_immutable_digest() -> None:
    pinned = "registry.example/hypertrade-sandbox@sha256:" + "a" * 64

    assert is_pinned_oci_image(pinned)
    assert not is_pinned_oci_image("registry.example/hypertrade-sandbox:latest")
    with pytest.raises(ValueError, match="sha256"):
        DockerSandboxRunner("registry.example/hypertrade-sandbox:latest")


@pytest.mark.anyio
async def test_sql_sandbox_projection_persists_runs_and_reviews(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sandbox.db'}"
    Database(database_url).create_all()
    store = SqlSandboxStore(database_url)
    try:
        run = await StrategySandbox(store).run("mis_sandbox_sql", request())
        review = await store.review(
            run,
            ImportReviewV1(
                decision="reject",
                reason="Candidate needs another robustness test",
                patch_hash=run.patch.patch_hash,
                artifact_hash=run.artifact_hash,
                idempotency_key="sandbox-review-sql-001",
            ),
            "admin",
        )
        runs = await store.runs("mis_sandbox_sql")
        reviews = await store.reviews("mis_sandbox_sql")
    finally:
        await store.dispose()

    assert runs[0].artifact_hash == run.artifact_hash
    assert reviews[0] == review
    assert reviews[0].external_write_performed is False


def test_sandbox_api_requires_succeeded_assignment_and_exact_context() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="sandbox-api-test-secret",
        MISSION_RUNTIME_ENABLED=True,
        AGENT_DYNAMIC_TEAM_ENABLED=True,
        AGENT_STRATEGY_SANDBOX_ENABLED=True,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
        mission_id = client.post(
            "/api/agent/missions",
            json={
                "objective": "Develop a bounded candidate strategy",
                "success_criteria": [
                    {
                        "criterion_id": "validated",
                        "kind": "all_steps_validated",
                        "description": "The foundation step validates",
                    }
                ],
            },
        ).json()["mission_id"]
        client.post(f"/api/agent/missions/{mission_id}/run")
        pack = client.get(f"/api/agent/missions/{mission_id}/context-packs").json()[
            "context_packs"
        ][0]
        context_ref = f"context:{pack['context_pack_id']}@{pack['manifest_hash']}"
        team_payload = {
            "idempotency_key": "sandbox-team-001",
            "assignments": [
                {
                    "role_id": "research_lead",
                    "objective": "Prepare a bounded strategy sandbox assignment",
                    "capability_id": "runtime.objective_inspection",
                    "context_pack_refs": [context_ref],
                }
            ],
        }
        client.post(f"/api/agent/missions/{mission_id}/team/run", json=team_payload)
        assignment_id = client.get(f"/api/agent/missions/{mission_id}/supervision").json()[
            "assignments"
        ][0]["assignment_id"]
        sandbox_payload = request(
            assignment_ref=f"assignment:{assignment_id}",
            context_pack_refs=(context_ref,),
        )
        run = client.post(
            f"/api/agent/missions/{mission_id}/sandbox-runs",
            json=sandbox_payload.model_dump(mode="json"),
        )
        unknown_source = client.post(
            f"/api/agent/missions/{mission_id}/sandbox-runs",
            json=sandbox_payload.model_copy(
                update={"source_artifact_refs": ("artifact:missing@" + "b" * 64,)}
            ).model_dump(mode="json"),
        )
        run_body = run.json()
        review = client.post(
            f"/api/agent/missions/{mission_id}/sandbox-runs/{run_body['sandbox_run_id']}/review",
            json={
                "decision": "accept",
                "reason": "Exact isolated run reviewed",
                "patch_hash": run_body["patch"]["patch_hash"],
                "artifact_hash": run_body["artifact_hash"],
                "idempotency_key": "sandbox-api-review-001",
            },
        )
        projection = client.get(f"/api/agent/missions/{mission_id}/sandbox-runs")

    assert run.status_code == review.status_code == 200
    assert unknown_source.status_code == 409
    assert run_body["status"] == "validated"
    assert review.json()["external_write_performed"] is False
    assert len(projection.json()["runs"]) == len(projection.json()["reviews"]) == 1
