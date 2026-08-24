"""
ARC (Autonomous Research Core) Domain Contracts and Value Objects
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ARCSuccessCriteriaV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_oos_net_return: Decimal = Field(default=Decimal("0.05"))
    min_oos_sharpe: Decimal = Field(default=Decimal("1.2"))
    max_drawdown: Decimal = Field(default=Decimal("0.15"))
    min_trades: int = Field(default=10)
    required_validation_policy: str = Field(default="validation_policy_v2")
    paper_required: bool = Field(default=True)


class PaperObservationPolicyV1(BaseModel):
    """When a paper instance has produced enough evidence for a live decision."""

    model_config = ConfigDict(extra="forbid")

    min_hours: int = Field(default=24, ge=0, le=24 * 90)
    min_trades: int = Field(default=10, ge=0, le=100_000)


class ARCBudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 5 candidates could not support any search narrative: the catalogue alone
    # has six families. Ten leaves room for seeds, mutations and one provider
    # hypothesis while staying inside an operator-approved mission budget.
    max_candidates: int = Field(default=10)
    max_model_calls: int = Field(default=20)
    max_tool_calls: int = Field(default=30)
    max_backtests: int = Field(default=10)
    max_wall_seconds: int = Field(default=3600)

    candidates_used: int = Field(default=0)
    model_calls_used: int = Field(default=0)
    backtests_used: int = Field(default=0)

    def is_exhausted(self) -> bool:
        return (
            self.candidates_used >= self.max_candidates
            or self.model_calls_used >= self.max_model_calls
            or self.backtests_used >= self.max_backtests
        )


class PaperPreauthorizationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["paper_preauthorization.v1"] = "paper_preauthorization.v1"
    approved_by: str = Field(default="operator")
    platform: Literal["bitpro"] = "bitpro"
    symbols: list[str] = Field(default_factory=lambda: ["BTC-USDT-SWAP"])
    max_instances: int = Field(default=1)
    max_capital_per_instance: Decimal = Field(default=Decimal("10000"))
    allowed_actions: list[str] = Field(
        default_factory=lambda: ["configure", "start", "observe", "pause", "retire"]
    )
    valid_until: datetime | None = None
    policy_hash: str = Field(default="policy_sha256_placeholder")


class ARCGoalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["arc_goal.v1"] = "arc_goal.v1"
    objective: str
    platform: Literal["bitpro"] = "bitpro"
    market_type: str = Field(default="crypto_swap")
    symbols: list[str] = Field(default_factory=lambda: ["BTC-USDT-SWAP"])
    timeframes: list[str] = Field(default_factory=lambda: ["1H"])
    strategy_families: list[str] = Field(
        default_factory=lambda: ["trend_following", "mean_reversion"]
    )
    success_criteria: ARCSuccessCriteriaV1 = Field(default_factory=ARCSuccessCriteriaV1)
    observation: PaperObservationPolicyV1 = Field(default_factory=PaperObservationPolicyV1)
    budget: ARCBudgetV1 = Field(default_factory=ARCBudgetV1)
    paper_authorization: PaperPreauthorizationV1 | None = None
    # Evidence-window provenance consent. The gate refuses to spend candidate budget on
    # a window whose origin is not provably OKX unless the operator set this at mission
    # creation; it is a mission fact, so restarts and replays keep the same consent.
    alternative_source_confirmed: bool = False
    live_allowed: Literal[False] = False
    live_max_capital_u: Decimal = Field(default=Decimal("100"))
    live_mandate_hours: int = Field(default=24, ge=1, le=24 * 30)


class ARCReflexionEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["arc_reflexion_event.v1"] = "arc_reflexion_event.v1"
    candidate_id: str
    failure_class: str  # e.g., "drawdown_exceeded", "sharpe_too_low", "red_team_attack_failed"
    reason_codes: list[str]
    failed_gates: list[str]
    observed_metrics: dict[str, Any]
    negative_constraints: list[str]
    # What each reason code actually measured. `negative_constraints` is deduped, sorted
    # mutation guidance with no positional relationship to `reason_codes`, so pairing the
    # two by index attributed the wrong explanation to every objection. Defaults empty so
    # projections persisted before this field still load.
    reason_details: dict[str, str] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ARCCandidateAttemptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    candidate_id: str
    # Where the hypothesis came from. Defaults keep pre-provider events replayable.
    origin: Literal["deterministic_family", "provider_hypothesis"] = (
        "deterministic_family"
    )
    provider_model: str | None = None
    provider_request_hash: str | None = None
    state: Literal[
        "proposed",
        "mutated",
        "red_team_testing",
        "validated",
        "rejected",
        "paper_authorizing",
        "paper_observing",
        "live_canary",
        "failed",
    ] = "proposed"
    hypothesis: str
    strategy_code: str
    strategy_spec: dict[str, Any] = Field(default_factory=dict)
    bitpro_strategy_id: str | None = None
    bitpro_backtest_id: str | None = None
    validation_id: str | None = None
    paper_instance_id: str | None = None
    live_instance_id: str | None = None
    observed_metrics: dict[str, Any] = Field(default_factory=dict)
    reflexion_events: list[ARCReflexionEventV1] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CanaryTier(str):
    PAPER_INCUBATION = "paper_incubation"  # Tier 0 (0% Real Capital)
    CANARY_LIVE_MICRO = "canary_live_micro"  # Tier 1 (0.5% Capital)
    CANARY_LIVE_MINI = "canary_live_mini"  # Tier 2 (2.0% Capital)
    PRODUCTION_LIVE_VAULT = "production_live_vault"  # Tier 3 (Dynamic Capital)


class LiveTradingMandateV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["live_trading_mandate.v1"] = "live_trading_mandate.v1"
    mandate_id: str
    approved_by: str = Field(default="operator")
    approval_token: str
    symbol: str = Field(default="BTC-USDT-SWAP")
    candidate_id: str
    canary_tier: str = Field(default=CanaryTier.PAPER_INCUBATION)
    max_capital_u: Decimal = Field(default=Decimal("100"))
    max_daily_drawdown_pct: Decimal = Field(default=Decimal("3.0"))
    max_pnl_drift_pct: Decimal = Field(default=Decimal("10.0"))
    mandatory_stop_loss_pct: Decimal = Field(default=Decimal("7.0"))
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LiveApprovalPackageV1(BaseModel):
    """Operator-facing evidence for the single live decision. Missing refs => incomplete."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["live_approval_package.v1"] = "live_approval_package.v1"
    mission_id: str
    status: Literal["incomplete", "ready", "approved", "rejected", "promoted"]
    recommendation: Literal["approve", "reject", "wait"]
    package_hash: str
    strategy: dict[str, Any] = Field(default_factory=dict)
    backtest: dict[str, Any] = Field(default_factory=dict)
    paper: dict[str, Any] = Field(default_factory=dict)
    comparison: dict[str, Any] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)
    live_intent: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] | None = None
