"""Bounded existing-strategy evolution over settled, source-bound facts."""

from __future__ import annotations

import builtins
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from sqlalchemy import select

from hypertrade.db import (
    BitProStrategyEvidenceRecord,
    Database,
    ExperimentManifest,
    StrategyEvolutionCandidate,
    StrategyEvolutionRun,
    StrategyOutcome,
    StrategyVersion,
    utc_now,
)
from hypertrade.research.evolution_schemas import (
    CandidateProposalV1,
    EvolutionRequestV1,
    StrategyCandidateVersionV1,
    StrategyDecayAssessmentV1,
    canonical_payload,
    digest,
)
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import (
    ExperimentManifestV1,
    ExperimentRegister,
)


class RuleCandidateValidator(Protocol):
    """Sandbox/dependency validation only; no strategy creation or runtime mutation."""

    def validate(self, *, code_ref: str, code_sha256: str) -> dict[str, Any]: ...


class StrategyEvolutionService:
    def __init__(
        self,
        db: Database,
        *,
        rule_validator: RuleCandidateValidator | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.db = db
        self.rule_validator = rule_validator
        self.clock = clock

    def assess_decay(
        self,
        *,
        parent_version_id: str,
        outcome_ids: list[str],
        evidence_record_ids: list[str],
        now: datetime | None = None,
    ) -> StrategyDecayAssessmentV1:
        current = _utc(now or utc_now())
        with self.db.session() as session:
            parent = session.get(StrategyVersion, parent_version_id)
            if parent is None:
                raise KeyError(parent_version_id)
            outcomes = session.scalars(
                select(StrategyOutcome).where(StrategyOutcome.id.in_(outcome_ids))
            ).all()
            evidence = session.scalars(
                select(BitProStrategyEvidenceRecord).where(
                    BitProStrategyEvidenceRecord.id.in_(evidence_record_ids)
                )
            ).all()
        unknowns: list[str] = []
        reasons: list[str] = []
        if len(outcomes) != len(set(outcome_ids)):
            unknowns.append("settled_outcome_missing")
        if len(evidence) != len(set(evidence_record_ids)):
            unknowns.append("bitpro_evidence_missing")
        if any(row.strategy_version_id != parent_version_id for row in outcomes):
            unknowns.append("outcome_parent_version_mismatch")
        if any(_utc(row.as_of) > _utc(row.settled_at) for row in outcomes):
            unknowns.append("outcome_not_settled")
        if len(outcomes) < 2:
            unknowns.append("single_outcome_cannot_trigger_evolution")
        if any(
            list(dict(row.outcome_json).get("unknowns", []))
            or list(dict(row.outcome_json).get("data_gaps", []))
            for row in outcomes
        ):
            unknowns.append("outcome_contains_unknown_or_data_gap")
        ordered = sorted(outcomes, key=lambda row: (_utc(row.as_of), row.id))
        classification = "unknown"
        if any(
            reason in unknowns
            for reason in (
                "bitpro_evidence_missing",
                "outcome_contains_unknown_or_data_gap",
            )
        ):
            classification = "data_quality"
        if not unknowns:
            failures = [str(dict(row.outcome_json).get("failure_class", "")) for row in ordered]
            if any("execution" in value.casefold() for value in failures):
                classification = "execution_drift"
                reasons.append("settled outcomes identify execution drift")
            else:
                returns = [_return_metric(dict(row.outcome_json)) for row in ordered]
                regimes = [tuple(dict(row.outcome_json).get("regimes", [])) for row in ordered]
                if len(set(regimes)) > 1 and _has_sign_change(returns):
                    classification = "regime_mismatch"
                    reasons.append("settled return direction changes across regimes")
                elif (
                    returns[0] is not None
                    and returns[-1] is not None
                    and returns[-1] < returns[0]
                ):
                    classification = "performance_decay"
                    reasons.append("latest settled return is below the earlier settled return")
                else:
                    unknowns.append("decay_not_demonstrated_by_settled_outcomes")
        status = "actionable" if classification != "unknown" and not unknowns else "needs_review"
        return StrategyDecayAssessmentV1(
            classification=cast(Any, classification),
            status=status,
            parent_version_id=parent_version_id,
            outcome_ids=sorted(set(outcome_ids)),
            evidence_record_ids=sorted(set(evidence_record_ids)),
            reasons=reasons,
            unknowns=sorted(set(unknowns)),
            as_of=current,
        )

    def evolve(
        self,
        request: EvolutionRequestV1,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _utc(now or utc_now())
        request_body = canonical_payload(
            request.model_dump(mode="python", exclude={"idempotency_key"})
        )
        request_hash = digest(request_body)
        with self.db.session() as session:
            replay = session.scalar(
                select(StrategyEvolutionRun).where(
                    StrategyEvolutionRun.idempotency_key == request.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("evolution idempotency key is bound to another request")
                return self._run_projection(replay.id, replay="idempotency")

        parent, parent_manifest = self._validate_mandate(request, now=current)
        assessment = self.assess_decay(
            parent_version_id=request.mandate.parent_version_id,
            outcome_ids=request.mandate.outcome_ids,
            evidence_record_ids=request.mandate.evidence_record_ids,
            now=current,
        )
        with self.db.session() as session:
            run = StrategyEvolutionRun(
                schema_version="strategy_evolution_run.v1",
                parent_version_id=parent.id,
                status="needs_review" if assessment.status != "actionable" else "generating",
                request_hash=request_hash,
                idempotency_key=request.idempotency_key,
                mandate_json=canonical_payload(request.mandate),
                assessment_json=canonical_payload(assessment),
                usage_json={
                    "trials": 0,
                    "accepted": 0,
                    "rejected": 0,
                    "model_calls": 0,
                    "tool_calls": 0,
                    "elapsed_ms": 0,
                    "candidate_ids": [],
                    "reused_candidate_ids": [],
                },
                created_by=actor,
            )
            session.add(run)
            session.flush()
            run_id = run.id

        if assessment.status != "actionable":
            return self._run_projection(run_id)

        started = self.clock()
        usage: dict[str, Any] = {
            "trials": 0,
            "accepted": 0,
            "rejected": 0,
            "model_calls": 0,
            "tool_calls": 0,
            "elapsed_ms": 0,
            "candidate_ids": [],
            "reused_candidate_ids": [],
        }
        for proposal in request.proposals:
            elapsed = max(0.0, float(self.clock()) - float(started))
            budget_reasons = self._budget_reasons(request, proposal, usage, elapsed)
            if budget_reasons:
                recorded = self._record_candidate(
                    run_id=run_id,
                    request=request,
                    proposal=proposal,
                    status="budget_exhausted",
                    rejection_reasons=budget_reasons,
                    actor=actor,
                )
                usage["candidate_ids"].append(recorded["id"])
                if recorded["replay"]:
                    usage["reused_candidate_ids"].append(recorded["id"])
                usage["rejected"] += 1
                break
            usage["trials"] += 1
            usage["model_calls"] += proposal.model_calls
            usage["tool_calls"] += proposal.tool_calls
            rejection_reasons = self._proposal_rejections(
                request, proposal, parent_manifest=parent_manifest
            )
            if rejection_reasons:
                recorded = self._record_candidate(
                    run_id=run_id,
                    request=request,
                    proposal=proposal,
                    status="rejected",
                    rejection_reasons=rejection_reasons,
                    actor=actor,
                )
                usage["candidate_ids"].append(recorded["id"])
                if recorded["replay"]:
                    usage["reused_candidate_ids"].append(recorded["id"])
                usage["rejected"] += 1
                continue
            candidate = self._register_candidate(
                run_id=run_id,
                request=request,
                proposal=proposal,
                parent_manifest=parent_manifest,
                actor=actor,
            )
            usage["candidate_ids"].append(candidate["id"])
            if candidate["replay"]:
                usage["reused_candidate_ids"].append(candidate["id"])
            if candidate["status"] == "accepted":
                usage["accepted"] += 1
            else:
                usage["rejected"] += 1
            if usage["accepted"] >= request.mandate.max_candidates:
                break
        usage["elapsed_ms"] = int(max(0.0, float(self.clock()) - float(started)) * 1000)
        with self.db.session() as session:
            run_row = session.get(StrategyEvolutionRun, run_id)
            if run_row is None:
                raise KeyError(run_id)
            run_row.status = "candidates_registered" if usage["accepted"] else "needs_review"
            run_row.usage_json = usage
        return self._run_projection(run_id)

    def get(self, run_id: str) -> dict[str, Any]:
        return self._run_projection(run_id)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(StrategyEvolutionRun)
                .order_by(StrategyEvolutionRun.created_at.desc())
                .limit(max(1, min(limit, 500)))
            ).all()
            ids = [row.id for row in rows]
        return [self._run_projection(run_id) for run_id in ids]

    def _validate_mandate(
        self, request: EvolutionRequestV1, *, now: datetime
    ) -> tuple[StrategyVersion, ExperimentManifestV1]:
        mandate = request.mandate
        with self.db.session() as session:
            parent = session.get(StrategyVersion, mandate.parent_version_id)
            if parent is None:
                raise KeyError(mandate.parent_version_id)
            manifest_row = session.get(ExperimentManifest, parent.manifest_id)
            if manifest_row is None:
                raise KeyError(parent.manifest_id)
            evidence = session.scalars(
                select(BitProStrategyEvidenceRecord).where(
                    BitProStrategyEvidenceRecord.id.in_(mandate.evidence_record_ids)
                )
            ).all()
            session.expunge(parent)
        manifest = ExperimentManifestV1.model_validate(manifest_row.canonical_json)
        if not set(mandate.symbols).issubset(set(manifest.strategy_spec.symbols)):
            raise ValueError("evolution mandate cannot expand strategy symbols")
        if not set(mandate.timeframes).issubset(set(manifest.strategy_spec.timeframes)):
            raise ValueError("evolution mandate cannot expand strategy timeframes")
        parent_bounds = manifest.strategy_spec.parameter_bounds
        for name, bounds in mandate.parameter_ranges.items():
            declared = parent_bounds.get(name)
            if declared is None:
                raise ValueError(f"parameter is not declared by StrategySpec: {name}")
            if bounds.minimum < Decimal(str(declared["min"])) or bounds.maximum > Decimal(
                str(declared["max"])
            ):
                raise ValueError(f"evolution range expands StrategySpec bounds: {name}")
        if len(evidence) != len(set(mandate.evidence_record_ids)):
            raise ValueError("evolution requires all declared BitPro evidence records")
        cutoff = now - timedelta(hours=mandate.freshness_hours)
        if any(_utc(row.created_at) < cutoff for row in evidence):
            raise ValueError("evolution BitPro evidence is stale")
        if mandate.data_source_hash not in {row.source_hash for row in evidence}:
            raise ValueError("evolution data_source_hash is not bound to declared evidence")
        return parent, manifest

    def _budget_reasons(
        self,
        request: EvolutionRequestV1,
        proposal: CandidateProposalV1,
        usage: dict[str, Any],
        elapsed: float,
    ) -> builtins.list[str]:
        mandate = request.mandate
        reasons = []
        if usage["trials"] >= mandate.max_trials:
            reasons.append("max_trials_exhausted")
        if usage["accepted"] >= mandate.max_candidates:
            reasons.append("max_candidates_exhausted")
        if usage["model_calls"] + proposal.model_calls > mandate.max_model_calls:
            reasons.append("max_model_calls_exhausted")
        if usage["tool_calls"] + proposal.tool_calls > mandate.max_tool_calls:
            reasons.append("max_tool_calls_exhausted")
        if elapsed > mandate.max_wall_seconds:
            reasons.append("max_wall_seconds_exhausted")
        return reasons

    def _proposal_rejections(
        self,
        request: EvolutionRequestV1,
        proposal: CandidateProposalV1,
        *,
        parent_manifest: ExperimentManifestV1,
    ) -> builtins.list[str]:
        mandate = request.mandate
        reasons: list[str] = []
        for name, value in proposal.parameter_changes.items():
            bounds = mandate.parameter_ranges.get(name)
            if bounds is None:
                reasons.append(f"parameter_not_allowed:{name}")
            elif value < bounds.minimum or value > bounds.maximum:
                reasons.append(f"parameter_out_of_bounds:{name}")
        for slot in proposal.rule_changes:
            if slot not in mandate.mutable_rule_slots:
                reasons.append(f"rule_slot_not_allowed:{slot}")
        if proposal.rule_changes:
            if not proposal.strategy_code_ref.startswith(("artifact:", "hypertrade:candidate:")):
                reasons.append("candidate_code_ref_not_immutable")
            if self.rule_validator is None:
                reasons.append("rule_candidate_validator_unavailable")
            else:
                result = self.rule_validator.validate(
                    code_ref=proposal.strategy_code_ref,
                    code_sha256=proposal.strategy_code_sha256,
                )
                if not result.get("valid"):
                    reasons.append("strategy_schema_validation_failed")
                if not result.get("sandbox_passed"):
                    reasons.append("strategy_sandbox_failed")
                if result.get("dependency_status") != "approved":
                    reasons.append("strategy_dependency_unapproved")
        if (
            not proposal.rule_changes
            and proposal.strategy_code_sha256
            and proposal.strategy_code_sha256 != parent_manifest.strategy_code_sha256
        ):
            reasons.append("parameter_candidate_changed_code")
        return sorted(set(reasons))

    def _register_candidate(
        self,
        *,
        run_id: str,
        request: EvolutionRequestV1,
        proposal: CandidateProposalV1,
        parent_manifest: ExperimentManifestV1,
        actor: str,
    ) -> dict[str, Any]:
        fingerprint = self._candidate_fingerprint(request, proposal)
        existing = self._candidate_by_fingerprint(fingerprint)
        if existing is not None:
            return _candidate_to_dict(existing, replay="fingerprint")
        manifest_payload = parent_manifest.model_dump(mode="python")
        parameters = dict(parent_manifest.parameters)
        parameters.update(proposal.parameter_changes)
        manifest_payload["parameters"] = parameters
        spec = dict(manifest_payload["strategy_spec"])
        rules = proposal.rule_changes
        if "entry" in rules:
            spec["entry_logic"] = rules["entry"]
        if "exit" in rules:
            spec["exit_logic"] = rules["exit"]
        if "risk" in rules:
            spec["risk_conditions"] = [rules["risk"]]
        if "filter" in rules:
            spec["entry_logic"] = f"{spec['entry_logic']} Filter: {rules['filter']}"
        manifest_payload["strategy_spec"] = spec
        manifest_payload["data_snapshot_hash"] = request.mandate.data_source_hash.removeprefix(
            "sha256:"
        )
        if rules:
            manifest_payload["strategy_code_sha256"] = proposal.strategy_code_sha256
            manifest_payload["strategy_code_ref"] = proposal.strategy_code_ref
        manifest = ExperimentManifestV1.model_validate(manifest_payload)
        registration = ExperimentLedgerService(self.db).register(
            ExperimentRegister(
                manifest=manifest,
                idempotency_key=f"evolution:{fingerprint}",
            ),
            actor=actor,
        )
        manifest_id = str(registration["manifest"]["id"])
        execution_id = str(registration["execution"]["id"])
        with self.db.session() as session:
            version = session.scalar(
                select(StrategyVersion).where(StrategyVersion.manifest_id == manifest_id)
            )
            if version is None:
                raise ValueError("candidate manifest did not produce an immutable strategy version")
            candidate_version_id = version.id
        candidate = StrategyCandidateVersionV1(
            fingerprint=fingerprint,
            parent_version_id=request.mandate.parent_version_id,
            candidate_version_id=candidate_version_id,
            manifest_id=manifest_id,
            experiment_execution_id=execution_id,
            proposal_kind=proposal.proposal_kind,
            parameter_changes=proposal.parameter_changes,
            rule_changes=proposal.rule_changes,
            proposal_reason=proposal.proposal_reason,
            outcome_ids=request.mandate.outcome_ids,
            evidence_record_ids=request.mandate.evidence_record_ids,
            data_source_hash=request.mandate.data_source_hash,
            deterministic_seed=request.mandate.deterministic_seed,
            status="accepted",
            rejection_reasons=[],
        )
        return self._persist_candidate(run_id, candidate, actor=actor)

    def _record_candidate(
        self,
        *,
        run_id: str,
        request: EvolutionRequestV1,
        proposal: CandidateProposalV1,
        status: str,
        rejection_reasons: builtins.list[str],
        actor: str,
    ) -> dict[str, Any]:
        fingerprint = self._candidate_fingerprint(request, proposal)
        existing = self._candidate_by_fingerprint(fingerprint)
        if existing is not None:
            return _candidate_to_dict(existing, replay="fingerprint")
        candidate = StrategyCandidateVersionV1(
            fingerprint=fingerprint,
            parent_version_id=request.mandate.parent_version_id,
            proposal_kind=proposal.proposal_kind,
            parameter_changes=proposal.parameter_changes,
            rule_changes=proposal.rule_changes,
            proposal_reason=proposal.proposal_reason,
            outcome_ids=request.mandate.outcome_ids,
            evidence_record_ids=request.mandate.evidence_record_ids,
            data_source_hash=request.mandate.data_source_hash,
            deterministic_seed=request.mandate.deterministic_seed,
            status=cast(Any, status),
            rejection_reasons=rejection_reasons,
        )
        return self._persist_candidate(run_id, candidate, actor=actor)

    def _persist_candidate(
        self, run_id: str, candidate: StrategyCandidateVersionV1, *, actor: str
    ) -> dict[str, Any]:
        with self.db.session() as session:
            row = StrategyEvolutionCandidate(
                run_id=run_id,
                schema_version=candidate.schema_version,
                fingerprint=candidate.fingerprint,
                parent_version_id=candidate.parent_version_id,
                candidate_version_id=candidate.candidate_version_id,
                manifest_id=candidate.manifest_id,
                experiment_execution_id=candidate.experiment_execution_id,
                status=candidate.status,
                proposal_kind=candidate.proposal_kind,
                candidate_json=canonical_payload(candidate),
                created_by=actor,
            )
            session.add(row)
            session.flush()
            return _candidate_to_dict(row)

    @staticmethod
    def _candidate_fingerprint(
        request: EvolutionRequestV1, proposal: CandidateProposalV1
    ) -> str:
        return digest(
            {
                "parent_version_id": request.mandate.parent_version_id,
                "data_source_hash": request.mandate.data_source_hash,
                "outcome_ids": sorted(request.mandate.outcome_ids),
                "proposal": canonical_payload(proposal),
                "deterministic_seed": request.mandate.deterministic_seed,
            }
        )

    def _candidate_by_fingerprint(
        self, fingerprint: str
    ) -> StrategyEvolutionCandidate | None:
        with self.db.session() as session:
            row = session.scalar(
                select(StrategyEvolutionCandidate).where(
                    StrategyEvolutionCandidate.fingerprint == fingerprint
                )
            )
            if row is not None:
                session.expunge(row)
            return row

    def _run_projection(self, run_id: str, *, replay: str = "") -> dict[str, Any]:
        with self.db.session() as session:
            run = session.get(StrategyEvolutionRun, run_id)
            if run is None:
                raise KeyError(run_id)
            candidate_ids = list(dict(run.usage_json).get("candidate_ids", []))
            candidates = session.scalars(
                select(StrategyEvolutionCandidate)
                .where(
                    (StrategyEvolutionCandidate.run_id == run_id)
                    | (StrategyEvolutionCandidate.id.in_(candidate_ids))
                )
                .order_by(StrategyEvolutionCandidate.created_at, StrategyEvolutionCandidate.id)
            ).all()
            return {
                "id": run.id,
                "schema_version": run.schema_version,
                "parent_version_id": run.parent_version_id,
                "status": run.status,
                "request_hash": run.request_hash,
                "mandate": dict(run.mandate_json),
                "assessment": dict(run.assessment_json),
                "usage": dict(run.usage_json),
                "candidates": [_candidate_to_dict(row) for row in candidates],
                "execution_authorized": False,
                "mutation_boundary": {
                    "bitpro_writes": False,
                    "paper_writes": False,
                    "live_writes": False,
                    "order_writes": False,
                    "capital_writes": False,
                },
                "replay": replay,
            }


def _candidate_to_dict(
    row: StrategyEvolutionCandidate, *, replay: str = ""
) -> dict[str, Any]:
    return {
        "id": row.id,
        **dict(row.candidate_json),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "replay": replay,
    }


def _return_metric(outcome: dict[str, Any]) -> Decimal | None:
    metrics = dict(outcome.get("metrics", {}))
    for key in ("net_return", "return_pct", "total_return_pct"):
        if key not in metrics:
            continue
        try:
            value = Decimal(str(metrics[key]))
        except (InvalidOperation, ValueError):
            return None
        return value if value.is_finite() else None
    return None


def _has_sign_change(values: list[Decimal | None]) -> bool:
    known = [value for value in values if value is not None]
    return bool(known) and min(known) < 0 < max(known)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
