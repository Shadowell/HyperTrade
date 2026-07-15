"""Execution-isolated Shadow Portfolio research over immutable cohort facts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    Database,
    PaperCohortLabelDecision,
    PaperCohortSnapshot,
    ShadowPortfolioProposal,
    ShadowPortfolioReviewDecision,
    StrategyCardSnapshot,
    utc_now,
)
from hypertrade.portfolio.shadow_schemas import (
    ShadowPortfolioBuildV1,
    ShadowPortfolioReviewV1,
)

SCHEMA_VERSION = "shadow_portfolio.v1"
POLICY_VERSION = "shadow_portfolio_policy.v1"
TEMPLATES = ("equal_weight", "inverse_volatility", "capped_risk_budget_proxy")
LIQUIDITY_PASSED = frozenset({"adequate", "available", "high", "liquid", "ok", "passed"})
POLICY = {
    "policy_version": POLICY_VERSION,
    "templates": list(TEMPLATES),
    "automatic_template_selection": False,
    "long_only": True,
    "leverage_allowed": False,
    "execution_allowed": False,
    "capital_allocation_allowed": False,
}


class ShadowPortfolioService:
    """Build hypothetical scenarios without importing data or execution adapters."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def build(
        self,
        payload: ShadowPortfolioBuildV1,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        observed_at = _aware(now or utc_now())
        request = payload.model_dump(mode="json", exclude={"idempotency_key"})
        request_hash = _hash(request)
        with self.db.session() as session:
            replay = session.scalar(
                select(ShadowPortfolioProposal).where(
                    ShadowPortfolioProposal.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("shadow idempotency key is bound to another request")
                return {**proposal_to_dict(replay), "idempotent": True}
            cohort = self._cohort(session, payload.cohort_snapshot_id)
            if payload.cohort_snapshot_id and cohort is None:
                raise KeyError(payload.cohort_snapshot_id)
            members, source_decisions, card_sources = self._members(
                session, cohort, observed_at=observed_at
            )

        cohort_key = cohort.cohort_key if cohort is not None else "no_cohort"
        portfolio_key = _hash({"cohort_key": cohort_key, "policy": POLICY_VERSION})
        source_refs = {
            "cohort_snapshot_id": cohort.id if cohort is not None else "",
            "cohort_content_hash": cohort.content_hash if cohort is not None else "",
            "observation_window_id": cohort.observation_window_id if cohort is not None else "",
            "cohort_policy_hash": cohort.policy_hash if cohort is not None else "",
            "label_decisions": source_decisions,
            "card_snapshots": card_sources,
        }
        source_hash = _hash({"request_hash": request_hash, "source_refs": source_refs})
        with self.db.session() as session:
            duplicate = session.scalar(
                select(ShadowPortfolioProposal).where(
                    ShadowPortfolioProposal.portfolio_key == portfolio_key,
                    ShadowPortfolioProposal.source_hash == source_hash,
                )
            )
            if duplicate is not None:
                return {**proposal_to_dict(duplicate), "idempotent_content": True}
            current_version = session.scalar(
                select(func.max(ShadowPortfolioProposal.version_number)).where(
                    ShadowPortfolioProposal.portfolio_key == portfolio_key
                )
            )
        eligible = [member for member in members if member["eligible"]]
        unknowns = _proposal_unknowns(cohort, members, eligible, payload.max_strategy_weight)
        comparison_keys = {str(member.get("comparison_key", "")) for member in eligible}
        same_comparison_group = len(comparison_keys) == 1 and "" not in comparison_keys
        if eligible and not same_comparison_group:
            unknowns.append("accepted_members_not_in_one_comparison_group")
        scenario_members = (
            eligible
            if cohort is not None
            and cohort.status == "review_ready"
            and same_comparison_group
            else []
        )
        scenarios = self._scenarios(scenario_members, payload=payload)
        generated = {scenario["template"] for scenario in scenarios}
        if scenario_members and "inverse_volatility" not in generated:
            unknowns.append("inverse_volatility_inputs_incomplete")
        if scenario_members and "capped_risk_budget_proxy" not in generated:
            unknowns.append("risk_budget_inputs_incomplete")
        status = "ready_for_review" if scenarios else "needs_data"
        valid_until = observed_at + timedelta(days=payload.review_valid_days)
        content = {
            "schema_version": SCHEMA_VERSION,
            "policy": POLICY,
            "status": status,
            "hypothetical": True,
            "observed_at": observed_at.isoformat(),
            "valid_until": valid_until.isoformat(),
            "hypothetical_notional": _fmt(payload.hypothetical_notional),
            "constraints": {
                "max_strategy_weight": _fmt(payload.max_strategy_weight),
                "long_only": True,
                "leverage_allowed": False,
                "weight_sum": "1.000000000000",
            },
            "cost_assumptions": {
                "fee_bps": _fmt(payload.fee_bps),
                "slippage_bps": _fmt(payload.slippage_bps),
            },
            "source_refs": source_refs,
            "intake_denominator": len(members),
            "eligible_count": len(eligible),
            "members": members,
            "unknowns": sorted(set(unknowns)),
            "scenarios": scenarios,
            "automatic_recommendation": None,
            "execution_authorized": False,
            "capital_authorized": False,
            "paper_lifecycle_authorized": False,
            "orders_created": False,
        }
        content_hash = _hash(content)
        row = ShadowPortfolioProposal(
            portfolio_key=portfolio_key,
            version_number=int(current_version or 0) + 1,
            schema_version=SCHEMA_VERSION,
            policy_version=POLICY_VERSION,
            policy_hash=_hash(POLICY),
            status=status,
            cohort_snapshot_id=cohort.id if cohort is not None else "",
            observation_window_id=cohort.observation_window_id if cohort is not None else "",
            intake_count=len(members),
            eligible_count=len(eligible),
            scenario_count=len(scenarios),
            request_hash=request_hash,
            source_hash=source_hash,
            content_hash=content_hash,
            idempotency_key=payload.idempotency_key,
            proposal_json=content,
            valid_until=valid_until,
            created_by=actor,
        )
        with self.db.session() as session:
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValueError(
                    "concurrent shadow proposal version conflict; retry the same request"
                ) from exc
            return proposal_to_dict(row)

    def review(
        self,
        proposal_id: str,
        payload: ShadowPortfolioReviewV1,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request_hash = _hash(
            {
                "proposal_id": proposal_id,
                "scenario_id": payload.scenario_id,
                "decision": payload.decision,
                "reason": " ".join(payload.reason.split()),
            }
        )
        with self.db.session() as session:
            replay = session.scalar(
                select(ShadowPortfolioReviewDecision).where(
                    ShadowPortfolioReviewDecision.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("review idempotency key is bound to another decision")
                return {**review_to_dict(replay), "idempotent": True}
            proposal = session.get(ShadowPortfolioProposal, proposal_id)
            if proposal is None:
                raise KeyError(proposal_id)
            if _aware(proposal.valid_until) <= _aware(now or utc_now()):
                raise ValueError("shadow proposal has expired")
            scenario = next(
                (
                    item
                    for item in dict(proposal.proposal_json).get("scenarios", [])
                    if item.get("scenario_id") == payload.scenario_id
                ),
                None,
            )
            if scenario is None:
                raise ValueError("scenario does not belong to shadow proposal")
            row = ShadowPortfolioReviewDecision(
                proposal_id=proposal.id,
                scenario_id=payload.scenario_id,
                template=str(scenario.get("template", "")),
                decision=payload.decision,
                reason=" ".join(payload.reason.split()),
                request_hash=request_hash,
                idempotency_key=payload.idempotency_key,
                valid_until=proposal.valid_until,
                decided_by=actor,
            )
            session.add(row)
            session.flush()
            return review_to_dict(row)

    def list_proposals(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(ShadowPortfolioProposal)
                .order_by(desc(ShadowPortfolioProposal.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [proposal_to_dict(row) for row in rows]

    def get(self, proposal_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(ShadowPortfolioProposal, proposal_id)
            if row is None:
                raise KeyError(proposal_id)
            reviews = session.scalars(
                select(ShadowPortfolioReviewDecision)
                .where(ShadowPortfolioReviewDecision.proposal_id == proposal_id)
                .order_by(ShadowPortfolioReviewDecision.created_at)
            ).all()
            return {
                **proposal_to_dict(row),
                "reviews": [review_to_dict(review) for review in reviews],
            }

    def diff(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        left_scenarios = {item["template"]: item for item in left["scenarios"]}
        right_scenarios = {item["template"]: item for item in right["scenarios"]}
        return {
            "schema_version": "shadow_portfolio_diff.v1",
            "left_id": left_id,
            "right_id": right_id,
            "version_change": {"from": left["version_number"], "to": right["version_number"]},
            "status_change": {"from": left["status"], "to": right["status"]},
            "added_templates": sorted(set(right_scenarios) - set(left_scenarios)),
            "removed_templates": sorted(set(left_scenarios) - set(right_scenarios)),
            "weight_changes": [
                {
                    "template": template,
                    "from": left_scenarios[template].get("weights", []),
                    "to": right_scenarios[template].get("weights", []),
                }
                for template in sorted(set(left_scenarios) & set(right_scenarios))
                if left_scenarios[template].get("weights")
                != right_scenarios[template].get("weights")
            ],
            "content_hash_changed": left["content_hash"] != right["content_hash"],
            "hypothetical": True,
        }

    @staticmethod
    def _cohort(session: Any, cohort_id: str) -> PaperCohortSnapshot | None:
        if cohort_id:
            return cast(
                PaperCohortSnapshot | None,
                session.get(PaperCohortSnapshot, cohort_id),
            )
        return cast(
            PaperCohortSnapshot | None,
            session.scalar(
                select(PaperCohortSnapshot)
                .order_by(desc(PaperCohortSnapshot.created_at))
                .limit(1)
            ),
        )

    @staticmethod
    def _members(
        session: Any,
        cohort: PaperCohortSnapshot | None,
        *,
        observed_at: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
        if cohort is None:
            return [], [], []
        content = dict(cohort.snapshot_json)
        proposals = {
            str(item.get("card_id", "")): item
            for group in content.get("groups", [])
            for item in group.get("label_proposals", [])
        }
        decisions = session.scalars(
            select(PaperCohortLabelDecision)
            .where(PaperCohortLabelDecision.cohort_snapshot_id == cohort.id)
            .order_by(PaperCohortLabelDecision.created_at, PaperCohortLabelDecision.id)
        ).all()
        latest_decisions = {row.proposal_id: row for row in decisions}
        source_decisions = [
            {
                "id": row.id,
                "proposal_id": row.proposal_id,
                "decision": row.decision,
                "valid_until": _aware(row.valid_until).isoformat(),
            }
            for row in decisions
        ]
        members: list[dict[str, Any]] = []
        card_sources: list[dict[str, str]] = []
        for source_member in content.get("members", []):
            card_id = str(source_member.get("card_id", ""))
            reasons = list(source_member.get("reasons", []))
            if not source_member.get("comparable"):
                reasons.append("cohort_member_not_comparable")
            proposal = proposals.get(card_id)
            decision = (
                latest_decisions.get(str(proposal.get("proposal_id", "")))
                if proposal is not None
                else None
            )
            if proposal is None:
                reasons.append("label_proposal_missing")
            else:
                proposal_expiry = _parse_time(proposal.get("valid_until"))
                if proposal_expiry is None:
                    reasons.append("label_proposal_validity_missing")
                elif proposal_expiry <= observed_at:
                    reasons.append("label_proposal_expired")
            if decision is None:
                reasons.append("label_decision_missing")
            elif decision.decision != "accept":
                reasons.append(f"label_decision_{decision.decision}")
            elif _aware(decision.valid_until) <= observed_at:
                reasons.append("label_decision_expired")
            snapshot_id = str(
                dict(source_member.get("source_refs", {})).get("card_snapshot_id", "")
            )
            card_snapshot = session.get(StrategyCardSnapshot, snapshot_id) if snapshot_id else None
            if card_snapshot is None:
                reasons.append("card_snapshot_missing")
                card_json: dict[str, Any] = {}
                card_hash = ""
            else:
                card_json = dict(card_snapshot.card_json)
                card_hash = card_snapshot.content_hash
                card_sources.append({"id": card_snapshot.id, "content_hash": card_hash})
            capacity = _decimal(card_json.get("capacity"))
            liquidity = str(card_json.get("liquidity", "unknown")).lower()
            volatility = _decimal(dict(source_member.get("metrics", {})).get("volatility_proxy"))
            members.append(
                {
                    "card_id": card_id,
                    "strategy_version_id": str(source_member.get("strategy_version_id", "")),
                    "comparison_key": str(source_member.get("comparison_key", "")),
                    "status": "eligible" if not reasons else "excluded",
                    "eligible": not reasons,
                    "reasons": sorted(set(reasons)),
                    "accepted_label": (
                        str(proposal.get("proposed_label", ""))
                        if proposal is not None
                        and decision is not None
                        and decision.decision == "accept"
                        else ""
                    ),
                    "metrics": {
                        "volatility_proxy": (
                            _fmt(volatility) if volatility is not None else "unknown"
                        ),
                        "capacity": _fmt(capacity) if capacity is not None else "unknown",
                        "liquidity": liquidity,
                    },
                    "source_refs": {
                        "cohort_snapshot_id": cohort.id,
                        "cohort_member_card_id": card_id,
                        "label_proposal_id": (
                            str(proposal.get("proposal_id", "")) if proposal is not None else ""
                        ),
                        "label_decision_id": decision.id if decision is not None else "",
                        "card_snapshot_id": snapshot_id,
                        "card_content_hash": card_hash,
                        "observation_window_id": cohort.observation_window_id,
                    },
                }
            )
        return members, source_decisions, sorted(card_sources, key=lambda item: item["id"])

    @staticmethod
    def _scenarios(
        eligible: list[dict[str, Any]], *, payload: ShadowPortfolioBuildV1
    ) -> list[dict[str, Any]]:
        if len(eligible) < 2:
            return []
        scores: list[tuple[str, Decimal]] = [
            (member["card_id"], Decimal("1")) for member in eligible
        ]
        scenarios: list[dict[str, Any]] = []
        equal_weights = _capped_weights(scores, payload.max_strategy_weight)
        if equal_weights is not None:
            scenarios.append(_scenario("equal_weight", equal_weights, eligible, payload))
        vol_scores: list[tuple[str, Decimal]] = []
        for member in eligible:
            volatility = _decimal(member["metrics"].get("volatility_proxy"))
            if volatility is None or volatility <= 0:
                vol_scores = []
                break
            vol_scores.append((member["card_id"], Decimal("1") / volatility))
        inverse_weights = _capped_weights(vol_scores, payload.max_strategy_weight)
        if inverse_weights is not None:
            scenarios.append(
                _scenario("inverse_volatility", inverse_weights, eligible, payload)
            )
        risk_scores: list[tuple[str, Decimal]] = []
        for member in eligible:
            volatility = _decimal(member["metrics"].get("volatility_proxy"))
            capacity = _decimal(member["metrics"].get("capacity"))
            liquidity = str(member["metrics"].get("liquidity", "unknown")).lower()
            if (
                volatility is None
                or volatility <= 0
                or capacity is None
                or capacity <= 0
                or liquidity not in LIQUIDITY_PASSED
            ):
                risk_scores = []
                break
            capacity_factor = min(capacity / payload.hypothetical_notional, Decimal("1"))
            risk_scores.append((member["card_id"], capacity_factor / volatility))
        risk_weights = _capped_weights(risk_scores, payload.max_strategy_weight)
        if risk_weights is not None:
            scenarios.append(
                _scenario("capped_risk_budget_proxy", risk_weights, eligible, payload)
            )
        return scenarios


def proposal_to_dict(row: ShadowPortfolioProposal) -> dict[str, Any]:
    content = dict(row.proposal_json)
    content.update(
        {
            "id": row.id,
            "portfolio_key": row.portfolio_key,
            "version_number": row.version_number,
            "status": row.status,
            "policy_version": row.policy_version,
            "policy_hash": row.policy_hash,
            "cohort_snapshot_id": row.cohort_snapshot_id,
            "observation_window_id": row.observation_window_id,
            "intake_count": row.intake_count,
            "eligible_count": row.eligible_count,
            "scenario_count": row.scenario_count,
            "request_hash": row.request_hash,
            "source_hash": row.source_hash,
            "content_hash": row.content_hash,
            "valid_until": row.valid_until.isoformat(),
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat(),
            "hypothetical": True,
            "execution_authorized": False,
            "capital_authorized": False,
            "paper_lifecycle_authorized": False,
            "orders_created": False,
        }
    )
    return content


def review_to_dict(row: ShadowPortfolioReviewDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "proposal_id": row.proposal_id,
        "scenario_id": row.scenario_id,
        "template": row.template,
        "decision": row.decision,
        "reason": row.reason,
        "valid_until": row.valid_until.isoformat(),
        "decided_by": row.decided_by,
        "created_at": row.created_at.isoformat(),
        "hypothetical": True,
        "execution_authorized": False,
        "capital_authorized": False,
        "paper_lifecycle_authorized": False,
        "orders_created": False,
    }


def _proposal_unknowns(
    cohort: PaperCohortSnapshot | None,
    members: list[dict[str, Any]],
    eligible: list[dict[str, Any]],
    cap: Decimal,
) -> list[str]:
    unknowns: list[str] = []
    if cohort is None:
        unknowns.append("paper_cohort_missing")
    elif cohort.status != "review_ready":
        unknowns.append(f"paper_cohort_{cohort.status}")
    if not members:
        unknowns.append("shadow_intake_empty")
    if len(eligible) < 2:
        unknowns.append("insufficient_accepted_comparable_members")
    if eligible and Decimal(len(eligible)) * cap < Decimal("1"):
        unknowns.append("max_weight_constraint_infeasible")
    return unknowns


def _capped_weights(
    scores: list[tuple[str, Decimal]], cap: Decimal
) -> list[tuple[str, Decimal]] | None:
    if len(scores) < 2 or Decimal(len(scores)) * cap < Decimal("1"):
        return None
    if any(score <= 0 or not score.is_finite() for _, score in scores):
        return None
    remaining = dict(scores)
    weights: dict[str, Decimal] = {}
    remaining_mass = Decimal("1")
    while remaining:
        total = sum(remaining.values(), Decimal("0"))
        trial = {key: remaining_mass * score / total for key, score in remaining.items()}
        capped = [key for key, weight in trial.items() if weight > cap]
        if not capped:
            weights.update(trial)
            break
        for key in sorted(capped):
            weights[key] = cap
            remaining_mass -= cap
            remaining.pop(key)
        if remaining_mass < 0:
            return None
    quantized = {
        key: weight.quantize(Decimal("0.000000000001")) for key, weight in weights.items()
    }
    residual = Decimal("1") - sum(quantized.values(), Decimal("0"))
    for key in sorted(quantized):
        candidate = quantized[key] + residual
        if Decimal("0") <= candidate <= cap:
            quantized[key] = candidate
            residual = Decimal("0")
            break
    if residual or any(weight < 0 or weight > cap for weight in quantized.values()):
        return None
    return sorted(quantized.items())


def _scenario(
    template: str,
    weights: list[tuple[str, Decimal]],
    members: list[dict[str, Any]],
    payload: ShadowPortfolioBuildV1,
) -> dict[str, Any]:
    member_by_id = {member["card_id"]: member for member in members}
    turnover = Decimal("1")
    fee = payload.hypothetical_notional * turnover * payload.fee_bps / Decimal("10000")
    slippage = (
        payload.hypothetical_notional
        * turnover
        * payload.slippage_bps
        / Decimal("10000")
    )
    portfolio_volatility = sum(
        (
            weight
            * (_decimal(member_by_id[card_id]["metrics"].get("volatility_proxy")) or Decimal("0"))
            for card_id, weight in weights
        ),
        Decimal("0"),
    )
    impacts = []
    serialized_weights = []
    for card_id, weight in weights:
        target_notional = payload.hypothetical_notional * weight
        serialized_weights.append({"card_id": card_id, "weight": _fmt(weight)})
        impacts.append(
            {
                "card_id": card_id,
                "target_weight": _fmt(weight),
                "target_notional": _fmt(target_notional),
                "estimated_fee": _fmt(target_notional * payload.fee_bps / Decimal("10000")),
                "estimated_slippage": _fmt(
                    target_notional * payload.slippage_bps / Decimal("10000")
                ),
                "hypothetical": True,
                "order_created": False,
            }
        )
    scenario_id = f"shsc_{_hash({'template': template, 'weights': serialized_weights})[:20]}"
    return {
        "scenario_id": scenario_id,
        "template": template,
        "formula": {
            "equal_weight": "score=1",
            "inverse_volatility": "score=1/volatility_proxy",
            "capped_risk_budget_proxy": "score=min(capacity/notional,1)/volatility_proxy",
        }[template],
        "weights": serialized_weights,
        "weight_sum": _fmt(sum((weight for _, weight in weights), Decimal("0"))),
        "max_weight": _fmt(max(weight for _, weight in weights)),
        "turnover_assumption": _fmt(turnover),
        "estimated_costs": {
            "fee": _fmt(fee),
            "slippage": _fmt(slippage),
            "total": _fmt(fee + slippage),
        },
        "stress_tests": [
            {
                "name": "uniform_market_loss",
                "assumption_pct": _fmt(payload.stress_loss_pct),
                "hypothetical_loss": _fmt(
                    payload.hypothetical_notional
                    * payload.stress_loss_pct
                    / Decimal("100")
                ),
            },
            {
                "name": "volatility_2x_proxy",
                "portfolio_volatility_proxy": _fmt(portfolio_volatility * Decimal("2")),
                "correlation_assumption": "unknown",
            },
            {
                "name": "cost_2x",
                "hypothetical_cost": _fmt((fee + slippage) * Decimal("2")),
            },
        ],
        "hypothetical_order_impacts": impacts,
        "constraints_passed": True,
        "unknowns": ["cross_strategy_correlation_not_used"],
        "hypothetical": True,
        "execution_authorized": False,
        "capital_authorized": False,
        "orders_created": False,
    }


def _decimal(value: Any) -> Decimal | None:
    if value in {None, "", "unknown"}:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000000001")), "f")


def _hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
