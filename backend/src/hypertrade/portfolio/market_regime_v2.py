"""Immutable point-in-time market regime probability snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import Database, MarketRegimeSnapshotV2, utc_now
from hypertrade.portfolio.regime_shadow_schemas import (
    MarketRegimeCaptureV2,
    canonical_payload,
    digest,
)

MODEL_VERSION = "deterministic_regime_probability.v2"
REGIME_FIELDS = {
    "trend": "trend_score",
    "range": "range_score",
    "high_volatility": "high_volatility_score",
    "stress": "stress_score",
    "liquidity": "liquidity_score",
    "correlation": "correlation_score",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MarketRegimeSnapshotServiceV2:
    """Normalize source-bound scores without using ex-post labels."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def capture(
        self,
        request: MarketRegimeCaptureV2,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = _aware(now or utc_now())
        evidence = request.evidence
        if evidence.as_of > observed_at:
            raise ValueError("regime evidence as_of cannot be in the future")
        request_payload = canonical_payload(request.model_dump(exclude={"idempotency_key"}))
        request_hash = digest(request_payload)
        with self.db.session() as session:
            replay = session.scalar(
                select(MarketRegimeSnapshotV2).where(
                    MarketRegimeSnapshotV2.idempotency_key == request.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("regime idempotency key is content-bound")
                return {**snapshot_to_dict(replay), "replay": "idempotency"}

        raw = {
            regime: getattr(evidence, field)
            for regime, field in REGIME_FIELDS.items()
        }
        available = {
            regime: value for regime, value in raw.items() if value is not None
        }
        total = sum(available.values(), Decimal("0"))
        unknowns = [
            f"regime.{regime}.score_missing"
            for regime, value in raw.items()
            if value is None
        ]
        probabilities: dict[str, str] = {}
        if total <= 0:
            probabilities = dict.fromkeys(REGIME_FIELDS, "unknown")
            unknowns.append("regime.probability_denominator_unavailable")
        else:
            probabilities = _normalized_probabilities(raw, total)
        stale = observed_at - evidence.as_of > timedelta(
            minutes=request.freshness_minutes
        )
        if stale:
            unknowns.append("regime.source_stale")
        coverage = Decimal(len(available)) / Decimal(len(REGIME_FIELDS))
        max_probability = max(
            (
                Decimal(value)
                for value in probabilities.values()
                if value != "unknown"
            ),
            default=Decimal("0"),
        )
        confidence = coverage * max_probability
        status = (
            "needs_data"
            if not available
            else "stale"
            if stale
            else "available"
            if not unknowns
            else "partial"
        )
        policy = {
            "model_version": MODEL_VERSION,
            "normalization": "available_positive_scores_sum_to_one",
            "missing_scores": "unknown_not_zero",
            "ex_post_labels_allowed_for_decision": False,
            "freshness_minutes": request.freshness_minutes,
        }
        content = {
            "schema_version": "market_regime_snapshot.v2",
            "status": status,
            "model_version": MODEL_VERSION,
            "policy": policy,
            "as_of": evidence.as_of.isoformat(),
            "available_at": evidence.available_at.isoformat(),
            "probabilities": probabilities,
            "confidence": _fmt(confidence),
            "source_refs": evidence.source_refs,
            "source_hash": evidence.source_hash,
            "unknowns": sorted(set(unknowns)),
            "ex_post": {
                "label": evidence.ex_post_label,
                "used_for_decision": False,
            },
            "execution_authorized": False,
            "paper_lifecycle_authorized": False,
            "live_authorized": False,
        }
        policy_hash = digest(policy)
        content_hash = digest(content)
        with self.db.session() as session:
            duplicate = session.scalar(
                select(MarketRegimeSnapshotV2).where(
                    MarketRegimeSnapshotV2.content_hash == content_hash
                )
            )
            if duplicate is not None:
                return {**snapshot_to_dict(duplicate), "replay": "content"}
            row = MarketRegimeSnapshotV2(
                schema_version="market_regime_snapshot.v2",
                status=status,
                model_version=MODEL_VERSION,
                as_of=evidence.as_of,
                available_at=evidence.available_at,
                policy_hash=policy_hash,
                source_hash=evidence.source_hash,
                request_hash=request_hash,
                content_hash=content_hash,
                idempotency_key=request.idempotency_key,
                snapshot_json=content,
                created_by=actor,
            )
            session.add(row)
            session.flush()
            return snapshot_to_dict(row)

    def get(self, snapshot_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(MarketRegimeSnapshotV2, snapshot_id)
            if row is None:
                raise KeyError(snapshot_id)
            return snapshot_to_dict(row)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(MarketRegimeSnapshotV2)
                .order_by(desc(MarketRegimeSnapshotV2.as_of))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [snapshot_to_dict(row) for row in rows]

    def latest_at(self, as_of: datetime) -> dict[str, Any] | None:
        decision_time = _aware(as_of)
        with self.db.session() as session:
            row = session.scalar(
                select(MarketRegimeSnapshotV2)
                .where(
                    MarketRegimeSnapshotV2.as_of <= decision_time,
                    MarketRegimeSnapshotV2.available_at <= decision_time,
                )
                .order_by(
                    desc(MarketRegimeSnapshotV2.as_of),
                    desc(MarketRegimeSnapshotV2.created_at),
                )
                .limit(1)
            )
            return snapshot_to_dict(row) if row is not None else None

    def diff(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        return {
            "schema_version": "market_regime_diff.v2",
            "left_id": left_id,
            "right_id": right_id,
            "status": {"from": left["status"], "to": right["status"]},
            "probability_changes": {
                regime: {
                    "from": left["probabilities"].get(regime, "unknown"),
                    "to": right["probabilities"].get(regime, "unknown"),
                }
                for regime in REGIME_FIELDS
                if left["probabilities"].get(regime)
                != right["probabilities"].get(regime)
            },
            "source_hash_changed": left["source_hash"] != right["source_hash"],
            "execution_authorized": False,
        }


def snapshot_to_dict(row: MarketRegimeSnapshotV2) -> dict[str, Any]:
    content = dict(row.snapshot_json)
    content.update(
        {
            "id": row.id,
            "status": row.status,
            "model_version": row.model_version,
            "as_of": row.as_of.isoformat(),
            "available_at": row.available_at.isoformat(),
            "policy_hash": row.policy_hash,
            "source_hash": row.source_hash,
            "request_hash": row.request_hash,
            "content_hash": row.content_hash,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat(),
            "execution_authorized": False,
            "paper_lifecycle_authorized": False,
            "live_authorized": False,
        }
    )
    return content


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000000001")), "f")


def _normalized_probabilities(
    raw: dict[str, Decimal | None],
    total: Decimal,
) -> dict[str, str]:
    quantum = Decimal("0.000000000001")
    known = [regime for regime, value in raw.items() if value is not None]
    normalized = {
        regime: (value / total).quantize(quantum)
        for regime, value in raw.items()
        if value is not None
    }
    residual = Decimal("1.000000000000") - sum(
        normalized.values(), Decimal("0")
    )
    normalized[known[-1]] += residual
    return {
        regime: (
            format(normalized[regime], "f")
            if regime in normalized
            else "unknown"
        )
        for regime in raw
    }
