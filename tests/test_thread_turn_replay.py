from __future__ import annotations

import pytest
from hypertrade.db import Database
from hypertrade.runtime.adapters.thread_store import SqlAlchemyThreadStore
from hypertrade.runtime.domain.thread_turn import projection_hash, reduce_thread_events


@pytest.mark.anyio
async def test_sql_projection_matches_offline_event_replay(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'thread-turn.db'}"
    Database(database_url).create_all()
    store = SqlAlchemyThreadStore(database_url)
    try:
        snapshot = await store.create_thread(
            tenant_id="default",
            owner="operator",
            title="SQL replay",
            retention="durable",
        )
        assert snapshot.thread is not None
        thread_id = snapshot.thread.thread_id
        _, turn, _ = await store.start_turn(
            thread_id,
            client_message_id="message-1",
            text="看下 LAB 的价格",
            actor="operator",
        )
        await store.append(
            thread_id,
            "turn.contextualization_started",
            actor="runtime",
            payload={"turn_id": turn.turn_id},
        )
        online = await store.append(
            thread_id,
            "turn.failed",
            actor="runtime",
            payload={"turn_id": turn.turn_id, "code": "test_failure"},
        )

        events = await store.events(thread_id, after=0, limit=1_000)
        replayed = reduce_thread_events(list(events))

        assert projection_hash(replayed) == projection_hash(online)
        assert projection_hash(await store.get(thread_id)) == projection_hash(online)
    finally:
        await store.dispose()
