"""Immutable Strategy Outcome ledger and independently reviewed Lesson candidates."""

from __future__ import annotations

import builtins
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    AgentApproval,
    AgentMission,
    AgentToolCall,
    Database,
    ExperimentExecution,
    PortfolioObservationWindow,
    ResearchEvidence,
    StrategyCardSnapshot,
    StrategyLessonCandidate,
    StrategyLessonReview,
    StrategyOutcome,
    StrategyVersion,
    utc_now,
)
from hypertrade.research.outcome_schemas import (
    LessonCandidateV1,
    LessonReviewV1,
    StrategyOutcomeV1,
    canonical_payload,
    content_hash,
)


class StrategyOutcomeLedgerService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def append(self, payload: StrategyOutcomeV1, *, actor: str) -> dict[str, Any]:
        digest = content_hash(payload, exclude={"idempotency_key"})
        body = canonical_payload(payload, exclude={"idempotency_key"})
        with self.db.session() as session:
            replay = session.scalar(
                select(StrategyOutcome).where(
                    StrategyOutcome.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.content_hash != digest:
                    raise ValueError("outcome idempotency key is bound to another payload")
                return {**outcome_to_dict(replay), "idempotent": True}
            duplicate = session.scalar(
                select(StrategyOutcome).where(StrategyOutcome.content_hash == digest)
            )
            if duplicate is not None:
                return {**outcome_to_dict(duplicate), "deduplicated": True}

            self._validate_sources(session, payload)
            row = StrategyOutcome(
                schema_version=payload.schema_version,
                outcome_type=payload.outcome_type,
                strategy_lineage_id=payload.strategy_lineage_id,
                strategy_version_id=payload.strategy_version_id,
                strategy_card_id=payload.strategy_card_id,
                manifest_id=payload.manifest_id,
                experiment_execution_id=payload.experiment_execution_id,
                mission_id=payload.mission_id,
                observation_window_id=payload.observation_window_id,
                corrects_id=payload.corrects_id,
                supersedes_id=payload.supersedes_id,
                as_of=payload.as_of,
                settled_at=payload.settled_at,
                content_hash=digest,
                idempotency_key=payload.idempotency_key,
                outcome_json=body,
                created_by=actor,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                winner = session.scalar(
                    select(StrategyOutcome).where(StrategyOutcome.content_hash == digest)
                )
                if winner is None:
                    raise
                return {**outcome_to_dict(winner), "deduplicated": True}
            return outcome_to_dict(row)

    def get(self, outcome_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(StrategyOutcome, outcome_id)
            if row is None:
                raise KeyError(outcome_id)
            return outcome_to_dict(row)

    def list(self, *, strategy_lineage_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            statement = select(StrategyOutcome).order_by(StrategyOutcome.created_at.desc())
            if strategy_lineage_id:
                statement = statement.where(
                    StrategyOutcome.strategy_lineage_id == strategy_lineage_id
                )
            rows = session.scalars(statement.limit(max(1, min(limit, 500)))).all()
            return [outcome_to_dict(row) for row in rows]

    def replay_hash(self) -> str:
        with self.db.session() as session:
            rows = session.scalars(
                select(StrategyOutcome).order_by(
                    StrategyOutcome.settled_at, StrategyOutcome.content_hash
                )
            ).all()
        return _hash([row.content_hash for row in rows])

    @staticmethod
    def _validate_sources(session: Any, payload: StrategyOutcomeV1) -> None:
        version = session.get(StrategyVersion, payload.strategy_version_id)
        if version is None or version.lineage_id != payload.strategy_lineage_id:
            raise ValueError("outcome strategy version/lineage is not canonical")
        if version.manifest_id != payload.manifest_id:
            raise ValueError("outcome manifest does not match strategy version")
        card = session.scalar(
            select(StrategyCardSnapshot).where(
                StrategyCardSnapshot.card_id == payload.strategy_card_id,
                StrategyCardSnapshot.version_id == payload.strategy_version_id,
            )
        )
        if card is None:
            raise ValueError("outcome requires a matching StrategyCard snapshot")

        if payload.outcome_type == "backtest_validated" and not payload.experiment_execution_id:
            raise ValueError("backtest outcome requires an experiment execution")
        if payload.experiment_execution_id:
            execution = session.get(ExperimentExecution, payload.experiment_execution_id)
            if (
                execution is None
                or execution.status != "completed"
                or execution.manifest_id != payload.manifest_id
                or execution.completed_at is None
            ):
                raise ValueError("outcome requires a completed matching experiment execution")

        mission = session.get(AgentMission, payload.mission_id)
        proof = dict(mission.completion_proof_json or {}) if mission is not None else {}
        if (
            mission is None
            or mission.status != "completed"
            or not proof.get("passed")
            or proof.get("mission_id") != payload.mission_id
            or int(proof.get("mission_version", -1)) != mission.version
            or bool(proof.get("effect_unknown"))
        ):
            raise ValueError("outcome requires a current passing Mission CompletionProof")

        evidence = session.scalars(
            select(ResearchEvidence).where(ResearchEvidence.id.in_(payload.evidence_ids))
        ).all()
        now = utc_now()
        if len(evidence) != len(set(payload.evidence_ids)) or any(
            row.status != "active"
            or (row.valid_until is not None and _utc(row.valid_until) <= now)
            or _utc(row.as_of) > payload.as_of
            for row in evidence
        ):
            raise ValueError("outcome evidence is missing, expired, stale, or unsettled")

        if payload.approval_ids:
            approvals = session.scalars(
                select(AgentApproval).where(AgentApproval.id.in_(payload.approval_ids))
            ).all()
            if len(approvals) != len(set(payload.approval_ids)) or any(
                row.status != "consumed" or row.mission_id != payload.mission_id
                for row in approvals
            ):
                raise ValueError("outcome approval source is not consumed or mission-bound")

        if payload.tool_call_ids:
            calls = session.scalars(
                select(AgentToolCall).where(AgentToolCall.id.in_(payload.tool_call_ids))
            ).all()
            if len(calls) != len(set(payload.tool_call_ids)) or any(
                row.mission_id != payload.mission_id or not _tool_call_is_settled(row)
                for row in calls
            ):
                raise ValueError("outcome ToolCall source has an unknown or unfinished effect")

        if payload.observation_window_id:
            window = session.get(PortfolioObservationWindow, payload.observation_window_id)
            summaries = list(window.strategy_summaries_json or []) if window else []
            matching = [
                item for item in summaries if str(item.get("card_id")) == payload.strategy_card_id
            ]
            acceptable = {"available"}
            if payload.outcome_type == "paper_degraded":
                acceptable |= {"stale", "insufficient", "source_unhealthy", "no_window"}
            if (
                window is None
                or _utc(window.window_end) > payload.as_of
                or not matching
                or str(matching[0].get("status")) not in acceptable
            ):
                raise ValueError("paper outcome requires a settled matching observation window")

        source_artifacts = set(proof.get("artifact_refs", []))
        if payload.experiment_execution_id:
            execution = session.get(ExperimentExecution, payload.experiment_execution_id)
            if execution is not None:
                source_artifacts.update(
                    str(item.get("artifact_ref", ""))
                    for item in dict(execution.artifact_manifest_json or {}).get("items", [])
                )
        if not set(payload.artifact_refs).issubset(source_artifacts):
            raise ValueError("outcome artifact refs are not bound to canonical sources")

        for relation_id in (payload.corrects_id, payload.supersedes_id):
            if not relation_id:
                continue
            prior = session.get(StrategyOutcome, relation_id)
            if prior is None or prior.strategy_lineage_id != payload.strategy_lineage_id:
                raise ValueError("outcome correction must reference the same strategy lineage")


class LessonCandidateService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def propose(self, payload: LessonCandidateV1, *, actor: str) -> dict[str, Any]:
        digest = content_hash(payload, exclude={"idempotency_key"})
        body = canonical_payload(payload, exclude={"idempotency_key"})
        with self.db.session() as session:
            replay = session.scalar(
                select(StrategyLessonCandidate).where(
                    StrategyLessonCandidate.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.content_hash != digest:
                    raise ValueError("lesson idempotency key is bound to another payload")
                return {**lesson_to_dict(replay), "idempotent": True}
            duplicate = session.scalar(
                select(StrategyLessonCandidate).where(
                    StrategyLessonCandidate.content_hash == digest
                )
            )
            if duplicate is not None:
                return {**lesson_to_dict(duplicate), "deduplicated": True}
            if payload.valid_until <= utc_now():
                raise ValueError("lesson validity must end in the future")
            outcomes = session.scalars(
                select(StrategyOutcome).where(StrategyOutcome.id.in_(payload.outcome_ids))
            ).all()
            if len(outcomes) != len(set(payload.outcome_ids)):
                raise ValueError("lesson requires settled canonical outcomes")
            row = StrategyLessonCandidate(
                schema_version=payload.schema_version,
                status="proposed",
                stance=payload.stance,
                target_type=payload.target_type,
                content_hash=digest,
                idempotency_key=payload.idempotency_key,
                valid_until=payload.valid_until,
                lesson_json=body,
                created_by=actor,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                winner = session.scalar(
                    select(StrategyLessonCandidate).where(
                        StrategyLessonCandidate.content_hash == digest
                    )
                )
                if winner is None:
                    raise
                return {**lesson_to_dict(winner), "deduplicated": True}
            return lesson_to_dict(row)

    def review(self, lesson_id: str, payload: LessonReviewV1, *, actor: str) -> dict[str, Any]:
        if actor.strip().casefold() in {"agent", "model", "runtime", "planner"}:
            raise PermissionError("models and runtime cannot approve lessons")
        with self.db.session() as session:
            replay = session.scalar(
                select(StrategyLessonReview).where(
                    StrategyLessonReview.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.lesson_id != lesson_id or replay.decision != payload.decision:
                    raise ValueError("lesson review idempotency key is bound to another decision")
                row = session.get(StrategyLessonCandidate, lesson_id)
                if row is None:
                    raise KeyError(lesson_id)
                return {**lesson_to_dict(row), "idempotent": True}
            row = session.get(StrategyLessonCandidate, lesson_id)
            if row is None:
                raise KeyError(lesson_id)
            if row.status not in {"proposed", "disputed"}:
                raise ValueError(f"lesson cannot be reviewed from {row.status}")
            if _utc(row.valid_until) <= utc_now() and payload.decision == "approve":
                raise ValueError("expired lesson cannot be approved")
            row.status = {"approve": "active", "reject": "rejected", "dispute": "disputed"}[
                payload.decision
            ]
            row.reviewed_by = actor
            row.review_reason = payload.reason.strip()
            session.add(
                StrategyLessonReview(
                    lesson_id=row.id,
                    decision=payload.decision,
                    reason=payload.reason.strip(),
                    idempotency_key=payload.idempotency_key,
                    decided_by=actor,
                )
            )
            session.flush()
            return lesson_to_dict(row)

    def list(self, *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
        self.refresh_lifecycle()
        with self.db.session() as session:
            statement = select(StrategyLessonCandidate).order_by(
                StrategyLessonCandidate.created_at.desc()
            )
            if status:
                statement = statement.where(StrategyLessonCandidate.status == status)
            rows = session.scalars(statement.limit(max(1, min(limit, 500)))).all()
            return [lesson_to_dict(row) for row in rows]

    def active_for_context(self, *, limit: int = 20) -> builtins.list[dict[str, Any]]:
        # Callers may project these bounded reviewed facts into ContextPack; no Memory,
        # strategy, policy, paper, or execution state is mutated here.
        return [item for item in self.list(status="active", limit=limit) if item["usable"]]

    def refresh_lifecycle(self) -> builtins.list[str]:
        expired: builtins.list[str] = []
        with self.db.session() as session:
            rows = session.scalars(
                select(StrategyLessonCandidate).where(
                    StrategyLessonCandidate.status.in_(["proposed", "active", "disputed"]),
                    StrategyLessonCandidate.valid_until <= utc_now(),
                )
            ).all()
            for row in rows:
                row.status = "expired"
                expired.append(row.id)
        return expired

    def replay_hash(self) -> str:
        with self.db.session() as session:
            rows = session.scalars(
                select(StrategyLessonCandidate).order_by(StrategyLessonCandidate.content_hash)
            ).all()
        return _hash([{"content_hash": row.content_hash, "status": row.status} for row in rows])


def outcome_to_dict(row: StrategyOutcome) -> dict[str, Any]:
    return {
        "id": row.id,
        **dict(row.outcome_json),
        "content_hash": row.content_hash,
        "created_by": row.created_by,
        "created_at": _utc(row.created_at).isoformat(),
    }


def lesson_to_dict(row: StrategyLessonCandidate) -> dict[str, Any]:
    return {
        "id": row.id,
        **dict(row.lesson_json),
        "status": row.status,
        "content_hash": row.content_hash,
        "reviewed_by": row.reviewed_by,
        "review_reason": row.review_reason,
        "usable": row.status == "active" and _utc(row.valid_until) > utc_now(),
        "created_by": row.created_by,
        "created_at": _utc(row.created_at).isoformat(),
    }


def _tool_call_is_settled(row: AgentToolCall) -> bool:
    if row.status in {"succeeded", "failed"}:
        return True
    if row.status != "reconciled":
        return False
    outcome = str(dict(row.call_json or {}).get("reconciliation_outcome", ""))
    return outcome in {"committed", "not_committed"}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
