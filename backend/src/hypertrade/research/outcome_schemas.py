"""Privacy-bounded contracts for settled strategy outcomes and reviewed lessons."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OutcomeType = Literal[
    "research_rejected",
    "backtest_validated",
    "paper_window_settled",
    "paper_degraded",
    "live_window_settled",
]

_FORBIDDEN_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "credentials",
    "orders",
    "password",
    "positions",
    "private_reasoning",
    "prompt",
    "raw_candles",
    "raw_result",
    "secret",
    "token",
    "trades",
}


class OutcomeWindowV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def normalize(self) -> OutcomeWindowV1:
        self.start = _utc(self.start)
        self.end = _utc(self.end)
        if self.end <= self.start:
            raise ValueError("outcome data window end must be after start")
        return self


class StrategyOutcomeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["strategy_outcome.v1"] = "strategy_outcome.v1"
    outcome_type: OutcomeType
    strategy_lineage_id: str = Field(min_length=1, max_length=32)
    strategy_version_id: str = Field(min_length=1, max_length=32)
    strategy_card_id: str = Field(min_length=1, max_length=64)
    manifest_id: str = Field(min_length=1, max_length=32)
    experiment_execution_id: str = Field(default="", max_length=32)
    mission_id: str = Field(min_length=1, max_length=32)
    evidence_ids: list[str] = Field(min_length=1, max_length=128)
    artifact_refs: list[str] = Field(default_factory=list, max_length=128)
    approval_ids: list[str] = Field(default_factory=list, max_length=64)
    tool_call_ids: list[str] = Field(default_factory=list, max_length=64)
    observation_window_id: str = Field(default="", max_length=32)
    parameters: dict[str, Decimal] = Field(default_factory=dict, max_length=128)
    data_window: OutcomeWindowV1
    cost_model: dict[str, str] = Field(default_factory=dict, max_length=64)
    regimes: list[str] = Field(min_length=1, max_length=32)
    metrics: dict[str, Decimal | str | int | bool] = Field(default_factory=dict, max_length=128)
    unknowns: list[str] = Field(default_factory=list, max_length=128)
    data_gaps: list[str] = Field(default_factory=list, max_length=128)
    failure_class: str = Field(default="", max_length=128)
    decision_snapshot: dict[str, str | int | bool] = Field(default_factory=dict, max_length=64)
    producer_lineage: dict[str, str] = Field(min_length=1, max_length=32)
    as_of: datetime
    settled_at: datetime
    corrects_id: str = Field(default="", max_length=32)
    supersedes_id: str = Field(default="", max_length=32)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator(
        "evidence_ids",
        "artifact_refs",
        "approval_ids",
        "tool_call_ids",
        "regimes",
        "unknowns",
        "data_gaps",
    )
    @classmethod
    def unique_sorted(cls, value: list[str]) -> list[str]:
        return sorted({" ".join(str(item).split()) for item in value if str(item).strip()})

    @model_validator(mode="after")
    def validate_settlement(self) -> StrategyOutcomeV1:
        self.as_of = _utc(self.as_of)
        self.settled_at = _utc(self.settled_at)
        if self.settled_at < self.as_of or self.as_of < self.data_window.end:
            raise ValueError("outcome must settle after its complete data window")
        if self.outcome_type in {"backtest_validated", "paper_window_settled"} and self.unknowns:
            raise ValueError("validated/settled outcomes cannot retain unknowns")
        if self.outcome_type.startswith("paper_") and not self.observation_window_id:
            raise ValueError("paper outcomes require an observation window")
        if self.outcome_type == "live_window_settled":
            raise ValueError("live outcomes are reserved until a LiveTradingMandate exists")
        if self.corrects_id and self.supersedes_id:
            raise ValueError("an outcome cannot both correct and supersede another outcome")
        _reject_sensitive(self.model_dump(mode="python"))
        return self


class LessonCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["lesson_candidate.v1"] = "lesson_candidate.v1"
    claim: str = Field(min_length=3, max_length=4_000)
    outcome_ids: list[str] = Field(min_length=1, max_length=64)
    support_outcome_ids: list[str] = Field(default_factory=list, max_length=64)
    opposition_outcome_ids: list[str] = Field(default_factory=list, max_length=64)
    stance: Literal["supporting", "opposing", "mixed", "unknown"]
    scope: dict[str, list[str] | str] = Field(default_factory=dict, max_length=32)
    regimes: list[str] = Field(min_length=1, max_length=32)
    confidence: Decimal = Field(ge=0, le=1)
    confidence_method: Literal["reviewed_frequency", "bayesian", "interval", "qualitative"]
    valid_until: datetime
    producer_lineage: dict[str, str] = Field(min_length=1, max_length=32)
    target_type: Literal["memory", "strategy", "portfolio_policy"]
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("outcome_ids", "support_outcome_ids", "opposition_outcome_ids", "regimes")
    @classmethod
    def unique_sorted(cls, value: list[str]) -> list[str]:
        return sorted({" ".join(str(item).split()) for item in value if str(item).strip()})

    @model_validator(mode="after")
    def validate_sources(self) -> LessonCandidateV1:
        self.claim = " ".join(self.claim.split())
        self.valid_until = _utc(self.valid_until)
        source_ids = set(self.outcome_ids)
        if not set(self.support_outcome_ids).issubset(source_ids):
            raise ValueError("support outcomes must be included in outcome_ids")
        if not set(self.opposition_outcome_ids).issubset(source_ids):
            raise ValueError("opposition outcomes must be included in outcome_ids")
        if set(self.support_outcome_ids) & set(self.opposition_outcome_ids):
            raise ValueError("an outcome cannot support and oppose the same lesson")
        if self.stance == "mixed" and (
            not self.support_outcome_ids or not self.opposition_outcome_ids
        ):
            raise ValueError("mixed lessons require support and opposition")
        _reject_sensitive(self.model_dump(mode="python"))
        return self


class LessonReviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "dispute"]
    reason: str = Field(min_length=3, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


def canonical_payload(model: BaseModel, *, exclude: set[str] | None = None) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        _canonical(model.model_dump(mode="python", exclude=exclude or set())),
    )


def content_hash(model: BaseModel, *, exclude: set[str] | None = None) -> str:
    encoded = json.dumps(
        canonical_payload(model, exclude=exclude),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("outcome timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _reject_sensitive(value: Any, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_KEYS or any(
                token in normalized for token in ("credential", "private_reasoning", "secret")
            ):
                raise ValueError(f"sensitive or raw field is forbidden: {path}{key}")
            _reject_sensitive(item, path=f"{path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive(item, path=f"{path}{index}.")
