from __future__ import annotations

import pytest
from hypertrade.runtime.adapters.thread_store import InMemoryThreadStore
from hypertrade.runtime.application.thread_context import compile_thread_context
from hypertrade.runtime.domain.thread_turn import (
    ThreadIdempotencyConflict,
    ThreadProtocolError,
    ThreadSnapshotV1,
    ThreadVersionGap,
    apply_thread_event,
    content_hash,
    make_event,
    projection_hash,
    reduce_thread_events,
)


@pytest.mark.anyio
async def test_thread_events_replay_to_the_online_projection_hash() -> None:
    store = InMemoryThreadStore()
    snapshot = await store.create_thread(
        tenant_id="tenant-a",
        owner="operator",
        title="Research",
        retention="durable",
    )
    thread_id = snapshot.thread.thread_id if snapshot.thread else ""
    snapshot, turn, created = await store.start_turn(
        thread_id,
        client_message_id="msg-1",
        text="比较 momentum_breakout_v1 和 mean_reversion_v1",
        actor="operator",
    )
    assert created is True
    snapshot = await store.append(
        thread_id,
        "turn.contextualization_started",
        actor="runtime",
        payload={"turn_id": turn.turn_id},
    )
    snapshot = await store.append(
        thread_id,
        "turn.context_resolved",
        actor="runtime",
        payload={
            "turn_id": turn.turn_id,
            "resolved_context": {"strategy_refs": ["momentum_breakout_v1", "mean_reversion_v1"]},
        },
    )
    snapshot = await store.append(
        thread_id,
        "turn.started",
        actor="runtime",
        payload={"turn_id": turn.turn_id, "mission_id": "mis-1"},
    )
    snapshot = await store.append(
        thread_id,
        "evidence_ready.completed",
        actor="runtime",
        payload={
            "turn_id": turn.turn_id,
            "item_id": "evidence-1",
            "content": {"source_refs": ["bitpro:test"]},
        },
    )
    snapshot = await store.append(
        thread_id,
        "agent_message.completed",
        actor="runtime",
        payload={
            "turn_id": turn.turn_id,
            "item_id": "answer-1",
            "content": {"text": "mean_reversion_v1 回撤较低。"},
        },
    )
    snapshot = await store.append(
        thread_id,
        "turn.completed",
        actor="runtime",
        payload={"turn_id": turn.turn_id},
    )

    replayed = reduce_thread_events(list(await store.events(thread_id, after=0, limit=1_000)))

    assert projection_hash(replayed) == projection_hash(snapshot)
    assert replayed.turn(turn.turn_id).status.value == "completed"
    assert replayed.thread and replayed.thread.active_turn_id == ""


@pytest.mark.anyio
async def test_client_message_id_is_content_bound_and_replay_safe() -> None:
    store = InMemoryThreadStore()
    created = await store.create_thread(
        tenant_id="default",
        owner="operator",
        title="Replay",
        retention="ephemeral",
    )
    assert created.thread is not None
    first, turn, was_created = await store.start_turn(
        created.thread.thread_id,
        client_message_id="same-id",
        text="看下 LAB 的价格",
        actor="operator",
    )
    replay, replay_turn, replay_created = await store.start_turn(
        created.thread.thread_id,
        client_message_id="same-id",
        text="看下 LAB 的价格",
        actor="operator",
    )

    assert was_created is True
    assert replay_created is False
    assert replay_turn.turn_id == turn.turn_id
    assert projection_hash(replay) == projection_hash(first)
    with pytest.raises(ThreadIdempotencyConflict):
        await store.start_turn(
            created.thread.thread_id,
            client_message_id="same-id",
            text="换成 ETH",
            actor="operator",
        )


