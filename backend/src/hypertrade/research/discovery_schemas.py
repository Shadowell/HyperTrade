"""Bounded contracts for autonomous discovery of new strategy families."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hypertrade.research.experiment_schemas import (
    ExperimentCosts,
    ExperimentVersions,
    ExperimentWindow,
)
from hypertrade.research.schemas import StrategySpecDraft

StrategyFamily = Literal[
    "trend",
    "mean_reversion",
    "breakout",
    "carry_funding",
    "basis",
    "relative_strength",
    "volatility_liquidity",
    "multi_timeframe",
]


def _clean(value: str) -> str:
    return " ".join(value.split())


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("discovery timestamps must include a timezone")
    return value.astimezone(UTC)


class DiscoveryMandateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["discovery_mandate.v1"] = "discovery_mandate.v1"
    research_mandate_id: str = Field(min_length=1, max_length=32)
    evidence_ids: list[str] = Field(min_length=1, max_length=128)
    symbols: list[str] = Field(min_length=1, max_length=20)
    timeframes: list[str] = Field(min_length=1, max_length=8)
    market_type: str = Field(min_length=2, max_length=32)
    data_sources: list[Literal["tool", "bitpro_result", "snapshot"]] = Field(
        min_length=1, max_length=3
    )
    strategy_families: list[StrategyFamily] = Field(min_length=1, max_length=8)
    forbidden_features: list[str] = Field(default_factory=list, max_length=64)
    max_phenomena: int = Field(default=5, ge=1, le=20)
    max_hypotheses: int = Field(default=5, ge=1, le=20)
    max_candidates: int = Field(default=3, ge=1, le=10)
    max_model_calls: int = Field(default=10, ge=0, le=50)
    max_tool_calls: int = Field(default=20, ge=0, le=100)
    max_wall_seconds: int = Field(default=300, ge=1, le=3_600)
    freshness_hours: int = Field(default=24, ge=1, le=24 * 30)
    exploration_ratio: Decimal = Field(default=Decimal("0.25"), ge=0, le=1)
    deterministic_seed: int = Field(ge=0, le=2**31 - 1)

    @field_validator("evidence_ids", "forbidden_features")
    @classmethod
    def normalize_ids(cls, values: list[str]) -> list[str]:
        return sorted({_clean(str(value)).casefold() for value in values if str(value).strip()})

    @field_validator("symbols", "timeframes", "market_type")
    @classmethod
    def normalize_scope(cls, value: Any) -> Any:
        if isinstance(value, list):
            return sorted({str(item).strip().upper() for item in value if str(item).strip()})
        return str(value).strip().upper()

    @field_validator("strategy_families", "data_sources")
    @classmethod
    def normalize_enum_lists(cls, values: list[str]) -> list[str]:
        return sorted(set(values))


class MarketPhenomenonV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["market_phenomenon.v1"] = "market_phenomenon.v1"
    phenomenon_key: str = Field(pattern=r"^[a-z0-9_]{3,128}$")
    description: str = Field(min_length=10, max_length=2_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=64)
    symbols: list[str] = Field(min_length=1, max_length=20)
    timeframes: list[str] = Field(min_length=1, max_length=8)
    window_start: datetime
    window_end: datetime
    observed_at: datetime
    statistics: dict[str, Decimal] = Field(min_length=1, max_length=64)
    regimes: list[str] = Field(default_factory=list, max_length=16)
    alternative_explanations: list[str] = Field(min_length=1, max_length=16)
    unknowns: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return _clean(value)

    @field_validator("evidence_ids", "regimes", "alternative_explanations", "unknowns")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return sorted({_clean(str(value)) for value in values if str(value).strip()})

    @field_validator("symbols", "timeframes")
    @classmethod
    def normalize_scope(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip().upper() for value in values if str(value).strip()})

    @field_validator("window_start", "window_end", "observed_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_window(self) -> MarketPhenomenonV1:
        if self.window_end <= self.window_start:
            raise ValueError("phenomenon window_end must be after window_start")
        if self.observed_at < self.window_end:
            raise ValueError("phenomenon cannot be observed before its window ends")
        return self


class AlphaHypothesisV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["alpha_hypothesis.v1"] = "alpha_hypothesis.v1"
    hypothesis_key: str = Field(pattern=r"^[a-z0-9_]{3,128}$")
    hypothesis_version: int = Field(default=1, ge=1)
    strategy_family: StrategyFamily
    phenomenon_keys: list[str] = Field(min_length=1, max_length=16)
    economic_rationale: str = Field(min_length=10, max_length=2_000)
    features: list[str] = Field(min_length=1, max_length=32)
    expected_regimes: list[str] = Field(min_length=1, max_length=16)
    failure_conditions: list[str] = Field(min_length=1, max_length=16)
    required_data: list[str] = Field(min_length=1, max_length=32)
    falsification_criteria: list[str] = Field(min_length=1, max_length=16)
    distinguishing_dimensions: list[str] = Field(default_factory=list, max_length=16)
    strategy_spec: StrategySpecDraft
    locked_oos_visible: Literal[False] = False
    frozen_at: datetime

    @field_validator(
        "phenomenon_keys",
        "features",
        "expected_regimes",
        "failure_conditions",
        "required_data",
        "falsification_criteria",
        "distinguishing_dimensions",
    )
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return sorted({_clean(str(value)) for value in values if str(value).strip()})

    @field_validator("economic_rationale")
    @classmethod
    def normalize_rationale(cls, value: str) -> str:
        return _clean(value)

    @field_validator("frozen_at")
    @classmethod
    def normalize_frozen_at(cls, value: datetime) -> datetime:
        return _utc(value)


class NoveltyComparisonV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    existing_version_id: str = Field(min_length=1, max_length=32)
    return_correlation: Decimal | None = Field(default=None, ge=Decimal("-1"), le=Decimal("1"))
    signal_similarity: Decimal | None = Field(default=None, ge=0, le=1)
    regime_overlap: Decimal | None = Field(default=None, ge=0, le=1)


class StrategyNoveltyReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_novelty_report.v1"] = "strategy_novelty_report.v1"
    status: Literal["novel", "existing_strategy_variant", "unknown"]
    reasons: list[str]
    compared_version_ids: list[str]
    code_fingerprint_match: bool = False
    max_return_correlation: Decimal | None = None
    max_signal_similarity: Decimal | None = None
    unknowns: list[str] = Field(default_factory=list)


class DiscoveryExperimentContextV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: str = Field(min_length=2, max_length=32)
    market_type: str = Field(min_length=2, max_length=32)
    windows: list[ExperimentWindow] = Field(min_length=1, max_length=32)
    costs: ExperimentCosts
    data_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    versions: ExperimentVersions


class DiscoveryProposalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phenomenon: MarketPhenomenonV1
    hypothesis: AlphaHypothesisV1
    experiment: DiscoveryExperimentContextV1
    strategy_code: str = Field(min_length=20, max_length=100_000)
    template_version: str = Field(min_length=1, max_length=128)
    novelty_comparisons: list[NoveltyComparisonV1] = Field(default_factory=list, max_length=500)
    model_calls: int = Field(default=0, ge=0, le=50)
    tool_calls: int = Field(default=0, ge=0, le=100)


class DiscoveryRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandate: DiscoveryMandateV1
    proposals: list[DiscoveryProposalV1] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=128)


class DiscoveryCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_discovery_candidate.v1"] = (
        "strategy_discovery_candidate.v1"
    )
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    phenomenon_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    hypothesis_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    hypothesis_version: int = Field(ge=1)
    status: Literal[
        "rejected",
        "duplicate",
        "needs_data",
        "sandbox_failed",
        "budget_exhausted",
        "candidate_ready",
    ]
    novelty: StrategyNoveltyReportV1
    strategy_code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    strategy_code_ref: str = Field(default="", max_length=512)
    bitpro_strategy_id: str = Field(default="", max_length=64)
    manifest_id: str = Field(default="", max_length=32)
    experiment_execution_id: str = Field(default="", max_length=32)
    strategy_version_id: str = Field(default="", max_length=32)
    evidence_ids: list[str]
    rejection_reasons: list[str]
    prompt_template_version: str
    data_snapshot_hash: str
    deterministic_seed: int


def canonical_payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    return cast(dict[str, Any], _canonical(raw))


def digest(value: BaseModel | dict[str, Any]) -> str:
    body = json.dumps(canonical_payload(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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
