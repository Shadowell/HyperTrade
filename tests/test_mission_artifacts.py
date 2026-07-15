from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.runtime.adapters.context_engine import (
    ContextArtifactEngine,
    InMemoryContextArtifactStore,
    SqlContextArtifactStore,
)
from hypertrade.runtime.adapters.foundation import FoundationPlanner, ReadOnlyCapabilityPolicy
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.context import MissionArtifactCreateV1, hash_payload
from hypertrade.runtime.domain.models import (
    MissionCreate,
    StepObservationV2,
    SuccessCriterionV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def artifact_payload(**updates: object) -> MissionArtifactCreateV1:
    preview = {"decision": "needs_data", "source_count": 2}
    values: dict[str, object] = {
        "kind": "research_report",
        "title": "Bounded research report",
        "inline_preview": preview,
        "producer_ref": "step:report",
        "source_refs": ("observation:tobs_123", "evidence:ev_123"),
    }
    values.update(updates)
    return MissionArtifactCreateV1.model_validate(values)


class UnknownArtifactExecutor:
    async def execute(self, *_: object) -> StepObservationV2:
        return StepObservationV2(
            status="succeeded",
            summary="Claims an artifact that is not indexed.",
            artifact_refs=("artifact:forged@" + "0" * 64,),
        )


@pytest.mark.anyio
async def test_forged_artifact_reference_cannot_complete_mission() -> None:
    mission_store = InMemoryMissionStore()
    context_store = InMemoryContextArtifactStore()
    runtime = MissionRuntime(
        mission_store,
        FoundationPlanner(),
        UnknownArtifactExecutor(),
        ReadOnlyCapabilityPolicy(),
        ContextArtifactEngine(context_store),
    )
    mission = await runtime.create(
        MissionCreate(
            objective="Reject a forged artifact completion reference",
            success_criteria=(
                SuccessCriterionV1(
                    criterion_id="validated",
                    kind="all_steps_validated",
                    description="The step is validated",
                ),
            ),
        )
    )

    result = await runtime.run(mission.mission_id)

    assert result.status == "waiting_input"
    assert len(await context_store.list_packs(mission.mission_id)) == 1


@pytest.mark.anyio
async def test_artifact_dedupes_versions_and_preserves_supersede_relation() -> None:
    store = InMemoryContextArtifactStore()
    first = await store.register_artifact("mis_artifact", artifact_payload())
    replay = await store.register_artifact("mis_artifact", artifact_payload())
    second = await store.register_artifact(
        "mis_artifact",
        artifact_payload(
            inline_preview={"decision": "validated", "source_count": 3},
            supersedes_artifact_id=first.artifact_id,
        ),
    )

    rows = await store.list_artifacts("mis_artifact")
    relations = await store.relations("mis_artifact")

    assert replay == first
    assert [row.version for row in rows] == [1, 2]
    assert rows[0].status == "superseded"
    assert second.status == "current"
    assert any(row.relation_type == "supersedes" for row in relations)


@pytest.mark.anyio
async def test_artifact_rejects_unsafe_or_cross_mission_content() -> None:
    store = InMemoryContextArtifactStore()
    first = await store.register_artifact("mis_one", artifact_payload())

    with pytest.raises(ValueError, match="hash mismatch"):
        await store.register_artifact("mis_one", artifact_payload(content_hash="0" * 64))
    with pytest.raises(ValueError, match="secret or raw-series"):
        await store.register_artifact(
            "mis_one", artifact_payload(inline_preview={"api_key": "secret"})
        )
    with pytest.raises(ValueError, match="does not belong"):
        await store.register_artifact(
            "mis_two", artifact_payload(supersedes_artifact_id=first.artifact_id)
        )


@pytest.mark.anyio
async def test_external_artifact_requires_hash_and_stable_uri() -> None:
    store = InMemoryContextArtifactStore()
    with pytest.raises(ValueError, match="content hash"):
        await store.register_artifact(
            "mis_external",
            artifact_payload(inline_preview={}, external_ref="s3://bucket/report.json"),
        )
    with pytest.raises(ValueError, match="stable URI"):
        await store.register_artifact(
            "mis_external",
            artifact_payload(
                inline_preview={}, external_ref="relative/path", content_hash="a" * 64
            ),
        )


@pytest.mark.anyio
async def test_sql_artifact_index_persists_deduped_metadata(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'artifacts.db'}"
    Database(database_url).create_all()
    store = SqlContextArtifactStore(database_url)
    try:
        first = await store.register_artifact("mis_sql", artifact_payload())
        replay = await store.register_artifact("mis_sql", artifact_payload())
        rows = await store.list_artifacts("mis_sql")
        relations = await store.relations("mis_sql")
    finally:
        await store.dispose()

    assert replay.artifact_id == first.artifact_id
    assert len(rows) == 1
    assert len(relations) == 2
    assert rows[0].content_hash == hash_payload(rows[0].inline_preview)


def test_context_and_artifact_api_projects_mission_owned_state() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="context-api-test-secret",
        MISSION_RUNTIME_ENABLED=True,
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "secret"},
            ).status_code
            == 200
        )
        created = client.post(
            "/api/agent/missions",
            json={
                "objective": "Compile bounded context and inspect the objective",
                "success_criteria": [
                    {
                        "criterion_id": "validated",
                        "kind": "all_steps_validated",
                        "description": "Every step validates",
                    }
                ],
            },
        )
        mission_id = created.json()["mission_id"]
        completed = client.post(f"/api/agent/missions/{mission_id}/run")
        packs = client.get(f"/api/agent/missions/{mission_id}/context-packs")
        artifact = client.post(
            f"/api/agent/missions/{mission_id}/artifacts",
            json=artifact_payload().model_dump(mode="json"),
        )
        artifacts = client.get(f"/api/agent/missions/{mission_id}/artifacts")

    assert completed.json()["status"] == "completed"
    assert len(packs.json()["context_packs"]) == 1
    assert packs.json()["context_packs"][0]["ledger"]["used_tokens"] > 0
    assert artifact.status_code == 200
    assert len(artifacts.json()["artifacts"]) == 1
