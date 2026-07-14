"""Versioned, privacy-bounded contracts for reproducible experiments."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hypertrade.research.schemas import StrategySpecDraft

_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "private_reasoning",
    "prompt",
    "raw_candles",
    "raw_result",
    "secret",
}


class ExperimentWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> ExperimentWindow:
        self.start = _utc(self.start)
        self.end = _utc(self.end)
        if self.end <= self.start:
            raise ValueError("experiment window end must be after start")
        return self


class ExperimentCosts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    maker_fee_bps: Decimal = Field(ge=0)
    taker_fee_bps: Decimal = Field(ge=0)
    slippage_bps: Decimal = Field(ge=0)
    funding_mode: Literal["included", "excluded", "unavailable"]


class ExperimentVersions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=160)
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    tool_registry_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    mcp_contract_version: str = Field(min_length=1, max_length=128)
    git_commit_sha: str = Field(min_length=7, max_length=64)


class ExperimentManifestV1(BaseModel):
    """Semantic inputs only; Task/Job IDs are deliberately not fingerprint fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["experiment_manifest.v1"] = "experiment_manifest.v1"
    strategy_spec: StrategySpecDraft
    strategy_code_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    strategy_code_ref: str = Field(min_length=1, max_length=512)
    parameters: dict[str, Decimal] = Field(default_factory=dict, max_length=128)
    exchange: str = Field(min_length=2, max_length=32)
    market_type: str = Field(min_length=2, max_length=32)
    windows: list[ExperimentWindow] = Field(min_length=1, max_length=32)
    costs: ExperimentCosts
    data_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    versions: ExperimentVersions

    @field_validator("exchange", "market_type")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("parameters")
    @classmethod
    def normalize_parameters(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        return {
            str(key).strip(): Decimal(str(item))
            for key, item in sorted(value.items())
            if str(key).strip()
        }

    @field_validator("windows")
    @classmethod
    def normalize_windows(cls, value: list[ExperimentWindow]) -> list[ExperimentWindow]:
        names = [item.name for item in value]
        if len(names) != len(set(names)):
            raise ValueError("experiment window names must be unique")
        return sorted(value, key=lambda item: (item.name, item.start, item.end))

    @model_validator(mode="after")
    def reject_sensitive_content(self) -> ExperimentManifestV1:
        _reject_sensitive(self.model_dump(mode="python"))
        return self


class ExperimentRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: ExperimentManifestV1
    idempotency_key: str = Field(min_length=8, max_length=128)
    task_id: str = Field(default="", max_length=32)
    research_job_id: str = Field(default="", max_length=32)
    force_rerun: bool = False
    force_reason: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def validate_force(self) -> ExperimentRegister:
        self.force_reason = " ".join(self.force_reason.split())
        if self.force_rerun and len(self.force_reason) < 3:
            raise ValueError("force_rerun requires an audit reason")
        if not self.force_rerun and self.force_reason:
            raise ValueError("force_reason requires force_rerun=true")
        return self


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=256)
    artifact_ref: str = Field(min_length=1, max_length=1_000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    contract_version: str = Field(min_length=1, max_length=128)
    content_type: str = Field(default="application/json", max_length=128)


class ExperimentExecutionComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_refs: dict[str, str | int | float | bool] = Field(
        default_factory=dict, max_length=128
    )
    metrics: dict[str, Decimal] = Field(default_factory=dict, max_length=128)
    artifacts: list[ArtifactReference] = Field(default_factory=list, max_length=128)
    usage: dict[str, int] = Field(default_factory=dict, max_length=32)
    evidence_ids: list[str] = Field(default_factory=list, max_length=512)
    evidence_kind: Literal["evidence_v2", "legacy_experiment"] = "evidence_v2"

    @model_validator(mode="after")
    def validate_bounded_output(self) -> ExperimentExecutionComplete:
        _reject_sensitive(self.model_dump(mode="python"))
        self.evidence_ids = sorted(set(self.evidence_ids))
        return self


def canonical_manifest_payload(manifest: ExperimentManifestV1) -> dict[str, Any]:
    return cast(dict[str, Any], _canonical_value(manifest.model_dump(mode="python")))


def canonical_manifest_json(manifest: ExperimentManifestV1) -> str:
    return json.dumps(
        canonical_manifest_payload(manifest),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def experiment_fingerprint(manifest: ExperimentManifestV1) -> str:
    return hashlib.sha256(canonical_manifest_json(manifest).encode("utf-8")).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("experiment timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _reject_sensitive(value: Any, *, path: str = "") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in _SENSITIVE_KEYS or any(
                token in normalized for token in ("credential", "private_reasoning", "secret")
            ):
                raise ValueError(f"sensitive or raw field is forbidden: {path}{key}")
            _reject_sensitive(item, path=f"{path}{key}.")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive(item, path=f"{path}{index}.")
