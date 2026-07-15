from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from hypertrade.runtime.domain.models import StrictModel, utc_now


class RoleDefinitionV1(StrictModel):
    role_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    title: str = Field(min_length=3, max_length=120)
    purpose: str = Field(min_length=3, max_length=500)
    capability_allowlist: tuple[str, ...] = Field(min_length=1, max_length=24)
    permission_profiles: tuple[str, ...] = ("read_only.v1",)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    reviewed: bool = True
    version: str = "1"


class BudgetReservationV1(StrictModel):
    tokens: int = Field(default=1_000, ge=0, le=120_000)
    tool_calls: int = Field(default=1, ge=0, le=48)
    model_calls: int = Field(default=1, ge=0, le=24)
    duration_ms: int = Field(default=30_000, ge=1, le=900_000)


class AssignmentCreateV1(StrictModel):
    assignment_id: str = ""
    role_id: str
    objective: str = Field(min_length=3, max_length=2_000)
    capability_id: str
    depends_on: tuple[str, ...] = ()
    context_pack_refs: tuple[str, ...] = Field(min_length=1, max_length=24)
    artifact_refs: tuple[str, ...] = Field(default=(), max_length=100)
    reservation: BudgetReservationV1 = Field(default_factory=BudgetReservationV1)
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)


class AssignmentV1(StrictModel):
    assignment_id: str
    mission_id: str
    role_id: str
    objective: str
    capability_id: str
    depends_on: tuple[str, ...]
    context_pack_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    reservation: BudgetReservationV1
    status: Literal["pending", "running", "succeeded", "failed", "canceled"] = "pending"
    error: str = ""


class HandoffV1(StrictModel):
    schema_version: Literal["agent_handoff.v1"] = "agent_handoff.v1"
    handoff_id: str
    mission_id: str
    assignment_id: str
    role_id: str
    summary: str = Field(min_length=1, max_length=4_000)
    claims: dict[str, str] = Field(default_factory=dict)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=100)
    artifact_refs: tuple[str, ...] = Field(default=(), max_length=100)
    unknowns: tuple[str, ...] = Field(default=(), max_length=100)
    output_hash: str = ""

    @model_validator(mode="after")
    def bind_output_hash(self) -> HandoffV1:
        forbidden = ("private reasoning", "chain of thought", "raw transcript")
        if any(token in self.summary.casefold() for token in forbidden):
            raise ValueError("handoff contains forbidden hidden transcript content")
        expected = supervision_hash(
            {
                "mission_id": self.mission_id,
                "assignment_id": self.assignment_id,
                "role_id": self.role_id,
                "summary": self.summary,
                "claims": self.claims,
                "source_refs": self.source_refs,
                "artifact_refs": self.artifact_refs,
                "unknowns": self.unknowns,
            }
        )
        if self.output_hash and self.output_hash != expected:
            raise ValueError("handoff output hash mismatch")
        if not self.output_hash:
            object.__setattr__(self, "output_hash", expected)
        return self


class ConflictV1(StrictModel):
    conflict_id: str
    mission_id: str
    claim_key: str
    values: dict[str, tuple[str, ...]]
    source_refs: tuple[str, ...]
    status: Literal["unresolved", "resolved"] = "unresolved"
    resolution: str = ""


class MergeDecisionV1(StrictModel):
    mission_id: str
    handoff_refs: tuple[str, ...]
    agreed_claims: dict[str, str] = Field(default_factory=dict)
    conflicts: tuple[ConflictV1, ...] = ()
    unknowns: tuple[str, ...] = ()
    merged_at: datetime = Field(default_factory=utc_now)


class TeamRunRequestV1(StrictModel):
    assignments: tuple[AssignmentCreateV1, ...] = Field(min_length=1, max_length=4)
    idempotency_key: str = Field(min_length=8, max_length=128)


def supervision_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode()).hexdigest()
