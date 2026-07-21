"""In-memory and SQL adapters for the canonical Thread event model."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hypertrade.db import (
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
    AgentThreadLease,
    AgentTurn,
    new_id,
)
from hypertrade.runtime.adapters.sql_store import async_database_url
from hypertrade.runtime.domain.thread_turn import (
    ItemProjectionV1,
    ThreadEventV1,
    ThreadIdempotencyConflict,
    ThreadProjectionV1,
    ThreadSnapshotV1,
    ThreadStatus,
    TurnProjectionV1,
    TurnStatus,
    apply_thread_event,
    content_hash,
    make_event,
    projection_hash,
)


class InMemoryThreadStore:
    """Deterministic adapter for property, reducer, and API tests."""

    def __init__(self) -> None:
        self._events: dict[str, list[ThreadEventV1]] = {}
        self._snapshots: dict[str, ThreadSnapshotV1] = {}
        self._event_idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._fencing: dict[str, tuple[str, int]] = {}

    async def dispose(self) -> None:
        return None

    async def create_thread(
        self,
        *,
        tenant_id: str,
        owner: str,
        title: str,
        retention: str,
    ) -> ThreadSnapshotV1:
        thread_id = new_id("thr")
        event = make_event(
            event_id=new_id("thevt"),
            event_type="thread.created",
            thread_id=thread_id,
            version=1,
            tenant_id=tenant_id,
            actor=owner,
            payload={"owner": owner, "title": title, "retention": retention},
        )
        snapshot = apply_thread_event(ThreadSnapshotV1(), event)
        self._events[thread_id] = [event]
        self._snapshots[thread_id] = snapshot
        return snapshot

    async def get(self, thread_id: str) -> ThreadSnapshotV1:
        try:
            return self._snapshots[thread_id]
        except KeyError as exc:
            raise KeyError(thread_id) from exc

    async def start_turn(
        self,
        thread_id: str,
        *,
        client_message_id: str,
        text: str,
        actor: str,
    ) -> tuple[ThreadSnapshotV1, TurnProjectionV1, bool]:
        snapshot = await self.get(thread_id)
        request_hash = content_hash({"text": text})
        for turn in snapshot.turns:
            if turn.client_message_id != client_message_id:
                continue
            if turn.request_hash != request_hash:
                raise ThreadIdempotencyConflict(
                    "client_message_id is bound to different request content"
                )
            return snapshot, turn, False
        turn_id = new_id("trn")
        snapshot = await self.append(
            thread_id,
            "turn.accepted",
            actor=actor,
            idempotency_key=f"turn:{client_message_id}",
            payload={
                "turn_id": turn_id,
                "item_id": new_id("itm"),
                "client_message_id": client_message_id,
                "request_hash": request_hash,
                "text": _redact_user_text(text),
            },
        )
        return snapshot, snapshot.turn(turn_id), True

    async def claim_turn(self, thread_id: str, turn_id: str, *, worker_id: str) -> int:
        snapshot = await self.get(thread_id)
        snapshot.turn(turn_id)
        token = self._fencing.get(thread_id, ("", 0))[1] + 1
        self._fencing[thread_id] = (worker_id, token)
        return token

    async def append(
        self,
        thread_id: str,
        event_type: str,
        *,
        payload: dict[str, object],
        actor: str,
        idempotency_key: str = "",
        causation_id: str = "",
        policy_snapshot_hash: str = "",
        fencing_token: int = 0,
    ) -> ThreadSnapshotV1:
        snapshot = await self.get(thread_id)
        if fencing_token:
            current = self._fencing.get(thread_id)
            if current is None or current[1] != fencing_token:
                raise PermissionError("stale canonical Turn worker fencing token")
        if idempotency_key:
            bound = self._event_idempotency.get((thread_id, idempotency_key))
            candidate_hash = content_hash(payload)
            if bound is not None:
                if bound != (event_type, candidate_hash):
                    raise ThreadIdempotencyConflict(
                        "thread event idempotency key is bound to different content"
                    )
                return snapshot
        assert snapshot.thread is not None
        event = make_event(
            event_id=new_id("thevt"),
            event_type=event_type,
            thread_id=thread_id,
            version=snapshot.thread.version + 1,
            tenant_id=snapshot.thread.tenant_id,
            actor=actor,
            idempotency_key=idempotency_key,
            causation_id=causation_id,
            policy_snapshot_hash=policy_snapshot_hash,
            payload=payload,
        )
        updated = apply_thread_event(snapshot, event)
        self._events[thread_id].append(event)
        self._snapshots[thread_id] = updated
        if idempotency_key:
            self._event_idempotency[(thread_id, idempotency_key)] = (
                event_type,
                event.payload_hash,
            )
        return updated

    async def events(
        self,
        thread_id: str,
        *,
        after: int = 0,
        limit: int = 500,
    ) -> Sequence[ThreadEventV1]:
        await self.get(thread_id)
        return [event for event in self._events[thread_id] if event.thread_sequence > after][
            : max(1, min(limit, 1_000))
        ]


class SqlAlchemyThreadStore:
    """Transactional SQL adapter; events and reducer projections commit together."""

    def __init__(self, database_url: str, *, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_async_engine(
            async_database_url(database_url), pool_pre_ping=True
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def create_thread(
        self,
        *,
        tenant_id: str,
        owner: str,
        title: str,
        retention: str,
    ) -> ThreadSnapshotV1:
        thread_id = new_id("thr")
        event = make_event(
            event_id=new_id("thevt"),
            event_type="thread.created",
            thread_id=thread_id,
            version=1,
            tenant_id=tenant_id,
            actor=owner,
            payload={"owner": owner, "title": title, "retention": retention},
        )
        snapshot = apply_thread_event(ThreadSnapshotV1(), event)
        async with self.sessions.begin() as session:
            session.add(_event_row(event))
            await _persist_snapshot(session, snapshot)
        return snapshot

    async def get(self, thread_id: str) -> ThreadSnapshotV1:
        async with self.sessions() as session:
            return await _load_snapshot(session, thread_id)

    async def start_turn(
        self,
        thread_id: str,
        *,
        client_message_id: str,
        text: str,
        actor: str,
    ) -> tuple[ThreadSnapshotV1, TurnProjectionV1, bool]:
        request_hash = content_hash({"text": text})
        async with self.sessions.begin() as session:
            await _locked_thread(session, thread_id)
            existing = await session.scalar(
                select(AgentTurn)
                .where(AgentTurn.thread_id == thread_id)
                .where(AgentTurn.client_message_id == client_message_id)
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise ThreadIdempotencyConflict(
                        "client_message_id is bound to different request content"
                    )
                snapshot = await _load_snapshot(session, thread_id)
                return snapshot, snapshot.turn(existing.id), False
            snapshot = await _load_snapshot(session, thread_id)
            assert snapshot.thread is not None
            turn_id = new_id("trn")
            event = make_event(
                event_id=new_id("thevt"),
                event_type="turn.accepted",
                thread_id=thread_id,
                version=snapshot.thread.version + 1,
                tenant_id=snapshot.thread.tenant_id,
                actor=actor,
                idempotency_key=f"turn:{client_message_id}",
                payload={
                    "turn_id": turn_id,
                    "item_id": new_id("itm"),
                    "client_message_id": client_message_id,
                    "request_hash": request_hash,
                    "text": _redact_user_text(text),
                },
            )
            updated = apply_thread_event(snapshot, event)
            session.add(_event_row(event))
            await _persist_snapshot(session, updated)
            return updated, updated.turn(turn_id), True

    async def claim_turn(self, thread_id: str, turn_id: str, *, worker_id: str) -> int:
        async with self.sessions.begin() as session:
            await _locked_thread(session, thread_id)
            turn = await session.get(AgentTurn, turn_id)
            if turn is None or turn.thread_id != thread_id:
                raise KeyError(turn_id)
            lease = await session.get(AgentThreadLease, thread_id)
            if lease is None:
                lease = AgentThreadLease(
                    thread_id=thread_id,
                    worker_id=worker_id,
                    fencing_token=1,
                )
                session.add(lease)
            else:
                lease.worker_id = worker_id
                lease.fencing_token += 1
            await session.flush()
            return lease.fencing_token

    async def append(
        self,
        thread_id: str,
        event_type: str,
        *,
        payload: dict[str, object],
        actor: str,
        idempotency_key: str = "",
        causation_id: str = "",
        policy_snapshot_hash: str = "",
        fencing_token: int = 0,
    ) -> ThreadSnapshotV1:
        async with self.sessions.begin() as session:
            await _locked_thread(session, thread_id)
            if fencing_token:
                lease = await session.get(AgentThreadLease, thread_id)
                if lease is None or lease.fencing_token != fencing_token:
                    raise PermissionError("stale canonical Turn worker fencing token")
            if idempotency_key:
                existing = await session.scalar(
                    select(AgentThreadEvent)
                    .where(AgentThreadEvent.thread_id == thread_id)
                    .where(AgentThreadEvent.idempotency_key == idempotency_key)
                )
                if existing is not None:
                    if existing.event_type != event_type or existing.payload_hash != content_hash(
                        payload
                    ):
                        raise ThreadIdempotencyConflict(
                            "thread event idempotency key is bound to different content"
                        )
                    return await _load_snapshot(session, thread_id)
            snapshot = await _load_snapshot(session, thread_id)
            assert snapshot.thread is not None
            event = make_event(
                event_id=new_id("thevt"),
                event_type=event_type,
                thread_id=thread_id,
                version=snapshot.thread.version + 1,
                tenant_id=snapshot.thread.tenant_id,
                actor=actor,
                idempotency_key=idempotency_key,
                causation_id=causation_id,
                policy_snapshot_hash=policy_snapshot_hash,
                payload=payload,
            )
            updated = apply_thread_event(snapshot, event)
            session.add(_event_row(event))
            await _persist_snapshot(session, updated)
            return updated

    async def events(
        self,
        thread_id: str,
        *,
        after: int = 0,
        limit: int = 500,
    ) -> Sequence[ThreadEventV1]:
        async with self.sessions() as session:
            if await session.get(AgentThread, thread_id) is None:
                raise KeyError(thread_id)
            rows = (
                await session.scalars(
                    select(AgentThreadEvent)
                    .where(AgentThreadEvent.thread_id == thread_id)
                    .where(AgentThreadEvent.thread_sequence > after)
                    .order_by(AgentThreadEvent.thread_sequence)
                    .limit(max(1, min(limit, 1_000)))
                )
            ).all()
            return [_event_projection(row) for row in rows]


async def _locked_thread(session: AsyncSession, thread_id: str) -> AgentThread:
    row = await session.scalar(
        select(AgentThread).where(AgentThread.id == thread_id).with_for_update()
    )
    if row is None:
        raise KeyError(thread_id)
    return row


async def _load_snapshot(session: AsyncSession, thread_id: str) -> ThreadSnapshotV1:
    thread = await session.get(AgentThread, thread_id)
    if thread is None:
        raise KeyError(thread_id)
    turns = (
        await session.scalars(
            select(AgentTurn)
            .where(AgentTurn.thread_id == thread_id)
            .order_by(AgentTurn.created_at, AgentTurn.id)
        )
    ).all()
    items = (
        await session.scalars(
            select(AgentThreadItem)
            .where(AgentThreadItem.thread_id == thread_id)
            .order_by(AgentThreadItem.sequence, AgentThreadItem.id)
        )
    ).all()
    return ThreadSnapshotV1(
        thread=_thread_projection(thread),
        turns=tuple(_turn_projection(row) for row in turns),
        items=tuple(_item_projection(row) for row in items),
    )


async def _persist_snapshot(session: AsyncSession, snapshot: ThreadSnapshotV1) -> None:
    thread = snapshot.thread
    if thread is None:
        raise ValueError("cannot persist an empty thread snapshot")
    row = await session.get(AgentThread, thread.thread_id)
    values: dict[str, Any] = {
        "tenant_id": thread.tenant_id,
        "owner": thread.owner,
        "title": thread.title,
        "status": thread.status.value,
        "retention": thread.retention,
        "active_turn_id": thread.active_turn_id,
        "version": thread.version,
        "event_cursor": thread.event_cursor,
        "projection_hash": projection_hash(snapshot),
        "quarantine_reason": thread.quarantine_reason,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
    }
    if row is None:
        row = AgentThread(id=thread.thread_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    for turn in snapshot.turns:
        turn_row = await session.get(AgentTurn, turn.turn_id)
        turn_values: dict[str, Any] = {
            "thread_id": turn.thread_id,
            "status": turn.status.value,
            "client_message_id": turn.client_message_id,
            "request_hash": turn.request_hash,
            "input_item_id": turn.input_item_id,
            "response_item_id": turn.response_item_id,
            "mission_id": turn.mission_id,
            "resolved_context_json": turn.resolved_context,
            "version": turn.version,
            "created_at": turn.created_at,
            "updated_at": turn.updated_at,
        }
        if turn_row is None:
            session.add(AgentTurn(id=turn.turn_id, **turn_values))
        else:
            for key, value in turn_values.items():
                setattr(turn_row, key, value)
    for item in snapshot.items:
        item_row = await session.get(AgentThreadItem, item.item_id)
        item_values: dict[str, Any] = {
            "thread_id": item.thread_id,
            "turn_id": item.turn_id,
            "item_type": item.item_type.value,
            "status": item.status,
            "sequence": item.sequence,
            "content_json": item.content,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        if item_row is None:
            session.add(AgentThreadItem(id=item.item_id, **item_values))
        else:
            for key, value in item_values.items():
                setattr(item_row, key, value)
    await session.flush()


def _event_row(event: ThreadEventV1) -> AgentThreadEvent:
    return AgentThreadEvent(
        id=event.event_id,
        thread_id=event.aggregate_id,
        event_type=event.event_type,
        aggregate_type=event.aggregate_type,
        aggregate_version=event.aggregate_version,
        thread_sequence=event.thread_sequence,
        schema_version=event.schema_version,
        reducer_version=event.reducer_version,
        tenant_id=event.tenant_id,
        idempotency_key=event.idempotency_key or None,
        causation_id=event.causation_id,
        correlation_id=event.correlation_id,
        actor=event.actor,
        policy_snapshot_hash=event.policy_snapshot_hash,
        payload_hash=event.payload_hash,
        payload_json=event.payload,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
    )


def _event_projection(row: AgentThreadEvent) -> ThreadEventV1:
    return ThreadEventV1(
        event_id=row.id,
        event_type=row.event_type,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.thread_id,
        aggregate_version=row.aggregate_version,
        thread_sequence=row.thread_sequence,
        schema_version=row.schema_version,
        reducer_version=row.reducer_version,
        tenant_id=row.tenant_id,
        idempotency_key=row.idempotency_key or "",
        causation_id=row.causation_id,
        correlation_id=row.correlation_id,
        actor=row.actor,
        policy_snapshot_hash=row.policy_snapshot_hash,
        payload_hash=row.payload_hash,
        payload=row.payload_json,
        occurred_at=_as_utc(row.occurred_at),
        recorded_at=_as_utc(row.recorded_at),
    )


def _thread_projection(row: AgentThread) -> ThreadProjectionV1:
    return ThreadProjectionV1(
        thread_id=row.id,
        tenant_id=row.tenant_id,
        owner=row.owner,
        title=row.title,
        status=ThreadStatus(row.status),
        retention=row.retention,
        active_turn_id=row.active_turn_id,
        version=row.version,
        event_cursor=row.event_cursor,
        quarantine_reason=row.quarantine_reason,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


def _turn_projection(row: AgentTurn) -> TurnProjectionV1:
    return TurnProjectionV1(
        turn_id=row.id,
        thread_id=row.thread_id,
        status=TurnStatus(row.status),
        client_message_id=row.client_message_id,
        request_hash=row.request_hash,
        input_item_id=row.input_item_id,
        response_item_id=row.response_item_id,
        mission_id=row.mission_id,
        resolved_context=row.resolved_context_json or {},
        version=row.version,
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


def _item_projection(row: AgentThreadItem) -> ItemProjectionV1:
    return ItemProjectionV1(
        item_id=row.id,
        thread_id=row.thread_id,
        turn_id=row.turn_id,
        item_type=row.item_type,
        status=row.status,
        sequence=row.sequence,
        content=row.content_json or {},
        created_at=_as_utc(row.created_at),
        updated_at=_as_utc(row.updated_at),
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _redact_user_text(value: str) -> str:
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        value,
    )
    redacted = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", redacted)
    return re.sub(
        r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]",
        redacted,
        flags=re.DOTALL,
    )
