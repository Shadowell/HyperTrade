"""Bounded contracts for evolving an existing immutable strategy version."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ParameterRangeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum: Decimal
    maximum: Decimal

    @model_validator(mode="after")
    def validate_order(self) -> ParameterRangeV1:
        if self.maximum < self.minimum:
            raise ValueError("parameter maximum must be greater than or equal to minimum")
        return self


class EvolutionMandateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["evolution_mandate.v1"] = "evolution_mandate.v1"
    parent_version_id: str = Field(min_length=1, max_length=32)
    outcome_ids: list[str] = Field(min_length=1, max_length=64)
    evidence_record_ids: list[str] = Field(min_length=1, max_length=64)
    data_source_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    symbols: list[str] = Field(min_length=1, max_length=20)
    timeframes: list[str] = Field(min_length=1, max_length=8)
    parameter_ranges: dict[str, ParameterRangeV1] = Field(default_factory=dict, max_length=128)
    mutable_rule_slots: list[Literal["entry", "exit", "filter", "risk"]] = Field(
        default_factory=list, max_length=4
    )
    max_candidates: int = Field(default=5, ge=1, le=20)
    max_trials: int = Field(default=20, ge=1, le=100)
    max_model_calls: int = Field(default=10, ge=0, le=50)
    max_tool_calls: int = Field(default=20, ge=0, le=100)
    max_wall_seconds: int = Field(default=300, ge=1, le=3_600)
    freshness_hours: int = Field(default=24, ge=1, le=24 * 30)
    deterministic_seed: int = Field(ge=0, le=2**31 - 1)
    stop_conditions: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("outcome_ids", "evidence_record_ids", "mutable_rule_slots", "stop_conditions")
    @classmethod
    def normalize_identifiers(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @field_validator("symbols", "timeframes")
    @classmethod
    def normalize_scope(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip().upper() for value in values if str(value).strip()})

    @field_validator("parameter_ranges")
    @classmethod
    def normalize_ranges(
        cls, value: dict[str, ParameterRangeV1]
    ) -> dict[str, ParameterRangeV1]:
        return {str(key).strip(): item for key, item in sorted(value.items()) if str(key).strip()}


class CandidateProposalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_kind: Literal["parameter", "rule", "hybrid"]
    parameter_changes: dict[str, Decimal] = Field(default_factory=dict, max_length=128)
    rule_changes: dict[Literal["entry", "exit", "filter", "risk"], str] = Field(
        default_factory=dict, max_length=4
    )
    strategy_code_sha256: str = Field(default="", pattern=r"^$|^[a-f0-9]{64}$")
    strategy_code_ref: str = Field(default="", max_length=512)
    proposal_reason: str = Field(min_length=3, max_length=2_000)
    model_calls: int = Field(default=0, ge=0, le=50)
    tool_calls: int = Field(default=0, ge=0, le=100)

    @field_validator("parameter_changes")
    @classmethod
    def normalize_parameters(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        return {
            str(key).strip(): Decimal(str(item))
            for key, item in sorted(value.items())
            if str(key).strip()
        }

    @field_validator("rule_changes")
    @classmethod
    def normalize_rules(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            str(key): " ".join(str(item).split())
            for key, item in sorted(value.items())
            if str(item).strip()
        }

    @model_validator(mode="after")
    def validate_shape(self) -> CandidateProposalV1:
        if not self.parameter_changes and not self.rule_changes:
            raise ValueError("candidate proposal must change parameters or declared rules")
        if self.proposal_kind == "parameter" and self.rule_changes:
            raise ValueError("parameter proposal cannot include rule changes")
        if self.proposal_kind == "rule" and self.parameter_changes:
            raise ValueError("rule proposal cannot include parameter changes")
        if self.rule_changes and (not self.strategy_code_sha256 or not self.strategy_code_ref):
            raise ValueError("rule changes require candidate code digest and reference")
        return self


class EvolutionRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandate: EvolutionMandateV1
    proposals: list[CandidateProposalV1] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=128)


class StrategyDecayAssessmentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_decay_assessment.v1"] = (
        "strategy_decay_assessment.v1"
    )
    classification: Literal[
        "performance_decay",
        "regime_mismatch",
        "execution_drift",
        "data_quality",
        "unknown",
    ]
    status: Literal["actionable", "needs_review"]
    parent_version_id: str
    outcome_ids: list[str]
    evidence_record_ids: list[str]
    reasons: list[str]
    unknowns: list[str]
    as_of: datetime


class StrategyCandidateVersionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_candidate_version.v1"] = (
        "strategy_candidate_version.v1"
    )
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    parent_version_id: str
    candidate_version_id: str = ""
    manifest_id: str = ""
    experiment_execution_id: str = ""
    proposal_kind: Literal["parameter", "rule", "hybrid"]
    parameter_changes: dict[str, Decimal]
    rule_changes: dict[str, str]
    proposal_reason: str
    outcome_ids: list[str]
    evidence_record_ids: list[str]
    data_source_hash: str
    deterministic_seed: int
    status: Literal["accepted", "rejected", "budget_exhausted"]
    rejection_reasons: list[str]


def canonical_payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    return cast(dict[str, Any], _canonical(raw))


def digest(value: BaseModel | dict[str, Any]) -> str:
    encoded = json.dumps(
        canonical_payload(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evolution timestamps must be timezone-aware")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value
