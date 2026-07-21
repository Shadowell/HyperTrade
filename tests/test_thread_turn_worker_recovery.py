from __future__ import annotations

import asyncio

import pytest
from hypertrade.runtime.adapters.foundation import (
    FoundationExecutor,
    FoundationPlanner,
    ReadOnlyCapabilityPolicy,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.thread_store import InMemoryThreadStore
from hypertrade.runtime.application.entrypoint import mission_request_for_prompt
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.application.thread_context import compile_thread_context
from hypertrade.runtime.application.thread_service import ThreadTurnService


@pytest.mark.anyio
async def test_committed_turn_resumes_after_process_loss_without_duplicate_delivery() -> None:
    thread_store = InMemoryThreadStore()
    mission_store = InMemoryMissionStore()
    runtime = MissionRuntime(
        mission_store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    snapshot = await thread_store.create_thread(
        tenant_id="default",
        owner="operator",
        title="Recovery",
        retention="durable",
    )
    assert snapshot.thread is not None
    thread_id = snapshot.thread.thread_id
    _, turn, _ = await thread_store.start_turn(
        thread_id,
        client_message_id="message-recovery",
        text="Inspect the current market research objective",
        actor="operator",
    )
    snapshot = await thread_store.append(
        thread_id,
        "turn.contextualization_started",
        actor="thread_runtime",
        payload={"turn_id": turn.turn_id},
    )
    context = compile_thread_context(snapshot, turn.turn_id)
    snapshot = await thread_store.append(
        thread_id,
        "turn.context_resolved",
        actor="thread_runtime",
        payload={
            "turn_id": turn.turn_id,
            "resolved_context": context.model_dump(mode="json"),
        },
    )
    mission = await runtime.create(
        mission_request_for_prompt(
            context.normalized_objective,
            actor="canonical_thread",
            idempotency_key=f"thread:{thread_id}:turn:{turn.turn_id}",
        )
    )
    await thread_store.append(
        thread_id,
        "turn.started",
        actor="thread_runtime",
        payload={"turn_id": turn.turn_id, "mission_id": mission.mission_id},
    )
    await runtime.run(mission.mission_id)

    first_process = ThreadTurnService(
        thread_store,
        mission_store,
        runtime,
        worker_enabled=False,
    )
    recovered_process = ThreadTurnService(
        thread_store,
        mission_store,
        runtime,
        worker_enabled=False,
    )
    await asyncio.gather(
        first_process.execute_turn(thread_id, turn.turn_id),
        recovered_process.execute_turn(thread_id, turn.turn_id),
    )

    recovered = await thread_store.get(thread_id)
    events = await thread_store.events(thread_id, after=0, limit=1_000)
    event_types = [event.event_type for event in events]
    assert recovered.turn(turn.turn_id).status.value == "completed"
    assert event_types.count("tool_call.started") == 1
    assert event_types.count("tool_call.completed") == 1
    assert event_types.count("agent_message.completed") == 1
    assert event_types.count("turn.completed") == 1
    assert len(await mission_store.list(limit=10)) == 1


@pytest.mark.anyio
async def test_new_worker_claim_rejects_stale_fencing_token() -> None:
    store = InMemoryThreadStore()
    snapshot = await store.create_thread(
        tenant_id="default",
        owner="operator",
        title="Fencing",
        retention="durable",
    )
    assert snapshot.thread is not None
    thread_id = snapshot.thread.thread_id
    _, turn, _ = await store.start_turn(
        thread_id,
        client_message_id="message-fencing",
        text="Inspect evidence",
        actor="operator",
    )
    stale_token = await store.claim_turn(thread_id, turn.turn_id, worker_id="worker-old")
    current_token = await store.claim_turn(thread_id, turn.turn_id, worker_id="worker-new")

    with pytest.raises(PermissionError, match="stale canonical Turn worker fencing token"):
        await store.append(
            thread_id,
            "turn.contextualization_started",
            actor="thread_runtime",
            fencing_token=stale_token,
            payload={"turn_id": turn.turn_id},
        )
    updated = await store.append(
        thread_id,
        "turn.contextualization_started",
        actor="thread_runtime",
        fencing_token=current_token,
        payload={"turn_id": turn.turn_id},
    )

    assert updated.turn(turn.turn_id).status.value == "contextualizing"
