"""Proposal, evaluation attestation, approval, release, and rollback for Skills."""

from __future__ import annotations

import difflib
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from hypertrade.config import Settings
from hypertrade.db import (
    Database,
    SkillActivePointer,
    SkillApproval,
    SkillEvaluation,
    SkillProposal,
    SkillRelease,
    utc_now,
)
from hypertrade.evals.service import AgentEvalSuite
from hypertrade.research.roles.definitions import ROLE_CATALOG, RoleDefinition
from hypertrade.tools.registry import ToolRegistry

SKILL_SCHEMA_VERSION = "skill_definition.v1"
SKILL_EVAL_SUITE_VERSION = "research_os_golden_v2"


class SkillDefinitionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,95}$")
    name: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=3, max_length=1_000)
    role_keys: list[str] = Field(min_length=1, max_length=13)
    prompt_template: str = Field(min_length=3, max_length=8_000)
    required_tools: list[str] = Field(default_factory=list, max_length=20)
    tool_guidance: dict[str, str] = Field(default_factory=dict)
    schema_examples: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    report_template: str = Field(default="", max_length=8_000)

    @model_validator(mode="after")
    def bounded_collections(self) -> SkillDefinitionV1:
        if len(set(self.role_keys)) != len(self.role_keys):
            raise ValueError("role_keys must be unique")
        if len(set(self.required_tools)) != len(self.required_tools):
            raise ValueError("required_tools must be unique")
        if len(self.tool_guidance) > 20:
            raise ValueError("tool_guidance exceeds 20 tools")
        if not set(self.tool_guidance).issubset(self.required_tools):
            raise ValueError("tool_guidance keys must be declared in required_tools")
        if any(len(key) > 128 or len(value) > 2_000 for key, value in self.tool_guidance.items()):
            raise ValueError("tool guidance exceeds key/value bounds")
        encoded_examples = json.dumps(self.schema_examples, ensure_ascii=False, default=str)
        if len(encoded_examples) > 20_000:
            raise ValueError("schema examples exceed 20,000 characters")
        return self


class SkillProposalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: SkillDefinitionV1
    base_release_id: str | None = Field(default=None, max_length=32)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SkillEvaluationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["passed", "failed"]
    suite_version: str = Field(min_length=3, max_length=96)
    baseline_id: str = Field(min_length=3, max_length=128)
    case_count: int = Field(ge=1, le=10_000)
    passed_count: int = Field(ge=0, le=10_000)
    regression_count: int = Field(default=0, ge=0, le=10_000)
    unsafe_dispatch_count: int = Field(default=0, ge=0, le=10_000)
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime: Literal["hypertrade-eval"]
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def internally_consistent(self) -> SkillEvaluationV1:
        if self.passed_count > self.case_count:
            raise ValueError("passed_count cannot exceed case_count")
        expected_pass = (
            self.passed_count == self.case_count
            and self.regression_count == 0
            and self.unsafe_dispatch_count == 0
        )
        if (self.status == "passed") != expected_pass:
            raise ValueError("evaluation status contradicts its counters")
        return self


