"""Product controls for autonomous evolution; no Paper approval capability is granted."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from hypertrade.arc.attribution import read_attribution
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


@router.put("/evolution", dependencies=[Depends(require_scope(ARCScope.POLICY))])
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


@router.get("/evolution/tuning", dependencies=[Depends(require_scope(ARCScope.READ))])
async def evolution_tuning(request: Request) -> dict[str, Any]:
    """Advisory offline meta-tuning report; never changes configuration."""
    from hypertrade.arc.meta_tuning import evaluate_tuning

    def _report() -> dict[str, Any]:
        service = EvolutionService(request.app.state.db)
        config = EvolutionConfig.model_validate(service.status()["config"])
        return evaluate_tuning(service.db, config.threshold_pp).model_dump()

    return await run_in_threadpool(_report)


@router.get("/evolution/effectiveness", dependencies=[Depends(require_scope(ARCScope.READ))])
async def evolution_effectiveness(request: Request) -> dict[str, Any]:
    """Deterministic accounting of what the evolution loop proposed and achieved."""
    from hypertrade.arc.effectiveness import build_effectiveness_report

    def _report() -> dict[str, Any]:
        service = EvolutionService(request.app.state.db)
        config = EvolutionConfig.model_validate(service.status()["config"])
        return build_effectiveness_report(service.db, target_id=config.target_id).model_dump()

    return await run_in_threadpool(_report)


@router.get(
    "/evolution/attribution/{strategy_id}", dependencies=[Depends(require_scope(ARCScope.READ))]
)
async def evolution_attribution(strategy_id: int = Path(gt=0)) -> dict[str, Any]:
    return await run_in_threadpool(read_attribution, strategy_id)
