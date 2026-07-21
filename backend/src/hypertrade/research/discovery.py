"""Deterministic, budgeted new-strategy discovery orchestration."""

from __future__ import annotations

import builtins
import hashlib
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast

from sqlalchemy import select

from hypertrade.db import (
    Database,
    ExperimentManifest,
    ResearchEvidence,
    ResearchMandate,
    StrategyDiscoveryCandidate,
    StrategyDiscoveryRun,
    StrategyVersion,
    utc_now,
)
from hypertrade.research.discovery_schemas import (
    AlphaHypothesisV1,
    DiscoveryCandidateV1,
    DiscoveryProposalV1,
    DiscoveryRequestV1,
    StrategyNoveltyReportV1,
    canonical_payload,
    digest,
)
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import ExperimentManifestV1, ExperimentRegister


class DiscoveryBitProAdapter(Protocol):
    """Narrow reviewed BitPro boundary: validate and persist a research candidate only."""

    def strategy_validate_code(
        self,
        *,
        script_content: str,
        idempotency_key: str,
        symbols: list[str],
        market_type: str,
        timeframe: str,
        smoke: bool,
    ) -> dict[str, Any]: ...

    def strategy_create(
        self,
        *,
        name: str,
        script_content: str,
        description: str,
        config: dict[str, Any],
        exchange: str,
        symbols: list[str],
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class StrategyDiscoveryService:
    """Freeze hypotheses, reject aliases, validate code and register research candidates."""

    def __init__(
        self,
        db: Database,
        *,
        adapter: DiscoveryBitProAdapter | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.db = db
        self.adapter = adapter
        self.clock = clock

    def discover(
        self,
        request: DiscoveryRequestV1,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _utc(now or utc_now())
        request_hash = digest(
            canonical_payload(request.model_dump(mode="python", exclude={"idempotency_key"}))
        )
        with self.db.session() as session:
            replay = session.scalar(
                select(StrategyDiscoveryRun).where(
                    StrategyDiscoveryRun.idempotency_key == request.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("discovery idempotency key is bound to another request")
                return self._run_projection(replay.id, replay="idempotency")

        evidence = self._validate_mandate(request, now=current)
        for proposal in request.proposals:
            self._require_immutable_hypothesis(proposal)
            existing = self._candidate_by_fingerprint(
                self._candidate_fingerprint(request, proposal)
            )
            if existing is not None:
                _require_matching_code(existing, proposal.strategy_code)
        usage: dict[str, Any] = {
            "phenomena": 0,
            "hypotheses": 0,
            "candidates_ready": 0,
            "rejected": 0,
            "model_calls": 0,
            "tool_calls": 0,
            "elapsed_ms": 0,
            "candidate_ids": [],
            "reused_candidate_ids": [],
        }
        with self.db.session() as session:
            run = StrategyDiscoveryRun(
                schema_version="strategy_discovery_run.v1",
                research_mandate_id=request.mandate.research_mandate_id,
                status="discovering",
                request_hash=request_hash,
                idempotency_key=request.idempotency_key,
                mandate_json=canonical_payload(request.mandate),
                usage_json=usage,
                created_by=actor,
            )
            session.add(run)
            session.flush()
            run_id = run.id

        started = float(self.clock())
        for proposal in request.proposals:
            elapsed = max(0.0, float(self.clock()) - started)
            budget_reasons = self._budget_reasons(request, proposal, usage, elapsed)
            if budget_reasons:
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status="budget_exhausted",
                    reasons=budget_reasons,
                    novelty=_unknown_novelty("budget_not_evaluated"),
                    actor=actor,
                )
                self._count(row, usage)
                break

            usage["phenomena"] += 1
            usage["hypotheses"] += 1
            usage["model_calls"] += proposal.model_calls
            usage["tool_calls"] += proposal.tool_calls
            preflight = self._proposal_rejections(request, proposal, evidence=evidence, now=current)
            if preflight:
                status = (
                    "needs_data"
                    if any(reason.startswith("data_") for reason in preflight)
                    else "rejected"
                )
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status=status,
                    reasons=preflight,
                    novelty=_unknown_novelty("preflight_failed"),
                    actor=actor,
                )
                self._count(row, usage)
                continue

            code_sha = hashlib.sha256(proposal.strategy_code.encode("utf-8")).hexdigest()
            novelty = self.assess_novelty(proposal, code_sha=code_sha)
            if novelty.status != "novel":
                status = (
                    "duplicate"
                    if novelty.status == "existing_strategy_variant"
                    else "rejected"
                )
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status=status,
                    reasons=novelty.reasons + novelty.unknowns,
                    novelty=novelty,
                    actor=actor,
                )
                self._count(row, usage)
                continue

            static_rejections = _static_code_rejections(proposal.strategy_code)
            if static_rejections:
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status="sandbox_failed",
                    reasons=static_rejections,
                    novelty=novelty,
                    actor=actor,
                )
                self._count(row, usage)
                continue
            if self.adapter is None:
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status="sandbox_failed",
                    reasons=["bitpro_validation_adapter_unavailable"],
                    novelty=novelty,
                    actor=actor,
                )
                self._count(row, usage)
                continue

            fingerprint = self._candidate_fingerprint(request, proposal)
            try:
                validation = self.adapter.strategy_validate_code(
                    script_content=proposal.strategy_code,
                    idempotency_key=f"discovery-validate-{fingerprint[:32]}",
                    symbols=proposal.hypothesis.strategy_spec.symbols,
                    market_type=request.mandate.market_type.casefold(),
                    timeframe=proposal.hypothesis.strategy_spec.timeframes[0],
                    smoke=True,
                )
            except Exception:
                # Provider failures are recorded without copying upstream error text or secrets.
                usage["tool_calls"] += 1
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status="sandbox_failed",
                    reasons=["bitpro_strategy_validation_unavailable"],
                    novelty=novelty,
                    actor=actor,
                )
                self._count(row, usage)
                continue
            usage["tool_calls"] += 1
            if not _validation_passed(validation):
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status="sandbox_failed",
                    reasons=["bitpro_strategy_code_validation_failed"],
                    novelty=novelty,
                    actor=actor,
                )
                self._count(row, usage)
                continue

            try:
                row = self._create_candidate(
                    run_id=run_id,
                    request=request,
                    proposal=proposal,
                    novelty=novelty,
                    code_sha=code_sha,
                    actor=actor,
                )
            except Exception:
                # The BitPro idempotency key makes an unknown external effect retry-safe.
                row = self._record_terminal(
                    run_id,
                    request,
                    proposal,
                    status="rejected",
                    reasons=["bitpro_strategy_create_or_registration_failed"],
                    novelty=novelty,
                    actor=actor,
                )
            usage["tool_calls"] += 1
            self._count(row, usage)
            if usage["candidates_ready"] >= request.mandate.max_candidates:
                break

        usage["elapsed_ms"] = int(max(0.0, float(self.clock()) - started) * 1000)
        with self.db.session() as session:
            run_row = session.get(StrategyDiscoveryRun, run_id)
            if run_row is None:
                raise KeyError(run_id)
            run_row.status = (
                "candidates_ready" if usage["candidates_ready"] else "needs_review"
            )
            run_row.usage_json = usage
        return self._run_projection(run_id)

    def assess_novelty(
        self, proposal: DiscoveryProposalV1, *, code_sha: str
    ) -> StrategyNoveltyReportV1:
        with self.db.session() as session:
            rows = session.execute(
                select(StrategyVersion, ExperimentManifest).join(
                    ExperimentManifest, StrategyVersion.manifest_id == ExperimentManifest.id
                )
            ).all()
        comparison_by_id = {
            item.existing_version_id: item for item in proposal.novelty_comparisons
        }
        compared: list[str] = []
        reasons: list[str] = []
        unknowns: list[str] = []
        code_match = False
        max_corr: Decimal | None = None
        max_signal: Decimal | None = None
        candidate_signature = _spec_signature(proposal.hypothesis.strategy_spec.model_dump())
        for version, manifest_row in rows:
            compared.append(version.id)
            manifest = ExperimentManifestV1.model_validate(manifest_row.canonical_json)
            if manifest.strategy_code_sha256 == code_sha:
                code_match = True
                reasons.append(f"code_fingerprint_match:{version.id}")
            if _spec_signature(manifest.strategy_spec.model_dump()) == candidate_signature:
                reasons.append(f"equivalent_strategy_logic:{version.id}")
            same_family = (
                manifest.strategy_spec.strategy_category.casefold()
                == proposal.hypothesis.strategy_family.casefold()
            )
            same_scope = bool(
                set(manifest.strategy_spec.symbols)
                & set(proposal.hypothesis.strategy_spec.symbols)
            ) and bool(
                set(manifest.strategy_spec.timeframes)
                & set(proposal.hypothesis.strategy_spec.timeframes)
            )
            comparison = comparison_by_id.get(version.id)
            if comparison is None:
                if same_family and same_scope:
                    unknowns.append(f"missing_comparison:{version.id}")
                continue
            if comparison.return_correlation is not None:
                value = abs(comparison.return_correlation)
                max_corr = value if max_corr is None else max(max_corr, value)
                if value >= Decimal("0.90"):
                    reasons.append(f"high_return_correlation:{version.id}")
            if comparison.signal_similarity is not None:
                value = comparison.signal_similarity
                max_signal = value if max_signal is None else max(max_signal, value)
                if value >= Decimal("0.90"):
                    reasons.append(f"high_signal_similarity:{version.id}")

        if reasons:
            status = "existing_strategy_variant"
        elif not proposal.hypothesis.distinguishing_dimensions:
            status = "unknown"
            unknowns.append("no_explainable_distinguishing_dimension")
        elif rows and unknowns:
            status = "unknown"
        else:
            status = "novel"
            reasons = ["explainable_feature_or_regime_difference"]
        return StrategyNoveltyReportV1(
            status=cast(Any, status),
            reasons=sorted(set(reasons)),
            compared_version_ids=sorted(compared),
            code_fingerprint_match=code_match,
            max_return_correlation=max_corr,
            max_signal_similarity=max_signal,
            unknowns=sorted(set(unknowns)),
        )

    def get(self, run_id: str) -> dict[str, Any]:
        return self._run_projection(run_id)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            ids = list(
                session.scalars(
                    select(StrategyDiscoveryRun.id)
                    .order_by(StrategyDiscoveryRun.created_at.desc())
                    .limit(max(1, min(limit, 500)))
                ).all()
            )
        return [self._run_projection(run_id) for run_id in ids]

    def _validate_mandate(
        self, request: DiscoveryRequestV1, *, now: datetime
    ) -> dict[str, ResearchEvidence]:
        mandate = request.mandate
        with self.db.session() as session:
            root = session.get(ResearchMandate, mandate.research_mandate_id)
            if root is None:
                raise KeyError(mandate.research_mandate_id)
            if root.status != "active":
                raise ValueError("discovery requires an active ResearchMandate")
            if not set(mandate.symbols).issubset(set(root.symbols_json)):
                raise ValueError("discovery mandate cannot expand symbols")
            if not set(mandate.timeframes).issubset(set(root.timeframes_json)):
                raise ValueError("discovery mandate cannot expand timeframes")
            if mandate.market_type != root.market_type:
                raise ValueError("discovery mandate cannot change market_type")
            allowed_categories = {
                str(item).casefold() for item in root.strategy_categories_json
            }
            if not set(mandate.strategy_families).issubset(allowed_categories):
                raise ValueError("discovery mandate cannot expand strategy families")
            rows = session.scalars(
                select(ResearchEvidence).where(ResearchEvidence.id.in_(mandate.evidence_ids))
            ).all()
            for row in rows:
                session.expunge(row)
        if len(rows) != len(set(mandate.evidence_ids)):
            raise ValueError("discovery requires all declared evidence")
        cutoff = now - timedelta(hours=mandate.freshness_hours)
        if any(
            row.status != "active"
            or _utc(row.as_of) < cutoff
            or (row.valid_until is not None and _utc(row.valid_until) <= now)
            for row in rows
        ):
            raise ValueError("discovery evidence is inactive or stale")
        return {row.id: row for row in rows}

    def _require_immutable_hypothesis(self, proposal: DiscoveryProposalV1) -> None:
        hypothesis = proposal.hypothesis
        current_hash = digest(hypothesis)
        with self.db.session() as session:
            rows = session.scalars(select(StrategyDiscoveryCandidate)).all()
            for row in rows:
                stored = dict(row.hypothesis_json)
                if (
                    stored.get("hypothesis_key") == hypothesis.hypothesis_key
                    and stored.get("hypothesis_version") == hypothesis.hypothesis_version
                    and row.hypothesis_hash != current_hash
                ):
                    raise ValueError(
                        "alpha hypothesis version is immutable; increment hypothesis_version"
                    )

    def _proposal_rejections(
        self,
        request: DiscoveryRequestV1,
        proposal: DiscoveryProposalV1,
        *,
        evidence: dict[str, ResearchEvidence],
        now: datetime,
    ) -> builtins.list[str]:
        mandate = request.mandate
        phenomenon = proposal.phenomenon
        hypothesis = proposal.hypothesis
        spec = hypothesis.strategy_spec
        reasons: list[str] = []
        if not set(phenomenon.evidence_ids).issubset(set(mandate.evidence_ids)):
            reasons.append("data_evidence_outside_mandate")
        selected = [evidence[item] for item in phenomenon.evidence_ids if item in evidence]
        for row in selected:
            if row.evidence_type == "data_gap":
                reasons.append(f"data_gap:{row.id}")
            sources = list(row.sources_json)
            if not any(
                str(source.get("source_type", "")) in mandate.data_sources
                and source.get("availability") == "available"
                for source in sources
            ):
                reasons.append(f"data_no_real_source:{row.id}")
        if _utc(phenomenon.observed_at) > now:
            reasons.append("phenomenon_observed_in_future")
        if not set(phenomenon.symbols).issubset(set(mandate.symbols)):
            reasons.append("phenomenon_symbol_outside_mandate")
        if not set(phenomenon.timeframes).issubset(set(mandate.timeframes)):
            reasons.append("phenomenon_timeframe_outside_mandate")
        if hypothesis.strategy_family not in mandate.strategy_families:
            reasons.append("strategy_family_not_allowed")
        if phenomenon.phenomenon_key not in hypothesis.phenomenon_keys:
            reasons.append("hypothesis_not_bound_to_phenomenon")
        if hypothesis.frozen_at < phenomenon.observed_at:
            reasons.append("hypothesis_frozen_before_evidence")
        if spec.mandate_id != mandate.research_mandate_id:
            reasons.append("strategy_spec_mandate_mismatch")
        if not set(spec.symbols).issubset(set(mandate.symbols)):
            reasons.append("strategy_spec_symbol_outside_mandate")
        if not set(spec.timeframes).issubset(set(mandate.timeframes)):
            reasons.append("strategy_spec_timeframe_outside_mandate")
        if spec.strategy_category.casefold() != hypothesis.strategy_family.casefold():
            reasons.append("strategy_spec_family_mismatch")
        forbidden = set(mandate.forbidden_features)
        for feature in hypothesis.features:
            if feature.casefold() in forbidden:
                reasons.append(f"forbidden_feature:{feature.casefold()}")
        if proposal.experiment.market_type.upper() != mandate.market_type:
            reasons.append("experiment_market_type_mismatch")
        if not any(window.name == "locked_oos" for window in proposal.experiment.windows):
            reasons.append("data_locked_oos_window_missing")
        return sorted(set(reasons))

    def _budget_reasons(
        self,
        request: DiscoveryRequestV1,
        proposal: DiscoveryProposalV1,
        usage: dict[str, Any],
        elapsed: float,
    ) -> builtins.list[str]:
        mandate = request.mandate
        reasons = []
        if usage["phenomena"] >= mandate.max_phenomena:
            reasons.append("max_phenomena_exhausted")
        if usage["hypotheses"] >= mandate.max_hypotheses:
            reasons.append("max_hypotheses_exhausted")
        if usage["candidates_ready"] >= mandate.max_candidates:
            reasons.append("max_candidates_exhausted")
        if usage["model_calls"] + proposal.model_calls > mandate.max_model_calls:
            reasons.append("max_model_calls_exhausted")
        if usage["tool_calls"] + proposal.tool_calls + 2 > mandate.max_tool_calls:
            reasons.append("max_tool_calls_exhausted")
        if elapsed > mandate.max_wall_seconds:
            reasons.append("max_wall_seconds_exhausted")
        return reasons

    def _create_candidate(
        self,
        *,
        run_id: str,
        request: DiscoveryRequestV1,
        proposal: DiscoveryProposalV1,
        novelty: StrategyNoveltyReportV1,
        code_sha: str,
        actor: str,
    ) -> dict[str, Any]:
        fingerprint = self._candidate_fingerprint(request, proposal)
        existing = self._candidate_by_fingerprint(fingerprint)
        if existing is not None:
            _require_matching_code(existing, proposal.strategy_code)
            return _candidate_to_dict(existing, replay="fingerprint")
        assert self.adapter is not None
        strategy_name = _strategy_name(proposal.hypothesis)
        created = self.adapter.strategy_create(
            name=strategy_name,
            script_content=proposal.strategy_code,
            description=proposal.hypothesis.economic_rationale,
            config={
                "strategy_source": "db_script",
                "script_content_source": "db",
                "research_candidate": True,
                "paper_enabled": False,
                "live_enabled": False,
                "market_type": request.mandate.market_type,
                "timeframe": proposal.hypothesis.strategy_spec.timeframes[0],
                "discovery_fingerprint": fingerprint,
            },
            exchange=proposal.experiment.exchange,
            symbols=proposal.hypothesis.strategy_spec.symbols,
            idempotency_key=f"discovery-create-{fingerprint[:32]}",
        )
        strategy_id = _strategy_id(created)
        code_ref = f"bitpro:strategy:{strategy_id}@sha256:{code_sha}"
        manifest = ExperimentManifestV1(
            strategy_spec=proposal.hypothesis.strategy_spec,
            strategy_code_sha256=code_sha,
            strategy_code_ref=code_ref,
            parameters={},
            exchange=proposal.experiment.exchange,
            market_type=proposal.experiment.market_type,
            windows=proposal.experiment.windows,
            costs=proposal.experiment.costs,
            data_snapshot_hash=proposal.experiment.data_snapshot_hash,
            versions=proposal.experiment.versions,
        )
        registration = ExperimentLedgerService(self.db).register(
            ExperimentRegister(
                manifest=manifest,
                idempotency_key=f"discovery-manifest-{fingerprint[:32]}",
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
                raise ValueError("discovery manifest did not produce a StrategyVersion")
            version_id = version.id
        candidate = self._candidate_model(
            request,
            proposal,
            status="candidate_ready",
            novelty=novelty,
            reasons=[],
            strategy_code_ref=code_ref,
            bitpro_strategy_id=strategy_id,
            manifest_id=manifest_id,
            experiment_execution_id=execution_id,
            strategy_version_id=version_id,
        )
        return self._persist(run_id, proposal, candidate, actor=actor)

    def _record_terminal(
        self,
        run_id: str,
        request: DiscoveryRequestV1,
        proposal: DiscoveryProposalV1,
        *,
        status: str,
        reasons: builtins.list[str],
        novelty: StrategyNoveltyReportV1,
        actor: str,
    ) -> dict[str, Any]:
        fingerprint = self._candidate_fingerprint(request, proposal)
        existing = self._candidate_by_fingerprint(fingerprint)
        if existing is not None:
            _require_matching_code(existing, proposal.strategy_code)
            return _candidate_to_dict(existing, replay="fingerprint")
        candidate = self._candidate_model(
            request,
            proposal,
            status=status,
            novelty=novelty,
            reasons=reasons,
        )
        return self._persist(run_id, proposal, candidate, actor=actor)

    def _candidate_model(
        self,
        request: DiscoveryRequestV1,
        proposal: DiscoveryProposalV1,
        *,
        status: str,
        novelty: StrategyNoveltyReportV1,
        reasons: builtins.list[str],
        strategy_code_ref: str = "",
        bitpro_strategy_id: str = "",
        manifest_id: str = "",
        experiment_execution_id: str = "",
        strategy_version_id: str = "",
    ) -> DiscoveryCandidateV1:
        return DiscoveryCandidateV1(
            fingerprint=self._candidate_fingerprint(request, proposal),
            phenomenon_hash=digest(proposal.phenomenon),
            hypothesis_hash=digest(proposal.hypothesis),
            hypothesis_version=proposal.hypothesis.hypothesis_version,
            status=cast(Any, status),
            novelty=novelty,
            strategy_code_sha256=hashlib.sha256(
                proposal.strategy_code.encode("utf-8")
            ).hexdigest(),
            strategy_code_ref=strategy_code_ref,
            bitpro_strategy_id=bitpro_strategy_id,
            manifest_id=manifest_id,
            experiment_execution_id=experiment_execution_id,
            strategy_version_id=strategy_version_id,
            evidence_ids=proposal.phenomenon.evidence_ids,
            rejection_reasons=sorted(set(reasons)),
            prompt_template_version=proposal.template_version,
            data_snapshot_hash=proposal.experiment.data_snapshot_hash,
            deterministic_seed=request.mandate.deterministic_seed,
        )

    def _persist(
        self,
        run_id: str,
        proposal: DiscoveryProposalV1,
        candidate: DiscoveryCandidateV1,
        *,
        actor: str,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            row = StrategyDiscoveryCandidate(
                run_id=run_id,
                schema_version=candidate.schema_version,
                fingerprint=candidate.fingerprint,
                phenomenon_hash=candidate.phenomenon_hash,
                hypothesis_hash=candidate.hypothesis_hash,
                status=candidate.status,
                strategy_family=proposal.hypothesis.strategy_family,
                bitpro_strategy_id=candidate.bitpro_strategy_id,
                manifest_id=candidate.manifest_id,
                experiment_execution_id=candidate.experiment_execution_id,
                strategy_version_id=candidate.strategy_version_id,
                phenomenon_json=canonical_payload(proposal.phenomenon),
                hypothesis_json=canonical_payload(proposal.hypothesis),
                novelty_json=canonical_payload(candidate.novelty),
                candidate_json=canonical_payload(candidate),
                created_by=actor,
            )
            session.add(row)
            session.flush()
            return _candidate_to_dict(row)

    def _candidate_by_fingerprint(
        self, fingerprint: str
    ) -> StrategyDiscoveryCandidate | None:
        with self.db.session() as session:
            row = session.scalar(
                select(StrategyDiscoveryCandidate).where(
                    StrategyDiscoveryCandidate.fingerprint == fingerprint
                )
            )
            if row is not None:
                session.expunge(row)
            return row

    @staticmethod
    def _candidate_fingerprint(
        request: DiscoveryRequestV1, proposal: DiscoveryProposalV1
    ) -> str:
        return digest(
            {
                "hypothesis": canonical_payload(proposal.hypothesis),
                "template_version": proposal.template_version,
                "data_snapshot_hash": proposal.experiment.data_snapshot_hash,
                "deterministic_seed": request.mandate.deterministic_seed,
            }
        )

    @staticmethod
    def _count(row: dict[str, Any], usage: dict[str, Any]) -> None:
        usage["candidate_ids"].append(row["id"])
        if row.get("replay"):
            usage["reused_candidate_ids"].append(row["id"])
        if row["status"] == "candidate_ready":
            usage["candidates_ready"] += 1
        else:
            usage["rejected"] += 1

    def _run_projection(self, run_id: str, *, replay: str = "") -> dict[str, Any]:
        with self.db.session() as session:
            run = session.get(StrategyDiscoveryRun, run_id)
            if run is None:
                raise KeyError(run_id)
            candidate_ids = list(dict(run.usage_json).get("candidate_ids", []))
            rows = session.scalars(
                select(StrategyDiscoveryCandidate)
                .where(
                    (StrategyDiscoveryCandidate.run_id == run_id)
                    | (StrategyDiscoveryCandidate.id.in_(candidate_ids))
                )
                .order_by(
                    StrategyDiscoveryCandidate.created_at, StrategyDiscoveryCandidate.id
                )
            ).all()
            return {
                "id": run.id,
                "schema_version": run.schema_version,
                "research_mandate_id": run.research_mandate_id,
                "status": run.status,
                "request_hash": run.request_hash,
                "mandate": dict(run.mandate_json),
                "usage": dict(run.usage_json),
                "candidates": [_candidate_to_dict(row) for row in rows],
                "execution_authorized": False,
                "mutation_boundary": {
                    "bitpro_strategy_create": True,
                    "paper_writes": False,
                    "live_writes": False,
                    "order_writes": False,
                    "capital_writes": False,
                },
                "replay": replay,
            }


def _candidate_to_dict(
    row: StrategyDiscoveryCandidate, *, replay: str = ""
) -> dict[str, Any]:
    return {
        "id": row.id,
        **dict(row.candidate_json),
        "phenomenon": dict(row.phenomenon_json),
        "hypothesis": dict(row.hypothesis_json),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "replay": replay,
    }


def _require_matching_code(row: StrategyDiscoveryCandidate, strategy_code: str) -> None:
    expected = str(dict(row.candidate_json).get("strategy_code_sha256", ""))
    actual = hashlib.sha256(strategy_code.encode("utf-8")).hexdigest()
    if expected != actual:
        raise ValueError("nondeterministic discovery code digest mismatch")


def _unknown_novelty(reason: str) -> StrategyNoveltyReportV1:
    return StrategyNoveltyReportV1(
        status="unknown",
        reasons=[],
        compared_version_ids=[],
        unknowns=[reason],
    )


def _spec_signature(spec: dict[str, Any]) -> tuple[str, ...]:
    def normalized(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()

    return (
        normalized(spec.get("strategy_category", "")),
        normalized(spec.get("entry_logic", "")),
        normalized(spec.get("exit_logic", "")),
        "|".join(sorted(normalized(item) for item in spec.get("risk_conditions", []))),
        "|".join(sorted(str(item).upper() for item in spec.get("symbols", []))),
        "|".join(sorted(str(item).upper() for item in spec.get("timeframes", []))),
    )


def _static_code_rejections(code: str) -> builtins.list[str]:
    lowered = code.casefold()
    reasons: list[str] = []
    if len(re.findall(r"class\s+\w+\s*\([^)]*BaseStrategy[^)]*\)\s*:", code)) != 1:
        reasons.append("code_requires_single_basestrategy_subclass")
    forbidden = {
        "network_access": ("socket", "requests", "urllib", "httpx", "aiohttp"),
        "filesystem_access": ("open(", "pathlib", "os.", "shutil"),
        "process_execution": ("subprocess", "os.system", "popen("),
        "dynamic_execution": ("eval(", "exec(", "compile(", "__import__("),
        "secret_access": ("environ", "getenv", "api_key", "secret", "password"),
        "unbounded_loop": ("while true", "while 1"),
    }
    for reason, tokens in forbidden.items():
        if any(token in lowered for token in tokens):
            reasons.append(reason)
    return sorted(set(reasons))


def _validation_passed(payload: dict[str, Any]) -> bool:
    raw = payload.get("validation", payload)
    validation = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    return bool(validation.get("valid") or validation.get("passed")) or str(
        validation.get("status", "")
    ).casefold() in {"ok", "valid", "passed"}


def _strategy_id(payload: dict[str, Any]) -> str:
    raw = payload.get("strategy", payload)
    strategy = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    value = strategy.get("id") or strategy.get("strategy_id")
    if value is None:
        raise RuntimeError("bitpro_strategy_create_missing_strategy_id")
    return str(value)


def _strategy_name(hypothesis: AlphaHypothesisV1) -> str:
    suffix = digest(hypothesis)[:10]
    return f"ht_{hypothesis.strategy_family}_{suffix}"[:128]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
