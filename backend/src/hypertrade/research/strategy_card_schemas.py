"""Strict contracts for stable strategy identity and rebuildable Card V2 projections."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LifecycleStatus = Literal[
    "researching",
    "testing",
    "validation_rejected",
    "validated",
    "paper_pending",
    "observing",
    "degraded",
    "review_required",
    "retired",
]


class StrategyLineageV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_lineage.v1"] = "strategy_lineage.v1"
    id: str
    lineage_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    mandate_id: str
    strategy_key: str


class StrategyVersionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_version.v1"] = "strategy_version.v1"
    id: str
    lineage_id: str
    version_number: int = Field(ge=1)
    manifest_id: str
    manifest_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    strategy_spec_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class StrategyCardV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_card.v2"] = "strategy_card.v2"
    card_id: str
    lineage: StrategyLineageV1
    version: StrategyVersionV1
    lifecycle_status: LifecycleStatus
    completeness_score: str
    missing_fields: list[str]
    unknowns: list[str]
    strategy_key: str
    title: str
    hypothesis: str
    mandate_id: str
    allowed_symbols: list[str]
    allowed_timeframes: list[str]
    strategy_category: list[str]
    validation_status: str
    robustness_status: str
    paper_status: str
    evidence_freshness: str
    direction_exposure: str = "unknown"
    drawdown: str = "unknown"
    capacity: str = "unknown"
    liquidity: str = "unknown"
    memory_assertion_ids: list[str]
    coverage_flags: list[str]
    qualified_for_paper_review: bool
    source_refs: dict[str, Any]
    latest_decision: dict[str, Any]
    promotion_id: str = ""
    job_id: str = ""
    evidence_id: str = ""
    bitpro_strategy_id: str = ""
    declared_regime_fit: list[str] = Field(default_factory=lambda: ["unknown"])
    monitor_snapshot_id: str = ""
    monitor_drift: dict[str, Any] = Field(default_factory=dict)
    retirement_reason: str = ""
    robustness_validation_id: str = ""
    experiment_manifest_id: str = ""


class StrategyCardDecisionRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_card_decision_request.v1"] = (
        "strategy_card_decision_request.v1"
    )
    target_status: Literal["review_required", "retired"]
    decision: Literal["accept", "reject", "hold"]
    reason: str = Field(min_length=3, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("reason", "idempotency_key")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())
