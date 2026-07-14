"""Versioned contracts for bounded, fail-closed robustness validation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GateOutcome = Literal["passed", "failed", "unknown", "not_applicable"]
ValidationFinalStatus = Literal["validated", "rejected", "needs_data", "needs_review"]
ScenarioKind = Literal[
    "locked_oos",
    "walk_forward",
    "parameter_sensitivity",
    "cost_stress",
    "regime_stress",
]


class RobustnessPolicyV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["robustness_policy.v2"] = "robustness_policy.v2"
    walk_forward_folds: int = Field(default=2, ge=2, le=8)
    train_bars: int = Field(default=200, ge=50, le=50_000)
    validation_bars: int = Field(default=50, ge=25, le=25_000)
    test_bars: int = Field(default=50, ge=25, le=25_000)
    locked_oos_bars: int = Field(default=100, ge=25, le=25_000)
    min_trade_count: int = Field(default=20, ge=1, le=10_000)
    max_drawdown_pct: Decimal = Field(default=Decimal("20"), gt=0, le=100)
    sensitivity_max_degradation_pct: Decimal = Field(default=Decimal("80"), ge=0, le=100)
    cost_max_degradation_pct: Decimal = Field(default=Decimal("80"), ge=0, le=100)
    cost_multipliers: list[Decimal] = Field(
        default_factory=lambda: [Decimal("1.5"), Decimal("2")], min_length=2, max_length=4
    )
    max_parameter_neighbors: int = Field(default=2, ge=1, le=8)
    max_largest_trade_contribution_pct: Decimal = Field(
        default=Decimal("50"), gt=0, le=100
    )
    require_regime_stress: bool = False

    @field_validator("cost_multipliers")
    @classmethod
    def normalize_costs(cls, values: list[Decimal]) -> list[Decimal]:
        normalized = sorted({Decimal(str(value)) for value in values})
        if any(value <= 1 for value in normalized):
            raise ValueError("cost stress multipliers must be greater than one")
        return normalized


class RobustnessWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> RobustnessWindow:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("robustness windows require timezone-aware timestamps")
        self.start = self.start.astimezone(UTC)
        self.end = self.end.astimezone(UTC)
        if self.end <= self.start:
            raise ValueError("robustness window end must be after start")
        return self


class RobustnessScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^[a-z0-9_]{3,96}$")
    kind: ScenarioKind
    required: bool = True
    source: Literal["execute", "reuse"]
    window: RobustnessWindow
    parameters: dict[str, Decimal] = Field(default_factory=dict, max_length=32)
    maker_fee_bps: Decimal = Field(ge=0)
    taker_fee_bps: Decimal = Field(ge=0)
    slippage_bps: Decimal = Field(ge=0)
    regime: str = Field(default="", max_length=64)


class RobustnessPlanV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["robustness_plan.v2"] = "robustness_plan.v2"
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    candidate_frozen_at: datetime
    scenarios: list[RobustnessScenario] = Field(min_length=1, max_length=32)
    projected_new_backtests: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_plan(self) -> RobustnessPlanV2:
        if self.candidate_frozen_at.tzinfo is None:
            raise ValueError("candidate freeze time must be timezone-aware")
        self.candidate_frozen_at = self.candidate_frozen_at.astimezone(UTC)
        ids = [item.scenario_id for item in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("robustness scenario ids must be unique")
        if self.projected_new_backtests != sum(
            item.source == "execute" for item in self.scenarios
        ):
            raise ValueError("projected backtests must match executable scenarios")
        return self


class ScenarioObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(pattern=r"^[a-z0-9_]{3,96}$")
    status: Literal["completed", "failed", "unknown"]
    result_ref: dict[str, str | int] = Field(default_factory=dict, max_length=16)
    metrics: dict[str, Decimal] = Field(default_factory=dict, max_length=64)
    error_code: str = Field(default="", max_length=128)

    @field_validator("metrics")
    @classmethod
    def reject_non_finite_metrics(cls, values: dict[str, Decimal]) -> dict[str, Decimal]:
        normalized = {str(key): Decimal(str(value)) for key, value in values.items()}
        if any(not value.is_finite() for value in normalized.values()):
            raise ValueError("scenario metrics must be finite")
        return normalized


class RobustnessGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: GateOutcome
    required: bool
    reasons: list[str] = Field(default_factory=list, max_length=64)
    scenario_ids: list[str] = Field(default_factory=list, max_length=32)


class RobustnessValidationResultV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["robustness_validation_result.v2"] = (
        "robustness_validation_result.v2"
    )
    final_status: ValidationFinalStatus
    gates: dict[str, RobustnessGateResult]
    scenario_gates: dict[str, dict[str, GateOutcome]]
    unknowns: list[str] = Field(default_factory=list, max_length=128)
    summary: dict[str, str | int] = Field(default_factory=dict, max_length=64)


def robustness_policy_payload(policy: RobustnessPolicyV2) -> dict[str, Any]:
    return cast(dict[str, Any], _canonical(policy.model_dump(mode="python")))


def robustness_policy_hash(policy: RobustnessPolicyV2) -> str:
    payload = json.dumps(
        robustness_policy_payload(policy), separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value
