"""Strict contracts for bounded hypothetical portfolio research."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ShadowPortfolioBuildV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["shadow_portfolio_build.v1"] = "shadow_portfolio_build.v1"
    cohort_snapshot_id: str = Field(default="", max_length=32)
    hypothetical_notional: Decimal = Field(
        default=Decimal("100000"), gt=Decimal("0"), le=Decimal("10000000")
    )
    max_strategy_weight: Decimal = Field(
        default=Decimal("0.60"), ge=Decimal("0.10"), le=Decimal("0.75")
    )
    fee_bps: Decimal = Field(default=Decimal("10"), ge=Decimal("0"), le=Decimal("100"))
    slippage_bps: Decimal = Field(
        default=Decimal("15"), ge=Decimal("0"), le=Decimal("200")
    )
    stress_loss_pct: Decimal = Field(
        default=Decimal("20"), gt=Decimal("0"), le=Decimal("80")
    )
    review_valid_days: int = Field(default=7, ge=1, le=30)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ShadowPortfolioReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["shadow_portfolio_review.v1"] = "shadow_portfolio_review.v1"
    scenario_id: str = Field(min_length=1, max_length=64)
    decision: Literal["accept", "reject", "hold"]
    reason: str = Field(min_length=3, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
