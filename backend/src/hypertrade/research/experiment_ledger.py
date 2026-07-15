"""Immutable manifest and append-only execution ledger service."""

from __future__ import annotations

import builtins
from datetime import datetime
from typing import Any, cast

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    Database,
    ExperimentEvidenceLink,
    ExperimentExecution,
    ExperimentManifest,
    ResearchEvidence,
    ResearchExperimentEvidence,
    utc_now,
)
from hypertrade.research.experiment_schemas import (
    ExperimentExecutionComplete,
    ExperimentRegister,
    canonical_manifest_payload,
    experiment_fingerprint,
)


class ExperimentLedgerService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def register(self, payload: ExperimentRegister, *, actor: str) -> dict[str, Any]:
        fingerprint = experiment_fingerprint(payload.manifest)
        existing_by_key = self._execution_by_idempotency(payload.idempotency_key)
        if existing_by_key is not None:
            manifest = self._manifest_by_id(existing_by_key.manifest_id)
            if manifest.fingerprint != fingerprint:
                raise ValueError("idempotency key is bound to a different fingerprint")
            return self._projection(manifest, existing_by_key, replay="idempotency")

        manifest = self._get_or_create_manifest(payload, fingerprint=fingerprint, actor=actor)
        with self.db.session() as session:
            query = (
                select(ExperimentExecution)
                .where(ExperimentExecution.manifest_id == manifest.id)
                .order_by(desc(ExperimentExecution.attempt))
            )
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            latest = session.scalar(query.limit(1))
            if latest is not None and not payload.force_rerun:
                if latest.status in {"queued", "running", "completed"}:
                    session.expunge(latest)
                    return self._projection(manifest, latest, replay=f"status:{latest.status}")
                raise ValueError("failed experiment requires force_rerun and reason")
            attempt = int(latest.attempt if latest is not None else 0) + 1
            execution = ExperimentExecution(
                manifest_id=manifest.id,
                attempt=attempt,
                status="queued",
                task_id=payload.task_id,
                research_job_id=payload.research_job_id,
                retry_of_id=latest.id if latest is not None else None,
                idempotency_key=payload.idempotency_key,
                force_reason=payload.force_reason,
                created_by=actor,
            )
            session.add(execution)
            try:
                session.flush()
            except IntegrityError:
                # A concurrent registrar may win either the fingerprint/attempt or
                # idempotency constraint. Resolve through the committed ledger
                # instead of creating a second physical experiment.
                session.rollback()
                winner = self._execution_by_idempotency(payload.idempotency_key)
                if winner is None:
                    winner = self._latest_execution(manifest.id)
                if winner is None:
                    raise
                return self._projection(manifest, winner, replay="concurrent")
            session.expunge(execution)
        return self._projection(manifest, execution, replay="")

    def start(self, execution_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = self._locked_execution(session, execution_id)
            if row.status == "running":
                session.expunge(row)
                return execution_to_dict(row)
            if row.status != "queued":
                raise ValueError(f"execution is not startable from {row.status}")
            row.status = "running"
            row.started_at = utc_now()
            session.flush()
            session.expunge(row)
            return execution_to_dict(row)

    def complete(
        self, execution_id: str, payload: ExperimentExecutionComplete, *, actor: str
    ) -> dict[str, Any]:
        with self.db.session() as session:
            row = self._locked_execution(session, execution_id)
            if row.status == "completed":
                session.expunge(row)
                return execution_to_dict(row)
            if row.status != "running":
                raise ValueError(f"execution is not completable from {row.status}")
            self._verify_artifact_contract(session, row, payload)
            row.status = "completed"
            row.external_refs_json = dict(payload.external_refs)
            row.metrics_json = {
                key: format(value.normalize(), "f")
                for key, value in sorted(payload.metrics.items())
            }
            row.artifact_manifest_json = {
                "schema_version": "experiment_artifacts.v1",
                "items": [item.model_dump(mode="json") for item in payload.artifacts],
            }
            row.usage_json = {key: max(0, int(value)) for key, value in payload.usage.items()}
            row.completed_at = utc_now()
            for evidence_id in payload.evidence_ids:
                self._verify_evidence(session, evidence_id, payload.evidence_kind)
                existing = session.scalar(
                    select(ExperimentEvidenceLink).where(
                        ExperimentEvidenceLink.execution_id == row.id,
                        ExperimentEvidenceLink.evidence_id == evidence_id,
                    )
                )
                if existing is None:
                    session.add(
                        ExperimentEvidenceLink(
                            execution_id=row.id,
                            evidence_id=evidence_id,
                            evidence_kind=payload.evidence_kind,
                            created_by=actor,
                        )
                    )
            session.flush()
            session.expunge(row)
            return execution_to_dict(row)

    def fail(self, execution_id: str, *, error: dict[str, Any]) -> dict[str, Any]:
        bounded = {
            str(key): str(value)[:1_000]
            for key, value in list(error.items())[:32]
            if str(key).casefold() not in {"prompt", "raw", "secret"}
        }
        with self.db.session() as session:
            row = self._locked_execution(session, execution_id)
            if row.status not in {"queued", "running"}:
                raise ValueError(f"execution is not failable from {row.status}")
            row.status = "failed"
            row.error_json = bounded
            row.completed_at = utc_now()
            session.flush()
            session.expunge(row)
            return execution_to_dict(row)

    def get(self, fingerprint: str) -> dict[str, Any]:
        manifest = self._manifest_by_fingerprint(fingerprint)
        executions = self.executions(fingerprint)
        return {
            "manifest": manifest_to_dict(manifest),
            "executions": executions,
        }

    def list(self, *, limit: int = 50) -> builtins.list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(ExperimentManifest)
                .order_by(desc(ExperimentManifest.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [manifest_to_dict(row) for row in rows]

    def executions(self, fingerprint: str) -> builtins.list[dict[str, Any]]:
        manifest = self._manifest_by_fingerprint(fingerprint)
        with self.db.session() as session:
            rows = session.scalars(
                select(ExperimentExecution)
                .where(ExperimentExecution.manifest_id == manifest.id)
                .order_by(ExperimentExecution.attempt)
            ).all()
            links = session.scalars(
                select(ExperimentEvidenceLink).where(
                    ExperimentEvidenceLink.execution_id.in_([row.id for row in rows])
                )
            ).all()
        by_execution: dict[str, builtins.list[dict[str, str]]] = {}
        for link in links:
            by_execution.setdefault(link.execution_id, []).append(
                {"evidence_id": link.evidence_id, "evidence_kind": link.evidence_kind}
            )
        result = []
        for row in rows:
            item = execution_to_dict(row)
            item["evidence"] = sorted(
                by_execution.get(row.id, []), key=lambda value: value["evidence_id"]
            )
            result.append(item)
        return result

    def diff(self, left_fingerprint: str, right_fingerprint: str) -> dict[str, Any]:
        left = dict(self._manifest_by_fingerprint(left_fingerprint).canonical_json)
        right = dict(self._manifest_by_fingerprint(right_fingerprint).canonical_json)
        changes = _manifest_diff(left, right)
        return {
            "schema_version": "experiment_manifest_diff.v1",
            "left_fingerprint": left_fingerprint,
            "right_fingerprint": right_fingerprint,
            "equal": not changes,
            "changes": changes,
        }

    def _get_or_create_manifest(
        self, payload: ExperimentRegister, *, fingerprint: str, actor: str
    ) -> ExperimentManifest:
        existing = self._optional_manifest_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        try:
            with self.db.session() as session:
                row = ExperimentManifest(
                    schema_version=payload.manifest.schema_version,
                    fingerprint=fingerprint,
                    strategy_key=payload.manifest.strategy_spec.strategy_key,
                    mandate_id=payload.manifest.strategy_spec.mandate_id,
                    research_job_id=payload.research_job_id,
                    canonical_json=canonical_manifest_payload(payload.manifest),
                    created_by=actor,
                )
                session.add(row)
                session.flush()
                session.expunge(row)
                return row
        except IntegrityError:
            return self._manifest_by_fingerprint(fingerprint)

    def _projection(
        self, manifest: ExperimentManifest, execution: ExperimentExecution, *, replay: str
    ) -> dict[str, Any]:
        # Strategy identity is established with the immutable Manifest, never
        # delayed until paper promotion. The service writes projection tables only.
        from hypertrade.research.strategy_cards import StrategyCardService

        StrategyCardService(self.db).reconcile_manifest(
            manifest.id,
            actor="experiment_ledger",
        )
        return {
            "manifest": manifest_to_dict(manifest),
            "execution": execution_to_dict(execution),
            "reused": bool(replay),
            "reuse_reason": replay,
        }

    def _manifest_by_fingerprint(self, fingerprint: str) -> ExperimentManifest:
        row = self._optional_manifest_by_fingerprint(fingerprint)
        if row is None:
            raise KeyError(fingerprint)
        return row

    def _optional_manifest_by_fingerprint(self, fingerprint: str) -> ExperimentManifest | None:
        with self.db.session() as session:
            row = session.scalar(
                select(ExperimentManifest).where(ExperimentManifest.fingerprint == fingerprint)
            )
            if row is not None:
                session.expunge(row)
            return row

    def _manifest_by_id(self, manifest_id: str) -> ExperimentManifest:
        with self.db.session() as session:
            row = session.get(ExperimentManifest, manifest_id)
            if row is None:
                raise KeyError(manifest_id)
            session.expunge(row)
            return row

    def _execution_by_idempotency(self, key: str) -> ExperimentExecution | None:
        with self.db.session() as session:
            row = session.scalar(
                select(ExperimentExecution).where(ExperimentExecution.idempotency_key == key)
            )
            if row is not None:
                session.expunge(row)
            return row

    def _latest_execution(self, manifest_id: str) -> ExperimentExecution | None:
        with self.db.session() as session:
            row = session.scalar(
                select(ExperimentExecution)
                .where(ExperimentExecution.manifest_id == manifest_id)
                .order_by(desc(ExperimentExecution.attempt))
                .limit(1)
            )
            if row is not None:
                session.expunge(row)
            return row

    @staticmethod
    def _locked_execution(session: Any, execution_id: str) -> ExperimentExecution:
        query = select(ExperimentExecution).where(ExperimentExecution.id == execution_id)
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise KeyError(execution_id)
        return cast(ExperimentExecution, row)

    @staticmethod
    def _verify_evidence(session: Any, evidence_id: str, kind: str) -> None:
        model = ResearchEvidence if kind == "evidence_v2" else ResearchExperimentEvidence
        if session.get(model, evidence_id) is None:
            raise ValueError(f"experiment evidence reference not found: {evidence_id}")

    def _verify_artifact_contract(
        self,
        session: Any,
        execution: ExperimentExecution,
        payload: ExperimentExecutionComplete,
    ) -> None:
        manifest = session.get(ExperimentManifest, execution.manifest_id)
        if manifest is None:
            raise KeyError(execution.manifest_id)
        expected = str(dict(manifest.canonical_json)["versions"]["mcp_contract_version"])
        incompatible = [
            item.artifact_id
            for item in payload.artifacts
            if item.contract_version != expected
        ]
        if incompatible:
            raise ValueError(
                f"artifact contract mismatch for manifest {manifest.fingerprint}: {incompatible}"
            )


def manifest_to_dict(row: ExperimentManifest) -> dict[str, Any]:
    return {
        "id": row.id,
        "schema_version": row.schema_version,
        "fingerprint": row.fingerprint,
        "strategy_key": row.strategy_key,
        "mandate_id": row.mandate_id,
        "research_job_id": row.research_job_id,
        "manifest": dict(row.canonical_json),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


def execution_to_dict(row: ExperimentExecution) -> dict[str, Any]:
    return {
        "id": row.id,
        "manifest_id": row.manifest_id,
        "attempt": row.attempt,
        "status": row.status,
        "task_id": row.task_id,
        "research_job_id": row.research_job_id,
        "retry_of_id": row.retry_of_id,
        "idempotency_key": row.idempotency_key,
        "force_reason": row.force_reason,
        "external_refs": dict(row.external_refs_json),
        "metrics": dict(row.metrics_json),
        "artifacts": dict(row.artifact_manifest_json),
        "usage": dict(row.usage_json),
        "error": dict(row.error_json),
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "created_at": row.created_at.isoformat(),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _manifest_diff(left: Any, right: Any, *, path: str = "") -> list[dict[str, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else str(key)
            changes.extend(_manifest_diff(left.get(key), right.get(key), path=child))
        return changes
    if left == right:
        return []
    return [
        {
            "path": path,
            "category": _diff_category(path),
            "left": left,
            "right": right,
        }
    ]


def _diff_category(path: str) -> str:
    if path.startswith("strategy_spec") or path.startswith("strategy_code"):
        return "strategy"
    if path.startswith("windows") or path.startswith("data_snapshot"):
        return "data"
    if path.startswith("costs"):
        return "costs"
    if path.startswith("versions.provider") or path.startswith("versions.model"):
        return "model"
    if path.startswith("versions.prompt"):
        return "prompt"
    if path.startswith("versions.tool"):
        return "tool"
    if path.startswith("versions.policy"):
        return "policy"
    return "runtime"
