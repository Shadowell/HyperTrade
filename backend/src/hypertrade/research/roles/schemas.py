"""Strict planner and evidence-draft outputs for research roles."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RoleToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class RoleToolPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_calls: list[RoleToolCall] = Field(default_factory=list, max_length=8)
    rationale: str = Field(default="", max_length=1_000)


class EvidenceDraftBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: Literal["fact", "inference", "counter_evidence", "data_gap"]
    claim: str = Field(min_length=3, max_length=4_000)
    confidence: float = Field(ge=0.0, le=1.0)
    valid_for_seconds: int | None = Field(default=None, ge=60, le=604_800)
    source_ids: list[str] = Field(default_factory=list, max_length=32)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    opposing_evidence_ids: list[str] = Field(default_factory=list, max_length=64)

    @field_validator(
        "source_ids", "supporting_evidence_ids", "opposing_evidence_ids"
    )
    @classmethod
    def normalize_ids(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})


class FactDraft(EvidenceDraftBase):
    evidence_type: Literal["fact"] = "fact"

    @model_validator(mode="after")
    def require_source(self) -> FactDraft:
        if not self.source_ids:
            raise ValueError("fact draft requires source_ids")
        return self


class InferenceDraft(EvidenceDraftBase):
    evidence_type: Literal["inference"] = "inference"
    inference_method: str = Field(min_length=3, max_length=1_000)

    @model_validator(mode="after")
    def require_support(self) -> InferenceDraft:
        if not self.supporting_evidence_ids:
            raise ValueError("inference draft requires supporting_evidence_ids")
        return self


class CounterEvidenceDraft(EvidenceDraftBase):
    evidence_type: Literal["counter_evidence"] = "counter_evidence"
    challenged_evidence_ids: list[str] = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=3, max_length=1_000)

    @field_validator("challenged_evidence_ids")
    @classmethod
    def normalize_challenged_ids(cls, values: list[str]) -> list[str]:
        normalized = sorted({str(value).strip() for value in values if str(value).strip()})
        if not normalized:
            raise ValueError("counter evidence draft requires challenged evidence ids")
        return normalized


class DataGapDraft(EvidenceDraftBase):
    evidence_type: Literal["data_gap"] = "data_gap"
    expected_sources: list[
        Literal["tool", "bitpro_result", "snapshot", "rag", "memory"]
    ] = Field(min_length=1, max_length=16)
    remediation: str = Field(min_length=3, max_length=1_000)


EvidenceDraft = Annotated[
    FactDraft | InferenceDraft | CounterEvidenceDraft | DataGapDraft,
    Field(discriminator="evidence_type"),
]


class RoleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=3, max_length=4_000)
    evidence: list[EvidenceDraft] = Field(min_length=1, max_length=8)
    strategy_spec: dict[str, Any] | None = None


class RoleUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    available: bool
    summary: str = Field(max_length=4_000)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    artifact_ref: dict[str, Any] = Field(default_factory=dict)
    error_code: str = Field(default="", max_length=128)
