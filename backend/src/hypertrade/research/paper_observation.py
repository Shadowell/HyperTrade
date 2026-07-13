"""Read-only paper sampling and operator review queue."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import Database, PaperPromotion, PaperReviewRequest
from hypertrade.research.paper_promotion import PaperPromotionAdapter, PaperPromotionService


class PaperObservationService:
    def __init__(self, db: Database, *, bitpro_adapter: PaperPromotionAdapter) -> None:
        self.db = db
        self.bitpro_adapter = bitpro_adapter

    def sample_all(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            ids = list(
                session.scalars(
                    select(PaperPromotion.id).where(
                        PaperPromotion.status.in_(
                            ["paper_observing", "paper_degraded", "paper_review_required"]
                        )
                    )
                )
            )
        return [self.sample(promotion_id) for promotion_id in ids]

    def sample(self, promotion_id: str) -> dict[str, Any]:
        promotion = PaperPromotionService(self.db, bitpro_adapter=self.bitpro_adapter).observe(
            promotion_id
        )
        status = str(promotion["status"])
        if status == "paper_observing":
            return {"promotion": promotion, "review_request": None}
        action = (
            "request_pause_review" if status == "paper_review_required" else "request_paper_review"
        )
        with self.db.session() as session:
            request = session.scalar(
                select(PaperReviewRequest).where(
                    PaperReviewRequest.promotion_id == promotion_id,
                    PaperReviewRequest.status == "open",
                    PaperReviewRequest.action == action,
                )
            )
            if request is None:
                request = PaperReviewRequest(
                    promotion_id=promotion_id,
                    action=action,
                    reason="paper observation requires human review",
                    evidence_json=dict(promotion["observation"]),
                )
                session.add(request)
                session.flush()
            return {"promotion": promotion, "review_request": _request_dict(request)}

    def list_requests(self, *, status: str = "open") -> list[dict[str, Any]]:
        with self.db.session() as session:
            statement = select(PaperReviewRequest).order_by(desc(PaperReviewRequest.created_at))
            if status:
                statement = statement.where(PaperReviewRequest.status == status)
            return [_request_dict(row) for row in session.scalars(statement)]


def _request_dict(row: PaperReviewRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "promotion_id": row.promotion_id,
        "status": row.status,
        "action": row.action,
        "reason": row.reason,
        "evidence": dict(row.evidence_json),
        "created_at": row.created_at.isoformat(),
    }
