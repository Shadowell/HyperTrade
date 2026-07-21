"""FastAPI adapter for the canonical Thread/Turn/Item protocol."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from hypertrade.runtime.application.thread_service import ThreadTurnService
from hypertrade.runtime.domain.thread_turn import (
    TERMINAL_TURN_STATUSES,
    ThreadIdempotencyConflict,
    ThreadProtocolError,
    ThreadSnapshotV1,
)


class ThreadCreatePayload(BaseModel):
    title: str = Field(default="Agent Thread", min_length=1, max_length=200)
    retention: Literal["durable", "ephemeral"] = "durable"


class TurnCreatePayload(BaseModel):
    input: str = Field(min_length=1, max_length=8_000)
    client_message_id: str = Field(min_length=1, max_length=128)


def build_thread_turn_router(
    service: ThreadTurnService,
    require_admin: Callable[[Request], str],
) -> APIRouter:
    router = APIRouter(prefix="/api/agent/v1/threads", tags=["agent-threads"])
    @router.post("")
    async def create_thread(
        payload: ThreadCreatePayload,
        username: str = Depends(require_admin),
    ) -> dict[str, object]:
        snapshot = await service.create_thread(
            owner=username,
            title=payload.title,
            retention=payload.retention,
        )
        return _snapshot_payload(snapshot)

    @router.get("/{thread_id}")
    async def get_thread(
        thread_id: str,
        _: str = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            snapshot = await service.thread_store.get(thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc
        if snapshot.thread and snapshot.thread.active_turn_id:
            service.ensure_scheduled(thread_id, snapshot.thread.active_turn_id)
        return _snapshot_payload(snapshot)

    @router.post("/{thread_id}/turns", status_code=202)
    async def start_turn(
        thread_id: str,
        payload: TurnCreatePayload,
        username: str = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            snapshot, turn, created = await service.start_turn(
                thread_id,
                client_message_id=payload.client_message_id,
                text=payload.input,
                actor=username,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc
        except ThreadIdempotencyConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ThreadProtocolError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "created": created,
            "turn": turn.model_dump(mode="json"),
            "event_cursor": snapshot.thread.event_cursor if snapshot.thread else 0,
        }

    @router.get("/{thread_id}/turns/{turn_id}")
    async def get_turn(
        thread_id: str,
        turn_id: str,
        _: str = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            snapshot = await service.thread_store.get(thread_id)
            turn = snapshot.turn(turn_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread or Turn not found") from exc
        if turn.status not in TERMINAL_TURN_STATUSES:
            service.ensure_scheduled(thread_id, turn_id)
        return _turn_payload(snapshot, turn_id)

    @router.get("/{thread_id}/events")
    async def list_events(
        thread_id: str,
        after: int = 0,
        limit: int = 500,
        _: str = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            events = await service.thread_store.events(thread_id, after=after, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc
        return {
            "events": [event.model_dump(mode="json") for event in events],
            "next_cursor": events[-1].thread_sequence if events else after,
        }

    @router.get("/{thread_id}/events/stream")
    async def stream_events(
        thread_id: str,
        request: Request,
        after: int = 0,
        _: str = Depends(require_admin),
    ) -> StreamingResponse:
        raw_last_event = request.headers.get("Last-Event-ID", "").strip()
        if raw_last_event:
            try:
                after = max(after, int(raw_last_event))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Invalid Last-Event-ID") from exc
        try:
            snapshot = await service.thread_store.get(thread_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc
        if snapshot.thread and snapshot.thread.active_turn_id:
            service.ensure_scheduled(thread_id, snapshot.thread.active_turn_id)

        async def replay() -> AsyncIterator[str]:
            cursor = after
            while True:
                try:
                    events = await service.thread_store.events(
                        thread_id,
                        after=cursor,
                        limit=1_000,
                    )
                    current = await service.thread_store.get(thread_id)
                except KeyError:
                    yield 'event: error\ndata: {"error":"thread_not_found"}\n\n'
                    return
                for event in events:
                    cursor = event.thread_sequence
                    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {cursor}\nevent: {event.event_type}\ndata: {data}\n\n"
                if _latest_turn_is_terminal(current):
                    return
                if await request.is_disconnected():
                    return
                if not events:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(replay(), media_type="text/event-stream")

    @router.post("/{thread_id}/turns/{turn_id}/interrupt")
    async def interrupt_turn(
        thread_id: str,
        turn_id: str,
        username: str = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            snapshot = await service.interrupt(thread_id, turn_id, actor=username)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread or Turn not found") from exc
        except ThreadProtocolError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _turn_payload(snapshot, turn_id)

    return router


def _snapshot_payload(snapshot: ThreadSnapshotV1) -> dict[str, object]:
    if snapshot.thread is None:
        raise ValueError("Thread snapshot is empty")
    return {
        "thread": snapshot.thread.model_dump(mode="json"),
        "turns": [turn.model_dump(mode="json") for turn in snapshot.turns[-50:]],
        "items": [item.model_dump(mode="json") for item in snapshot.items[-200:]],
    }


def _turn_payload(snapshot: ThreadSnapshotV1, turn_id: str) -> dict[str, object]:
    turn = snapshot.turn(turn_id)
    return {
        "turn": turn.model_dump(mode="json"),
        "items": [
            item.model_dump(mode="json") for item in snapshot.items if item.turn_id == turn_id
        ],
        "event_cursor": snapshot.thread.event_cursor if snapshot.thread else 0,
    }


def _latest_turn_is_terminal(snapshot: ThreadSnapshotV1) -> bool:
    if not snapshot.turns:
        return False
    return snapshot.turns[-1].status in TERMINAL_TURN_STATUSES
