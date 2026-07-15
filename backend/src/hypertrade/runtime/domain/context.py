from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, model_validator

from hypertrade.runtime.domain.models import StrictModel, utc_now

ContextSourceKind = Literal[
    "mission",
    "plan",
    "step",
    "observation",
    "evidence",
    "memory",
    "rag",
    "artifact",
]


class ContextBudgetExceeded(ValueError):
    pass


class ContextSourceV1(StrictModel):
    source_ref: str = Field(min_length=3, max_length=500)
    kind: ContextSourceKind
    tier: int = Field(ge=0, le=9)
    required: bool = False
    content: str = Field(min_length=1, max_length=100_000)
    content_hash: str = ""
    source_version: str = "1"
    fresh_until: datetime | None = None

    @model_validator(mode="after")
    def bind_content_hash(self) -> ContextSourceV1:
        expected = hash_payload(self.content)
        if self.content_hash and self.content_hash != expected:
            raise ValueError("context source hash mismatch")
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected)
        return self

    def stale(self, *, now: datetime | None = None) -> bool:
        if self.fresh_until is None:
            return False
        fresh_until = self.fresh_until
        if fresh_until.tzinfo is None:
            fresh_until = fresh_until.replace(tzinfo=UTC)
        return fresh_until <= (now or utc_now())


class ContextDecisionV1(StrictModel):
    source_ref: str
    kind: ContextSourceKind
    tier: int
    included: bool
    reason: Literal[
        "required",
        "selected",
        "compacted",
        "stale",
        "budget",
        "unsafe_content",
        "duplicate",
    ]
    source_hash: str
    token_estimate: int = Field(ge=0)
    rendered_content: str = Field(default="", max_length=30_000)


class ContextTokenLedgerV1(StrictModel):
    budget_tokens: int = Field(ge=128, le=120_000)
    used_tokens: int = Field(ge=0)
    required_tokens: int = Field(ge=0)
    included_sources: int = Field(ge=0)
    dropped_sources: int = Field(ge=0)

    @model_validator(mode="after")
    def enforce_budget(self) -> ContextTokenLedgerV1:
        if self.used_tokens > self.budget_tokens:
            raise ValueError("context token budget exceeded")
        return self


class ContextPackV1(StrictModel):
    schema_version: Literal["agent_context_pack.v1"] = "agent_context_pack.v1"
    context_pack_id: str
    mission_id: str
    plan_version: int = Field(ge=1, le=5)
    step_id: str
    attempt: int = Field(ge=1, le=3)
    policy_ref: str
    decisions: tuple[ContextDecisionV1, ...]
    ledger: ContextTokenLedgerV1
    manifest_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=utc_now)


class MissionArtifactCreateV1(StrictModel):
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    title: str = Field(min_length=3, max_length=240)
    media_type: str = Field(default="application/json", max_length=128)
    content_hash: str = Field(default="", max_length=64)
    size_bytes: int = Field(default=0, ge=0, le=1_000_000_000)
    external_ref: str = Field(default="", max_length=1_000)
    inline_preview: dict[str, Any] = Field(default_factory=dict)
    producer_ref: str = Field(min_length=3, max_length=300)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=100)
    supersedes_artifact_id: str = ""

    @model_validator(mode="after")
    def require_stable_content(self) -> MissionArtifactCreateV1:
        if not self.external_ref and not self.inline_preview:
            raise ValueError("artifact requires an external ref or bounded inline preview")
        return self


class MissionArtifactV1(StrictModel):
    schema_version: Literal["mission_artifact.v1"] = "mission_artifact.v1"
    artifact_id: str
    mission_id: str
    version: int = Field(ge=1)
    kind: str
    title: str
    media_type: str
    content_hash: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    external_ref: str = ""
    inline_preview: dict[str, Any] = Field(default_factory=dict)
    producer_ref: str
    source_refs: tuple[str, ...]
    supersedes_artifact_id: str = ""
    status: Literal["current", "superseded", "unavailable"] = "current"
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def stable_ref(self) -> str:
        return f"artifact:{self.artifact_id}@{self.content_hash}"


class ArtifactRelationV1(StrictModel):
    from_artifact_id: str
    to_ref: str
    relation_type: Literal["derived_from", "supersedes"]


def hash_payload(payload: object) -> str:
    if isinstance(payload, str):
        encoded = payload
    else:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode()).hexdigest()
