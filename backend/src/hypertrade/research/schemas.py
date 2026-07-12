"""Schema contracts for the Sprint 81 research-program boundary."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ResearchBudget(BaseModel):
    max_candidates_per_day: int = Field(default=3, ge=1, le=50)
    max_variants_per_candidate: int = Field(default=3, ge=1, le=10)
    max_concurrent_backtests: int = Field(default=1, ge=1, le=5)
    max_total_backtests_per_day: int = Field(default=9, ge=1, le=100)

    @model_validator(mode="after")
    def validate_total_backtests(self) -> ResearchBudget:
        minimum = self.max_candidates_per_day * self.max_variants_per_candidate
        if self.max_total_backtests_per_day < minimum:
            raise ValueError("max_total_backtests_per_day must cover candidate variant budget")
        return self


class ValidationPolicy(BaseModel):
    min_candle_count: int = Field(default=500, ge=100, le=100_000)
    in_sample_bars: int = Field(default=300, ge=50, le=50_000)
    validation_bars: int = Field(default=100, ge=25, le=25_000)
    locked_out_of_sample_bars: int = Field(default=100, ge=25, le=25_000)
    min_trade_count: int = Field(default=20, ge=1, le=10_000)
    max_drawdown_pct: float = Field(default=20.0, gt=0.0, le=100.0)
    fee_bps: float = Field(default=10.0, ge=0.0, le=1_000.0)
    slippage_bps: float = Field(default=5.0, ge=0.0, le=1_000.0)
    include_funding: bool = True

    @model_validator(mode="after")
    def validate_window_coverage(self) -> ValidationPolicy:
        required = self.in_sample_bars + self.validation_bars + self.locked_out_of_sample_bars
        if self.min_candle_count < required:
            raise ValueError("min_candle_count must cover all chronological validation windows")
        return self


class ResearchMandateCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    symbols: list[str] = Field(min_length=1, max_length=20)
    timeframes: list[str] = Field(min_length=1, max_length=8)
    strategy_categories: list[str] = Field(min_length=1, max_length=8)
    market_type: str = Field(default="SWAP", min_length=2, max_length=32)
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    validation: ValidationPolicy = Field(default_factory=ValidationPolicy)
    paper_promotion_mode: Literal["manual_approval"] = "manual_approval"
    live_mode: Literal["disabled"] = "disabled"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("symbols", "timeframes", "strategy_categories")
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            cleaned = str(value).strip().upper()
            if not cleaned:
                continue
            if cleaned not in normalized:
                normalized.append(cleaned)
        if not normalized:
            raise ValueError("at least one non-empty value is required")
        return normalized

    @field_validator("market_type")
    @classmethod
    def normalize_market_type(cls, value: str) -> str:
        return value.strip().upper()


class StrategySpecDraft(BaseModel):
    schema_version: Literal["research_strategy_spec.v1"] = "research_strategy_spec.v1"
    mandate_id: str = Field(min_length=1, max_length=32)
    strategy_key: str = Field(pattern=r"^[a-z0-9_]{3,128}$")
    title: str = Field(min_length=3, max_length=160)
    hypothesis: str = Field(min_length=10, max_length=2_000)
    symbols: list[str] = Field(min_length=1, max_length=20)
    timeframes: list[str] = Field(min_length=1, max_length=8)
    strategy_category: str = Field(min_length=2, max_length=64)
    entry_logic: str = Field(min_length=10, max_length=2_000)
    exit_logic: str = Field(min_length=10, max_length=2_000)
    risk_conditions: list[str] = Field(min_length=1, max_length=12)
    data_requirements: list[str] = Field(min_length=1, max_length=12)
    parameter_bounds: dict[str, dict[str, float]] = Field(default_factory=dict)
    invalidation_conditions: list[str] = Field(min_length=1, max_length=12)

    @field_validator("symbols", "timeframes")
    @classmethod
    def normalize_scope(cls, values: list[str]) -> list[str]:
        return ResearchMandateCreate.normalize_list(values)

    @field_validator("strategy_category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned:
            raise ValueError("strategy_category must not be blank")
        return cleaned


class ResearchJobCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=4_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    strategy_spec: StrategySpecDraft | None = None
    source_run_id: str = Field(default="", max_length=32)

    @field_validator("prompt", "idempotency_key")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned


def strategy_key_from_prompt(*, category: str, symbol: str, timeframe: str, prompt: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")
    suffix = words[:40] or "candidate"
    return "_".join(
        [
            "research",
            re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_") or "strategy",
            re.sub(r"[^a-z0-9]+", "_", symbol.lower()).strip("_") or "symbol",
            re.sub(r"[^a-z0-9]+", "_", timeframe.lower()).strip("_") or "bar",
            suffix,
        ]
    )[:128]
