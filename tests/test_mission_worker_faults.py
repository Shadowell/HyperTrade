from __future__ import annotations

from pathlib import Path

import pytest
from hypertrade.db import Database
from hypertrade.runtime.adapters.foundation import (
    FoundationExecutor,
    FoundationPlanner,
    ReadOnlyCapabilityPolicy,
)
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.application.entrypoint import mission_request_for_prompt
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.mission_events import (
    MissionSnapshotV2,
    mission_projection_hash,
    reduce_mission_events,
)


@pytest.mark.anyio
async def test_stale_worker_event_quarantines_sql_mission(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'stale-worker.db'}"
    Database(database_url).create_all()
    store = SqlAlchemyMissionStore(database_url)
    try:
        mission = await store.create(
            mission_request_for_prompt(
                "研究 BTC 当前市场状态",
                actor="test",
                idempotency_key="stale-worker",
            )
        )
        first = await store.claim_next("worker-old", lease_seconds=10)
        assert first is not None
        await store.release(mission.mission_id, "worker-old")
        second = await store.claim_next("worker-new", lease_seconds=10)
        assert second is not None and second.fencing_token > first.fencing_token

        with pytest.raises(PermissionError, match="stale"):
            await store.append_event(
                mission.mission_id,
                "context.compiled",
                actor="worker:old",
                payload={"manifest_hash": "old"},
                fencing_token=first.fencing_token,
            )
        quarantined = await store.get(mission.mission_id)
    finally:
        await store.dispose()

    assert quarantined.replay_status == "quarantined"
    assert "stale" in quarantined.quarantine_reason


@pytest.mark.anyio
async def test_reopen_after_each_boundary_keeps_events_and_single_terminal(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'worker-recovery.db'}"
    Database(database_url).create_all()
    store = SqlAlchemyMissionStore(database_url)
    runtime = MissionRuntime(
        store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = await runtime.create(
        mission_request_for_prompt(
            "研究 ETH 当前市场状态",
            actor="test",
            idempotency_key="worker-recovery",
        )
    )
    await store.dispose()

    reopened = SqlAlchemyMissionStore(database_url)
    runtime = MissionRuntime(
        reopened,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    try:
        completed = await runtime.run(mission.mission_id)
        before = list(await reopened.events(mission.mission_id, limit=1_000))
        replayed = reduce_mission_events(before)
        again = await runtime.run(mission.mission_id)
        after = list(await reopened.events(mission.mission_id, limit=1_000))
        online = MissionSnapshotV2(
            mission=completed,
            plans=tuple(await reopened.plans(mission.mission_id)),
            attempts=tuple(await reopened.attempts(mission.mission_id)),
        )
    finally:
        await reopened.dispose()

    assert again == completed
    assert len(after) == len(before)
    assert sum(
        row.event_type in {"mission.transitioned", "mission_transitioned"}
        and row.payload.get("to") == "completed"
        for row in after
    ) == 1
    assert mission_projection_hash(replayed) == mission_projection_hash(online)
