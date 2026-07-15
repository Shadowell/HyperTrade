from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, model_validator

from hypertrade.runtime.domain.models import StrictModel, utc_now

CapabilityScope = Literal[
    "read",
    "research_write",
    "paper_write",
    "testnet_write",
    "live_read",
    "live_write",
]


class CapabilityDefinitionV1(StrictModel):
    schema_version: Literal["capability.v1"] = "capability.v1"
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,159}$")
    version: str = Field(default="1", min_length=1, max_length=32)
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=1_000)
    source_owner: str = Field(min_length=2, max_length=128)
    handler_key: str = Field(min_length=2, max_length=160)
    scope: CapabilityScope = "read"
    side_effect: Literal["none", "idempotent_write", "destructive"] = "none"
    approval: Literal["none", "required", "blocked"] = "none"
    idempotency: Literal["not_required", "required"] = "not_required"
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    max_result_bytes: int = Field(default=32_768, ge=256, le=262_144)

    @model_validator(mode="after")
    def validate_policy_coherence(self) -> CapabilityDefinitionV1:
        if self.scope == "read" and self.side_effect != "none":
            raise ValueError("read capability cannot declare a side effect")
        if self.side_effect != "none" and self.idempotency != "required":
            raise ValueError("write/destructive capability requires idempotency")
        if (
            self.scope in {"paper_write", "testnet_write", "live_write"}
            and self.approval != "required"
        ):
            raise ValueError("trading write capability requires approval")
        return self

    def contract_hash(self) -> str:
        payload = {
            "capability_id": self.capability_id,
            "version": self.version,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "handler_key": self.handler_key,
        }
        return _hash(payload)

    def policy_hash(self) -> str:
        payload = {
            "scope": self.scope,
            "side_effect": self.side_effect,
            "approval": self.approval,
            "idempotency": self.idempotency,
            "timeout_seconds": self.timeout_seconds,
            "max_result_bytes": self.max_result_bytes,
        }
        return _hash(payload)


class CapabilitySnapshotV1(StrictModel):
    snapshot_id: str
    definition: CapabilityDefinitionV1
    review_status: Literal["reviewed", "pending_review", "rejected"]
    health: Literal["healthy", "degraded", "unhealthy", "unknown"] = "unknown"
    contract_hash: str = Field(min_length=64, max_length=64)
    policy_hash: str = Field(min_length=64, max_length=64)
    reviewed_by: str = ""
    review_reason: str = ""
    verified_at: datetime | None = None
    fresh_until: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def hashes_match_definition(self) -> CapabilitySnapshotV1:
        if self.contract_hash != self.definition.contract_hash():
            raise ValueError("capability contract hash mismatch")
        if self.policy_hash != self.definition.policy_hash():
            raise ValueError("capability policy hash mismatch")
        return self

    def executable(self, *, now: datetime | None = None) -> bool:
        instant = now or utc_now()
        fresh_until = self.fresh_until
        # SQLite drops timezone metadata; normalize persisted timestamps before
        # enforcing the freshness gate.
        if fresh_until is not None and fresh_until.tzinfo is None:
            fresh_until = fresh_until.replace(tzinfo=UTC)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        return (
            self.review_status == "reviewed"
            and self.health in {"healthy", "degraded"}
            and fresh_until is not None
            and fresh_until > instant
        )


class CapabilityProposalV1(StrictModel):
    proposal_id: str = ""
    definition: CapabilityDefinitionV1
    discovered_from: str = Field(min_length=3, max_length=300)
    discovery_hash: str = ""
    status: Literal["pending_review", "approved", "rejected"] = "pending_review"
    reason: str = ""
    created_by: str = Field(default="discovery", min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=utc_now)


class CapabilityReviewV1(StrictModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=1_000)
    actor: str = Field(default="operator", min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    freshness_seconds: int = Field(default=86_400, ge=60, le=2_592_000)


class ToolRequestV2(StrictModel):
    request_id: str
    mission_id: str
    plan_version: int = Field(ge=1)
    step_id: str
    attempt: int = Field(ge=1, le=3)
    capability_id: str
    capability_version: str
    contract_hash: str = Field(min_length=64, max_length=64)
    policy_hash: str = Field(min_length=64, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = ""
    approval_ref: str = ""


class ToolObservationV2(StrictModel):
    schema_version: Literal["tool_observation.v2"] = "tool_observation.v2"
    observation_id: str
    request_id: str
    mission_id: str
    step_id: str
    capability_id: str
    capability_version: str
    contract_hash: str
    policy_hash: str
    status: Literal["succeeded", "failed", "denied", "replayed"]
    result_preview: dict[str, Any] = Field(default_factory=dict)
    result_hash: str = ""
    source_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    error_category: Literal[
        "",
        "invalid_input",
        "permission_denied",
        "source_unavailable",
        "timeout",
        "rate_limited",
        "contract_mismatch",
        "partial_result",
        "unsafe_request",
        "unknown_failure",
        "circuit_open",
    ] = ""
    retry_action: Literal["none", "retry", "replan", "wait_human", "fail"] = "none"
    duration_ms: int = Field(default=0, ge=0)
    truncated: bool = False
    observed_at: datetime = Field(default_factory=utc_now)


class CircuitStateV1(StrictModel):
    capability_id: str
    state: Literal["closed", "open", "half_open"] = "closed"
    consecutive_failures: int = Field(default=0, ge=0)
    opened_at: datetime | None = None
    retry_after: datetime | None = None


def reviewed_snapshot(
    definition: CapabilityDefinitionV1,
    *,
    snapshot_id: str,
    actor: str = "code_review",
    freshness_seconds: int = 86_400,
) -> CapabilitySnapshotV1:
    now = utc_now()
    return CapabilitySnapshotV1(
        snapshot_id=snapshot_id,
        definition=definition,
        review_status="reviewed",
        health="healthy",
        contract_hash=definition.contract_hash(),
        policy_hash=definition.policy_hash(),
        reviewed_by=actor,
        review_reason="version-controlled built-in capability",
        verified_at=now,
        fresh_until=now + timedelta(seconds=freshness_seconds),
    )


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode()).hexdigest()