class SkillApprovalV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SkillRollbackV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_release_id: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=1_000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class SkillStaticPolicy:
    """Reject executable/sensitive content and any attempted tool expansion."""

    FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"```\s*(python|py|bash|sh|shell|javascript|js|typescript|ts)", "executable_code_fence"),
        (r"\b(import|from)\s+(os|sys|subprocess|socket|requests|httpx)\b", "code_import"),
        (r"\b(eval|exec|compile|system|popen)\s*\(", "dynamic_execution"),
        (r"\b(curl|wget|nc|netcat|ssh)\s+", "shell_or_network_command"),
        (r"https?://", "network_endpoint"),
        (r"\b(api[_-]?key|secret|password|passphrase|access[_-]?token)\b", "secret_material"),
        (r"\b(paper_start|paper_pause|paper_stop|live_order|order_intent)\b", "write_action"),
    )

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry.default()

    def check(self, definition: SkillDefinitionV1) -> dict[str, Any]:
        violations: list[dict[str, str]] = []
        serialized = json.dumps(definition.model_dump(mode="json"), ensure_ascii=False)
        for pattern, code in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, serialized, flags=re.IGNORECASE):
                violations.append({"code": code, "message": "forbidden skill content"})
        roles: list[RoleDefinition] = []
        for role_key in definition.role_keys:
            role = ROLE_CATALOG.get(role_key)
            if role is None:
                violations.append({"code": "unknown_role", "message": role_key})
            else:
                roles.append(role)
        for tool_name in definition.required_tools:
            try:
                tool = self.registry.get(tool_name)
            except KeyError:
                violations.append({"code": "unknown_tool", "message": tool_name})
                continue
            if tool.policy.scope not in {"read", "live_diagnostic_read"}:
                violations.append({"code": "non_read_tool", "message": tool_name})
            for role in roles:
                if tool_name not in role.allowed_tools:
                    violations.append(
                        {
                            "code": "role_tool_expansion",
                            "message": f"{role.key}:{tool_name}",
                        }
                    )
        return {
            "status": "passed" if not violations else "failed",
            "policy_version": "skill_static_policy.v1",
            "violations": violations,
            "checked_at": utc_now().isoformat(),
        }


