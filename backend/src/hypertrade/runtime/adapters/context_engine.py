from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hypertrade.db import AgentArtifactRelation, AgentContextPack, AgentMissionArtifact
from hypertrade.runtime.adapters.sql_store import async_database_url
from hypertrade.runtime.domain.context import (
    ArtifactRelationV1,
    ContextBudgetExceeded,
    ContextDecisionV1,
    ContextPackV1,
    ContextSourceV1,
    ContextTokenLedgerV1,
    MissionArtifactCreateV1,
    MissionArtifactV1,
    hash_payload,
)
from hypertrade.runtime.domain.models import (
    MissionProjection,
    PlanStepV2,
    PlanV2,
    StepAttemptV2,
    StepObservationV2,
)

_SECRET_ASSIGNMENT = re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")
_RAW_SERIES_KEYS = {
    "candles",
    "equity_curve",
    "returns",
    "orders",
    "trades",
    "positions",
}


def estimate_tokens(text: str) -> int:
    """Provider-independent deterministic upper approximation for context accounting."""

    return max(1, (len(text.encode("utf-8")) + 3) // 4)


class DeterministicContextCompiler:
    def __init__(self, *, max_source_tokens: int = 1_500) -> None:
        self.max_source_tokens = max_source_tokens

    def compile(
        self,
        *,
        mission_id: str,
        plan_version: int,
        step_id: str,
        attempt: int,
        policy_ref: str,
        budget_tokens: int,
        sources: Sequence[ContextSourceV1],
    ) -> ContextPackV1:
        decisions: list[ContextDecisionV1] = []
        seen_hashes: set[str] = set()
        used = 0
        required_tokens = 0
        ordered = sorted(
            sources,
            key=lambda source: (
                not source.required,
                source.tier,
                source.source_ref,
                source.content_hash,
            ),
        )
        for source in ordered:
            if source.content_hash in seen_hashes:
                decisions.append(self._drop(source, "duplicate"))
                continue
            seen_hashes.add(source.content_hash)
            if source.stale():
                if source.required:
                    raise ContextBudgetExceeded(f"required context is stale: {source.source_ref}")
                decisions.append(self._drop(source, "stale"))
                continue
            if _unsafe_source(source.content):
                if source.required:
                    raise ValueError(f"required context is unsafe: {source.source_ref}")
                decisions.append(self._drop(source, "unsafe_content"))
                continue
            rendered = _redact_text(source.content)
            reason = "required" if source.required else "selected"
            tokens = estimate_tokens(rendered)
            if not source.required and tokens > self.max_source_tokens:
                rendered = _compact(rendered, self.max_source_tokens)
                tokens = estimate_tokens(rendered)
                reason = "compacted"
            if used + tokens > budget_tokens:
                if source.required:
                    raise ContextBudgetExceeded("required context exceeds hard token budget")
                decisions.append(self._drop(source, "budget", tokens=tokens))
                continue
            decisions.append(
                ContextDecisionV1(
                    source_ref=source.source_ref,
                    kind=source.kind,
                    tier=source.tier,
                    included=True,
                    reason=reason,
                    source_hash=source.content_hash,
                    token_estimate=tokens,
                    rendered_content=rendered,
                )
            )
            used += tokens
            if source.required:
                required_tokens += tokens
        manifest = [
            decision.model_dump(mode="json", exclude={"rendered_content"}) for decision in decisions
        ]
        ledger = ContextTokenLedgerV1(
            budget_tokens=budget_tokens,
            used_tokens=used,
            required_tokens=required_tokens,
            included_sources=sum(item.included for item in decisions),
            dropped_sources=sum(not item.included for item in decisions),
        )
        manifest_hash = hash_payload(
            {
                "mission_id": mission_id,
                "plan_version": plan_version,
                "step_id": step_id,
                "attempt": attempt,
                "policy_ref": policy_ref,
                "ledger": ledger.model_dump(mode="json"),
                "decisions": manifest,
            }
        )
        return ContextPackV1(
            context_pack_id=f"ctxp_{manifest_hash[:20]}",
            mission_id=mission_id,
            plan_version=plan_version,
            step_id=step_id,
            attempt=attempt,
            policy_ref=policy_ref,
            decisions=tuple(decisions),
            ledger=ledger,
            manifest_hash=manifest_hash,
        )

    @staticmethod
    def _drop(source: ContextSourceV1, reason: str, *, tokens: int = 0) -> ContextDecisionV1:
        return ContextDecisionV1.model_validate(
            {
                "source_ref": source.source_ref,
                "kind": source.kind,
                "tier": source.tier,
                "included": False,
                "reason": reason,
                "source_hash": source.content_hash,
                "token_estimate": tokens,
            }
        )


class ContextArtifactStore(Protocol):
    async def save_pack(self, pack: ContextPackV1) -> ContextPackV1: ...

    async def list_packs(self, mission_id: str) -> Sequence[ContextPackV1]: ...

    async def register_artifact(
        self, mission_id: str, payload: MissionArtifactCreateV1
    ) -> MissionArtifactV1: ...

    async def list_artifacts(self, mission_id: str) -> Sequence[MissionArtifactV1]: ...

    async def artifact(self, mission_id: str, artifact_id: str) -> MissionArtifactV1: ...

    async def relations(self, mission_id: str) -> Sequence[ArtifactRelationV1]: ...


class InMemoryContextArtifactStore:
    def __init__(self) -> None:
        self.packs: dict[tuple[str, int, str, int], ContextPackV1] = {}
        self.artifacts: dict[str, MissionArtifactV1] = {}
        self._hashes: dict[tuple[str, str], str] = {}
        self._relations: list[tuple[str, ArtifactRelationV1]] = []

    async def save_pack(self, pack: ContextPackV1) -> ContextPackV1:
        key = (pack.mission_id, pack.plan_version, pack.step_id, pack.attempt)
        existing = self.packs.get(key)
        if existing is not None and existing.manifest_hash != pack.manifest_hash:
            raise ValueError("context attempt is bound to a different manifest")
        self.packs[key] = existing or pack
        return self.packs[key]

    async def list_packs(self, mission_id: str) -> Sequence[ContextPackV1]:
        return sorted(
            (row for row in self.packs.values() if row.mission_id == mission_id),
            key=lambda row: (row.plan_version, row.step_id, row.attempt),
        )

    async def register_artifact(
        self, mission_id: str, payload: MissionArtifactCreateV1
    ) -> MissionArtifactV1:
        content_hash = _artifact_hash(payload)
        existing_id = self._hashes.get((mission_id, content_hash))
        if existing_id:
            return self.artifacts[existing_id]
        superseded = self._validate_supersedes(mission_id, payload.supersedes_artifact_id)
        version = 1 + max(
            (row.version for row in self.artifacts.values() if row.mission_id == mission_id),
            default=0,
        )
        artifact = MissionArtifactV1(
            artifact_id=f"mart_{uuid4().hex[:20]}",
            mission_id=mission_id,
            version=version,
            kind=payload.kind,
            title=payload.title,
            media_type=payload.media_type,
            content_hash=content_hash,
            size_bytes=payload.size_bytes or len(_artifact_bytes(payload)),
            external_ref=payload.external_ref,
            inline_preview=payload.inline_preview,
            producer_ref=payload.producer_ref,
            source_refs=payload.source_refs,
            supersedes_artifact_id=payload.supersedes_artifact_id,
        )
        self.artifacts[artifact.artifact_id] = artifact
        self._hashes[(mission_id, content_hash)] = artifact.artifact_id
        for source_ref in payload.source_refs:
            self._relations.append(
                (
                    mission_id,
                    ArtifactRelationV1(
                        from_artifact_id=artifact.artifact_id,
                        to_ref=source_ref,
                        relation_type="derived_from",
                    ),
                )
            )
        if superseded is not None:
            self.artifacts[superseded.artifact_id] = superseded.model_copy(
                update={"status": "superseded"}
            )
            self._relations.append(
                (
                    mission_id,
                    ArtifactRelationV1(
                        from_artifact_id=artifact.artifact_id,
                        to_ref=superseded.stable_ref,
                        relation_type="supersedes",
                    ),
                )
            )
        return artifact

    def _validate_supersedes(self, mission_id: str, artifact_id: str) -> MissionArtifactV1 | None:
        if not artifact_id:
            return None
        artifact = self.artifacts.get(artifact_id)
        if artifact is None or artifact.mission_id != mission_id:
            raise ValueError("superseded artifact does not belong to mission")
        if artifact.status != "current":
            raise ValueError("superseded artifact is not current")
        return artifact

    async def list_artifacts(self, mission_id: str) -> Sequence[MissionArtifactV1]:
        return sorted(
            (row for row in self.artifacts.values() if row.mission_id == mission_id),
            key=lambda row: row.version,
        )

    async def artifact(self, mission_id: str, artifact_id: str) -> MissionArtifactV1:
        artifact = self.artifacts.get(artifact_id)
        if artifact is None or artifact.mission_id != mission_id:
            raise KeyError(artifact_id)
        return artifact

    async def relations(self, mission_id: str) -> Sequence[ArtifactRelationV1]:
        return [row for owner, row in self._relations if owner == mission_id]


class SqlContextArtifactStore(InMemoryContextArtifactStore):
    def __init__(self, database_url: str) -> None:
        super().__init__()
        self.engine = create_async_engine(async_database_url(database_url), pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def save_pack(self, pack: ContextPackV1) -> ContextPackV1:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(AgentContextPack)
                .where(AgentContextPack.mission_id == pack.mission_id)
                .where(AgentContextPack.plan_version == pack.plan_version)
                .where(AgentContextPack.step_id == pack.step_id)
                .where(AgentContextPack.attempt == pack.attempt)
            )
            if existing is not None:
                if existing.manifest_hash != pack.manifest_hash:
                    raise ValueError("context attempt is bound to a different manifest")
                return _pack_from_row(existing)
            session.add(
                AgentContextPack(
                    id=pack.context_pack_id,
                    mission_id=pack.mission_id,
                    plan_version=pack.plan_version,
                    step_id=pack.step_id,
                    attempt=pack.attempt,
                    policy_ref=pack.policy_ref,
                    budget_tokens=pack.ledger.budget_tokens,
                    used_tokens=pack.ledger.used_tokens,
                    manifest_hash=pack.manifest_hash,
                    decisions_json=[item.model_dump(mode="json") for item in pack.decisions],
                    created_at=pack.created_at,
                )
            )
        return pack

    async def list_packs(self, mission_id: str) -> Sequence[ContextPackV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentContextPack)
                    .where(AgentContextPack.mission_id == mission_id)
                    .order_by(
                        AgentContextPack.plan_version,
                        AgentContextPack.step_id,
                        AgentContextPack.attempt,
                    )
                )
            ).all()
            return [_pack_from_row(row) for row in rows]

    async def register_artifact(
        self, mission_id: str, payload: MissionArtifactCreateV1
    ) -> MissionArtifactV1:
        _validate_artifact_payload(payload)
        content_hash = _artifact_hash(payload)
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(AgentMissionArtifact)
                .where(AgentMissionArtifact.mission_id == mission_id)
                .where(AgentMissionArtifact.content_hash == content_hash)
            )
            if existing is not None:
                return _artifact_from_row(existing)
            superseded = None
            if payload.supersedes_artifact_id:
                superseded = await session.get(
                    AgentMissionArtifact,
                    payload.supersedes_artifact_id,
                    with_for_update=True,
                )
                if (
                    superseded is None
                    or superseded.mission_id != mission_id
                    or superseded.status != "current"
                ):
                    raise ValueError("superseded artifact is not a current mission artifact")
            latest = await session.scalar(
                select(func.max(AgentMissionArtifact.version)).where(
                    AgentMissionArtifact.mission_id == mission_id
                )
            )
            row = AgentMissionArtifact(
                mission_id=mission_id,
                version=int(latest or 0) + 1,
                kind=payload.kind,
                title=payload.title,
                media_type=payload.media_type,
                content_hash=content_hash,
                size_bytes=payload.size_bytes or len(_artifact_bytes(payload)),
                external_ref=payload.external_ref,
                inline_preview_json=payload.inline_preview,
                producer_ref=payload.producer_ref,
                source_refs_json=list(payload.source_refs),
                supersedes_artifact_id=payload.supersedes_artifact_id,
                status="current",
            )
            session.add(row)
            await session.flush()
            for source_ref in payload.source_refs:
                session.add(
                    AgentArtifactRelation(
                        mission_id=mission_id,
                        from_artifact_id=row.id,
                        to_ref=source_ref,
                        relation_type="derived_from",
                    )
                )
            if superseded is not None:
                superseded.status = "superseded"
                session.add(
                    AgentArtifactRelation(
                        mission_id=mission_id,
                        from_artifact_id=row.id,
                        to_ref=_stable_row_ref(superseded),
                        relation_type="supersedes",
                    )
                )
            return _artifact_from_row(row)

    async def list_artifacts(self, mission_id: str) -> Sequence[MissionArtifactV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentMissionArtifact)
                    .where(AgentMissionArtifact.mission_id == mission_id)
                    .order_by(AgentMissionArtifact.version)
                )
            ).all()
            return [_artifact_from_row(row) for row in rows]

    async def artifact(self, mission_id: str, artifact_id: str) -> MissionArtifactV1:
        async with self.sessions() as session:
            row = await session.get(AgentMissionArtifact, artifact_id)
            if row is None or row.mission_id != mission_id:
                raise KeyError(artifact_id)
            return _artifact_from_row(row)

    async def relations(self, mission_id: str) -> Sequence[ArtifactRelationV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentArtifactRelation)
                    .where(AgentArtifactRelation.mission_id == mission_id)
                    .order_by(AgentArtifactRelation.created_at)
                )
            ).all()
            return [
                ArtifactRelationV1(
                    from_artifact_id=row.from_artifact_id,
                    to_ref=row.to_ref,
                    relation_type=row.relation_type,
                )
                for row in rows
            ]


