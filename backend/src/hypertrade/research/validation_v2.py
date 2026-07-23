"""Unified deterministic quarantine for evolved and newly discovered candidates."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from statistics import median
from typing import Any, cast

from sqlalchemy import desc, func, select

from hypertrade.db import (
    Database,
    ExperimentExecution,
    ExperimentManifest,
    StrategyDiscoveryCandidate,
    StrategyEvolutionCandidate,
    UnifiedStrategyValidation,
)
from hypertrade.research.validation_v2_schemas import (
    UnifiedValidationRequestV2,
    ValidationDecisionV2,
    ValidationGateV2,
    canonical_payload,
    digest,
)


class UnifiedStrategyValidationService:
    """Verify immutable candidate facts; model output cannot supply gate outcomes."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def validate(
        self, request: UnifiedValidationRequestV2, *, actor: str
    ) -> dict[str, Any]:
        request_hash = digest(
            canonical_payload(request.model_dump(mode="python", exclude={"idempotency_key"}))
        )
        policy_hash = digest(request.policy)
        fingerprint = digest(
            {
                "candidate_kind": request.trial_family.candidate_kind,
                "candidate_id": request.trial_family.candidate_id,
                "trial_family": canonical_payload(request.trial_family),
                "policy_hash": policy_hash,
                "source_hash": request.evidence.source_hash,
            }
        )
        with self.db.session() as session:
            replay = session.scalar(
                select(UnifiedStrategyValidation).where(
                    UnifiedStrategyValidation.idempotency_key == request.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("validation idempotency key is bound to another request")
                return _row_to_dict(replay, replay="idempotency")
            same = session.scalar(
                select(UnifiedStrategyValidation).where(
                    UnifiedStrategyValidation.fingerprint == fingerprint
                )
            )
            if same is not None:
                return _row_to_dict(same, replay="fingerprint")

        candidate = self._candidate(request)
        gates = self._evaluate_gates(request, candidate=candidate)
        required_failed = [
            name
            for name, gate in gates.items()
            if gate.required and gate.outcome == "failed"
        ]
        required_unknown = [
            name
            for name, gate in gates.items()
            if gate.required and gate.outcome == "unknown"
        ]
        review = [
            name
            for name, gate in gates.items()
            if not gate.required and gate.outcome in {"failed", "unknown"}
        ]
        status = (
            "rejected"
            if required_failed
            else "needs_data"
            if required_unknown
            else "needs_review"
            if review
            else "validated"
        )
        unknowns = sorted(
            {
                reason
                for gate in gates.values()
                if gate.outcome == "unknown"
                for reason in gate.reasons
            }
        )
        with self.db.session() as session:
            version = (
                session.scalar(
                    select(func.max(UnifiedStrategyValidation.validation_version)).where(
                        UnifiedStrategyValidation.candidate_kind
                        == request.trial_family.candidate_kind,
                        UnifiedStrategyValidation.candidate_id
                        == request.trial_family.candidate_id,
                    )
                )
                or 0
            ) + 1
            decision = ValidationDecisionV2(
                validation_version=version,
                candidate_kind=request.trial_family.candidate_kind,
                candidate_id=request.trial_family.candidate_id,
                trial_family_id=request.trial_family.family_id,
                status=cast(Any, status),
                gates=gates,
                unknowns=unknowns,
                policy_hash=policy_hash,
                source_hash=request.evidence.source_hash,
                fingerprint=fingerprint,
            )
            row = UnifiedStrategyValidation(
                schema_version=decision.schema_version,
                candidate_kind=decision.candidate_kind,
                candidate_id=decision.candidate_id,
                trial_family_id=decision.trial_family_id,
                manifest_id=request.trial_family.manifest_id,
                experiment_execution_id=request.trial_family.experiment_execution_id,
                validation_version=version,
                status=decision.status,
                fingerprint=fingerprint,
                policy_hash=policy_hash,
                source_hash=request.evidence.source_hash,
                request_hash=request_hash,
                idempotency_key=request.idempotency_key,
                policy_json=canonical_payload(request.policy),
                trial_family_json=canonical_payload(request.trial_family),
                evidence_json=canonical_payload(request.evidence),
                decision_json=canonical_payload(decision),
                created_by=actor,
            )
            session.add(row)
            session.flush()
            validation_id = row.id
            result = _row_to_dict(row)
        from hypertrade.research.strategy_cards import StrategyCardService

        result["strategy_card_snapshot"] = StrategyCardService(self.db).reconcile_manifest(
            request.trial_family.manifest_id,
            actor="unified_validation_v2",
        )
        result["id"] = validation_id
        return result

    def get(self, validation_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(UnifiedStrategyValidation, validation_id)
            if row is None:
                raise KeyError(validation_id)
            return _row_to_dict(row)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(UnifiedStrategyValidation)
                .order_by(desc(UnifiedStrategyValidation.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [_row_to_dict(row) for row in rows]

    def diff(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        keys = ("status", "policy_hash", "source_hash", "gates", "unknowns")
        changes = {
            key: {"left": left[key], "right": right[key]}
            for key in keys
            if left[key] != right[key]
        }
        return {
            "schema_version": "validation_decision_diff.v2",
            "left_id": left_id,
            "right_id": right_id,
            "equal": not changes,
            "changes": changes,
        }

    def _candidate(self, request: UnifiedValidationRequestV2) -> dict[str, Any]:
        family = request.trial_family
        with self.db.session() as session:
            row: StrategyEvolutionCandidate | StrategyDiscoveryCandidate | None
            if family.candidate_kind == "evolution":
                row = session.get(StrategyEvolutionCandidate, family.candidate_id)
                valid_status = "accepted"
            else:
                row = session.get(StrategyDiscoveryCandidate, family.candidate_id)
                valid_status = "candidate_ready"
            if row is None:
                raise KeyError(family.candidate_id)
            payload = dict(row.candidate_json)
            if row.status != valid_status:
                raise ValueError("only accepted or candidate_ready candidates enter quarantine")
            if row.manifest_id != family.manifest_id:
                raise ValueError("trial family manifest does not match candidate")
            if row.experiment_execution_id != family.experiment_execution_id:
                raise ValueError("trial family execution does not match candidate")
            manifest = session.get(ExperimentManifest, family.manifest_id)
            execution = session.get(ExperimentExecution, family.experiment_execution_id)
            if manifest is None or execution is None or execution.manifest_id != manifest.id:
                raise ValueError("candidate experiment lineage is incomplete")
            frozen = row.created_at
            if isinstance(row, StrategyDiscoveryCandidate):
                hypothesis = dict(row.hypothesis_json)
                frozen = _parse_time(str(hypothesis["frozen_at"]))
        if _utc(family.candidate_frozen_at) != _utc(frozen):
            raise ValueError("trial family freeze time does not match immutable candidate")
        return payload

    def _evaluate_gates(
        self, request: UnifiedValidationRequestV2, *, candidate: dict[str, Any]
    ) -> dict[str, ValidationGateV2]:
        policy = request.policy
        family = request.trial_family
        evidence = request.evidence
        refs = evidence.result_refs
        gates: dict[str, ValidationGateV2] = {}

        gates["candidate_provenance"] = _boolean_gate(bool(candidate), refs=refs)
        access = family.locked_oos_first_accessed_at
        gates["locked_oos_access"] = (
            _unknown_gate("locked_oos_access_missing", refs=refs)
            if access is None
            else _boolean_gate(
                _utc(access) >= _utc(family.candidate_frozen_at),
                reason="locked_oos_access_precedes_candidate_freeze",
                refs=refs,
            )
        )
        gates["trial_accounting"] = _boolean_gate(
            len(family.attempts) == family.declared_attempt_count,
            reason="declared_trial_count_mismatch",
            refs=[item.result_ref for item in family.attempts if item.result_ref],
        )
        gates["real_data"] = _boolean_gate(
            evidence.real_data, reason="real_data_required", refs=refs
        )
        gates["chronological_split"] = _boolean_gate(
            evidence.chronological_split and evidence.locked_oos_complete,
            reason="chronological_or_locked_oos_incomplete",
            refs=refs,
        )
        gates["purge_embargo"] = _boolean_gate(
            evidence.purge_embargo_applied,
            reason="purge_embargo_not_applied",
            refs=refs,
        )
        gates["costs"] = _boolean_gate(
            evidence.costs_complete,
            reason="costs_incomplete",
            refs=refs,
        )
        gates["funding"] = (
            _optional_boolean_gate(evidence.funding_included, "funding_unknown", refs)
            if not policy.require_funding
            else _required_optional_boolean_gate(
                evidence.funding_included, "funding_unknown", "funding_not_included", refs
            )
        )
        gates["capacity"] = (
            _required_optional_boolean_gate(
                evidence.capacity_assessed, "capacity_unknown", "capacity_not_assessed", refs
            )
            if policy.require_capacity
            else _optional_boolean_gate(evidence.capacity_assessed, "capacity_unknown", refs)
        )
        gates["artifacts"] = _boolean_gate(
            bool(evidence.artifact_refs) or not policy.require_artifacts,
            reason="required_artifacts_missing",
            refs=evidence.artifact_refs,
        )
        gates["trade_count"] = _threshold_min(
            evidence.trade_count, policy.min_trade_count, "trade_count", refs
        )
        gates["drawdown"] = _threshold_max(
            evidence.max_drawdown_pct, policy.max_drawdown_pct, "drawdown", refs
        )
        gates["tail_risk"] = _threshold_max(
            evidence.tail_loss_pct, policy.max_tail_loss_pct, "tail_loss", refs
        )
        gates["probabilistic_sharpe"] = _threshold_min(
            evidence.probabilistic_sharpe,
            policy.min_probabilistic_sharpe,
            "probabilistic_sharpe",
            refs,
        )
        gates["deflated_sharpe"] = _threshold_min(
            evidence.deflated_sharpe,
            policy.min_deflated_sharpe,
            "deflated_sharpe",
            refs,
        )
        gates["selection_bias"] = _threshold_max(
            evidence.overfit_probability,
            policy.max_overfit_probability,
            "overfit_probability",
            refs,
        )
        folds = evidence.walk_forward_returns
        gates["walk_forward"] = (
            _unknown_gate("walk_forward_folds_missing", refs=refs)
            if len(folds) < policy.walk_forward_folds
            else _boolean_gate(
                sum(value > 0 for value in folds) * 2 >= len(folds)
                and median(folds) > 0,
                reason="walk_forward_distribution_unstable",
                refs=refs,
            )
        )
        neighbors = evidence.parameter_neighbor_returns
        baseline = evidence.locked_oos_return
        gates["parameter_stability"] = (
            _unknown_gate("parameter_neighborhood_missing", refs=refs)
            if not neighbors or baseline is None
            else _parameter_gate(neighbors, baseline, policy.max_parameter_degradation_pct, refs)
        )
        gates["cost_stress"] = (
            _unknown_gate("cost_stress_missing", refs=refs)
            if evidence.cost_stress_multiplier is None or evidence.cost_stress_return is None
            else _boolean_gate(
                evidence.cost_stress_multiplier >= policy.min_stress_multiplier
                and evidence.cost_stress_return >= 0,
                reason="cost_stress_failed",
                refs=refs,
            )
        )
        gates["regime_coverage"] = _boolean_gate(
            len(evidence.regime_results) >= policy.min_regime_count,
            reason="regime_coverage_below_minimum",
            refs=refs,
        )
        gates["regime_label_timing"] = ValidationGateV2(
            outcome=(
                "passed"
                if evidence.regime_label_mode == "point_in_time"
                else "unknown"
                if evidence.regime_label_mode == "unknown"
                else "failed"
            ),
            required=False,
            reasons=(
                []
                if evidence.regime_label_mode == "point_in_time"
                else [f"regime_label_mode:{evidence.regime_label_mode}"]
            ),
            source_refs=refs,
        )
        if family.candidate_kind == "discovery":
            gates["novelty_falsification"] = _required_optional_boolean_gate(
                evidence.novelty_falsification_passed,
                "novelty_falsification_unknown",
                "novelty_falsification_failed",
                refs,
            )
        else:
            gates["novelty_falsification"] = ValidationGateV2(
                outcome="not_applicable", required=False
            )
        return gates


def _boolean_gate(
    value: bool, *, reason: str = "gate_failed", refs: list[str]
) -> ValidationGateV2:
    return ValidationGateV2(
        outcome="passed" if value else "failed",
        reasons=[] if value else [reason],
        source_refs=refs,
    )


def _unknown_gate(reason: str, *, refs: list[str]) -> ValidationGateV2:
    return ValidationGateV2(outcome="unknown", reasons=[reason], source_refs=refs)


def _required_optional_boolean_gate(
    value: bool | None, unknown: str, failed: str, refs: list[str]
) -> ValidationGateV2:
    if value is None:
        return _unknown_gate(unknown, refs=refs)
    return _boolean_gate(value, reason=failed, refs=refs)


def _optional_boolean_gate(
    value: bool | None, unknown: str, refs: list[str]
) -> ValidationGateV2:
    gate = (
        _unknown_gate(unknown, refs=refs)
        if value is None
        else _boolean_gate(value, refs=refs)
    )
    gate.required = False
    return gate


def _threshold_min(
    value: Decimal | int | None, minimum: Decimal | int, name: str, refs: list[str]
) -> ValidationGateV2:
    if value is None:
        return _unknown_gate(f"{name}_missing", refs=refs)
    return _boolean_gate(value >= minimum, reason=f"{name}_below_minimum", refs=refs)


def _threshold_max(
    value: Decimal | None, maximum: Decimal, name: str, refs: list[str]
) -> ValidationGateV2:
    if value is None:
        return _unknown_gate(f"{name}_missing", refs=refs)
    return _boolean_gate(value <= maximum, reason=f"{name}_above_maximum", refs=refs)


def _parameter_gate(
    values: list[Decimal],
    baseline: Decimal,
    max_degradation: Decimal,
    refs: list[str],
) -> ValidationGateV2:
    if baseline <= 0:
        return _boolean_gate(False, reason="locked_oos_return_non_positive", refs=refs)
    floor = baseline * (Decimal("1") - max_degradation / Decimal("100"))
    return _boolean_gate(
        min(values) >= floor,
        reason="parameter_neighborhood_spike",
        refs=refs,
    )


def _row_to_dict(row: UnifiedStrategyValidation, *, replay: str = "") -> dict[str, Any]:
    decision = dict(row.decision_json)
    return {
        "id": row.id,
        **decision,
        "manifest_id": row.manifest_id,
        "experiment_execution_id": row.experiment_execution_id,
        "policy": dict(row.policy_json),
        "trial_family": dict(row.trial_family_json),
        "evidence": dict(row.evidence_json),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "mutation_boundary": {
            "paper_writes": False,
            "live_writes": False,
            "order_writes": False,
            "capital_writes": False,
        },
        "replay": replay,
    }


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