@pytest.mark.anyio
async def test_user_item_redacts_common_credentials_before_event_persistence() -> None:
    store = InMemoryThreadStore()
    snapshot = await store.create_thread(
        tenant_id="default",
        owner="operator",
        title="Redaction",
        retention="durable",
    )
    assert snapshot.thread is not None
    snapshot, turn, _ = await store.start_turn(
        snapshot.thread.thread_id,
        client_message_id="secret-message",
        text="检查 api_key=super-secret 和 Bearer live-token",
        actor="operator",
    )

    persisted = str(snapshot.item(turn.input_item_id).content["text"])
    assert "super-secret" not in persisted
    assert "live-token" not in persisted
    assert persisted.count("[REDACTED]") == 2


def test_reducer_rejects_version_gaps_and_terminal_reentry() -> None:
    created = make_event(
        event_id="event-1",
        event_type="thread.created",
        thread_id="thread-1",
        version=1,
        actor="operator",
        payload={"owner": "operator", "title": "Test", "retention": "durable"},
    )
    snapshot = apply_thread_event(ThreadSnapshotV1(), created)
    gap = make_event(
        event_id="event-3",
        event_type="turn.accepted",
        thread_id="thread-1",
        version=3,
        actor="operator",
        payload={
            "turn_id": "turn-1",
            "item_id": "item-1",
            "client_message_id": "message-1",
            "request_hash": content_hash({"text": "hello"}),
            "text": "hello",
        },
    )
    with pytest.raises(ThreadVersionGap):
        apply_thread_event(snapshot, gap)


@pytest.mark.anyio
async def test_terminal_turn_cannot_receive_a_second_terminal_event() -> None:
    store = InMemoryThreadStore()
    snapshot = await store.create_thread(
        tenant_id="default",
        owner="operator",
        title="Terminal",
        retention="durable",
    )
    assert snapshot.thread is not None
    thread_id = snapshot.thread.thread_id
    _, turn, _ = await store.start_turn(
        thread_id,
        client_message_id="terminal-1",
        text="hello",
        actor="operator",
    )
    await store.append(
        thread_id,
        "turn.contextualization_started",
        actor="runtime",
        payload={"turn_id": turn.turn_id},
    )
    await store.append(
        thread_id,
        "turn.failed",
        actor="runtime",
        payload={"turn_id": turn.turn_id, "code": "test"},
    )
    with pytest.raises(ThreadProtocolError):
        await store.append(
            thread_id,
            "turn.failed",
            actor="runtime",
            payload={"turn_id": turn.turn_id, "code": "duplicate"},
        )


@pytest.mark.anyio
async def test_server_items_resolve_latter_strategy_without_client_history() -> None:
    store = InMemoryThreadStore()
    snapshot = await store.create_thread(
        tenant_id="default",
        owner="operator",
        title="Context",
        retention="durable",
    )
    assert snapshot.thread is not None
    thread_id = snapshot.thread.thread_id
    _, first, _ = await store.start_turn(
        thread_id,
        client_message_id="message-1",
        text="比较 momentum_breakout_v1 和 mean_reversion_v1 哪个收益更高？",
        actor="operator",
    )
    await store.append(
        thread_id,
        "turn.contextualization_started",
        actor="runtime",
        payload={"turn_id": first.turn_id},
    )
    context = compile_thread_context(await store.get(thread_id), first.turn_id)
    await store.append(
        thread_id,
        "turn.context_resolved",
        actor="runtime",
        payload={
            "turn_id": first.turn_id,
            "resolved_context": context.model_dump(mode="json"),
        },
    )
    await store.append(
        thread_id,
        "turn.failed",
        actor="runtime",
        payload={"turn_id": first.turn_id, "code": "test_terminal"},
    )
    snapshot, second, _ = await store.start_turn(
        thread_id,
        client_message_id="message-2",
        text="后者最大回撤多少？",
        actor="operator",
    )

    resolved = compile_thread_context(snapshot, second.turn_id)

    assert resolved.resolved_subject == "mean_reversion_v1"
    assert resolved.subject_kind == "strategy"
    assert resolved.normalized_objective.startswith("上文指代对象为 mean_reversion_v1")
