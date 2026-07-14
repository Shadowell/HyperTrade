"""Bounded portfolio assessment and human-only strategy lifecycle review."""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import desc, select

from hypertrade.db import (
    BitProPaperMonitorSnapshot,
    Database,
    PortfolioAssessment,
    StrategyLifecycleReview,
    utc_now,
)
from hypertrade.research.strategy_cards import StrategyCardService

PORTFOLIO_ASSESSMENT_SCHEMA_VERSION = "portfolio_assessment.v2"
PORTFOLIO_POLICY_VERSION = "portfolio_lifecycle_policy.v1"
ALLOWED_RECOMMENDATIONS = frozenset(
    {
        "observe",
        "run_targeted_research",
        "request_paper_review",
        "request_pause_review",
        "retire_candidate_review",
        "request_risk_budget_review",
    }
)


class PortfolioAssessmentRequestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_card_ids: list[str] = Field(default_factory=list, max_length=30)
    max_series_points: int = Field(default=50, ge=8, le=50)
    min_aligned_returns: int = Field(default=6, ge=5, le=30)
    alignment_bucket_minutes: Literal[5, 15, 30, 60, 240, 1440] = 60
    valid_for_minutes: int = Field(default=60, ge=5, le=1_440)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def valid_bounds(self) -> PortfolioAssessmentRequestV2:
        if len(set(self.strategy_card_ids)) != len(self.strategy_card_ids):
            raise ValueError("strategy_card_ids must be unique")
        if self.min_aligned_returns >= self.max_series_points:
            raise ValueError("min_aligned_returns must be below max_series_points")
        return self


class StrategyLifecycleDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_id: str = Field(min_length=1, max_length=96)
    decision: Literal["accept", "reject", "hold"]
    reason: str = Field(min_length=1, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PortfolioAssessmentService:
    """Persist explanatory research/review facts without importing mutation adapters."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def assess(
        self,
        payload: PortfolioAssessmentRequestV2,
        *,
        actor: str,
        world_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request_hash = _hash_json(
            payload.model_dump(mode="json", exclude={"idempotency_key"})
        )
        with self.db.session() as session:
            replay = session.scalar(
                select(PortfolioAssessment).where(
                    PortfolioAssessment.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("assessment idempotency key is bound to another request")
                return {**assessment_to_dict(replay), "idempotent": True}

        state = world_state if world_state is not None else self._world_state()
        cards = StrategyCardService(self.db).list()
        if payload.strategy_card_ids:
            wanted = set(payload.strategy_card_ids)
            cards = [card for card in cards if card.get("card_id") in wanted]
            missing_cards = sorted(wanted - {str(card.get("card_id")) for card in cards})
        else:
            missing_cards = []
        strategy_rows, unknowns = self._strategy_rows(cards, state)
        unknowns.extend(f"strategy_card.{card_id}.missing" for card_id in missing_cards)
        pairwise = self._pairwise(cards, payload)
        for pair in pairwise:
            if pair["correlation_status"] != "available":
                unknowns.append(
                    f"correlation.{pair['left_card_id']}.{pair['right_card_id']}.unknown"
                )
        valid_until = utc_now() + timedelta(minutes=payload.valid_for_minutes)
        recommendations = [
            {**item, "valid_until": valid_until.isoformat()}
            for item in _recommendations(strategy_rows, pairwise)
        ]
        if not strategy_rows:
            unknowns.append("portfolio.strategy_cards_unavailable")
        unknowns = sorted(set(unknowns))
        policy = {
            "policy_version": PORTFOLIO_POLICY_VERSION,
            "allowed_recommendations": sorted(ALLOWED_RECOMMENDATIONS),
            "allocation_change_allowed": False,
            "trading_mutation_allowed": False,
            "series_persistence": "summary_only",
            "min_aligned_returns": payload.min_aligned_returns,
            "max_series_points": payload.max_series_points,
            "alignment_bucket_minutes": payload.alignment_bucket_minutes,
        }
        input_refs = {
            "world_state_ref": str(state.get("source_id", "world_model:latest")),
            "world_state_generated_at": state.get("generated_at"),
            "strategy_card_ids": [row["card_id"] for row in strategy_rows],
            "source_evidence_ids": sorted(
                {
                    str(source_id)
                    for card in cards
                    for source_id in dict(card.get("source_refs", {})).values()
                    if source_id
                }
            ),
            "memory_assertion_ids": sorted(
                {
                    str(assertion_id)
                    for card in cards
                    for assertion_id in card.get("memory_assertion_ids", [])
                }
            ),
        }
        content = {
            "schema_version": PORTFOLIO_ASSESSMENT_SCHEMA_VERSION,
            "policy": policy,
            "input_refs": input_refs,
            "strategies": strategy_rows,
            "pairwise": pairwise,
            "unknowns": unknowns,
            "recommendations": recommendations,
        }
        with self.db.session() as session:
            row = PortfolioAssessment(
                schema_version=PORTFOLIO_ASSESSMENT_SCHEMA_VERSION,
                policy_version=PORTFOLIO_POLICY_VERSION,
                policy_hash=_hash_json(policy),
                status="needs_data" if unknowns else "completed",
                world_state_ref=input_refs["world_state_ref"],
                input_refs_json=input_refs,
                strategy_assessments_json=strategy_rows,
                pairwise_json=pairwise,
                unknowns_json=unknowns,
                recommendations_json=recommendations,
                request_hash=request_hash,
                content_hash=_hash_json(content),
                idempotency_key=payload.idempotency_key,
                valid_until=valid_until,
                created_by=actor,
            )
            session.add(row)
            session.flush()
            return assessment_to_dict(row)

    def review(
        self,
        assessment_id: str,
        payload: StrategyLifecycleDecisionV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            replay = session.scalar(
                select(StrategyLifecycleReview).where(
                    StrategyLifecycleReview.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if (
                    replay.assessment_id != assessment_id
                    or replay.recommendation_id != payload.recommendation_id
                    or replay.decision != payload.decision
                    or replay.reason != payload.reason.strip()
                ):
                    raise ValueError("review idempotency key is bound to another decision")
                return {**review_to_dict(replay), "idempotent": True}
            assessment = session.get(PortfolioAssessment, assessment_id)
            if assessment is None:
                raise KeyError(assessment_id)
            recommendation = next(
                (
                    item
                    for item in assessment.recommendations_json
                    if item.get("recommendation_id") == payload.recommendation_id
                ),
                None,
            )
            if recommendation is None:
                raise ValueError("recommendation does not belong to assessment")
            action = str(recommendation.get("action", ""))
            if action not in ALLOWED_RECOMMENDATIONS:
                raise ValueError("recommendation action is not read-only policy allowed")
            row = StrategyLifecycleReview(
                assessment_id=assessment.id,
                recommendation_id=payload.recommendation_id,
                strategy_card_id=str(recommendation.get("strategy_card_id", "")),
                recommendation_action=action,
                decision=payload.decision,
                reason=payload.reason.strip(),
                idempotency_key=payload.idempotency_key,
                decided_by=actor,
            )
            session.add(row)
            session.flush()
            return review_to_dict(row)

    def list_assessments(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(PortfolioAssessment)
                .order_by(desc(PortfolioAssessment.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [assessment_to_dict(row) for row in rows]

    def get(self, assessment_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(PortfolioAssessment, assessment_id)
            if row is None:
                raise KeyError(assessment_id)
            reviews = session.scalars(
                select(StrategyLifecycleReview)
                .where(StrategyLifecycleReview.assessment_id == row.id)
                .order_by(StrategyLifecycleReview.created_at)
            ).all()
            return {
                **assessment_to_dict(row),
                "reviews": [review_to_dict(review) for review in reviews],
            }

    def diff(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        left_cards = {row["card_id"]: row for row in left["strategies"]}
        right_cards = {row["card_id"]: row for row in right["strategies"]}
        return {
            "left_id": left_id,
            "right_id": right_id,
            "added_strategy_card_ids": sorted(set(right_cards) - set(left_cards)),
            "removed_strategy_card_ids": sorted(set(left_cards) - set(right_cards)),
            "lifecycle_changes": [
                {
                    "card_id": card_id,
                    "from": left_cards[card_id].get("lifecycle_status"),
                    "to": right_cards[card_id].get("lifecycle_status"),
                }
                for card_id in sorted(set(left_cards) & set(right_cards))
                if left_cards[card_id].get("lifecycle_status")
                != right_cards[card_id].get("lifecycle_status")
            ],
            "unknowns_added": sorted(set(right["unknowns"]) - set(left["unknowns"])),
            "unknowns_resolved": sorted(set(left["unknowns"]) - set(right["unknowns"])),
            "content_hash_changed": left["content_hash"] != right["content_hash"],
        }

    def _strategy_rows(
        self,
        cards: list[dict[str, Any]],
        world_state: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        regime = str(dict(world_state.get("global_market", {})).get("risk_regime", "unknown"))
        rows: list[dict[str, Any]] = []
        unknowns: list[str] = []
        for card in cards:
            card_id = str(card["card_id"])
            lifecycle = _lifecycle_status(str(card.get("paper_status", "unknown")))
            declared = [str(value) for value in card.get("declared_regime_fit", [])]
            regime_fit = (
                "unknown"
                if regime == "unknown" or "unknown" in declared
                else "favorable" if regime in declared else "mismatch"
            )
            if regime_fit == "unknown":
                unknowns.append(f"strategy.{card_id}.regime_fit")
            drawdown = card.get("drawdown", "unknown")
            if _decimal(drawdown) is None:
                unknowns.append(f"strategy.{card_id}.drawdown")
            capacity = card.get("capacity", "unknown")
            liquidity = card.get("liquidity", "unknown")
            if capacity == "unknown":
                unknowns.append(f"strategy.{card_id}.capacity")
            if liquidity == "unknown":
                unknowns.append(f"strategy.{card_id}.liquidity")
            rows.append(
                {
                    "card_id": card_id,
                    "strategy_key": card.get("strategy_key"),
                    "lifecycle_status": lifecycle,
                    "paper_status": card.get("paper_status"),
                    "regime": regime,
                    "regime_fit": regime_fit,
                    "symbols": list(card.get("allowed_symbols", [])),
                    "timeframes": list(card.get("allowed_timeframes", [])),
                    "factor_exposures": list(card.get("strategy_category", [])),
                    "direction_exposure": card.get("direction_exposure", "unknown"),
                    "drawdown_pct": drawdown,
                    "risk_contribution": "unknown",
                    "capacity": capacity,
                    "liquidity": liquidity,
                    "decay_status": _decay_status(card),
                    "coverage_flags": list(card.get("coverage_flags", [])),
                    "source_refs": dict(card.get("source_refs", {})),
                    "memory_assertion_ids": list(card.get("memory_assertion_ids", [])),
                }
            )
            unknowns.append(f"strategy.{card_id}.risk_contribution")
        return rows, unknowns

    def _pairwise(
        self,
        cards: list[dict[str, Any]],
        payload: PortfolioAssessmentRequestV2,
    ) -> list[dict[str, Any]]:
        series = {
            str(card["card_id"]): self._bounded_returns(
                str(card.get("bitpro_strategy_id", "")),
                max_points=payload.max_series_points,
                bucket_minutes=payload.alignment_bucket_minutes,
            )
            for card in cards
        }
        rows: list[dict[str, Any]] = []
        for left, right in combinations(cards, 2):
            left_id = str(left["card_id"])
            right_id = str(right["card_id"])
            left_returns, left_snapshot_ids = series[left_id]
            right_returns, right_snapshot_ids = series[right_id]
            common = sorted(set(left_returns) & set(right_returns))
            correlation: float | None = None
            reason = ""
            if len(common) < payload.min_aligned_returns:
                reason = "insufficient_aligned_returns"
            else:
                left_values = [left_returns[key] for key in common]
                right_values = [right_returns[key] for key in common]
                try:
                    correlation = max(
                        -1.0,
                        min(1.0, statistics.correlation(left_values, right_values)),
                    )
                except statistics.StatisticsError:
                    reason = "zero_variance_or_invalid_series"
            exposures = _shared_exposures(left, right)
            rows.append(
                {
                    "left_card_id": left_id,
                    "right_card_id": right_id,
                    "correlation_status": "available" if correlation is not None else "unknown",
                    "correlation": round(correlation, 6) if correlation is not None else None,
                    "sample_count": len(common),
                    "sample_start": common[0] if common else None,
                    "sample_end": common[-1] if common else None,
                    "alignment_bucket_minutes": payload.alignment_bucket_minutes,
                    "unknown_reason": reason,
                    "shared_exposures": exposures,
                    "source_snapshot_ids": sorted(
                        set(left_snapshot_ids + right_snapshot_ids)
                    ),
                }
            )
        return rows

    def _bounded_returns(
        self,
        strategy_id: str,
        *,
        max_points: int,
        bucket_minutes: int,
    ) -> tuple[dict[str, float], list[str]]:
        if not strategy_id:
            return {}, []
        with self.db.session() as session:
            rows = list(
                reversed(
                    session.scalars(
                        select(BitProPaperMonitorSnapshot)
                        .where(BitProPaperMonitorSnapshot.scope_key == strategy_id)
                        .order_by(desc(BitProPaperMonitorSnapshot.created_at))
                        .limit(max_points)
                    ).all()
                )
            )
        levels: dict[str, Decimal] = {}
        for row in rows:
            equity = _decimal(dict(row.metrics_json).get("latest_equity"))
            if equity is None:
                continue
            levels[_bucket(row.created_at, bucket_minutes)] = equity
        returns: dict[str, float] = {}
        previous: Decimal | None = None
        for key, equity in sorted(levels.items()):
            if previous is not None and previous != 0:
                returns[key] = float((equity / previous) - Decimal(1))
            previous = equity
        return returns, [row.id for row in rows]

    def _world_state(self) -> dict[str, Any]:
        # Local import prevents the legacy WorldState scheduler from depending
        # on this V2 persistence service or creating a recursion path.
        from hypertrade.world_model.service import WorldModelService

        return dict(WorldModelService(self.db).snapshot())


def assessment_to_dict(row: PortfolioAssessment) -> dict[str, Any]:
    return {
        "id": row.id,
        "schema_version": row.schema_version,
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "status": row.status,
        "world_state_ref": row.world_state_ref,
        "input_refs": dict(row.input_refs_json or {}),
        "strategies": list(row.strategy_assessments_json or []),
        "pairwise": list(row.pairwise_json or []),
        "unknowns": list(row.unknowns_json or []),
        "recommendations": list(row.recommendations_json or []),
        "request_hash": row.request_hash,
        "content_hash": row.content_hash,
        "valid_until": row.valid_until.isoformat(),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def review_to_dict(row: StrategyLifecycleReview) -> dict[str, Any]:
    return {
        "id": row.id,
        "assessment_id": row.assessment_id,
        "recommendation_id": row.recommendation_id,
        "strategy_card_id": row.strategy_card_id,
        "recommendation_action": row.recommendation_action,
        "decision": row.decision,
        "reason": row.reason,
        "decided_by": row.decided_by,
        "created_at": row.created_at.isoformat(),
    }


def _recommendations(
    strategies: list[dict[str, Any]],
    pairwise: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    strategies_by_id = {str(row["card_id"]): row for row in strategies}
    for strategy in strategies:
        lifecycle = strategy["lifecycle_status"]
        if lifecycle == "retired":
            action = "retire_candidate_review"
        elif lifecycle == "review_required":
            action = "request_pause_review"
        elif lifecycle == "degraded":
            action = "request_paper_review"
        elif strategy["regime_fit"] in {"mismatch", "unknown"} or strategy["coverage_flags"]:
            action = "run_targeted_research"
        else:
            action = "observe"
        recommendations.append(
            _recommendation(
                action,
                strategy_card_id=strategy["card_id"],
                reason=_reason(strategy),
                evidence_refs=_strategy_evidence_refs(strategy),
                unknown_fields=_strategy_unknown_fields(strategy),
            )
        )
    for pair in pairwise:
        correlation = pair.get("correlation")
        if isinstance(correlation, (int, float)) and abs(float(correlation)) >= 0.8:
            pair_ids = [pair["left_card_id"], pair["right_card_id"]]
            evidence_refs = list(pair.get("source_snapshot_ids", []))
            for card_id in pair_ids:
                pair_strategy = strategies_by_id.get(str(card_id))
                if pair_strategy is not None:
                    evidence_refs.extend(_strategy_evidence_refs(pair_strategy))
            recommendations.append(
                _recommendation(
                    "request_risk_budget_review",
                    strategy_card_id="",
                    reason=(
                        f"High absolute correlation ({float(correlation):.3f}) across "
                        f"{pair['sample_count']} aligned returns; request human review only."
                    ),
                    pair_ids=pair_ids,
                    evidence_refs=sorted(set(evidence_refs)),
                    unknown_fields=[],
                )
            )
    return [
        {**row, "recommendation_id": f"plrec_{index:03d}_{_short_hash(row)}"}
        for index, row in enumerate(recommendations, start=1)
    ]


def _recommendation(
    action: str,
    *,
    strategy_card_id: str,
    reason: str,
    pair_ids: list[str] | None = None,
    evidence_refs: list[str],
    unknown_fields: list[str],
) -> dict[str, Any]:
    if action not in ALLOWED_RECOMMENDATIONS:
        raise ValueError(f"unsupported lifecycle recommendation: {action}")
    return {
        "action": action,
        "strategy_card_id": strategy_card_id,
        "pair_card_ids": pair_ids or [],
        "reason": reason,
        "evidence_refs": evidence_refs,
        "unknown_fields": unknown_fields,
        "requires_human_review": action != "observe",
        "human_review_status": "pending" if action != "observe" else "not_required",
        "allocation_change_allowed": False,
        "trading_mutation_allowed": False,
    }


def _strategy_evidence_refs(strategy: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(value)
            for value in [
                *dict(strategy.get("source_refs", {})).values(),
                *strategy.get("memory_assertion_ids", []),
            ]
            if value
        }
    )


def _strategy_unknown_fields(strategy: dict[str, Any]) -> list[str]:
    return [
        field
        for field in (
            "regime_fit",
            "direction_exposure",
            "drawdown_pct",
            "risk_contribution",
            "capacity",
            "liquidity",
        )
        if strategy.get(field) in {None, "", "unknown"}
    ]


def _reason(strategy: dict[str, Any]) -> str:
    return (
        f"lifecycle={strategy['lifecycle_status']}; regime_fit={strategy['regime_fit']}; "
        f"decay={strategy['decay_status']}; gaps={len(strategy['coverage_flags'])}. "
        "Recommendation is research/review only."
    )


def _lifecycle_status(paper_status: str) -> str:
    return {
        "pending_paper_approval": "candidate",
        "approved_for_paper": "candidate",
        "paper_observing": "observing",
        "paper_degraded": "degraded",
        "paper_review_required": "review_required",
        "paper_retired": "retired",
    }.get(paper_status, "candidate")


def _decay_status(card: dict[str, Any]) -> str:
    if card.get("paper_status") in {"paper_degraded", "paper_review_required", "paper_retired"}:
        return "degraded"
    if card.get("evidence_freshness") != "fresh" or card.get("coverage_flags"):
        return "unknown"
    return "not_observed"


def _shared_exposures(left: dict[str, Any], right: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "symbols": sorted(
            set(left.get("allowed_symbols", []))
            & set(right.get("allowed_symbols", []))
        ),
        "timeframes": sorted(
            set(left.get("allowed_timeframes", [])) & set(right.get("allowed_timeframes", []))
        ),
        "factors": sorted(
            set(left.get("strategy_category", [])) & set(right.get("strategy_category", []))
        ),
    }


def _bucket(value: datetime, minutes: int) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    minute = (aware.minute // minutes) * minutes if minutes < 60 else 0
    if minutes >= 60:
        hours = max(1, minutes // 60)
        aware = aware.replace(hour=(aware.hour // hours) * hours)
    return aware.replace(minute=minute, second=0, microsecond=0).isoformat()


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _hash_json(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _short_hash(payload: Any) -> str:
    return _hash_json(payload)[:12]
