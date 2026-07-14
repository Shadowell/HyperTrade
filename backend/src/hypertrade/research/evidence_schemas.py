"""Versioned, source-bound contracts for research evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EVIDENCE_SCHEMA_VERSION: Literal["research_evidence.v2"] = "research_evidence.v2"
EvidenceType = Literal["fact", "inference", "counter_evidence", "data_gap"]
EvidenceStatus = Literal["active", "expired", "superseded", "rejected"]
SourceType = Literal["tool", "bitpro_result", "snapshot", "rag", "memory"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must include a timezone")
    return value.astimezone(UTC)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


class EvidenceScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(default_factory=list, max_length=32)
    timeframes: list[str] = Field(default_factory=list, max_length=16)
    market_type: str = Field(default="", max_length=32)
    mandate_id: str = Field(default="", max_length=32)
    strategy_key: str = Field(default="", max_length=128)
    window_start: datetime | None = None
    window_end: datetime | None = None

    @field_validator("symbols", "timeframes")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip().upper() for value in values if str(value).strip()})

    @field_validator("market_type")
    @classmethod
    def normalize_market_type(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("mandate_id", "strategy_key")
    @classmethod
    def normalize_identifiers(cls, value: str) -> str:
        return value.strip()

    @field_validator("window_start", "window_end")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def validate_window(self) -> EvidenceScope:
        if self.window_start and self.window_end and self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")
        return self


class EvidenceSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    source_id: str = Field(min_length=1, max_length=256)
    tool_name: str = Field(default="", max_length=128)
    observed_at: datetime
    content_hash: str = Field(default="", max_length=128)
    availability: Literal["available", "unavailable", "unknown"] = "available"

    @field_validator("source_id", "tool_name", "content_hash")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("observed_at")
    @classmethod
    def normalize_observed_at(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_source_contract(self) -> EvidenceSourceRef:
        if self.source_type == "tool" and not self.tool_name:
            raise ValueError("tool sources require tool_name")
        if self.source_type in {"bitpro_result", "snapshot"} and not self.content_hash:
            raise ValueError(f"{self.source_type} sources require content_hash")
        return self


class EvidenceInputBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["research_evidence.v2"] = EVIDENCE_SCHEMA_VERSION
    evidence_type: EvidenceType
    claim: str = Field(min_length=3, max_length=8_000)
    scope: EvidenceScope = Field(default_factory=EvidenceScope)
    sources: list[EvidenceSourceRef] = Field(default_factory=list, max_length=64)
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    as_of: datetime
    valid_until: datetime | None = None
    task_id: str = Field(default="", max_length=32)
    node_run_id: str = Field(default="", max_length=32)
    role_key: str = Field(default="", max_length=96)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=128)
    opposing_evidence_ids: list[str] = Field(default_factory=list, max_length=128)

    @field_validator("claim")
    @classmethod
    def normalize_claim(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if len(cleaned) < 3:
            raise ValueError("claim must not be blank")
        return cleaned

    @field_validator("task_id", "node_run_id", "role_key")
    @classmethod
    def normalize_refs(cls, value: str) -> str:
        return value.strip()

    @field_validator("supporting_evidence_ids", "opposing_evidence_ids")
    @classmethod
    def normalize_evidence_ids(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    @field_validator("as_of", "valid_until")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return _utc(value) if value is not None else None

    @field_validator("sources")
    @classmethod
    def normalize_sources(cls, values: list[EvidenceSourceRef]) -> list[EvidenceSourceRef]:
        deduplicated = {
            (
                value.source_type,
                value.source_id,
                value.tool_name,
                value.observed_at.isoformat(),
                value.content_hash,
            ): value
            for value in values
        }
        return [deduplicated[key] for key in sorted(deduplicated)]

    @model_validator(mode="after")
    def validate_validity_window(self) -> EvidenceInputBase:
        if self.valid_until is not None and self.valid_until <= self.as_of:
            raise ValueError("valid_until must be after as_of")
        return self


class FactEvidenceInput(EvidenceInputBase):
    evidence_type: Literal["fact"] = "fact"


class InferenceEvidenceInput(EvidenceInputBase):
    evidence_type: Literal["inference"] = "inference"
    inference_method: str = Field(min_length=3, max_length=1_000)

    @field_validator("inference_method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return _clean_text(value)

    @model_validator(mode="after")
    def validate_inference(self) -> InferenceEvidenceInput:
        if not self.supporting_evidence_ids:
            raise ValueError("inference requires supporting_evidence_ids")
        if not self.role_key:
            raise ValueError("inference requires role_key")
        return self


class CounterEvidenceInput(EvidenceInputBase):
    evidence_type: Literal["counter_evidence"] = "counter_evidence"
    challenged_evidence_ids: list[str] = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=3, max_length=2_000)

    @field_validator("challenged_evidence_ids")
    @classmethod
    def normalize_challenged_ids(cls, values: list[str]) -> list[str]:
        normalized = sorted({str(value).strip() for value in values if str(value).strip()})
        if not normalized:
            raise ValueError("counter evidence requires a challenged evidence id")
        return normalized

    @field_validator("rationale")
    @classmethod
    def normalize_rationale(cls, value: str) -> str:
        return _clean_text(value)


class DataGapEvidenceInput(EvidenceInputBase):
    evidence_type: Literal["data_gap"] = "data_gap"
    expected_sources: list[SourceType] = Field(min_length=1, max_length=16)
    remediation: str = Field(min_length=3, max_length=2_000)

    @field_validator("expected_sources")
    @classmethod
    def normalize_expected_sources(cls, values: list[SourceType]) -> list[SourceType]:
        return cast(list[SourceType], sorted(set(values)))

    @field_validator("remediation")
    @classmethod
    def normalize_remediation(cls, value: str) -> str:
        return _clean_text(value)


ResearchEvidenceInput = Annotated[
    FactEvidenceInput | InferenceEvidenceInput | CounterEvidenceInput | DataGapEvidenceInput,
    Field(discriminator="evidence_type"),
]


class EvidenceSupersedeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: ResearchEvidenceInput
    reason: str = Field(min_length=3, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return _clean_text(value)


class EvidenceLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return _clean_text(value)


def canonical_evidence_payload(payload: EvidenceInputBase) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _canonical_value(payload.model_dump(mode="python", exclude_none=False)),
    )


def canonical_evidence_json(payload: EvidenceInputBase) -> str:
    return json.dumps(
        canonical_evidence_payload(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def evidence_content_hash(payload: EvidenceInputBase) -> str:
    return hashlib.sha256(canonical_evidence_json(payload).encode("utf-8")).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = _utc(value).isoformat(timespec="microseconds")
        return normalized.replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value