class ContextArtifactEngine:
    def __init__(
        self,
        store: ContextArtifactStore,
        compiler: DeterministicContextCompiler | None = None,
    ) -> None:
        self.store = store
        self.compiler = compiler or DeterministicContextCompiler()

    async def prepare(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
        prior_attempts: Sequence[StepAttemptV2],
    ) -> ContextPackV1:
        sources = _runtime_sources(mission, plan, step, prior_attempts)
        remaining = max(0, mission.budget.max_tokens - mission.usage.tokens)
        budget = min(8_192, max(512, remaining))
        pack = self.compiler.compile(
            mission_id=mission.mission_id,
            plan_version=plan.version,
            step_id=step.step_id,
            attempt=attempt,
            policy_ref=mission.context_policy_ref,
            budget_tokens=budget,
            sources=sources,
        )
        return await self.store.save_pack(pack)

    async def validate_completion(
        self,
        mission: MissionProjection,
        observations: Sequence[StepObservationV2],
    ) -> bool:
        artifacts = await self.store.list_artifacts(mission.mission_id)
        by_ref = {artifact.stable_ref: artifact for artifact in artifacts}
        for observation in observations:
            for ref in observation.artifact_refs:
                artifact = by_ref.get(ref)
                if artifact is None or artifact.status != "current":
                    return False
        for criterion in mission.success_criteria:
            if criterion.kind == "artifact_kind_exists" and not any(
                artifact.kind == str(criterion.expected) and artifact.status == "current"
                for artifact in artifacts
            ):
                return False
        return True


