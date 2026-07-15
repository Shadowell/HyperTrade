"""Strict contracts for paper cohort comparison and human label review."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaperCohortBuildV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["paper_cohort_build.v1"] = "paper_cohort_build.v1"
    observation_window_id: str = Field(default="", max_length=32)
    strategy_card_ids: list[str] = Field(default_factory=list, max_length=30)
    horizon_days: Literal[30, 60, 90] = 30
    min_sample_count: int = Field(default=20, ge=5, le=500)
    label_valid_days: int = Field(default=7, ge=1, le=30)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def unique_cards(self) -> PaperCohortBuildV1:
        if len(set(self.strategy_card_ids)) != len(self.strategy_card_ids):
            raise ValueError("strategy_card_ids must be unique")
        return self


class PaperCohortLabelDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["paper_cohort_label_decision.v1"] = (
        "paper_cohort_label_decision.v1"
    )
    proposal_id: str = Field(min_length=1, max_length=64)
    decision: Literal["accept", "reject", "hold"]
    reason: str = Field(min_length=3, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
