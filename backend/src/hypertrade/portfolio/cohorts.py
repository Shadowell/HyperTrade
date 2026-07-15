"""Versioned paper cohorts over committed research facts; no lifecycle dispatch."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    Database,
    ExperimentManifest,
    PaperCohortLabelDecision,
    PaperCohortSnapshot,
    PortfolioObservationWindow,
    utc_now,
)
from hypertrade.portfolio.cohort_schemas import (
    PaperCohortBuildV1,
    PaperCohortLabelDecisionV1,
)
from hypertrade.research.strategy_cards import StrategyCardService

SCHEMA_VERSION = "paper_cohort.v1"
POLICY_VERSION = "paper_cohort_policy.v1"
PAPER_STATUSES = frozenset({"paper_observing", "paper_degraded", "paper_review_required"})
COMPARISON_ORDER = (
    "evidence_completeness",
    "validation",
    "data_quality",
    "decay",
    "drawdown",
    "volatility",
    "regime_coverage",
    "total_return_last",
)
POLICY = {
    "policy_version": POLICY_VERSION,
    "comparison_order": list(COMPARISON_ORDER),
    "single_return_ranking_allowed": False,
    "paper_lifecycle_mutation_allowed": False,
    "trading_mutation_allowed": False,
}


class PaperCohortService:
    """Build comparison/review facts without importing BitPro or paper services."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def build(
        self,
        payload: PaperCohortBuildV1,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = _aware(now or utc_now())
        request = payload.model_dump(mode="json", exclude={"idempotency_key"})
        request_hash = _hash(request)
        with self.db.session() as session:
            replay = session.scalar(
                select(PaperCohortSnapshot).where(
                    PaperCohortSnapshot.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("cohort idempotency key is bound to another request")
                return {**cohort_to_dict(replay), "idempotent": True}

        cards = [
            card
            for card in StrategyCardService(self.db).list()
            if card.get("schema_version") == "strategy_card.v2"
        ]
        if payload.strategy_card_ids:
            wanted = set(payload.strategy_card_ids)
            cards = [card for card in cards if str(card.get("card_id")) in wanted]
            missing_ids = sorted(wanted - {str(card.get("card_id")) for card in cards})
        else:
            missing_ids = []
        window = self._window(payload.observation_window_id)
        window_rows = {
            str(row.get("card_id")): row
            for row in (window.strategy_summaries_json if window is not None else [])
        }
        cohort_key = _hash(
            {
                "strategy_card_ids": sorted(
                    [str(card.get("card_id")) for card in cards] + missing_ids
                ),
                "horizon_days": payload.horizon_days,
            }
        )
        previous = self._latest_for_key(cohort_key)
        members = [
            self._member(
                card,
                window_row=window_rows.get(str(card["card_id"])),
                window=window,
                payload=payload,
                previous=previous,
            )
            for card in cards
        ]
        members.extend(
            {
                "card_id": card_id,
                "status": "rejected",
                "comparable": False,
                "reasons": ["strategy_card_missing"],
                "comparison_key": "",
                "metrics": {},
                "source_refs": {},
            }
            for card_id in missing_ids
        )
        groups = _groups(
            members,
            valid_until=observed_at + timedelta(days=payload.label_valid_days),
        )
        proposals = [proposal for group in groups for proposal in group["label_proposals"]]
        comparable_count = sum(bool(member.get("comparable")) for member in members)
        status = (
            "review_ready"
            if any(item["proposed_label"] == "champion_candidate" for item in proposals)
            else "needs_data"
        )
        source_refs = {
            "observation_window_id": window.id if window is not None else "",
            "observation_window_content_hash": window.content_hash if window is not None else "",
            "strategy_card_snapshot_ids": sorted(
                str(card.get("snapshot_id", "")) for card in cards if card.get("snapshot_id")
            ),
            "manifest_ids": sorted(
                str(dict(card.get("source_refs", {})).get("manifest_id", ""))
                for card in cards
                if dict(card.get("source_refs", {})).get("manifest_id")
            ),
        }
        source_hash = _hash({"request_hash": request_hash, "source_refs": source_refs})
        with self.db.session() as session:
            duplicate = session.scalar(
                select(PaperCohortSnapshot).where(
                    PaperCohortSnapshot.cohort_key == cohort_key,
                    PaperCohortSnapshot.source_hash == source_hash,
                )
            )
            if duplicate is not None:
                return {**cohort_to_dict(duplicate), "idempotent_content": True}
            latest_version = session.scalar(
                select(func.max(PaperCohortSnapshot.version_number)).where(
                    PaperCohortSnapshot.cohort_key == cohort_key
                )
            )
            version_number = int(latest_version or 0) + 1
            content = {
                "schema_version": SCHEMA_VERSION,
                "policy": POLICY,
                "cohort_key": cohort_key,
                "version_number": version_number,
                "status": status,
                "horizon_days": payload.horizon_days,
                "observation_window_id": window.id if window is not None else "",
                "intake_denominator": len(members),
                "comparable_count": comparable_count,
                "groups": groups,
                "members": members,
                "source_refs": source_refs,
                "unknowns": sorted(
                    {
                        f"member.{member['card_id']}.{reason}"
                        for member in members
                        for reason in member.get("reasons", [])
                    }
                ),
                "execution_authorized": False,
                "paper_lifecycle_authorized": False,
            }
            content_hash = _hash(content)
            row = PaperCohortSnapshot(
                cohort_key=cohort_key,
                version_number=version_number,
                schema_version=SCHEMA_VERSION,
                policy_version=POLICY_VERSION,
                policy_hash=_hash(POLICY),
                status=status,
                observation_window_id=window.id if window is not None else "",
                intake_count=len(members),
                comparable_count=comparable_count,
                proposal_count=len(proposals),
                request_hash=request_hash,
                source_hash=source_hash,
                content_hash=content_hash,
                idempotency_key=payload.idempotency_key,
                snapshot_json=content,
                created_by=actor,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValueError(
                    "concurrent cohort version conflict; retry with the same request"
                ) from exc
            return cohort_to_dict(row)

    def decide(
        self,
        cohort_id: str,
        payload: PaperCohortLabelDecisionV1,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request_hash = _hash(
            {
                "cohort_id": cohort_id,
                "proposal_id": payload.proposal_id,
                "decision": payload.decision,
                "reason": " ".join(payload.reason.split()),
            }
        )
        with self.db.session() as session:
            replay = session.scalar(
                select(PaperCohortLabelDecision).where(
                    PaperCohortLabelDecision.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("label idempotency key is bound to another decision")
                return {**decision_to_dict(replay), "idempotent": True}
            cohort = session.get(PaperCohortSnapshot, cohort_id)
            if cohort is None:
                raise KeyError(cohort_id)
            proposals = [
                proposal
                for group in dict(cohort.snapshot_json).get("groups", [])
                for proposal in group.get("label_proposals", [])
            ]
            proposal = next(
                (item for item in proposals if item.get("proposal_id") == payload.proposal_id),
                None,
            )
            if proposal is None:
                raise ValueError("label proposal does not belong to cohort snapshot")
            valid_until = _parse_time(proposal.get("valid_until"))
            if valid_until is None:
                raise ValueError("label proposal validity is missing")
            if valid_until <= _aware(now or utc_now()):
                raise ValueError("label proposal has expired")
            row = PaperCohortLabelDecision(
                cohort_snapshot_id=cohort.id,
                proposal_id=payload.proposal_id,
                strategy_card_id=str(proposal.get("card_id", "")),
                proposed_label=str(proposal.get("proposed_label", "watch")),
                decision=payload.decision,
                reason=" ".join(payload.reason.split()),
                request_hash=request_hash,
                idempotency_key=payload.idempotency_key,
                valid_until=valid_until,
                decided_by=actor,
            )
            session.add(row)
            session.flush()
            return decision_to_dict(row)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(PaperCohortSnapshot)
                .order_by(desc(PaperCohortSnapshot.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [cohort_to_dict(row) for row in rows]

    def get(self, cohort_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(PaperCohortSnapshot, cohort_id)
            if row is None:
                raise KeyError(cohort_id)
            decisions = session.scalars(
                select(PaperCohortLabelDecision)
                .where(PaperCohortLabelDecision.cohort_snapshot_id == cohort_id)
                .order_by(PaperCohortLabelDecision.created_at)
            ).all()
            return {
                **cohort_to_dict(row),
                "label_decisions": [decision_to_dict(item) for item in decisions],
            }

    def diff(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        left_members = {item["card_id"]: item for item in left["members"]}
        right_members = {item["card_id"]: item for item in right["members"]}
        return {
            "schema_version": "paper_cohort_diff.v1",
            "left_id": left_id,
            "right_id": right_id,
            "version_change": {"from": left["version_number"], "to": right["version_number"]},
            "status_change": {"from": left["status"], "to": right["status"]},
            "added_card_ids": sorted(set(right_members) - set(left_members)),
            "removed_card_ids": sorted(set(left_members) - set(right_members)),
            "comparability_changes": [
                {
                    "card_id": card_id,
                    "from": left_members[card_id].get("comparable"),
                    "to": right_members[card_id].get("comparable"),
                }
                for card_id in sorted(set(left_members) & set(right_members))
                if left_members[card_id].get("comparable")
                != right_members[card_id].get("comparable")
            ],
            "content_hash_changed": left["content_hash"] != right["content_hash"],
        }

    def _window(self, window_id: str) -> PortfolioObservationWindow | None:
        with self.db.session() as session:
            if window_id:
                return session.get(PortfolioObservationWindow, window_id)
            return session.scalar(
                select(PortfolioObservationWindow)
                .order_by(desc(PortfolioObservationWindow.created_at))
                .limit(1)
            )

    def _latest_for_key(self, cohort_key: str) -> PaperCohortSnapshot | None:
        with self.db.session() as session:
            return session.scalar(
                select(PaperCohortSnapshot)
                .where(PaperCohortSnapshot.cohort_key == cohort_key)
                .order_by(desc(PaperCohortSnapshot.version_number))
                .limit(1)
            )

    def _member(
        self,
        card: dict[str, Any],
        *,
        window_row: dict[str, Any] | None,
        window: PortfolioObservationWindow | None,
        payload: PaperCohortBuildV1,
        previous: PaperCohortSnapshot | None,
    ) -> dict[str, Any]:
        card_id = str(card["card_id"])
        reasons: list[str] = []
        manifest_id = str(dict(card.get("source_refs", {})).get("manifest_id", ""))
        with self.db.session() as session:
            manifest = session.get(ExperimentManifest, manifest_id) if manifest_id else None
        canonical = dict(manifest.canonical_json) if manifest is not None else {}
        spec = dict(canonical.get("strategy_spec", {}))
        costs = canonical.get("costs")
        market_type = str(canonical.get("market_type", ""))
        symbols = sorted(str(item).upper() for item in spec.get("symbols", []))
        timeframes = sorted(str(item).upper() for item in spec.get("timeframes", []))
        if str(card.get("paper_status", "")) not in PAPER_STATUSES:
            reasons.append("paper_status_not_observing")
        if window is None:
            reasons.append("observation_window_missing")
        elif window.horizon_days != payload.horizon_days:
            reasons.append("observation_horizon_mismatch")
        if window_row is None:
            reasons.append("window_member_missing")
            metrics: dict[str, Any] = {}
        else:
            metrics = dict(window_row.get("metrics", {}))
            if window_row.get("status") != "available":
                reasons.append(f"window_status_{window_row.get('status', 'unknown')}")
            if int(window_row.get("sample_count", 0)) < payload.min_sample_count:
                reasons.append("insufficient_sample_count")
            if window_row.get("freshness") != "fresh":
                reasons.append("window_not_fresh")
            if not _covers_horizon(window_row, payload.horizon_days):
                reasons.append("incomplete_observation_horizon")
        if card.get("validation_status") != "passed":
            reasons.append("validation_not_passed")
        if not market_type:
            reasons.append("market_type_unknown")
        if not symbols:
            reasons.append("symbols_unknown")
        if not timeframes:
            reasons.append("timeframes_unknown")
        if not isinstance(costs, dict) or not costs:
            reasons.append("cost_model_unknown")
        for metric in ("total_return_pct", "volatility_proxy", "max_drawdown_pct"):
            if _decimal(metrics.get(metric)) is None:
                reasons.append(f"{metric}_unknown")
        comparison_key = (
            _hash(
                {
                    "market_type": market_type,
                    "symbols": symbols,
                    "timeframes": timeframes,
                    "costs": costs,
                    "horizon_days": payload.horizon_days,
                    "bucket_minutes": window.bucket_minutes if window is not None else None,
                    "observation_policy": (
                        window.policy_version if window is not None else "unknown"
                    ),
                }
            )
            if not any(
                reason
                in {
                    "market_type_unknown",
                    "symbols_unknown",
                    "timeframes_unknown",
                    "cost_model_unknown",
                }
                for reason in reasons
            )
            else ""
        )
        decay = _decay(card_id, metrics, previous)
        return {
            "card_id": card_id,
            "strategy_key": str(card.get("strategy_key", "")),
            "strategy_version_id": str(dict(card.get("version", {})).get("id", "")),
            "paper_status": str(card.get("paper_status", "unknown")),
            "status": "comparable" if not reasons else "rejected",
            "comparable": not reasons,
            "reasons": sorted(set(reasons)),
            "comparison_key": comparison_key,
            "dimensions": {
                "market_type": market_type or "unknown",
                "symbols": symbols,
                "timeframes": timeframes,
                "cost_model_hash": _hash(costs) if isinstance(costs, dict) else "",
                "horizon_days": payload.horizon_days,
                "bucket_minutes": window.bucket_minutes if window is not None else None,
            },
            "metrics": {
                "total_return_pct": str(metrics.get("total_return_pct", "unknown")),
                "volatility_proxy": str(metrics.get("volatility_proxy", "unknown")),
                "max_drawdown_pct": str(metrics.get("max_drawdown_pct", "unknown")),
                "sample_count": int(window_row.get("sample_count", 0)) if window_row else 0,
                "freshness": (
                    str(window_row.get("freshness", "unknown"))
                    if window_row
                    else "unknown"
                ),
                "regime_coverage_count": len(
                    [
                        item
                        for item in card.get("declared_regime_fit", [])
                        if item != "unknown"
                    ]
                ),
                "decay_status": decay,
            },
            "source_refs": {
                "card_snapshot_id": str(card.get("snapshot_id", "")),
                "manifest_id": manifest_id,
                "manifest_fingerprint": str(
                    dict(card.get("version", {})).get("manifest_fingerprint", "")
                ),
                "observation_window_id": window.id if window is not None else "",
                "observation_window_content_hash": (
                    window.content_hash if window is not None else ""
                ),
                "window_source_refs": dict(window_row.get("source_refs", {})) if window_row else {},
            },
        }


def cohort_to_dict(row: PaperCohortSnapshot) -> dict[str, Any]:
    content = dict(row.snapshot_json)
    content.update(
        {
            "id": row.id,
            "cohort_key": row.cohort_key,
            "version_number": row.version_number,
            "status": row.status,
            "policy_version": row.policy_version,
            "policy_hash": row.policy_hash,
            "observation_window_id": row.observation_window_id,
            "intake_count": row.intake_count,
            "comparable_count": row.comparable_count,
            "proposal_count": row.proposal_count,
            "request_hash": row.request_hash,
            "source_hash": row.source_hash,
            "content_hash": row.content_hash,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat(),
            "execution_authorized": False,
            "paper_lifecycle_authorized": False,
        }
    )
    return content


def decision_to_dict(row: PaperCohortLabelDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "cohort_snapshot_id": row.cohort_snapshot_id,
        "proposal_id": row.proposal_id,
        "strategy_card_id": row.strategy_card_id,
        "proposed_label": row.proposed_label,
        "decision": row.decision,
        "reason": row.reason,
        "valid_until": row.valid_until.isoformat(),
        "decided_by": row.decided_by,
        "created_at": row.created_at.isoformat(),
        "execution_authorized": False,
        "paper_lifecycle_authorized": False,
    }


def _groups(members: list[dict[str, Any]], *, valid_until: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        if member.get("comparable") and member.get("comparison_key"):
            grouped.setdefault(str(member["comparison_key"]), []).append(member)
    result: list[dict[str, Any]] = []
    for key, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=_member_sort_key)
        proposals: list[dict[str, Any]] = []
        for index, member in enumerate(ordered):
            label = (
                "champion_candidate"
                if len(ordered) >= 2 and index == 0
                else "challenger"
                if len(ordered) >= 2
                else "watch"
            )
            proposal = {
                "card_id": member["card_id"],
                "proposed_label": label,
                "reason": (
                    "multi_dimensional_policy_candidate"
                    if len(ordered) >= 2
                    else "insufficient_comparable_members"
                ),
                "rank_basis": list(COMPARISON_ORDER),
                "metric_snapshot": dict(member["metrics"]),
                "source_refs": dict(member["source_refs"]),
                "valid_until": valid_until.isoformat(),
                "requires_human_review": True,
                "execution_authorized": False,
                "paper_lifecycle_authorized": False,
            }
            proposal["proposal_id"] = f"pclp_{_hash(proposal)[:20]}"
            proposals.append(proposal)
        result.append(
            {
                "comparison_key": key,
                "member_count": len(rows),
                "comparable": len(rows) >= 2,
                "member_card_ids": [str(item["card_id"]) for item in ordered],
                "label_proposals": proposals,
            }
        )
    return result


def _member_sort_key(member: dict[str, Any]) -> tuple[Any, ...]:
    metrics = dict(member["metrics"])
    decay_penalty = 1 if metrics.get("decay_status") == "degraded" else 0
    drawdown_value = _decimal(metrics.get("max_drawdown_pct"))
    volatility_value = _decimal(metrics.get("volatility_proxy"))
    return_value = _decimal(metrics.get("total_return_pct"))
    drawdown = drawdown_value if drawdown_value is not None else Decimal("Infinity")
    volatility = volatility_value if volatility_value is not None else Decimal("Infinity")
    regime = -int(metrics.get("regime_coverage_count", 0))
    total_return = -return_value if return_value is not None else Decimal("Infinity")
    return (decay_penalty, drawdown, volatility, regime, total_return, member["card_id"])


def _decay(
    card_id: str,
    metrics: dict[str, Any],
    previous: PaperCohortSnapshot | None,
) -> str:
    if previous is None:
        return "unknown"
    prior = next(
        (
            item
            for item in dict(previous.snapshot_json).get("members", [])
            if item.get("card_id") == card_id
        ),
        None,
    )
    if prior is None:
        return "unknown"
    prior_metrics = dict(prior.get("metrics", {}))
    current_return = _decimal(metrics.get("total_return_pct"))
    prior_return = _decimal(prior_metrics.get("total_return_pct"))
    current_drawdown = _decimal(metrics.get("max_drawdown_pct"))
    prior_drawdown = _decimal(prior_metrics.get("max_drawdown_pct"))
    if None in {current_return, prior_return, current_drawdown, prior_drawdown}:
        return "unknown"
    assert current_return is not None and prior_return is not None
    assert current_drawdown is not None and prior_drawdown is not None
    if current_return < prior_return - Decimal(5) or current_drawdown > prior_drawdown + Decimal(3):
        return "degraded"
    return "stable"


def _covers_horizon(row: dict[str, Any], horizon_days: int) -> bool:
    start = _parse_time(row.get("sample_start"))
    end = _parse_time(row.get("sample_end"))
    return bool(start and end and end - start >= timedelta(days=horizon_days, hours=-1))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()
