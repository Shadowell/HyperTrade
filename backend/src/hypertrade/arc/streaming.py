"""Read-only, bounded SSE connections over the persisted research event ledger."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from hypertrade.arc.auth import ARCScope, require_scope
from hypertrade.arc.controller import ARCMissionProjection
from hypertrade.arc.pipeline_view import _activity_row, build_pipeline_view
from hypertrade.arc.store import get_controller

router = APIRouter()
CHECKPOINTS = {
    "needs_operator",
    "paper_review_ready",
    "completed",
    "failed",
    "rejected",
    "live_approval_ready",
    "retired",
}


def stream_frames(
    projection: ARCMissionProjection, cursor: int
) -> list[tuple[str, int | None, dict[str, Any]]]:
    events = projection.events
    if cursor < 0 or cursor > len(events):
        raise ValueError("事件游标不属于当前任务，请从头重新连接")
    frames: list[tuple[str, int | None, dict[str, Any]]] = [
        ("activity", i + 1, _activity_row(event)) for i, event in enumerate(events) if i >= cursor
    ]
    snapshot = build_pipeline_view(projection)
    snapshot.pop("activity", None)
    frames.append(("snapshot", None, snapshot))
    if projection.state in CHECKPOINTS:
        frames.append(("checkpoint", None, {"state": projection.state}))
    return frames


def encode_frame(kind: str, cursor: int | None, payload: dict[str, Any]) -> str:
    identifier = f"id: {cursor}\n" if cursor is not None else ""
    return identifier + f"event: {kind}\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@router.get("/missions/{mission_id}/stream", dependencies=[Depends(require_scope(ARCScope.READ))])
async def research_stream(
    mission_id: str,
    request: Request,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    ctrl = get_controller(mission_id)
    if ctrl is None:
        raise HTTPException(404, "ARC Mission not found")
    try:
        cursor = int(last_event_id) if last_event_id is not None else after
        stream_frames(ctrl.projection, cursor)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc

    async def generate() -> AsyncIterator[str]:
        nonlocal cursor
        # Rotate after 16 seconds: reconnect rechecks the existing authentication policy.
        # Closing this read-only connection never cancels or mutates the research task.
        for _ in range(8):
            if await request.is_disconnected():
                return
            current = get_controller(mission_id)
            if current is None:
                yield encode_frame("error", None, {"message": "研究任务不可用"})
                return
            for kind, event_cursor, payload in stream_frames(current.projection, cursor):
                yield encode_frame(kind, event_cursor, payload)
                if event_cursor is not None:
                    cursor = event_cursor
                if kind == "checkpoint":
                    return
            await asyncio.sleep(2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
