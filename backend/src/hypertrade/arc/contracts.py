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


class ARCBudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_candidates: int = Field(default=5)
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
    budget: ARCBudgetV1 = Field(default_factory=ARCBudgetV1)
    paper_authorization: PaperPreauthorizationV1 | None = None
    live_allowed: Literal[False] = False


class ARCReflexionEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["arc_reflexion_event.v1"] = "arc_reflexion_event.v1"
    candidate_id: str
    failure_class: str  # e.g., "drawdown_exceeded", "sharpe_too_low", "red_team_attack_failed"
    reason_codes: list[str]
    failed_gates: list[str]
    observed_metrics: dict[str, Any]
    negative_constraints: list[str]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ARCCandidateAttemptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    candidate_id: str
    state: Literal[
        "proposed",
        "mutated",
        "red_team_testing",
        "validated",
        "rejected",
        "paper_authorizing",
        "paper_observing",
        "failed",
    ] = "proposed"
    hypothesis: str
    strategy_code: str
    strategy_spec: dict[str, Any] = Field(default_factory=dict)
    bitpro_strategy_id: str | None = None
    validation_id: str | None = None
    paper_instance_id: str | None = None
    observed_metrics: dict[str, Any] = Field(default_factory=dict)
    reflexion_events: list[ARCReflexionEventV1] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
