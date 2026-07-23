"""Unified, fail-closed validation contracts for all strategy candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GateOutcome = Literal["passed", "failed", "unknown", "not_applicable"]
DecisionStatus = Literal["validated", "rejected", "needs_data", "needs_review"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("validation timestamps must include a timezone")
    return value.astimezone(UTC)


class ValidationPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["validation_policy.v2"] = "validation_policy.v2"
    walk_forward_folds: int = Field(default=3, ge=2, le=12)
    purge_bars: int = Field(default=1, ge=0, le=10_000)
    embargo_bars: int = Field(default=1, ge=0, le=10_000)
    min_trade_count: int = Field(default=30, ge=1, le=100_000)
    max_drawdown_pct: Decimal = Field(default=Decimal("20"), gt=0, le=100)
    max_tail_loss_pct: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    min_probabilistic_sharpe: Decimal = Field(default=Decimal("0.75"), ge=0, le=1)
    min_deflated_sharpe: Decimal = Field(default=Decimal("0.60"), ge=0, le=1)
    max_overfit_probability: Decimal = Field(default=Decimal("0.20"), ge=0, le=1)
    max_parameter_degradation_pct: Decimal = Field(default=Decimal("50"), ge=0, le=100)
    min_regime_count: int = Field(default=2, ge=1, le=32)
    min_stress_multiplier: Decimal = Field(default=Decimal("1.5"), gt=1, le=10)
    require_funding: bool = True
    require_capacity: bool = True
    require_artifacts: bool = True
    missing_data_policy: Literal["needs_data"] = "needs_data"


class TrialAttemptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trial_id: str = Field(min_length=1, max_length=128)
    status: Literal["completed", "failed", "rejected", "unknown"]
    selected: bool = False
    result_ref: str = Field(default="", max_length=512)


class TrialFamilyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["trial_family.v1"] = "trial_family.v1"
    family_id: str = Field(pattern=r"^[a-z0-9_:-]{3,128}$")
    candidate_kind: Literal["evolution", "discovery"]
    candidate_id: str = Field(min_length=1, max_length=32)
    manifest_id: str = Field(min_length=1, max_length=32)
    experiment_execution_id: str = Field(min_length=1, max_length=32)
    candidate_frozen_at: datetime
    locked_oos_first_accessed_at: datetime | None = None
    attempts: list[TrialAttemptV1] = Field(min_length=1, max_length=10_000)
    declared_attempt_count: int = Field(ge=1, le=10_000)

    @field_validator("candidate_frozen_at", "locked_oos_first_accessed_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_attempts(self) -> TrialFamilyV1:
        ids = [item.trial_id for item in self.attempts]
        if len(ids) != len(set(ids)):
            raise ValueError("trial family contains duplicate trial ids")
        if sum(item.selected for item in self.attempts) > 1:
            raise ValueError("trial family may select at most one attempt")
        return self


class UnifiedValidationEvidenceV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["unified_validation_evidence.v2"] = (
        "unified_validation_evidence.v2"
    )
    source_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    result_refs: list[str] = Field(min_length=1, max_length=512)
    artifact_refs: list[str] = Field(default_factory=list, max_length=512)
    real_data: bool
    chronological_split: bool
    locked_oos_complete: bool
    purge_embargo_applied: bool
    costs_complete: bool
    funding_included: bool | None = None
    capacity_assessed: bool | None = None
    locked_oos_return: Decimal | None = None
    trade_count: int | None = Field(default=None, ge=0)
    max_drawdown_pct: Decimal | None = Field(default=None, ge=0, le=100)
    tail_loss_pct: Decimal | None = Field(default=None, ge=0, le=100)
    probabilistic_sharpe: Decimal | None = Field(default=None, ge=0, le=1)
    deflated_sharpe: Decimal | None = Field(default=None, ge=0, le=1)
    overfit_probability: Decimal | None = Field(default=None, ge=0, le=1)
    walk_forward_returns: list[Decimal] = Field(default_factory=list, max_length=64)
    parameter_neighbor_returns: list[Decimal] = Field(default_factory=list, max_length=128)
    cost_stress_multiplier: Decimal | None = Field(default=None, ge=1, le=10)
    cost_stress_return: Decimal | None = None
    regime_results: dict[str, Decimal] = Field(default_factory=dict, max_length=32)
    regime_label_mode: Literal["point_in_time", "ex_post_research", "unknown"] = "unknown"
    novelty_falsification_passed: bool | None = None

    @field_validator("result_refs", "artifact_refs")
    @classmethod
    def normalize_refs(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})


class UnifiedValidationRequestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: ValidationPolicyV2
    trial_family: TrialFamilyV1
    evidence: UnifiedValidationEvidenceV2
    idempotency_key: str = Field(min_length=8, max_length=128)


class ValidationGateV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: GateOutcome
    required: bool = True
    reasons: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class ValidationDecisionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["validation_decision.v2"] = "validation_decision.v2"
    validation_version: int = Field(ge=1)
    candidate_kind: Literal["evolution", "discovery"]
    candidate_id: str
    trial_family_id: str
    status: DecisionStatus
    gates: dict[str, ValidationGateV2]
    unknowns: list[str]
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    verified_by: Literal["deterministic_validation_verifier_v2"] = (
        "deterministic_validation_verifier_v2"
    )
    execution_authorized: Literal[False] = False


def canonical_payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    return cast(dict[str, Any], _canonical(raw))


def digest(value: BaseModel | dict[str, Any]) -> str:
    body = json.dumps(canonical_payload(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value
