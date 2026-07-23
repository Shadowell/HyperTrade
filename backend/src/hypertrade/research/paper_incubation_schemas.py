"""Strict paper-only mandates and autonomous incubation requests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PaperAction = Literal["configure", "start", "observe", "reduce", "pause", "retire"]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("paper mandate timestamps must include a timezone")
    return value.astimezone(UTC)


class PaperResearchMandateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["paper_research_mandate.v1"] = "paper_research_mandate.v1"
    name: str = Field(min_length=3, max_length=160)
    candidate_ids: list[str] = Field(min_length=1, max_length=100)
    validation_ids: list[str] = Field(min_length=1, max_length=100)
    validation_fingerprints: dict[str, str] = Field(min_length=1, max_length=100)
    symbols: list[str] = Field(min_length=1, max_length=20)
    paper_capital: Decimal = Field(gt=0, le=Decimal("1000000"))
    max_instances: int = Field(default=1, ge=1, le=20)
    observation_days: list[Literal[30, 60, 90]] = Field(min_length=1, max_length=3)
    allowed_actions: list[PaperAction] = Field(min_length=1, max_length=6)
    max_drawdown_pct: Decimal = Field(default=Decimal("10"), gt=0, le=100)
    max_error_count: int = Field(default=0, ge=0, le=1000)
    minimum_equity_samples: int = Field(default=30, ge=1, le=500)
    maker_fee_bps: Decimal = Field(ge=0, le=1000)
    taker_fee_bps: Decimal = Field(ge=0, le=1000)
    slippage_bps: Decimal = Field(ge=0, le=1000)
    valid_from: datetime
    valid_until: datetime
    approved_by: str = Field(min_length=3, max_length=128)
    revoke_mode: Literal["observe_only", "safe_pause"] = "safe_pause"

    @field_validator("candidate_ids", "validation_ids", "observation_days", "allowed_actions")
    @classmethod
    def normalize_lists(cls, values: list[Any]) -> list[Any]:
        return sorted(set(values))

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        return sorted({str(value).strip().upper() for value in values if str(value).strip()})

    @field_validator("valid_from", "valid_until")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_boundary(self) -> PaperResearchMandateV1:
        if self.valid_until <= self.valid_from:
            raise ValueError("paper mandate expiry must follow activation")
        if len(self.candidate_ids) != len(self.validation_ids):
            raise ValueError("candidate and validation denominators must have equal size")
        if set(self.validation_fingerprints) != set(self.candidate_ids):
            raise ValueError("validation fingerprints must bind every fixed-denominator candidate")
        if any(
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
            for fingerprint in self.validation_fingerprints.values()
        ):
            raise ValueError("validation fingerprints must be lowercase sha256 digests")
        if self.max_instances > len(self.candidate_ids):
            raise ValueError("max_instances cannot exceed the fixed candidate denominator")
        if "start" in self.allowed_actions and "configure" not in self.allowed_actions:
            raise ValueError("paper start requires configure authority")
        if self.approved_by.casefold().split(":", 1)[0] in {
            "agent",
            "model",
            "planner",
            "runtime",
        }:
            raise ValueError("an Agent or model cannot approve a paper mandate")
        return self


class PaperMandateCreateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandate: PaperResearchMandateV1
    idempotency_key: str = Field(min_length=8, max_length=128)


class PaperIncubationActionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member_id: str = Field(min_length=1, max_length=32)
    action: PaperAction
    reason: str = Field(min_length=3, max_length=1000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PaperIncubationCaptureV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandate_id: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=8, max_length=96)
    bucket_minutes: Literal[5, 15, 30, 60, 240, 1440] = 60
    max_points: int = Field(default=500, ge=8, le=500)


def canonical_payload(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="python") if isinstance(value, BaseModel) else value
    return cast(dict[str, Any], _canonical(raw))


def digest(value: BaseModel | dict[str, Any]) -> str:
    encoded = json.dumps(
        canonical_payload(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
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
