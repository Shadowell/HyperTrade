"""Product controls for autonomous evolution; no Paper approval capability is granted."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from hypertrade.arc.auth import ARCScope, require_scope
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService

router = APIRouter()


class EvolutionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    config: EvolutionConfig


@router.get("/evolution", dependencies=[Depends(require_scope(ARCScope.READ))])
async def evolution_status(request: Request) -> dict[str, Any]:
    return await run_in_threadpool(EvolutionService(request.app.state.db).status)


@router.put("/evolution", dependencies=[Depends(require_scope(ARCScope.START))])
async def evolution_update(payload: EvolutionUpdate, request: Request) -> dict[str, Any]:
    from hypertrade.arc.router import _actor_label

    try:
        return await run_in_threadpool(
            EvolutionService(request.app.state.db).configure,
            payload.config,
            revision=payload.revision,
            actor=_actor_label(request),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/evolution/scan", dependencies=[Depends(require_scope(ARCScope.START))])
async def evolution_preview(request: Request) -> dict[str, Any]:
    return await run_in_threadpool(EvolutionService(request.app.state.db).queue_preview)
