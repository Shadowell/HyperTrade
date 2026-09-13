"""Versioned evidence projection shared by AVO and long-term Agent Memory.

ARC development receipts remain authoritative. This interface contains observations,
never permission to approve, promote, trade, or change a validation threshold.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResearchMemoryV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["research_memory.v1"] = "research_memory.v1"
    memory_id: str | None = None
    mission_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    hypothesis: str = Field(max_length=400)
    code_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Only identities present in the historical receipt may populate these fields.
    config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    cost_policy_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    experiment_key: str
    spec: dict[str, Any]
    capital: str
    evidence_status: Literal["development_only"] = "development_only"
    development: dict[str, Any]
    hypothesis_assessment: dict[str, Any] | None = None
    identity_status: Literal["known", "unknown"] = "unknown"
    exclusion_reasons: list[str] = Field(default_factory=list)
    contamination_reasons: list[str] = Field(default_factory=list)
    example_polarity: Literal["supporting", "opposing"]
    approval_allowed: Literal[False] = False


def version_projection(entry: dict[str, Any], config_sha256: str | None) -> dict[str, Any]:
    reasons = []
    if not config_sha256:
        reasons.append("missing_config_identity")
    if not entry.get("cost_policy_hash"):
        reasons.append("missing_cost_identity")
    if reasons and isinstance(entry.get("hypothesis_assessment"), dict):
        entry = {
            **entry,
            "hypothesis_assessment": {
                **entry["hypothesis_assessment"],
                "status": "unknown",
            },
        }
    return ResearchMemoryV1(
        **entry,
        config_sha256=config_sha256,
        identity_status="unknown" if reasons else "known",
        exclusion_reasons=reasons,
        example_polarity="supporting" if entry["development"]["passed"] else "opposing",
    ).model_dump(mode="json", exclude_none=False)