def _runtime_sources(
    mission: MissionProjection,
    plan: PlanV2,
    step: PlanStepV2,
    prior_attempts: Sequence[StepAttemptV2],
) -> tuple[ContextSourceV1, ...]:
    required = (
        ContextSourceV1(
            source_ref=f"mission:{mission.mission_id}:objective",
            kind="mission",
            tier=0,
            required=True,
            content=_redact_text(mission.objective),
        ),
        ContextSourceV1(
            source_ref=f"mission:{mission.mission_id}:constraints",
            kind="mission",
            tier=0,
            required=True,
            content=json.dumps(
                {
                    "constraints": mission.constraints,
                    "permission_profile_ref": mission.permission_profile_ref,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
        ),
        ContextSourceV1(
            source_ref=f"plan:{plan.plan_id}@{plan.version}",
            kind="plan",
            tier=1,
            required=True,
            content=json.dumps(
                {
                    "goal_interpretation": plan.goal_interpretation,
                    "completion_checks": plan.completion_checks,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
        ),
        ContextSourceV1(
            source_ref=f"step:{step.step_id}",
            kind="step",
            tier=1,
            required=True,
            content=json.dumps(step.model_dump(mode="json"), sort_keys=True, ensure_ascii=False),
        ),
    )
    observations = tuple(
        ContextSourceV1(
            source_ref=f"observation:{row.attempt_id}",
            kind="observation",
            tier=2,
            content=json.dumps(
                {
                    "summary": row.observation.summary,
                    "source_refs": row.observation.source_refs,
                    "artifact_refs": row.observation.artifact_refs,
                    "unknowns": row.observation.unknowns,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
        )
        for row in prior_attempts
        if row.status == "succeeded" and row.observation is not None
    )
    return required + observations


def _artifact_hash(payload: MissionArtifactCreateV1) -> str:
    _validate_artifact_payload(payload)
    computed = (
        hash_payload(payload.inline_preview) if payload.inline_preview else payload.content_hash
    )
    if payload.content_hash and payload.inline_preview and payload.content_hash != computed:
        raise ValueError("artifact content hash mismatch")
    if not computed:
        raise ValueError("external artifact requires a content hash")
    return computed


def _validate_artifact_payload(payload: MissionArtifactCreateV1) -> None:
    encoded = _artifact_bytes(payload)
    if len(encoded) > 32_768:
        raise ValueError("artifact inline preview exceeds 32768 bytes")
    if _unsafe_value(payload.inline_preview):
        raise ValueError("artifact preview contains secret or raw-series fields")
    if payload.external_ref and "://" not in payload.external_ref:
        raise ValueError("artifact external ref must be a stable URI")


def _artifact_bytes(payload: MissionArtifactCreateV1) -> bytes:
    return json.dumps(
        payload.inline_preview, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def _unsafe_value(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).casefold()
            if any(token in lowered for token in ("secret", "password", "api_key", "token")):
                return True
            if lowered in _RAW_SERIES_KEYS:
                return True
            if _unsafe_value(item):
                return True
    elif isinstance(value, list):
        return any(_unsafe_value(item) for item in value)
    return False


def _unsafe_source(content: str) -> bool:
    """Reject embedded raw series, but retain trusted capability-schema metadata.

    A plan step legitimately declares output fields such as ``positions`` and
    ``orders``. Those declarations are not raw tool payloads. The context
    boundary only rejects a field when it actually embeds an array of raw
    records, so a governed read cannot fail before its tool is invoked.
    """

    keys = "|".join(re.escape(key) for key in sorted(_RAW_SERIES_KEYS))
    return bool(re.search(rf'"(?:{keys})"\s*:\s*\[', content, flags=re.IGNORECASE))


def _redact_text(text: str) -> str:
    return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def _compact(text: str, max_tokens: int) -> str:
    max_bytes = max_tokens * 4
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    prefix = encoded[: max(1, max_bytes - 80)].decode("utf-8", errors="ignore")
    return f"{prefix}\n[COMPACTED source_hash={hash_payload(text)}]"


def _pack_from_row(row: AgentContextPack) -> ContextPackV1:
    decisions = tuple(ContextDecisionV1.model_validate(item) for item in row.decisions_json)
    return ContextPackV1(
        context_pack_id=row.id,
        mission_id=row.mission_id,
        plan_version=row.plan_version,
        step_id=row.step_id,
        attempt=row.attempt,
        policy_ref=row.policy_ref,
        decisions=decisions,
        ledger=ContextTokenLedgerV1(
            budget_tokens=row.budget_tokens,
            used_tokens=row.used_tokens,
            required_tokens=sum(
                item.token_estimate
                for item in decisions
                if item.included and item.reason == "required"
            ),
            included_sources=sum(item.included for item in decisions),
            dropped_sources=sum(not item.included for item in decisions),
        ),
        manifest_hash=row.manifest_hash,
        created_at=row.created_at,
    )


def _artifact_from_row(row: AgentMissionArtifact) -> MissionArtifactV1:
    return MissionArtifactV1(
        artifact_id=row.id,
        mission_id=row.mission_id,
        version=row.version,
        kind=row.kind,
        title=row.title,
        media_type=row.media_type,
        content_hash=row.content_hash,
        size_bytes=row.size_bytes,
        external_ref=row.external_ref,
        inline_preview=row.inline_preview_json,
        producer_ref=row.producer_ref,
        source_refs=tuple(row.source_refs_json),
        supersedes_artifact_id=row.supersedes_artifact_id,
        status=row.status,
        created_at=row.created_at,
    )


def _stable_row_ref(row: AgentMissionArtifact) -> str:
    return f"artifact:{row.id}@{row.content_hash}"
