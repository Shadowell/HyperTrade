"""Canonical approval and external-effect governance contracts."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, model_validator

from hypertrade.runtime.domain.models import StrictModel, utc_now

PolicyDecision = Literal["allow", "ask", "deny"]
ApprovalStatus = Literal[
    "requested",
    "pending",
    "approved",
    "denied",
    "expired",
    "revoked",
    "consumed",
]
ToolCallStatus = Literal[
    "prepared",
    "dispatched",
    "acknowledged",
    "succeeded",
    "failed",
    "timed_out",
    "effect_unknown",
    "reconciled",
]
EffectOutcome = Literal["committed", "not_committed", "unknown"]


def effect_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return sha256(encoded).hexdigest()


class PolicyDecisionV1(StrictModel):
    schema_version: Literal["policy_decision.v1"] = "policy_decision.v1"
    decision_id: str = Field(min_length=1, max_length=64)
    mission_id: str = Field(min_length=1, max_length=64)
    decision: PolicyDecision
    capability_id: str = Field(min_length=3, max_length=160)
    capability_version: str = Field(min_length=1, max_length=32)
    contract_hash: str = Field(min_length=64, max_length=64)
    policy_hash: str = Field(min_length=64, max_length=64)
    arguments_hash: str = Field(min_length=64, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    account: str = Field(min_length=1, max_length=160)
    environment: Literal["isolated", "paper", "testnet", "production"]
    role: str = Field(min_length=1, max_length=128)
    budget_hash: str = Field(min_length=64, max_length=64)
    policy_snapshot_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=3, max_length=1_000)
    created_at: datetime = Field(default_factory=utc_now)


class ApprovalRequestV1(StrictModel):
    schema_version: Literal["approval_request.v1"] = "approval_request.v1"
    request_id: str = Field(min_length=1, max_length=64)
    decision_id: str = Field(min_length=1, max_length=64)
    mission_id: str = Field(min_length=1, max_length=64)
    capability_id: str = Field(min_length=3, max_length=160)
    capability_version: str = Field(min_length=1, max_length=32)
    contract_hash: str = Field(min_length=64, max_length=64)
    policy_hash: str = Field(min_length=64, max_length=64)
    arguments_hash: str = Field(min_length=64, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    account: str = Field(min_length=1, max_length=160)
    environment: Literal["isolated", "paper", "testnet", "production"]
    role: str = Field(min_length=1, max_length=128)
    resource_scope: tuple[str, ...] = Field(min_length=1, max_length=32)
    maximum_amount: str = Field(default="0", max_length=80)
    policy_snapshot_hash: str = Field(min_length=64, max_length=64)
    status: ApprovalStatus = "requested"
    requested_by: str = Field(min_length=1, max_length=128)
    requested_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime

    @model_validator(mode="after")
    def expiry_follows_request(self) -> ApprovalRequestV1:
        if self.expires_at <= self.requested_at:
            raise ValueError("approval expiry must follow request time")
        return self


class ApprovalGrantV1(StrictModel):
    schema_version: Literal["approval_grant.v1"] = "approval_grant.v1"
    grant_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=1, max_length=64)
    decision_id: str = Field(min_length=1, max_length=64)
    capability_id: str = Field(min_length=3, max_length=160)
    capability_version: str = Field(min_length=1, max_length=32)
    contract_hash: str = Field(min_length=64, max_length=64)
    policy_hash: str = Field(min_length=64, max_length=64)
    arguments_hash: str = Field(min_length=64, max_length=64)
    subject: str = Field(min_length=1, max_length=160)
    account: str = Field(min_length=1, max_length=160)
    environment: Literal["isolated", "paper", "testnet", "production"]
    role: str = Field(min_length=1, max_length=128)
    resource_scope: tuple[str, ...] = Field(min_length=1, max_length=32)
    maximum_amount: str = Field(default="0", max_length=80)
    policy_snapshot_hash: str = Field(min_length=64, max_length=64)
    token_hash: str = Field(min_length=64, max_length=64, exclude=True)
    status: ApprovalStatus = "approved"
    approved_by: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=1_000)
    approved_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    consumed_at: datetime | None = None
    consumed_intent_id: str = ""


class IssuedApprovalV1(StrictModel):
    grant: ApprovalGrantV1
    consumption_token: str = Field(min_length=32, max_length=256, exclude=True, repr=False)


class DispatchIntentV1(StrictModel):
    schema_version: Literal["dispatch_intent.v1"] = "dispatch_intent.v1"
    intent_id: str = Field(min_length=1, max_length=64)
    mission_id: str = Field(min_length=1, max_length=64)
    tool_call_id: str = Field(min_length=1, max_length=64)
    decision_id: str = Field(min_length=1, max_length=64)
    approval_grant_id: str = Field(default="", max_length=64)
    capability_id: str = Field(min_length=3, max_length=160)
    capability_version: str = Field(min_length=1, max_length=32)
    contract_hash: str = Field(min_length=64, max_length=64)
    policy_hash: str = Field(min_length=64, max_length=64)
    arguments_hash: str = Field(min_length=64, max_length=64)
    operation_scope: tuple[str, ...] = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(min_length=8, max_length=128)
    payload_hash: str = Field(min_length=64, max_length=64)
    fencing_token: int = Field(default=0, ge=0)
    reconciliation_policy: Literal[
        "operation_id",
        "idempotency_key",
        "read_state",
        "manual_only",
    ]
    status: Literal[
        "prepared", "dispatched", "acknowledged", "terminal", "effect_unknown", "reconciled"
    ] = "prepared"
    external_operation_id: str = Field(default="", max_length=256)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ToolCallV1(StrictModel):
    schema_version: Literal["tool_call.v1"] = "tool_call.v1"
    tool_call_id: str = Field(min_length=1, max_length=64)
    intent_id: str = Field(min_length=1, max_length=64)
    mission_id: str = Field(min_length=1, max_length=64)
    capability_id: str = Field(min_length=3, max_length=160)
    status: ToolCallStatus = "prepared"
    external_operation_id: str = Field(default="", max_length=256)
    result_hash: str = Field(default="", max_length=64)
    error_category: str = Field(default="", max_length=96)
    reconciliation_outcome: EffectOutcome | Literal[""] = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EffectAckV1(StrictModel):
    external_operation_id: str = Field(min_length=1, max_length=256)
    result: dict[str, Any] = Field(default_factory=dict)


class EffectResolutionV1(StrictModel):
    outcome: EffectOutcome
    external_operation_id: str = Field(default="", max_length=256)
    result: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=1_000)
    observed_at: datetime = Field(default_factory=utc_now)


class PersistentCircuitStateV1(StrictModel):
    capability_id: str = Field(min_length=3, max_length=160)
    state: Literal["closed", "open", "half_open"] = "closed"
    consecutive_failures: int = Field(default=0, ge=0)
    version: int = Field(default=1, ge=1)
    opened_at: datetime | None = None
    retry_after: datetime | None = None
    override_actor: str = Field(default="", max_length=128)
    override_reason: str = Field(default="", max_length=1_000)
    override_expires_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class EffectAuditEventV1(StrictModel):
    event_id: str = Field(min_length=1, max_length=64)
    aggregate_id: str = Field(min_length=1, max_length=64)
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=3, max_length=96)
    actor: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class EffectPublicItemV1(StrictModel):
    schema_version: Literal["effect_public_item.v1"] = "effect_public_item.v1"
    mission_id: str
    status: Literal["waiting_approval", "denied", "effect_unknown", "resolved"]
    message: str = Field(min_length=1, max_length=500)
    requires_operator_action: bool
    approval_request_id: str = ""
    tool_call_id: str = ""
