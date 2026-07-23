"""Deterministic, point-in-time regime-aware shadow allocation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    Database,
    ExperimentManifest,
    MarketRegimeSnapshotV2,
    PaperCohortSnapshot,
    PortfolioObservationWindow,
    RegimeShadowTargetV2,
    StrategyCardSnapshot,
)
from hypertrade.portfolio.regime_shadow_schemas import (
    RegimeShadowBuildV2,
    ShadowAllocationPolicyV2,
    canonical_payload,
    digest,
)

SCHEMA_VERSION = "regime_shadow_target.v2"
ELIGIBILITY_VERSION = "strategy_eligibility.v1"
LIQUIDITY_PASSED = frozenset({"adequate", "available", "high", "liquid", "ok", "passed"})
REGIMES = (
    "trend",
    "range",
    "high_volatility",
    "stress",
    "liquidity",
    "correlation",
)
ZERO = Decimal("0")
ONE = Decimal("1")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class RegimeShadowAllocatorServiceV2:
    """Produce immutable hypothetical targets without importing execution adapters."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def build(
        self,
        request: RegimeShadowBuildV2,
        *,
        actor: str,
    ) -> dict[str, Any]:
        request_payload = canonical_payload(request.model_dump(exclude={"idempotency_key"}))
        request_hash = digest(request_payload)
        with self.db.session() as session:
            replay = session.scalar(
                select(RegimeShadowTargetV2).where(
                    RegimeShadowTargetV2.idempotency_key == request.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("shadow target idempotency key is content-bound")
                return {**target_to_dict(replay), "replay": "idempotency"}
            regime = session.get(MarketRegimeSnapshotV2, request.regime_snapshot_id)
            cohort = session.get(PaperCohortSnapshot, request.cohort_snapshot_id)
            previous = (
                session.get(RegimeShadowTargetV2, request.previous_target_id)
                if request.previous_target_id
                else None
            )
            if regime is None:
                raise KeyError(request.regime_snapshot_id)
            if cohort is None:
                raise KeyError(request.cohort_snapshot_id)
            if request.previous_target_id and previous is None:
                raise KeyError(request.previous_target_id)
            sources = self._load_sources(
                session,
                cohort=cohort,
                regime=regime,
                previous=previous,
                decision_at=request.decision_at,
            )

        policy = request.policy
        previous_content = dict(previous.target_json) if previous is not None else {}
        eligibility = self._eligibility(
            sources,
            regime=dict(regime.snapshot_json),
            previous=previous_content,
            policy=policy,
            decision_at=request.decision_at,
        )
        eligible = [item for item in eligibility if item["eligible"]]
        allocations = [
            self._allocation(
                template,
                eligible,
                sources=sources,
                previous=previous_content,
                policy=policy,
            )
            for template in policy.templates
        ]
        feasible = [item for item in allocations if item["status"] == "feasible"]
        selected = feasible[0] if feasible else None
        unknowns = sorted(
            {
                reason
                for item in eligibility
                for reason in item["reasons"]
                if reason.endswith("_unknown")
                or reason.endswith("_missing")
                or reason.endswith("_stale")
            }
            | {reason for item in allocations for reason in item["infeasible_reasons"]}
        )
        status = "ready" if selected is not None else "infeasible"
        valid_until = request.decision_at + timedelta(minutes=policy.valid_minutes)
        policy_payload = canonical_payload(policy)
        policy_hash = digest(policy_payload)
        source_refs = {
            "regime_snapshot_id": regime.id,
            "regime_content_hash": regime.content_hash,
            "cohort_snapshot_id": cohort.id,
            "cohort_content_hash": cohort.content_hash,
            "observation_window_id": sources["window_id"],
            "observation_window_content_hash": sources["window_hash"],
            "card_snapshots": sources["card_refs"],
            "manifests": sources["manifest_refs"],
            "previous_target_id": previous.id if previous is not None else "",
            "previous_target_content_hash": (previous.content_hash if previous is not None else ""),
        }
        source_hash = digest(
            {
                "decision_at": request.decision_at,
                "policy_hash": policy_hash,
                "source_refs": source_refs,
            }
        )
        content = {
            "schema_version": SCHEMA_VERSION,
            "eligibility_schema_version": ELIGIBILITY_VERSION,
            "status": status,
            "hypothetical": True,
            "decision_at": request.decision_at.isoformat(),
            "valid_until": valid_until.isoformat(),
            "policy": policy_payload,
            "policy_hash": policy_hash,
            "source_refs": source_refs,
            "intake_denominator": len(eligibility),
            "eligible_count": len(eligible),
            "eligibility": eligibility,
            "allocations": allocations,
            "selected_template": (str(selected["template"]) if selected is not None else ""),
            "current_weights": self._previous_weights(previous_content),
            "target_weights": (list(selected["target_weights"]) if selected is not None else []),
            "estimated_turnover": (
                str(selected["estimated_turnover"]) if selected is not None else "unknown"
            ),
            "estimated_cost_bps": (
                str(selected["estimated_cost_bps"]) if selected is not None else "unknown"
            ),
            "unknowns": unknowns,
            "exchange_order_payload": None,
            "execution_authorized": False,
            "capital_authorized": False,
            "paper_lifecycle_authorized": False,
            "live_authorized": False,
            "orders_created": False,
        }
        content_hash = digest(content)
        portfolio_key = digest(
            {
                "cohort_key": cohort.cohort_key,
                "policy_version": policy.schema_version,
            }
        )
        with self.db.session() as session:
            duplicate = session.scalar(
                select(RegimeShadowTargetV2).where(
                    RegimeShadowTargetV2.portfolio_key == portfolio_key,
                    RegimeShadowTargetV2.source_hash == source_hash,
                )
            )
            if duplicate is not None:
                return {**target_to_dict(duplicate), "replay": "content"}
            latest = session.scalar(
                select(func.max(RegimeShadowTargetV2.version_number)).where(
                    RegimeShadowTargetV2.portfolio_key == portfolio_key
                )
            )
            row = RegimeShadowTargetV2(
                portfolio_key=portfolio_key,
                version_number=int(latest or 0) + 1,
                schema_version=SCHEMA_VERSION,
                status=status,
                regime_snapshot_id=regime.id,
                cohort_snapshot_id=cohort.id,
                previous_target_id=previous.id if previous is not None else "",
                policy_hash=policy_hash,
                request_hash=request_hash,
                source_hash=source_hash,
                content_hash=content_hash,
                idempotency_key=request.idempotency_key,
                target_json=content,
                valid_until=valid_until,
                created_by=actor,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ValueError(
                    "concurrent shadow target version conflict; retry request"
                ) from exc
            return target_to_dict(row)

    def get(self, target_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(RegimeShadowTargetV2, target_id)
            if row is None:
                raise KeyError(target_id)
            return target_to_dict(row)

    def list_targets(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(RegimeShadowTargetV2)
                .order_by(desc(RegimeShadowTargetV2.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [target_to_dict(row) for row in rows]

    def replay(self, target_id: str) -> dict[str, Any]:
        target = self.get(target_id)
        decision_at = _parse_time(target["decision_at"])
        if decision_at is None:
            raise ValueError("target decision_at is missing")
        future_sources = [
            ref
            for ref in target["source_refs"].get("card_snapshots", [])
            if (_parse_time(ref.get("created_at")) or decision_at) > decision_at
        ]
        return {
            "schema_version": "regime_shadow_replay.v2",
            "target_id": target_id,
            "decision_at": decision_at.isoformat(),
            "source_hash": target["source_hash"],
            "target_weights": target["target_weights"],
            "estimated_turnover": target["estimated_turnover"],
            "estimated_cost_bps": target["estimated_cost_bps"],
            "no_lookahead_verified": not future_sources,
            "future_sources": future_sources,
            "execution_authorized": False,
        }

    @staticmethod
    def _load_sources(
        session: Any,
        *,
        cohort: PaperCohortSnapshot,
        regime: MarketRegimeSnapshotV2,
        previous: RegimeShadowTargetV2 | None,
        decision_at: datetime,
    ) -> dict[str, Any]:
        cutoff = _aware(decision_at)
        for name, value in (
            ("regime.as_of", regime.as_of),
            ("regime.available_at", regime.available_at),
            ("cohort.created_at", cohort.created_at),
        ):
            if _aware(value) > cutoff:
                raise ValueError(f"lookahead source rejected: {name}")
        if previous is not None:
            if _aware(previous.created_at) > cutoff:
                raise ValueError("lookahead source rejected: previous.created_at")
            if previous.cohort_snapshot_id != cohort.id:
                raise ValueError("previous target belongs to a different cohort")

        window = (
            session.get(PortfolioObservationWindow, cohort.observation_window_id)
            if cohort.observation_window_id
            else None
        )
        if window is None:
            raise ValueError("cohort observation window is missing")
        if _aware(window.window_end) > cutoff or _aware(window.created_at) > cutoff:
            raise ValueError("lookahead source rejected: observation_window")
        pairs = {
            tuple(
                sorted(
                    (
                        str(item.get("left_card_id", item.get("left", ""))),
                        str(item.get("right_card_id", item.get("right", ""))),
                    )
                )
            ): item
            for item in window.pairwise_json
        }
        cards: dict[str, dict[str, Any]] = {}
        manifests: dict[str, dict[str, Any]] = {}
        card_refs: list[dict[str, str]] = []
        manifest_refs: list[dict[str, str]] = []
        for member in dict(cohort.snapshot_json).get("members", []):
            card_id = str(member.get("card_id", ""))
            snapshot_id = str(dict(member.get("source_refs", {})).get("card_snapshot_id", ""))
            card = session.get(StrategyCardSnapshot, snapshot_id) if snapshot_id else None
            if card is not None:
                if _aware(card.created_at) > cutoff:
                    raise ValueError("lookahead source rejected: card_snapshot")
                cards[card_id] = dict(card.card_json)
                card_refs.append(
                    {
                        "card_id": card_id,
                        "id": card.id,
                        "content_hash": card.content_hash,
                        "created_at": _aware(card.created_at).isoformat(),
                    }
                )
            manifest_id = str(dict(member.get("source_refs", {})).get("manifest_id", ""))
            manifest = session.get(ExperimentManifest, manifest_id) if manifest_id else None
            if manifest is not None:
                if _aware(manifest.created_at) > cutoff:
                    raise ValueError("lookahead source rejected: manifest")
                manifests[card_id] = dict(manifest.canonical_json)
                manifest_refs.append(
                    {
                        "card_id": card_id,
                        "id": manifest.id,
                        "fingerprint": manifest.fingerprint,
                        "created_at": _aware(manifest.created_at).isoformat(),
                    }
                )
        return {
            "members": list(dict(cohort.snapshot_json).get("members", [])),
            "pairs": pairs,
            "cards": cards,
            "manifests": manifests,
            "window_id": window.id,
            "window_hash": window.content_hash,
            "card_refs": sorted(card_refs, key=lambda item: item["card_id"]),
            "manifest_refs": sorted(manifest_refs, key=lambda item: item["card_id"]),
        }

    @staticmethod
    def _eligibility(
        sources: dict[str, Any],
        *,
        regime: dict[str, Any],
        previous: dict[str, Any],
        policy: ShadowAllocationPolicyV2,
        decision_at: datetime,
    ) -> list[dict[str, Any]]:
        previous_states = {
            str(item.get("card_id")): item for item in previous.get("eligibility", [])
        }
        probabilities = dict(regime.get("probabilities", {}))
        results: list[dict[str, Any]] = []
        for member in sources["members"]:
            card_id = str(member.get("card_id", ""))
            card = dict(sources["cards"].get(card_id, {}))
            manifest = dict(sources["manifests"].get(card_id, {}))
            metrics = dict(member.get("metrics", {}))
            reasons = list(member.get("reasons", []))
            if not member.get("comparable"):
                reasons.append("cohort_member_not_comparable")
            volatility = _decimal(metrics.get("volatility_proxy"))
            capacity = _decimal(card.get("capacity"))
            liquidity = str(card.get("liquidity", "unknown")).lower()
            costs = _cost_bps(manifest.get("costs"))
            symbols = _symbols(member, manifest)
            fits = [
                str(item) for item in card.get("declared_regime_fit", []) if str(item) in REGIMES
            ]
            regime_values = [_decimal(probabilities.get(item)) for item in fits]
            if volatility is None or volatility <= 0:
                reasons.append("volatility_unknown")
            if capacity is None or capacity <= 0:
                reasons.append("capacity_unknown")
            if liquidity not in LIQUIDITY_PASSED:
                reasons.append("liquidity_unknown")
            if costs is None:
                reasons.append("cost_unknown")
            if not symbols:
                reasons.append("symbols_unknown")
            if not fits or any(value is None for value in regime_values):
                reasons.append("regime_fit_unknown")
                regime_score = None
            else:
                regime_score = sum((value for value in regime_values if value is not None), ZERO)
            previous_state = previous_states.get(card_id, {})
            previous_eligible = bool(previous_state.get("eligible"))
            confirmation = int(previous_state.get("confirmation_count", 0))
            eligible_since = _parse_time(previous_state.get("eligible_since"))
            cooldown_until = _parse_time(previous_state.get("cooldown_until"))
            risk_pause = (
                str(card.get("paper_status", "")).lower()
                in {"paper_degraded", "paper_review_required"}
                or str(card.get("lifecycle_status", "")).lower() == "retired"
            )
            if risk_pause:
                reasons.append("strategy_risk_state")
            if cooldown_until is not None and decision_at < cooldown_until:
                reasons.append("cooldown_active")

            state = "unknown" if reasons else "observe"
            eligible = False
            if not reasons and regime_score is not None:
                if previous_eligible:
                    dwell_until = (
                        eligible_since + timedelta(hours=policy.minimum_dwell_hours)
                        if eligible_since is not None
                        else decision_at
                    )
                    if regime_score >= policy.exit_threshold:
                        state = "eligible"
                        eligible = True
                    elif decision_at < dwell_until:
                        state = "eligible"
                        eligible = True
                        reasons.append("minimum_dwell_active")
                    else:
                        state = "reduce"
                        reasons.append("regime_exit_threshold_failed")
                elif regime_score >= policy.entry_threshold:
                    confirmation += 1
                    if confirmation >= policy.confirmation_windows:
                        state = "eligible"
                        eligible = True
                        eligible_since = decision_at
                    else:
                        state = "observe"
                        reasons.append("entry_confirmation_pending")
                else:
                    confirmation = 0
                    state = "observe"
                    reasons.append("regime_entry_threshold_failed")
            if risk_pause:
                state = (
                    "retire"
                    if str(card.get("lifecycle_status", "")).lower() == "retired"
                    else "pause"
                )
                eligible = False
            if state in {"reduce", "pause", "retire"}:
                cooldown_until = decision_at + timedelta(hours=policy.cooldown_hours)
            results.append(
                {
                    "schema_version": ELIGIBILITY_VERSION,
                    "card_id": card_id,
                    "strategy_version_id": str(member.get("strategy_version_id", "")),
                    "status": state,
                    "eligible": eligible,
                    "reasons": sorted(set(reasons)),
                    "regime_score": (_fmt(regime_score) if regime_score is not None else "unknown"),
                    "confirmation_count": confirmation,
                    "eligible_since": (
                        eligible_since.isoformat() if eligible_since is not None else ""
                    ),
                    "cooldown_until": (
                        cooldown_until.isoformat() if cooldown_until is not None else ""
                    ),
                    "valid_until": (
                        decision_at + timedelta(minutes=policy.valid_minutes)
                    ).isoformat(),
                    "metrics": {
                        "volatility": (_fmt(volatility) if volatility is not None else "unknown"),
                        "capacity": (_fmt(capacity) if capacity is not None else "unknown"),
                        "liquidity": liquidity,
                        "cost_bps": (_fmt(costs) if costs is not None else "unknown"),
                        "symbols": symbols,
                    },
                    "evidence": {
                        "regime_snapshot_id": regime.get("id", ""),
                        "card_snapshot": next(
                            (item for item in sources["card_refs"] if item["card_id"] == card_id),
                            {},
                        ),
                        "manifest": next(
                            (
                                item
                                for item in sources["manifest_refs"]
                                if item["card_id"] == card_id
                            ),
                            {},
                        ),
                        "observation_window_id": sources["window_id"],
                    },
                }
            )
        return results

    @staticmethod
    def _allocation(
        template: str,
        eligible: list[dict[str, Any]],
        *,
        sources: dict[str, Any],
        previous: dict[str, Any],
        policy: ShadowAllocationPolicyV2,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        if len(eligible) < policy.min_members:
            reasons.append("minimum_members_not_met")
        if len(eligible) > policy.max_members:
            eligible = sorted(
                eligible,
                key=lambda item: (
                    -_required_decimal(item["regime_score"]),
                    item["card_id"],
                ),
            )[: policy.max_members]
        selected = _correlation_filter(
            eligible,
            sources["pairs"],
            policy.max_pair_correlation,
            reasons,
        )
        if len(selected) < policy.min_members:
            reasons.append("correlation_constraint_infeasible")
        scores: list[tuple[str, Decimal]] = []
        caps: dict[str, Decimal] = {}
        costs: dict[str, Decimal] = {}
        for member in selected:
            metrics = dict(member["metrics"])
            volatility = _decimal(metrics.get("volatility"))
            capacity = _decimal(metrics.get("capacity"))
            cost = _decimal(metrics.get("cost_bps"))
            regime_score = _decimal(member.get("regime_score"))
            if (
                volatility is None
                or volatility <= 0
                or capacity is None
                or capacity <= 0
                or cost is None
                or regime_score is None
            ):
                reasons.append(f"{member['card_id']}.required_input_missing")
                continue
            capacity_cap = min(capacity / policy.hypothetical_notional, ONE)
            caps[member["card_id"]] = min(policy.max_strategy_weight, capacity_cap)
            costs[member["card_id"]] = cost
            score = ONE
            if template == "inverse_volatility":
                score = ONE / volatility
            elif template == "capped_risk_contribution":
                score = capacity_cap / volatility
            elif template == "constrained_risk_adjusted":
                score = regime_score * capacity_cap / volatility / (ONE + cost / Decimal("10000"))
            scores.append((member["card_id"], score))
        if sum(caps.values(), ZERO) < ONE:
            reasons.append("member_or_capacity_caps_infeasible")
        weights = _capped_weights(scores, caps) if not reasons else None
        if weights is not None:
            symbol_totals: dict[str, Decimal] = {}
            for member in selected:
                weight = weights.get(member["card_id"], ZERO)
                for symbol in member["metrics"]["symbols"]:
                    symbol_totals[symbol] = symbol_totals.get(symbol, ZERO) + weight
            if any(weight > policy.max_symbol_weight for weight in symbol_totals.values()):
                reasons.append("symbol_weight_constraint_infeasible")
                weights = None
        previous_weights = {
            str(item["card_id"]): _required_decimal(item["weight"])
            for item in previous.get("target_weights", [])
        }
        turnover = (
            _turnover(previous_weights, weights)
            if weights is not None and previous_weights
            else ZERO
        )
        max_delta = (
            max(
                (
                    abs(weights.get(card_id, ZERO) - previous_weights.get(card_id, ZERO))
                    for card_id in set(weights) | set(previous_weights)
                ),
                default=ZERO,
            )
            if weights is not None and previous_weights
            else ZERO
        )
        if previous_weights and turnover > policy.max_turnover:
            reasons.append("max_turnover_exceeded")
            weights = None
        if previous_weights and max_delta > policy.max_weight_delta:
            reasons.append("max_weight_delta_exceeded")
            weights = None
        estimated_cost = (
            sum(
                (
                    abs((weights or {}).get(card_id, ZERO) - previous_weights.get(card_id, ZERO))
                    * costs.get(card_id, ZERO)
                    for card_id in set(weights or {}) | set(previous_weights)
                ),
                ZERO,
            )
            if previous_weights
            else sum(
                (
                    (weights or {}).get(card_id, ZERO) * costs.get(card_id, ZERO)
                    for card_id in (weights or {})
                ),
                ZERO,
            )
        )
        if weights is not None and estimated_cost > policy.max_estimated_cost_bps:
            reasons.append("estimated_cost_cap_exceeded")
            weights = None
        target_weights = (
            [
                {"card_id": card_id, "weight": _fmt(weight)}
                for card_id, weight in sorted(weights.items())
            ]
            if weights is not None
            else []
        )
        return {
            "template": template,
            "formula_version": f"{template}.v1",
            "status": "feasible" if weights is not None else "infeasible",
            "target_weights": target_weights,
            "weight_sum": (_fmt(sum(weights.values(), ZERO)) if weights is not None else "unknown"),
            "estimated_turnover": (_fmt(turnover) if weights is not None else "unknown"),
            "estimated_cost_bps": (_fmt(estimated_cost) if weights is not None else "unknown"),
            "infeasible_reasons": sorted(set(reasons)),
            "hypothetical": True,
            "execution_authorized": False,
            "capital_authorized": False,
        }

    @staticmethod
    def _previous_weights(previous: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {
                "card_id": str(item.get("card_id", "")),
                "weight": str(item.get("weight", "0")),
            }
            for item in previous.get("target_weights", [])
        ]


def target_to_dict(row: RegimeShadowTargetV2) -> dict[str, Any]:
    content = dict(row.target_json)
    content.update(
        {
            "id": row.id,
            "portfolio_key": row.portfolio_key,
            "version_number": row.version_number,
            "status": row.status,
            "regime_snapshot_id": row.regime_snapshot_id,
            "cohort_snapshot_id": row.cohort_snapshot_id,
            "previous_target_id": row.previous_target_id,
            "policy_hash": row.policy_hash,
            "request_hash": row.request_hash,
            "source_hash": row.source_hash,
            "content_hash": row.content_hash,
            "valid_until": _aware(row.valid_until).isoformat(),
            "created_by": row.created_by,
            "created_at": _aware(row.created_at).isoformat(),
            "execution_authorized": False,
            "capital_authorized": False,
            "paper_lifecycle_authorized": False,
            "live_authorized": False,
            "orders_created": False,
        }
    )
    return content


def _correlation_filter(
    members: list[dict[str, Any]],
    pairs: dict[tuple[str, str], dict[str, Any]],
    maximum: Decimal,
    reasons: list[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for member in sorted(
        members,
        key=lambda item: (-_required_decimal(item["regime_score"]), item["card_id"]),
    ):
        card_id = str(member["card_id"])
        permitted = True
        for existing in selected:
            existing_id = str(existing["card_id"])
            pair_key = (card_id, existing_id) if card_id <= existing_id else (existing_id, card_id)
            pair = pairs.get(pair_key)
            correlation = _decimal(pair.get("correlation")) if pair is not None else None
            if correlation is None:
                reasons.append(f"correlation_missing:{existing['card_id']}:{card_id}")
                permitted = False
                break
            if correlation > maximum:
                reasons.append(f"correlation_cap_exceeded:{existing['card_id']}:{card_id}")
                permitted = False
                break
        if permitted:
            selected.append(member)
    return selected


def _capped_weights(
    scores: list[tuple[str, Decimal]],
    caps: dict[str, Decimal],
) -> dict[str, Decimal] | None:
    if not scores or any(score <= 0 for _, score in scores):
        return None
    active = {key for key, _ in scores}
    score_map = dict(scores)
    weights = dict.fromkeys(active, ZERO)
    remaining = ONE
    while active and remaining > ZERO:
        denominator = sum((score_map[key] for key in active), ZERO)
        if denominator <= ZERO:
            return None
        capped: list[str] = []
        for key in sorted(active):
            candidate = remaining * score_map[key] / denominator
            headroom = caps.get(key, ZERO) - weights[key]
            if candidate >= headroom:
                weights[key] += max(headroom, ZERO)
                capped.append(key)
        if not capped:
            for key in active:
                weights[key] += remaining * score_map[key] / denominator
            remaining = ZERO
        else:
            remaining = ONE - sum(weights.values(), ZERO)
            active.difference_update(capped)
    if remaining > Decimal("0.000000000001"):
        return None
    quantized = {key: value.quantize(Decimal("0.000000000001")) for key, value in weights.items()}
    residual = ONE - sum(quantized.values(), ZERO)
    recipient = max(quantized, key=lambda key: (quantized[key], key))
    quantized[recipient] += residual
    if any(quantized[key] > caps[key] for key in quantized):
        return None
    return quantized


def _turnover(previous: dict[str, Decimal], current: dict[str, Decimal]) -> Decimal:
    return sum(
        abs(current.get(key, ZERO) - previous.get(key, ZERO))
        for key in set(previous) | set(current)
    ) / Decimal("2")


def _cost_bps(value: Any) -> Decimal | None:
    if not isinstance(value, dict):
        return None
    fee = _decimal(value.get("fee_bps"))
    slippage = _decimal(value.get("slippage_bps"))
    if fee is None or slippage is None:
        return None
    return fee + slippage


def _symbols(member: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    dimensions = dict(member.get("dimensions", {}))
    values = dimensions.get("symbols")
    if not isinstance(values, list):
        values = dict(manifest.get("strategy_spec", {})).get("symbols")
    return (
        sorted({str(value).upper() for value in values if str(value)})
        if isinstance(values, list)
        else []
    )


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "unknown"):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _required_decimal(value: Any) -> Decimal:
    parsed = _decimal(value)
    return parsed if parsed is not None else ZERO


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000000001")), "f")
