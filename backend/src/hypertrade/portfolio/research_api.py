"""Administrator-requested portfolio research; no scheduled or external mutation path."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from hypertrade.portfolio.research import PortfolioFreezeRequest, PortfolioResearchService


def build_portfolio_research_router(
    service: PortfolioResearchService, require_admin: Callable[[Request], str]
) -> APIRouter:
    router = APIRouter(prefix="/api/portfolio/research", tags=["portfolio-research"])

    @router.post("/freeze")
    def freeze(
        payload: PortfolioFreezeRequest, actor: str = Depends(require_admin)
    ) -> dict[str, Any]:
        return service.freeze(payload, actor=actor)

    @router.post("/compare/{manifest_id}")
    def compare(manifest_id: str, actor: str = Depends(require_admin)) -> dict[str, Any]:
        try:
            return service.compare(manifest_id, actor=actor)
        except KeyError as exc:
            raise HTTPException(404, "Portfolio manifest not found") from exc
        except ValueError as exc:
            raise HTTPException(409, "Portfolio manifest integrity or type mismatch") from exc

    @router.get("/records/{record_id}")
    def record(record_id: str, _: str = Depends(require_admin)) -> dict[str, Any]:
        try:
            return service.get(record_id)
        except KeyError as exc:
            raise HTTPException(404, "Portfolio record not found") from exc
        except ValueError as exc:
            raise HTTPException(409, "Portfolio record integrity mismatch") from exc

    return router
