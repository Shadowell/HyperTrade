"""Strict contracts for bounded portfolio observation evidence."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PortfolioObservationCaptureV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["portfolio_observation_capture.v1"] = (
        "portfolio_observation_capture.v1"
    )
    strategy_card_ids: list[str] = Field(default_factory=list, max_length=30)
    horizon_days: Literal[30, 60, 90] = 30
    bucket_minutes: Literal[5, 15, 30, 60, 240, 1440] = 60
    max_points: int = Field(default=500, ge=8, le=500)
    min_aligned_returns: int = Field(default=6, ge=5, le=100)
    freshness_minutes: int = Field(default=1_440, ge=5, le=10_080)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def valid_bounds(self) -> PortfolioObservationCaptureV1:
        if len(set(self.strategy_card_ids)) != len(self.strategy_card_ids):
            raise ValueError("strategy_card_ids must be unique")
        if self.min_aligned_returns >= self.max_points:
            raise ValueError("min_aligned_returns must be below max_points")
        return self


class PortfolioDataQualityV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["portfolio_data_quality.v1"] = "portfolio_data_quality.v1"
    status: Literal[
        "no_cards",
        "no_window",
        "source_unhealthy",
        "insufficient",
        "stale",
        "available",
    ]
    denominator: int = Field(ge=0)
    identity_count: int = Field(ge=0)
    fetched_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)
    insufficient_count: int = Field(ge=0)
    coverage_ratio: str
    gaps: list[str]


class PortfolioObservationWindowV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["portfolio_observation_window.v1"] = (
        "portfolio_observation_window.v1"
    )
    policy_version: Literal["portfolio_evidence_policy.v1"] = "portfolio_evidence_policy.v1"
    status: str
    horizon_days: int
    bucket_minutes: int
    window_start: str | None
    window_end: str
    source_refs: dict[str, Any]
    quality: PortfolioDataQualityV1
    strategies: list[dict[str, Any]]
    pairwise: list[dict[str, Any]]
    execution_authorized: Literal[False] = False
    raw_series_persisted: Literal[False] = False
