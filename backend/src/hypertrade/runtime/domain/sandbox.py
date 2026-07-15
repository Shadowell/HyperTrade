from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from hypertrade.runtime.domain.models import StrictModel, utc_now


class SandboxCommandV1(StrictModel):
    name: Literal["ruff", "pytest", "limited_backtest"]
    args: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def deny_unsafe_arguments(self) -> SandboxCommandV1:
        forbidden = ("-c", "--python", "..", "/", "\\", "http:", "https:")
        if any(any(token in arg.casefold() for token in forbidden) for arg in self.args):
            raise ValueError("sandbox command contains a forbidden argument")
        return self


# Contract name retained as an explicit alias; the wire shape is shared with
# the request's command entries.
CommandSpecV1 = SandboxCommandV1


class SandboxRequestV1(StrictModel):
    assignment_ref: str = Field(min_length=3, max_length=300)
    context_pack_refs: tuple[str, ...] = Field(min_length=1, max_length=24)
    source_artifact_refs: tuple[str, ...] = Field(default=(), max_length=100)
    files: dict[str, str] = Field(min_length=1, max_length=32)
    commands: tuple[SandboxCommandV1, ...] = Field(min_length=1, max_length=8)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SandboxCommandResultV1(StrictModel):
    name: str
    argv: tuple[str, ...]
    status: Literal["passed", "failed", "timeout", "denied"]
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    output_preview: str = Field(default="", max_length=16_384)
    output_hash: str
    output_bytes: int = Field(default=0, ge=0)
    truncated: bool = False


class PatchManifestV1(StrictModel):
    patch_hash: str = Field(min_length=64, max_length=64)
    diff_preview: str = Field(max_length=65_536)
    file_hashes: dict[str, str]
    total_bytes: int = Field(ge=0)


class SandboxArtifactV1(StrictModel):
    """Immutable metadata for one output of an ephemeral sandbox run.

    The workspace is deliberately discarded.  This ledger keeps enough
    content-addressed metadata to replay and review the run without retaining
    arbitrary generated files or command output.
    """

    artifact_id: str
    sandbox_run_id: str
    kind: Literal["source_file", "patch", "command_output", "manifest"]
    path: str = ""
    media_type: str = "application/octet-stream"
    size_bytes: int = Field(ge=0)
    content_hash: str = Field(min_length=64, max_length=64)
    preview: str = Field(default="", max_length=16_384)


class SandboxRunV1(StrictModel):
    schema_version: Literal["strategy_sandbox_run.v1"] = "strategy_sandbox_run.v1"
    sandbox_run_id: str
    mission_id: str
    assignment_ref: str
    context_pack_refs: tuple[str, ...]
    source_artifact_refs: tuple[str, ...]
    status: Literal["validated", "failed", "denied"]
    patch: PatchManifestV1
    commands: tuple[SandboxCommandResultV1, ...]
    artifacts: tuple[SandboxArtifactV1, ...] = ()
    request_hash: str = Field(min_length=64, max_length=64)
    artifact_hash: str
    idempotency_key: str
    created_at: datetime = Field(default_factory=utc_now)


class ImportReviewV1(StrictModel):
    decision: Literal["accept", "reject"]
    reason: str = Field(min_length=3, max_length=1_000)
    patch_hash: str = Field(min_length=64, max_length=64)
    artifact_hash: str = Field(min_length=64, max_length=64)
    target_contract: str = Field(default="bitpro.strategy_import.v1", max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ImportReviewFactV1(StrictModel):
    review_id: str
    sandbox_run_id: str
    mission_id: str
    decision: Literal["accept", "reject"]
    reason: str
    patch_hash: str
    artifact_hash: str
    target_contract: str
    actor: str
    idempotency_key: str
    external_write_performed: Literal[False] = False
    created_at: datetime = Field(default_factory=utc_now)


def sandbox_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(encoded.encode()).hexdigest()
