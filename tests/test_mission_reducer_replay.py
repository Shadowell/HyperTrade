from __future__ import annotations

from pathlib import Path

import pytest
from hypertrade.db import AgentMission, Database
from hypertrade.runtime.adapters.foundation import (
    FoundationExecutor,
    FoundationPlanner,
    ReadOnlyCapabilityPolicy,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.application.entrypoint import mission_request_for_prompt
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.mission_events import (
    MissionSnapshotV2,
    make_mission_event,
    mission_content_hash,
    mission_projection_hash,
    reduce_mission_events,
)
from hypertrade.runtime.domain.models import MissionEventV1, MissionReplayStatus
from sqlalchemy import select


@pytest.mark.anyio
async def test_memory_projection_hash_matches_empty_database_replay() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = await runtime.create(
        mission_request_for_prompt(
            "研究 BTC 当前市场状态",
            actor="test",
            idempotency_key="memory-replay",
        )
    )
    mission = await runtime.run(mission.mission_id)
    online = MissionSnapshotV2(
        mission=mission,
        plans=tuple(await store.plans(mission.mission_id)),
        attempts=tuple(await store.attempts(mission.mission_id)),
    )

    replayed = reduce_mission_events(await store.events(mission.mission_id, limit=1_000))

    assert mission_projection_hash(replayed) == mission_projection_hash(online)
    assert replayed.mission is not None
    assert replayed.mission.completion_proof is not None
    assert replayed.mission.completion_proof.passed


@pytest.mark.anyio
async def test_sql_projection_hash_matches_offline_replay(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'mission-replay.db'}"
    database = Database(database_url)
    database.create_all()
    store = SqlAlchemyMissionStore(database_url)
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    try:
        mission = await runtime.create(
            mission_request_for_prompt(
                "研究 ETH 当前市场状态",
                actor="test",
                idempotency_key="sql-replay",
            )
        )
        claimed = await store.claim_next("replay-worker", lease_seconds=60)
        assert claimed is not None
        await runtime.run(mission.mission_id, fencing_token=claimed.fencing_token)
        mission = await store.get(mission.mission_id)
        events = await store.events(mission.mission_id, limit=1_000)
        online = MissionSnapshotV2(
            mission=mission,
            plans=tuple(await store.plans(mission.mission_id)),
            attempts=tuple(await store.attempts(mission.mission_id)),
        )
    finally:
        await store.dispose()
    replayed = reduce_mission_events(events)
    with database.session() as session:
        stored_hash = session.scalar(
            select(AgentMission.projection_hash).where(AgentMission.id == mission.mission_id)
        )

    assert stored_hash == mission_projection_hash(online)
    assert mission_projection_hash(replayed) == stored_hash


def test_gap_conflict_unknown_version_and_stale_fencing_quarantine() -> None:
    store = InMemoryMissionStore()
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = __import__("asyncio").run(
        runtime.create(
            mission_request_for_prompt(
                "研究 SOL 当前市场状态",
                actor="test",
                idempotency_key="quarantine-cases",
            )
        )
    )
    created = __import__("asyncio").run(store.events(mission.mission_id))[0]

    gap = make_mission_event(
        event_id="mevt_gap",
        event_type="context.compiled",
        mission_id=mission.mission_id,
        sequence=3,
        actor="runtime",
        payload={},
    )
    assert reduce_mission_events([created, gap]).replay_status == "quarantined"

    conflicting = created.model_dump(mode="python")
    conflicting["event_id"] = "mevt_conflict"
    conflicting["payload"] = {
        "projection": conflicting["payload"]["projection"] | {"objective": "changed"}
    }
    conflicting["payload_hash"] = mission_content_hash(conflicting["payload"])
    assert reduce_mission_events([created, conflicting]).replay_status == "quarantined"

    unknown = created.model_dump(mode="python") | {"reducer_version": 99}
    assert reduce_mission_events([unknown]).replay_status == "quarantined"

    claim = make_mission_event(
        event_id="mevt_claim",
        event_type="mission.lease_claimed",
        mission_id=mission.mission_id,
        sequence=2,
        actor="worker:new",
        payload={"lease_seconds": 10},
        fencing_token=2,
    )
    stale = make_mission_event(
        event_id="mevt_stale",
        event_type="mission.lease_heartbeat",
        mission_id=mission.mission_id,
        sequence=3,
        actor="worker:old",
        payload={"lease_seconds": 10},
        fencing_token=1,
    )
    assert reduce_mission_events([created, claim, stale]).replay_status == "quarantined"

    legacy = MissionEventV1(sequence=1, event_type="mission_created", payload={})
    legacy_snapshot = reduce_mission_events([legacy])
    assert legacy_snapshot.replay_status == MissionReplayStatus.LEGACY_NON_REPLAYABLE
