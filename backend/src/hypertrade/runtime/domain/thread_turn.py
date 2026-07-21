"""Canonical server-owned Thread/Turn/Item event model.

The event log is the source of truth. Projections are derived by the reducer and
contain no provider secrets, raw tool payloads, or private reasoning.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import Field, model_validator

from hypertrade.runtime.domain.models import StrictModel

SCHEMA_VERSION = 1
REDUCER_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(UTC)


def content_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return sha256(encoded).hexdigest()


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    QUARANTINED = "quarantined"


class TurnStatus(StrEnum):
    ACCEPTED = "accepted"
    CONTEXTUALIZING = "contextualizing"
    RUNNING = "running"
    STREAMING = "streaming"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_TURN_STATUSES = {
    TurnStatus.COMPLETED,
    TurnStatus.FAILED,
    TurnStatus.CANCELLED,
    TurnStatus.EXPIRED,
}


class ItemType(StrEnum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TOOL_CALL = "tool_call"
    EVIDENCE_READY = "evidence_ready"
    INPUT_REQUEST = "input_request"
    APPROVAL_REQUEST = "approval_request"


class ThreadEventV1(StrictModel):
    event_id: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=3, max_length=96)
    aggregate_type: str = "thread"
    aggregate_id: str = Field(min_length=1, max_length=64)
    aggregate_version: int = Field(ge=1)
    thread_sequence: int = Field(ge=1)
    schema_version: int = SCHEMA_VERSION
    reducer_version: int = REDUCER_VERSION
    tenant_id: str = Field(default="default", min_length=1, max_length=128)
    idempotency_key: str = Field(default="", max_length=160)
    causation_id: str = Field(default="", max_length=64)
    correlation_id: str = Field(default="", max_length=64)
    actor: str = Field(default="runtime", min_length=1, max_length=128)
    policy_snapshot_hash: str = Field(default="", max_length=64)
    payload_hash: str = Field(min_length=64, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_envelope(self) -> ThreadEventV1:
        if self.aggregate_version != self.thread_sequence:
            raise ValueError("thread aggregate version must equal thread sequence")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported thread event schema version")
        if self.reducer_version != REDUCER_VERSION:
            raise ValueError("unsupported thread reducer version")
        if content_hash(self.payload) != self.payload_hash:
            raise ValueError("thread event payload hash mismatch")
        return self


class ThreadProjectionV1(StrictModel):
    thread_id: str
    tenant_id: str
    owner: str
    title: str
    status: ThreadStatus = ThreadStatus.ACTIVE
    retention: str = "durable"
    active_turn_id: str = ""
    version: int = 0
    event_cursor: int = 0
    quarantine_reason: str = ""
    created_at: datetime
    updated_at: datetime


class TurnProjectionV1(StrictModel):
    turn_id: str
    thread_id: str
    status: TurnStatus
    client_message_id: str
    request_hash: str
    input_item_id: str
    response_item_id: str = ""
    mission_id: str = ""
    resolved_context: dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: datetime
    updated_at: datetime


class ItemProjectionV1(StrictModel):
    item_id: str
    thread_id: str
    turn_id: str
    item_type: ItemType
    status: str
    sequence: int
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ThreadSnapshotV1(StrictModel):
    thread: ThreadProjectionV1 | None = None
    turns: tuple[TurnProjectionV1, ...] = ()
    items: tuple[ItemProjectionV1, ...] = ()

    def turn(self, turn_id: str) -> TurnProjectionV1:
        for row in self.turns:
            if row.turn_id == turn_id:
                return row
        raise KeyError(turn_id)

    def item(self, item_id: str) -> ItemProjectionV1:
        for row in self.items:
            if row.item_id == item_id:
                return row
        raise KeyError(item_id)


class ThreadProtocolError(ValueError):
    """A command or event violates the canonical state machine."""


class ThreadVersionGap(ThreadProtocolError):
    """The event stream cannot be reduced because an aggregate version is missing."""


class ThreadIdempotencyConflict(ThreadProtocolError):
    """An idempotency key was reused with different request content."""


def make_event(
    *,
    event_id: str,
    event_type: str,
    thread_id: str,
    version: int,
    payload: dict[str, Any],
    tenant_id: str = "default",
    idempotency_key: str = "",
    causation_id: str = "",
    correlation_id: str = "",
    actor: str = "runtime",
    policy_snapshot_hash: str = "",
    occurred_at: datetime | None = None,
) -> ThreadEventV1:
    happened = occurred_at or utc_now()
    return ThreadEventV1(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=thread_id,
        aggregate_version=version,
        thread_sequence=version,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        causation_id=causation_id,
        correlation_id=correlation_id or thread_id,
        actor=actor,
        policy_snapshot_hash=policy_snapshot_hash,
        payload_hash=content_hash(payload),
        payload=payload,
        occurred_at=happened,
        recorded_at=happened,
    )


def reduce_thread_events(
    events: list[ThreadEventV1] | tuple[ThreadEventV1, ...],
) -> ThreadSnapshotV1:
    snapshot = ThreadSnapshotV1()
    for event in events:
        snapshot = apply_thread_event(snapshot, event)
    return snapshot


def projection_hash(snapshot: ThreadSnapshotV1) -> str:
    return content_hash(snapshot.model_dump(mode="json"))


def apply_thread_event(snapshot: ThreadSnapshotV1, event: ThreadEventV1) -> ThreadSnapshotV1:
    thread = snapshot.thread
    expected = 1 if thread is None else thread.version + 1
    if event.aggregate_version != expected:
        raise ThreadVersionGap(
            f"thread event version gap: expected {expected}, got {event.aggregate_version}"
        )
    if thread is not None and event.aggregate_id != thread.thread_id:
        raise ThreadProtocolError("event aggregate does not match thread")

    turns = {row.turn_id: row for row in snapshot.turns}
    items = {row.item_id: row for row in snapshot.items}
    payload = event.payload
    at = event.occurred_at

    if event.event_type == "thread.created":
        if thread is not None:
            raise ThreadProtocolError("thread already exists")
        thread = ThreadProjectionV1(
            thread_id=event.aggregate_id,
            tenant_id=event.tenant_id,
            owner=str(payload["owner"]),
            title=str(payload.get("title") or "Agent Thread"),
            retention=str(payload.get("retention") or "durable"),
            version=event.aggregate_version,
            event_cursor=event.thread_sequence,
            created_at=at,
            updated_at=at,
        )
    else:
        if thread is None:
            raise ThreadProtocolError("first event must create the thread")
        if thread.status == ThreadStatus.QUARANTINED:
            raise ThreadProtocolError("quarantined thread is read-only")
        thread = _apply_existing_thread_event(thread, turns, items, event)

    return ThreadSnapshotV1(
        thread=thread,
        turns=tuple(sorted(turns.values(), key=lambda row: (row.created_at, row.turn_id))),
        items=tuple(sorted(items.values(), key=lambda row: (row.sequence, row.item_id))),
    )


def _apply_existing_thread_event(
    thread: ThreadProjectionV1,
    turns: dict[str, TurnProjectionV1],
    items: dict[str, ItemProjectionV1],
    event: ThreadEventV1,
) -> ThreadProjectionV1:
    payload = event.payload
    event_type = event.event_type
    at = event.occurred_at
    active_turn_id = thread.active_turn_id

    if event_type == "thread.archived":
        if active_turn_id:
            raise ThreadProtocolError("cannot archive a thread with an active turn")
        return thread.model_copy(
            update={
                "status": ThreadStatus.ARCHIVED,
                "version": event.aggregate_version,
                "event_cursor": event.thread_sequence,
                "updated_at": at,
            }
        )

    turn_id = str(payload.get("turn_id") or "")
    if not turn_id:
        raise ThreadProtocolError(f"{event_type} requires turn_id")

    if event_type == "turn.accepted":
        if thread.status != ThreadStatus.ACTIVE:
            raise ThreadProtocolError("thread is not active")
        if active_turn_id:
            raise ThreadProtocolError("thread already has an active turn")
        if turn_id in turns:
            raise ThreadProtocolError("turn already exists")
        item_id = str(payload["item_id"])
        turns[turn_id] = TurnProjectionV1(
            turn_id=turn_id,
            thread_id=thread.thread_id,
            status=TurnStatus.ACCEPTED,
            client_message_id=str(payload["client_message_id"]),
            request_hash=str(payload["request_hash"]),
            input_item_id=item_id,
            created_at=at,
            updated_at=at,
        )
        items[item_id] = ItemProjectionV1(
            item_id=item_id,
            thread_id=thread.thread_id,
            turn_id=turn_id,
            item_type=ItemType.USER_MESSAGE,
            status="completed",
            sequence=event.thread_sequence,
            content={"text": str(payload["text"])},
            created_at=at,
            updated_at=at,
        )
        active_turn_id = turn_id
    else:
        try:
            turn = turns[turn_id]
        except KeyError as exc:
            raise ThreadProtocolError(f"unknown turn: {turn_id}") from exc
        if turn.status in TERMINAL_TURN_STATUSES:
            raise ThreadProtocolError("terminal turn cannot receive new events")
        turns[turn_id], active_turn_id = _apply_turn_event(
            turn,
            items,
            event,
            active_turn_id=active_turn_id,
        )

    return thread.model_copy(
        update={
            "active_turn_id": active_turn_id,
            "version": event.aggregate_version,
            "event_cursor": event.thread_sequence,
            "updated_at": at,
        }
    )


def _apply_turn_event(
    turn: TurnProjectionV1,
    items: dict[str, ItemProjectionV1],
    event: ThreadEventV1,
    *,
    active_turn_id: str,
) -> tuple[TurnProjectionV1, str]:
    payload = event.payload
    event_type = event.event_type
    at = event.occurred_at
    updates: dict[str, Any] = {"version": turn.version + 1, "updated_at": at}

    if event_type == "turn.contextualization_started":
        _require_turn_status(turn, {TurnStatus.ACCEPTED})
        updates["status"] = TurnStatus.CONTEXTUALIZING
    elif event_type == "turn.context_resolved":
        _require_turn_status(turn, {TurnStatus.CONTEXTUALIZING})
        updates["resolved_context"] = dict(payload.get("resolved_context") or {})
    elif event_type == "turn.input_requested":
        _require_turn_status(turn, {TurnStatus.CONTEXTUALIZING, TurnStatus.RUNNING})
        item_id = str(payload["item_id"])
        items[item_id] = _new_item(event, ItemType.INPUT_REQUEST, "completed")
        updates["status"] = TurnStatus.WAITING_INPUT
    elif event_type == "turn.approval_requested":
        _require_turn_status(turn, {TurnStatus.RUNNING})
        item_id = str(payload["item_id"])
        items[item_id] = _new_item(event, ItemType.APPROVAL_REQUEST, "completed")
        updates["status"] = TurnStatus.WAITING_APPROVAL
    elif event_type == "turn.started":
        _require_turn_status(turn, {TurnStatus.CONTEXTUALIZING})
        updates.update({"status": TurnStatus.RUNNING, "mission_id": str(payload["mission_id"])})
    elif event_type in {"tool_call.started", "tool_call.completed"}:
        _require_turn_status(turn, {TurnStatus.RUNNING, TurnStatus.STREAMING})
        item_id = str(payload["item_id"])
        existing = items.get(item_id)
        if event_type == "tool_call.started":
            if existing is not None:
                raise ThreadProtocolError("tool call item already exists")
            items[item_id] = _new_item(event, ItemType.TOOL_CALL, "started")
        else:
            if existing is None or existing.item_type != ItemType.TOOL_CALL:
                raise ThreadProtocolError("tool completion requires a started item")
            items[item_id] = existing.model_copy(
                update={
                    "status": "completed",
                    "content": dict(payload.get("content") or existing.content),
                    "updated_at": at,
                }
            )
    elif event_type == "evidence_ready.completed":
        _require_turn_status(turn, {TurnStatus.RUNNING, TurnStatus.STREAMING})
        item_id = str(payload["item_id"])
        items[item_id] = _new_item(event, ItemType.EVIDENCE_READY, "completed")
        updates["status"] = TurnStatus.STREAMING
    elif event_type in {"agent_message.delta", "agent_message.completed"}:
        _require_turn_status(turn, {TurnStatus.RUNNING, TurnStatus.STREAMING})
        item_id = str(payload["item_id"])
        existing = items.get(item_id)
        if existing is None:
            items[item_id] = _new_item(
                event,
                ItemType.AGENT_MESSAGE,
                "completed" if event_type.endswith("completed") else "streaming",
            )
        else:
            content = dict(existing.content)
            content.update(dict(payload.get("content") or {}))
            items[item_id] = existing.model_copy(
                update={
                    "status": "completed" if event_type.endswith("completed") else "streaming",
                    "content": content,
                    "updated_at": at,
                }
            )
        updates.update({"status": TurnStatus.STREAMING, "response_item_id": item_id})
    elif event_type in {"turn.completed", "turn.failed", "turn.cancelled", "turn.expired"}:
        target = {
            "turn.completed": TurnStatus.COMPLETED,
            "turn.failed": TurnStatus.FAILED,
            "turn.cancelled": TurnStatus.CANCELLED,
            "turn.expired": TurnStatus.EXPIRED,
        }[event_type]
        if target == TurnStatus.COMPLETED:
            response_id = turn.response_item_id
            if not response_id or items[response_id].status != "completed":
                raise ThreadProtocolError("completed turn requires a completed agent message")
        updates["status"] = target
        active_turn_id = ""
    else:
        raise ThreadProtocolError(f"unsupported thread event: {event_type}")

    return turn.model_copy(update=updates), active_turn_id


def _new_item(event: ThreadEventV1, item_type: ItemType, status: str) -> ItemProjectionV1:
    return ItemProjectionV1(
        item_id=str(event.payload["item_id"]),
        thread_id=event.aggregate_id,
        turn_id=str(event.payload["turn_id"]),
        item_type=item_type,
        status=status,
        sequence=event.thread_sequence,
        content=dict(event.payload.get("content") or {}),
        created_at=event.occurred_at,
        updated_at=event.occurred_at,
    )


def _require_turn_status(turn: TurnProjectionV1, allowed: set[TurnStatus]) -> None:
    if turn.status not in allowed:
        expected = ", ".join(sorted(status.value for status in allowed))
        raise ThreadProtocolError(
            f"turn {turn.turn_id} is {turn.status.value}; expected one of {expected}"
        )