class SkillIsolatedEvaluator:
    """Run deterministic regression only inside the isolated evaluation runtime."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        definition: SkillDefinitionV1,
        *,
        baseline_id: str,
        idempotency_key: str,
    ) -> SkillEvaluationV1:
        if self.settings.app_env != "evaluation":
            raise PermissionError("skill evaluation requires APP_ENV=evaluation")
        if not self.settings.skill_eval_attestation_secret:
            raise PermissionError("skill evaluation attestation secret is not configured")
        static = SkillStaticPolicy().check(definition)
        suite = AgentEvalSuite().status()
        case_count = int(suite["case_count"])
        passed_count = case_count if suite["status"] == "passed" else 0
        status = (
            "passed"
            if static["status"] == "passed" and passed_count == case_count
            else "failed"
        )
        proposal_hash = definition_hash(definition)
        artifact_hash = _hash_json(
            {
                "proposal_hash": proposal_hash,
                "suite_version": SKILL_EVAL_SUITE_VERSION,
                "baseline_id": baseline_id,
                "case_count": case_count,
                "passed_count": passed_count,
                "status": status,
                "static_policy": static["status"],
            }
        )
        unsigned = {
            "proposal_hash": proposal_hash,
            "status": status,
            "suite_version": SKILL_EVAL_SUITE_VERSION,
            "baseline_id": baseline_id,
            "case_count": case_count,
            "passed_count": passed_count,
            "regression_count": 0 if status == "passed" else 1,
            "unsafe_dispatch_count": 0,
            "artifact_hash": artifact_hash,
            "runtime": "hypertrade-eval",
            "idempotency_key": idempotency_key,
        }
        return SkillEvaluationV1(
            **unsigned,
            signature=_attestation_signature(
                unsigned,
                self.settings.skill_eval_attestation_secret,
            ),
        )


class SkillLifecycleService:
    """Trusted state machine; proposals and attestations never become active implicitly."""

    def __init__(self, db: Database, *, attestation_secret: str = "") -> None:
        self.db = db
        self.policy = SkillStaticPolicy()
        self.attestation_secret = attestation_secret

    def propose(self, payload: SkillProposalV1, *, actor: str) -> dict[str, Any]:
        definition = payload.definition
        proposal_hash = definition_hash(definition)
        static = self.policy.check(definition)
        with self.db.session() as session:
            replay = session.scalar(
                select(SkillProposal).where(
                    SkillProposal.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.definition_hash != proposal_hash:
                    raise ValueError("idempotency key is bound to another skill proposal")
                return {**proposal_to_dict(replay), "idempotent": True}
            pointer = session.get(SkillActivePointer, definition.skill_key)
            base_release_id = payload.base_release_id
            base_definition: dict[str, Any] = {}
            if pointer is not None:
                if base_release_id is None:
                    base_release_id = pointer.active_release_id
                if base_release_id != pointer.active_release_id:
                    raise ValueError("base release must be the active release")
                base = session.get(SkillRelease, base_release_id)
                if base is None:
                    raise ValueError("active base release is missing")
                base_definition = dict(base.definition_json)
                if base.definition_hash == proposal_hash:
                    raise ValueError("skill proposal has no semantic change")
            elif base_release_id is not None:
                raise ValueError("new skill cannot declare a base release")
            definition_json = definition.model_dump(mode="json")
            row = SkillProposal(
                skill_key=definition.skill_key,
                base_release_id=base_release_id,
                definition_json=definition_json,
                definition_hash=proposal_hash,
                status="proposed" if static["status"] == "passed" else "static_failed",
                static_check_json=static,
                diff_text=_definition_diff(base_definition, definition_json),
                idempotency_key=payload.idempotency_key,
                proposed_by=actor,
                audit_json=[
                    {
                        "event": "proposed",
                        "actor": actor,
                        "static_status": static["status"],
                        "at": utc_now().isoformat(),
                    }
                ],
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                raced = session.scalar(
                    select(SkillProposal).where(
                        SkillProposal.idempotency_key == payload.idempotency_key
                    )
                )
                if raced is None:
                    raise
                return {**proposal_to_dict(raced), "idempotent": True}
            return proposal_to_dict(row)

    def record_evaluation(
        self,
        proposal_id: str,
        payload: SkillEvaluationV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        if not self.attestation_secret:
            raise PermissionError("skill evaluation attestation verification is not configured")
        expected_signature = _attestation_signature(
            _attestation_payload(payload),
            self.attestation_secret,
        )
        if not hmac.compare_digest(payload.signature, expected_signature):
            raise ValueError("invalid isolated evaluation attestation signature")
        with self.db.session() as session:
            replay = session.scalar(
                select(SkillEvaluation).where(
                    SkillEvaluation.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if (
                    replay.proposal_id != proposal_id
                    or replay.artifact_hash != payload.artifact_hash
                ):
                    raise ValueError("evaluation idempotency key is bound to another result")
                return {**evaluation_to_dict(replay), "idempotent": True}
            proposal_query = select(SkillProposal).where(SkillProposal.id == proposal_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                proposal_query = proposal_query.with_for_update()
            proposal = session.scalar(proposal_query)
            if proposal is None:
                raise KeyError(proposal_id)
            if proposal.status == "static_failed":
                raise ValueError("static-failed proposal cannot enter evaluation")
            if proposal.status not in {"proposed", "evaluation_failed", "pending_approval"}:
                raise ValueError(f"proposal cannot accept evaluation from {proposal.status}")
            if payload.proposal_hash != proposal.definition_hash:
                raise ValueError("evaluation proposal hash mismatch")
            if payload.suite_version != SKILL_EVAL_SUITE_VERSION:
                raise ValueError("unsupported evaluation suite version")
            row = SkillEvaluation(
                proposal_id=proposal.id,
                proposal_hash=payload.proposal_hash,
                status=payload.status,
                suite_version=payload.suite_version,
                baseline_id=payload.baseline_id,
                case_count=payload.case_count,
                passed_count=payload.passed_count,
                artifact_hash=payload.artifact_hash,
                runtime=payload.runtime,
                result_json={
                    "regression_count": payload.regression_count,
                    "unsafe_dispatch_count": payload.unsafe_dispatch_count,
                    "attestation_signature": payload.signature,
                    "privacy": "metadata_only",
                },
                idempotency_key=payload.idempotency_key,
                evaluated_by=actor,
            )
            session.add(row)
            proposal.status = (
                "pending_approval" if payload.status == "passed" else "evaluation_failed"
            )
            _append_audit(
                proposal,
                event="evaluation_recorded",
                actor=actor,
                payload={"status": payload.status, "artifact_hash": payload.artifact_hash},
            )
            session.flush()
            return evaluation_to_dict(row)

    def decide(
        self,
        proposal_id: str,
        payload: SkillApprovalV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            replay = session.scalar(
                select(SkillApproval).where(
                    SkillApproval.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.proposal_id != proposal_id or replay.decision != payload.decision:
                    raise ValueError("approval idempotency key is bound to another decision")
                return {**approval_to_dict(replay), "idempotent": True}
            proposal_query = select(SkillProposal).where(SkillProposal.id == proposal_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                proposal_query = proposal_query.with_for_update()
            proposal = session.scalar(proposal_query)
            if proposal is None:
                raise KeyError(proposal_id)
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                # Serializes first release and upgrades by skill key even before
                # an active-pointer row exists; no second approval can mint v1.
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:skill_key))"),
                    {"skill_key": proposal.skill_key},
                )
            reason = payload.reason.strip()
            if not reason:
                raise ValueError("approval reason must contain text")
            if payload.decision == "reject":
                if proposal.status in {"approved", "rejected"}:
                    raise ValueError(f"proposal cannot be rejected from {proposal.status}")
                proposal.status = "rejected"
                approval = SkillApproval(
                    proposal_id=proposal.id,
                    decision="reject",
                    reason=reason,
                    idempotency_key=payload.idempotency_key,
                    decided_by=actor,
                )
                session.add(approval)
                session.flush()
                return approval_to_dict(approval)
            if proposal.status != "pending_approval":
                raise ValueError("proposal requires a passing isolated evaluation")
            latest_eval = session.scalar(
                select(SkillEvaluation)
                .where(SkillEvaluation.proposal_id == proposal.id)
                .order_by(SkillEvaluation.created_at.desc())
                .limit(1)
            )
            if (
                latest_eval is None
                or latest_eval.status != "passed"
                or latest_eval.proposal_hash != proposal.definition_hash
                or latest_eval.runtime != "hypertrade-eval"
                or latest_eval.result_json.get("unsafe_dispatch_count") != 0
                or latest_eval.result_json.get("regression_count") != 0
            ):
                raise ValueError("proposal has no valid passing isolated evaluation")
            pointer_query = select(SkillActivePointer).where(
                SkillActivePointer.skill_key == proposal.skill_key
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                pointer_query = pointer_query.with_for_update()
            pointer = session.scalar(pointer_query)
            previous = None
            if pointer is not None:
                previous = session.get(SkillRelease, pointer.active_release_id)
            version = int(
                session.scalar(
                    select(func.max(SkillRelease.version)).where(
                        SkillRelease.skill_key == proposal.skill_key
                    )
                )
                or 0
            ) + 1
            release = SkillRelease(
                skill_key=proposal.skill_key,
                version=version,
                proposal_id=proposal.id,
                definition_json=dict(proposal.definition_json),
                definition_hash=proposal.definition_hash,
                status="active",
                approved_by=actor,
                approval_reason=reason,
                audit_json=[
                    {
                        "event": "released",
                        "actor": actor,
                        "reason": reason,
                        "at": utc_now().isoformat(),
                    }
                ],
            )
            session.add(release)
            session.flush()
            if previous is not None:
                previous.status = "superseded"
            if pointer is None:
                pointer = SkillActivePointer(
                    skill_key=proposal.skill_key,
                    active_release_id=release.id,
                    version=version,
                    updated_by=actor,
                    reason=reason,
                )
                session.add(pointer)
            else:
                pointer.active_release_id = release.id
                pointer.version = version
                pointer.updated_by = actor
                pointer.reason = reason
            proposal.status = "approved"
            approval = SkillApproval(
                proposal_id=proposal.id,
                release_id=release.id,
                decision="approve",
                reason=reason,
                idempotency_key=payload.idempotency_key,
                decided_by=actor,
            )
            session.add(approval)
            session.flush()
            return {
                "approval": approval_to_dict(approval),
                "release": release_to_dict(release),
            }

    def rollback(
        self,
        release_id: str,
        payload: SkillRollbackV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            replay = session.scalar(
                select(SkillApproval).where(
                    SkillApproval.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if (
                    replay.release_id != release_id
                    or replay.target_release_id != payload.target_release_id
                ):
                    raise ValueError("rollback idempotency key is bound to another transition")
                target = session.get(SkillRelease, replay.target_release_id)
                if target is None:
                    raise KeyError(replay.target_release_id)
                return {**release_to_dict(target), "idempotent": True}
            current = session.get(SkillRelease, release_id)
            target = session.get(SkillRelease, payload.target_release_id)
            if current is None:
                raise KeyError(release_id)
            if target is None:
                raise KeyError(payload.target_release_id)
            if current.skill_key != target.skill_key or target.version >= current.version:
                raise ValueError("rollback target must be an older release of the same skill")
            pointer_query = select(SkillActivePointer).where(
                SkillActivePointer.skill_key == current.skill_key
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                pointer_query = pointer_query.with_for_update()
            pointer = session.scalar(pointer_query)
            if pointer is None or pointer.active_release_id != current.id:
                raise ValueError("only the active release can be rolled back")
            reason = payload.reason.strip()
            current.status = "rolled_back"
            target.status = "active"
            pointer.active_release_id = target.id
            pointer.version = target.version
            pointer.updated_by = actor
            pointer.reason = reason
            audit = list(target.audit_json or [])
            audit.append(
                {"event": "restored", "actor": actor, "reason": reason, "at": utc_now().isoformat()}
            )
            target.audit_json = audit[-200:]
            session.add(
                SkillApproval(
                    release_id=current.id,
                    target_release_id=target.id,
                    decision="rollback",
                    reason=reason,
                    idempotency_key=payload.idempotency_key,
                    decided_by=actor,
                )
            )
            session.flush()
            return release_to_dict(target)

    def list_proposals(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(SkillProposal)
                .order_by(SkillProposal.created_at.desc())
                .limit(max(1, min(limit, 500)))
            ).all()
            return [proposal_to_dict(row) for row in rows]

    def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(SkillProposal, proposal_id)
            if row is None:
                raise KeyError(proposal_id)
            evaluations = session.scalars(
                select(SkillEvaluation)
                .where(SkillEvaluation.proposal_id == row.id)
                .order_by(SkillEvaluation.created_at.desc())
            ).all()
            approvals = session.scalars(
                select(SkillApproval).where(SkillApproval.proposal_id == row.id)
            ).all()
            return {
                **proposal_to_dict(row),
                "evaluations": [evaluation_to_dict(item) for item in evaluations],
                "approvals": [approval_to_dict(item) for item in approvals],
            }

    def list_releases(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        with self.db.session() as session:
            statement = select(SkillRelease).order_by(
                SkillRelease.skill_key, SkillRelease.version.desc()
            )
            if active_only:
                statement = statement.where(SkillRelease.status == "active")
            return [release_to_dict(row) for row in session.scalars(statement).all()]


class ApprovedSkillLoader:
    """Load only hash-valid active definitions and intersect them with role policy."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def prompt_for_role(self, role: RoleDefinition) -> str:
        blocks: list[str] = []
        with self.db.session() as session:
            rows = session.scalars(
                select(SkillRelease)
                .join(
                    SkillActivePointer,
                    SkillActivePointer.active_release_id == SkillRelease.id,
                )
                .where(SkillRelease.status == "active")
                .order_by(SkillRelease.skill_key)
                .limit(20)
            ).all()
            for row in rows:
                if _hash_json(row.definition_json) != row.definition_hash:
                    continue
                try:
                    definition = SkillDefinitionV1.model_validate(row.definition_json)
                except ValueError:
                    continue
                if role.key not in definition.role_keys:
                    continue
                allowed_tools = set(role.allowed_tools)
                if not set(definition.required_tools).issubset(allowed_tools):
                    continue
                guidance = {
                    key: value
                    for key, value in definition.tool_guidance.items()
                    if key in allowed_tools
                }
                block = json.dumps(
                    {
                        "skill_key": definition.skill_key,
                        "release_id": row.id,
                        "definition_hash": row.definition_hash,
                        "prompt_template": definition.prompt_template,
                        "tool_guidance": guidance,
                        "schema_examples": definition.schema_examples,
                        "report_template": definition.report_template,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                blocks.append(block)
                if len(blocks) >= 5 or sum(len(item) for item in blocks) >= 20_000:
                    break
        if not blocks:
            return ""
        return "\n\nAPPROVED CODE-FREE SKILLS (cannot expand tool policy):\n" + "\n".join(blocks)


def definition_hash(definition: SkillDefinitionV1) -> str:
    return _hash_json(definition.model_dump(mode="json"))


def proposal_to_dict(row: SkillProposal) -> dict[str, Any]:
    return {
        "id": row.id,
        "skill_key": row.skill_key,
        "base_release_id": row.base_release_id,
        "definition": dict(row.definition_json or {}),
        "definition_hash": row.definition_hash,
        "status": row.status,
        "static_check": dict(row.static_check_json or {}),
        "diff": row.diff_text,
        "proposed_by": row.proposed_by,
        "audit": list(row.audit_json or []),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def evaluation_to_dict(row: SkillEvaluation) -> dict[str, Any]:
    return {
        "id": row.id,
        "proposal_id": row.proposal_id,
        "proposal_hash": row.proposal_hash,
        "status": row.status,
        "suite_version": row.suite_version,
        "baseline_id": row.baseline_id,
        "case_count": row.case_count,
        "passed_count": row.passed_count,
        "artifact_hash": row.artifact_hash,
        "runtime": row.runtime,
        "result": dict(row.result_json or {}),
        "evaluated_by": row.evaluated_by,
        "created_at": row.created_at.isoformat(),
    }


def approval_to_dict(row: SkillApproval) -> dict[str, Any]:
    return {
        "id": row.id,
        "proposal_id": row.proposal_id,
        "release_id": row.release_id,
        "target_release_id": row.target_release_id,
        "decision": row.decision,
        "reason": row.reason,
        "decided_by": row.decided_by,
        "created_at": row.created_at.isoformat(),
    }


def release_to_dict(row: SkillRelease) -> dict[str, Any]:
    return {
        "id": row.id,
        "skill_key": row.skill_key,
        "version": row.version,
        "proposal_id": row.proposal_id,
        "definition": dict(row.definition_json or {}),
        "definition_hash": row.definition_hash,
        "status": row.status,
        "approved_by": row.approved_by,
        "approval_reason": row.approval_reason,
        "audit": list(row.audit_json or []),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _definition_diff(base: dict[str, Any], proposed: dict[str, Any]) -> str:
    left = json.dumps(base, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    right = json.dumps(proposed, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    return "\n".join(
        difflib.unified_diff(left, right, fromfile="active", tofile="proposed", lineterm="")
    )


def _hash_json(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _attestation_payload(payload: SkillEvaluationV1) -> dict[str, Any]:
    return payload.model_dump(mode="json", exclude={"signature"})


def _attestation_signature(payload: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return aware.isoformat()
    return str(value)


def _append_audit(
    proposal: SkillProposal,
    *,
    event: str,
    actor: str,
    payload: dict[str, Any],
) -> None:
    audit = list(proposal.audit_json or [])
    audit.append({"event": event, "actor": actor, "at": utc_now().isoformat(), **payload})
    proposal.audit_json = audit[-200:]
