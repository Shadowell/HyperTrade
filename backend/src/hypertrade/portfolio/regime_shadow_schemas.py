"""Strict point-in-time contracts for regime-aware shadow allocation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RegimeName = Literal[
    "trend",
    "range",
    "high_volatility",
    "stress",
    "liquidity",
    "correlation",
]
AllocationTemplate = Literal[
    "equal_weight",
    "inverse_volatility",
    "capped_risk_contribution",
    "constrained_risk_adjusted",
]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("regime timestamps must include a timezone")
    return value.astimezone(UTC)


class MarketRegimeEvidenceV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["market_regime_evidence.v2"] = "market_regime_evidence.v2"
    as_of: datetime
    available_at: datetime
    source_refs: list[str] = Field(min_length=1, max_length=100)
    source_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    trend_score: Decimal | None = Field(default=None, ge=0, le=1)
    range_score: Decimal | None = Field(default=None, ge=0, le=1)
    high_volatility_score: Decimal | None = Field(default=None, ge=0, le=1)
    stress_score: Decimal | None = Field(default=None, ge=0, le=1)
    liquidity_score: Decimal | None = Field(default=None, ge=0, le=1)
    correlation_score: Decimal | None = Field(default=None, ge=0, le=1)
    ex_post_label: str = Field(default="", max_length=64)

    @field_validator("as_of", "available_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @field_validator("source_refs")
    @classmethod
    def normalize_refs(cls, values: list[str]) -> list[str]:
        return sorted({value.strip() for value in values if value.strip()})

    @model_validator(mode="after")
    def no_lookahead(self) -> MarketRegimeEvidenceV2:
        if self.available_at > self.as_of:
            raise ValueError("regime evidence was not available at decision time")
        return self


class MarketRegimeCaptureV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: MarketRegimeEvidenceV2
    freshness_minutes: int = Field(default=1440, ge=1, le=10080)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ShadowAllocationPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["shadow_allocation_policy.v2"] = (
        "shadow_allocation_policy.v2"
    )
    templates: list[AllocationTemplate] = Field(min_length=1, max_length=4)
    hypothetical_notional: Decimal = Field(gt=0, le=Decimal("10000000"))
    min_members: int = Field(default=2, ge=2, le=20)
    max_members: int = Field(default=8, ge=2, le=20)
    max_strategy_weight: Decimal = Field(ge=Decimal("0.05"), le=Decimal("0.75"))
    max_symbol_weight: Decimal = Field(ge=Decimal("0.05"), le=Decimal("1"))
    max_pair_correlation: Decimal = Field(ge=Decimal("-1"), le=Decimal("1"))
    max_turnover: Decimal = Field(ge=0, le=2)
    max_weight_delta: Decimal = Field(gt=0, le=1)
    max_estimated_cost_bps: Decimal = Field(ge=0, le=1000)
    entry_threshold: Decimal = Field(ge=0, le=1)
    exit_threshold: Decimal = Field(ge=0, le=1)
    confirmation_windows: int = Field(default=2, ge=1, le=10)
    minimum_dwell_hours: int = Field(default=24, ge=0, le=2160)
    cooldown_hours: int = Field(default=24, ge=0, le=2160)
    valid_minutes: int = Field(default=60, ge=5, le=10080)

    @field_validator("templates")
    @classmethod
    def normalize_templates(
        cls, values: list[AllocationTemplate]
    ) -> list[AllocationTemplate]:
        return sorted(set(values))

    @model_validator(mode="after")
    def valid_policy(self) -> ShadowAllocationPolicyV2:
        if self.exit_threshold >= self.entry_threshold:
            raise ValueError("exit_threshold must be below entry_threshold")
        if self.min_members > self.max_members:
            raise ValueError("min_members cannot exceed max_members")
        if Decimal(self.min_members) * self.max_strategy_weight < Decimal("1"):
            raise ValueError("minimum member count and strategy cap are infeasible")
        return self


class RegimeShadowBuildV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["regime_shadow_build.v2"] = "regime_shadow_build.v2"
    decision_at: datetime
    regime_snapshot_id: str = Field(min_length=1, max_length=32)
    cohort_snapshot_id: str = Field(min_length=1, max_length=32)
    previous_target_id: str = Field(default="", max_length=32)
    policy: ShadowAllocationPolicyV2
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("decision_at")
    @classmethod
    def normalize_decision_time(cls, value: datetime) -> datetime:
        return _utc(value)


def canonical_payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    return cast(dict[str, Any], _canonical(raw))


def digest(value: BaseModel | dict[str, Any]) -> str:
    encoded = json.dumps(
        canonical_payload(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


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
