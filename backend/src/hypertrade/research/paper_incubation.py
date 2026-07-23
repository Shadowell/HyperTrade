"""Mandate-bounded autonomous Paper incubation with durable effect dispatch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast

from sqlalchemy import desc, select

from hypertrade.db import (
    Database,
    ExperimentManifest,
    PaperIncubationAction,
    PaperIncubationMember,
    PaperResearchMandate,
    StrategyDiscoveryCandidate,
    StrategyEvolutionCandidate,
    UnifiedStrategyValidation,
)
from hypertrade.portfolio.cohort_schemas import PaperCohortBuildV1
from hypertrade.portfolio.cohorts import PaperCohortService
from hypertrade.portfolio.evidence import PortfolioEvidenceService
from hypertrade.portfolio.evidence_schemas import PortfolioObservationCaptureV1
from hypertrade.research.paper_incubation_schemas import (
    PaperIncubationActionV1,
    PaperIncubationCaptureV1,
    PaperMandateCreateV1,
    canonical_payload,
    digest,
)
from hypertrade.research.strategy_cards import StrategyCardService
from hypertrade.runtime.application.effect_governance import EffectGovernanceService
from hypertrade.runtime.domain.capabilities import (
    CapabilityDefinitionV1,
    reviewed_snapshot,
)
from hypertrade.runtime.domain.effects import (
    DispatchIntentV1,
    EffectAckV1,
    EffectResolutionV1,
)

MUTATING_ACTIONS = frozenset({"configure", "start", "pause", "retire"})


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class PaperIncubationAdapter(Protocol):
    """The only external boundary; deliberately excludes Testnet and Live methods."""

    def paper_configure(
        self,
        *,
        strategy_id: int,
        initial_equity: float,
        exchange: str,
        loop_interval_sec: int,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def paper_start(self, *, strategy_id: int, idempotency_key: str) -> dict[str, Any]: ...

    def paper_pause(self, *, strategy_id: int) -> dict[str, Any]: ...

    def paper_stop(self, *, strategy_id: int, clear_metrics: bool = False) -> dict[str, Any]: ...

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]: ...

    def paper_equity_curve(
        self, *, strategy_id: int | None = None, sample_limit: int = 50
    ) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


class PaperEffectAdapter:
    """Translate a governed generic effect into the narrow BitPro Paper contract."""

    def __init__(self, adapter: PaperIncubationAdapter) -> None:
        self.adapter = adapter

    async def dispatch(self, intent: DispatchIntentV1, arguments: dict[str, Any]) -> EffectAckV1:
        action = str(arguments["action"])
        strategy_id = int(arguments["strategy_id"])
        if action == "configure":
            payload = self.adapter.paper_configure(
                strategy_id=strategy_id,
                initial_equity=float(arguments["paper_capital"]),
                exchange="okx",
                loop_interval_sec=60,
                idempotency_key=intent.idempotency_key,
            )
        elif action == "start":
            payload = self.adapter.paper_start(
                strategy_id=_paper_target_id(
                    str(arguments.get("paper_instance_id") or ""), strategy_id
                ),
                idempotency_key=intent.idempotency_key,
            )
        elif action == "pause":
            payload = self.adapter.paper_pause(strategy_id=strategy_id)
        elif action == "retire":
            payload = self.adapter.paper_stop(strategy_id=strategy_id, clear_metrics=False)
        else:
            raise ValueError("unsupported paper effect action")
        paper = _dict(payload.get("paper"))
        operation_id = str(
            paper.get("operation_id")
            or paper.get("instance_id")
            or paper.get("id")
            or f"paper:{strategy_id}:{action}"
        )
        return EffectAckV1(
            external_operation_id=operation_id,
            result={
                "action": action,
                "strategy_id": strategy_id,
                "paper": paper,
                "tool_calls": _tool_calls(payload),
            },
        )

    async def reconcile(self, intent: DispatchIntentV1) -> EffectResolutionV1:
        action = intent.capability_id.rsplit(".", 1)[-1]
        strategy_id = _strategy_id_from_scope(intent.operation_scope)
        try:
            payload = self.adapter.paper_snapshot(strategy_id=strategy_id)
        except Exception:
            return EffectResolutionV1(
                outcome="unknown",
                reason="BitPro Paper state could not be read for reconciliation",
            )
        snapshot = _dict(payload.get("snapshot"))
        status = str(snapshot.get("status", "")).casefold()
        committed = (
            (action in {"configure", "start"} and status in {"configured", "running", "paused"})
            or (action == "pause" and status == "paused")
            or (action == "retire" and status in {"stopped", "retired"})
        )
        if committed:
            return EffectResolutionV1(
                outcome="committed",
                external_operation_id=str(
                    snapshot.get("instance_id") or f"paper:{strategy_id}:{action}"
                ),
                result={"snapshot": snapshot},
                reason="BitPro Paper state confirms the requested action",
            )
        if status:
            return EffectResolutionV1(
                outcome="not_committed",
                result={"snapshot": snapshot},
                reason="BitPro Paper state is definite and does not reflect the requested action",
            )
        return EffectResolutionV1(
            outcome="unknown",
            result={"snapshot": snapshot},
            reason="BitPro Paper state lacks a lifecycle status",
        )


class AutonomousPaperIncubationService:
    """Intake validated candidates and execute only pre-approved Paper actions."""

    def __init__(
        self,
        db: Database,
        *,
        effect_governance: EffectGovernanceService | None = None,
        bitpro_adapter: PaperIncubationAdapter | None = None,
    ) -> None:
        self.db = db
        self.effect_governance = effect_governance
        self.bitpro_adapter = bitpro_adapter

    def create_mandate(self, request: PaperMandateCreateV1, *, actor: str) -> dict[str, Any]:
        mandate = request.mandate
        if actor != mandate.approved_by:
            raise PermissionError(
                "paper mandate creator must match the authenticated human approver"
            )
        body = canonical_payload(mandate)
        content_hash = digest(body)
        # The dispatch policy hash covers the complete immutable authority,
        # including candidate/validation fingerprints, symbols and validity.
        policy_hash = content_hash
        with self.db.session() as session:
            replay = session.scalar(
                select(PaperResearchMandate).where(
                    PaperResearchMandate.idempotency_key == request.idempotency_key
                )
            )
            if replay is not None:
                if replay.content_hash != content_hash:
                    raise ValueError("paper mandate idempotency key is content-bound")
                return self._projection(replay.id, replay="idempotency")
            same = session.scalar(
                select(PaperResearchMandate).where(
                    PaperResearchMandate.content_hash == content_hash
                )
            )
            if same is not None:
                return self._projection(same.id, replay="content")
            row = PaperResearchMandate(
                schema_version=mandate.schema_version,
                status="active",
                policy_hash=policy_hash,
                content_hash=content_hash,
                idempotency_key=request.idempotency_key,
                mandate_json=body,
                control_json={},
                approved_by=mandate.approved_by,
                kill_switch=False,
                valid_from=mandate.valid_from,
                valid_until=mandate.valid_until,
            )
            session.add(row)
            session.flush()
            mandate_id = row.id
        self._intake(mandate_id, actor=actor)
        return self._projection(mandate_id)

    async def act(self, request: PaperIncubationActionV1, *, actor: str) -> dict[str, Any]:
        if request.action not in MUTATING_ACTIONS:
            if request.action == "observe":
                observed = self.observe(request.member_id, actor=actor)
                automatic_decision = str(
                    dict(observed["observation"]).get("automatic_decision", "")
                )
                if automatic_decision == "pause":
                    automatic = await self.act(
                        PaperIncubationActionV1(
                            member_id=request.member_id,
                            action="pause",
                            reason=("Automatic safety pause from Paper observation thresholds"),
                            idempotency_key=(
                                "paper-auto-pause-"
                                f"{digest({'request': request.idempotency_key})[:32]}"
                            ),
                        ),
                        actor=actor,
                    )
                    return {**observed, "automatic_action": automatic}
                return observed
            raise ValueError("reduce is not available without a reviewed BitPro contract")
        if self.effect_governance is None or self.bitpro_adapter is None:
            raise RuntimeError("paper effect governance is unavailable")
        with self.db.session() as session:
            replay = session.scalar(
                select(PaperIncubationAction).where(
                    PaperIncubationAction.idempotency_key == request.idempotency_key
                )
            )
            if replay is not None:
                if (
                    replay.member_id != request.member_id
                    or replay.action != request.action
                    or replay.reason != request.reason
                ):
                    raise ValueError("paper action idempotency key is content-bound")
                return _action_dict(replay, replay="idempotency")
            member = _member(session, request.member_id)
            mandate = _mandate(session, member.mandate_id)
            self._authorize(mandate, member, request.action)
            arguments = self._arguments(mandate, member, request.action)
            before = _member_state(member)
            approved_by = mandate.approved_by
            policy = dict(mandate.mandate_json)
        snapshot = _paper_capability(request.action)
        decision = await self.effect_governance.evaluate(
            snapshot,
            arguments,
            mission_id=f"paper_incubation:{member.mandate_id}",
            subject=actor,
            account="paper-only",
            environment="paper",
            role="paper_incubation_controller",
            budget={"paper_capital": arguments["paper_capital"], "instances": 1},
            policy_snapshot={"mandate_id": member.mandate_id, "policy_hash": member.policy_hash},
        )
        approval = await self.effect_governance.request_approval(
            decision.decision_id,
            resource_scope=(f"paper:strategy:{member.bitpro_strategy_id}",),
            maximum_amount=str(arguments["paper_capital"]),
            requested_by=actor,
        )
        issued = await self.effect_governance.grant_approval(
            approval.request_id,
            actor=approved_by,
            reason="standing PaperResearchMandate exact-action authorization",
        )
        intent, call = await self.effect_governance.prepare_dispatch(
            decision.decision_id,
            arguments,
            operation_scope=(f"paper:strategy:{member.bitpro_strategy_id}",),
            idempotency_key=request.idempotency_key,
            fencing_token=1,
            reconciliation_policy="read_state",
            approval_request_id=approval.request_id,
            approval_grant_id=issued.grant.grant_id,
            approval_token=issued.consumption_token,
        )
        with self.db.session() as session:
            row = PaperIncubationAction(
                mandate_id=member.mandate_id,
                member_id=member.id,
                action=request.action,
                status="prepared",
                idempotency_key=request.idempotency_key,
                dispatch_intent_id=intent.intent_id,
                tool_call_id=call.tool_call_id,
                reason=request.reason,
                before_json=before,
                after_json={},
                evidence_json={
                    "mandate_policy_hash": member.policy_hash,
                    "validation_id": member.validation_id,
                    "source_hash": member.source_hash,
                    "approved_by": approved_by,
                    "allowed_actions": policy["allowed_actions"],
                },
                created_by=actor,
            )
            session.add(row)
            session.flush()
            action_id = row.id
        completed = await self.effect_governance.execute(
            intent.intent_id, arguments, PaperEffectAdapter(self.bitpro_adapter)
        )
        return self._record_effect(action_id, completed.status, completed.external_operation_id)

    async def reconcile(self, action_id: str, *, actor: str) -> dict[str, Any]:
        if self.effect_governance is None or self.bitpro_adapter is None:
            raise RuntimeError("paper effect governance is unavailable")
        with self.db.session() as session:
            action = _action(session, action_id)
            intent_id = action.dispatch_intent_id
        call, resolution = await self.effect_governance.reconcile(
            intent_id, PaperEffectAdapter(self.bitpro_adapter), actor=actor
        )
        return self._record_effect(
            action_id,
            call.status,
            call.external_operation_id,
            resolution=resolution.model_dump(mode="json"),
        )

    def observe(self, member_id: str, *, actor: str) -> dict[str, Any]:
        if self.bitpro_adapter is None:
            raise RuntimeError("paper observation adapter is unavailable")
        with self.db.session() as session:
            member = _member(session, member_id)
            mandate = _mandate(session, member.mandate_id)
            self._authorize(mandate, member, "observe")
            strategy_id = int(member.bitpro_strategy_id)
            instance_id = member.paper_instance_id or None
        payload = self.bitpro_adapter.paper_snapshot(
            strategy_id=strategy_id, instance_id=instance_id
        )
        snapshot = _dict(payload.get("snapshot"))
        try:
            health = dict(self.bitpro_adapter.health())
        except Exception as exc:
            health = {"status": "error", "error_type": type(exc).__name__}
        coverage = _dict(snapshot.get("data_coverage"))
        gaps = [
            field
            for field in ("status", "generated_at", "strategy_version", "config_version")
            if not snapshot.get(field)
        ]
        sample_count = int(coverage.get("equity_sample_count", 0) or 0)
        max_drawdown = _decimal(snapshot.get("max_drawdown_pct"))
        error_count = int(snapshot.get("error_count", 0) or 0)
        policy = dict(mandate.mandate_json)
        alerts: list[str] = []
        if str(health.get("status", "")).casefold() not in {
            "ok",
            "healthy",
            "available",
        }:
            alerts.append("bitpro_source_unhealthy")
        if max_drawdown is not None and max_drawdown > Decimal(str(policy["max_drawdown_pct"])):
            alerts.append("max_drawdown_exceeded")
        if error_count > int(policy["max_error_count"]):
            alerts.append("paper_error_threshold_exceeded")
        if int(snapshot.get("abnormal_trade_count", 0) or 0) > 0:
            alerts.append("abnormal_trade_detected")
        generated_at = _timestamp(snapshot.get("generated_at"))
        if generated_at is not None and _now() - generated_at > timedelta(days=1):
            alerts.append("paper_source_stale")
        if sample_count < int(policy["minimum_equity_samples"]):
            gaps.append("minimum_equity_samples_missing")
        next_status = (
            "paper_review_required" if alerts else "paper_degraded" if gaps else "observing"
        )
        observation = {
            "observed_at": _now().isoformat(),
            "actor": actor,
            "snapshot": snapshot,
            "health": health,
            "data_gaps": sorted(set(gaps)),
            "alerts": alerts,
            "automatic_decision": (
                "pause"
                if alerts and "pause" in policy["allowed_actions"]
                else "continue_observing"
                if not alerts and not gaps
                else "hold"
            ),
            "champion_authorized": False,
            "live_authorized": False,
        }
        with self.db.session() as session:
            member = _member(session, member_id)
            history = list(member.observation_json.get("history", []))
            member.status = next_status
            member.observation_json = {
                **observation,
                "history": [*history[-29:], observation],
            }
        return self.get_member(member_id)

    def capture_windows(self, request: PaperIncubationCaptureV1, *, actor: str) -> dict[str, Any]:
        if self.bitpro_adapter is None:
            raise RuntimeError("paper observation adapter is unavailable")
        with self.db.session() as session:
            mandate = _mandate(session, request.mandate_id)
            policy = dict(mandate.mandate_json)
            manifest_ids = {
                row.manifest_id
                for row in session.scalars(
                    select(PaperIncubationMember).where(
                        PaperIncubationMember.mandate_id == mandate.id,
                        PaperIncubationMember.status != "rejected",
                    )
                ).all()
            }
        cards = [
            card
            for card in StrategyCardService(self.db).list()
            if str(dict(card.get("source_refs", {})).get("manifest_id", "")) in manifest_ids
        ]
        card_ids = sorted(str(card["card_id"]) for card in cards)
        minimum_samples = int(policy["minimum_equity_samples"])
        min_aligned_returns = min(100, max(5, minimum_samples))
        max_points = max(request.max_points, min_aligned_returns + 1)
        windows: list[dict[str, Any]] = []
        cohorts: list[dict[str, Any]] = []
        evidence_service = PortfolioEvidenceService(self.db, adapter=self.bitpro_adapter)
        for horizon in policy["observation_days"]:
            window = evidence_service.capture(
                PortfolioObservationCaptureV1(
                    strategy_card_ids=card_ids,
                    horizon_days=horizon,
                    bucket_minutes=request.bucket_minutes,
                    max_points=max_points,
                    min_aligned_returns=min_aligned_returns,
                    idempotency_key=f"{request.idempotency_key}:window:{horizon}",
                ),
                actor=actor,
            )
            cohort = PaperCohortService(self.db).build(
                PaperCohortBuildV1(
                    observation_window_id=window["id"],
                    strategy_card_ids=card_ids,
                    horizon_days=horizon,
                    min_sample_count=min(500, max(5, minimum_samples)),
                    idempotency_key=f"{request.idempotency_key}:cohort:{horizon}",
                ),
                actor=actor,
            )
            windows.append(window)
            cohorts.append(cohort)
        return {
            "mandate_id": mandate.id,
            "policy_hash": mandate.policy_hash,
            "fixed_denominator": len(policy["candidate_ids"]),
            "strategy_card_ids": card_ids,
            "windows": windows,
            "cohorts": cohorts,
            "champion_authorized": False,
            "live_authorized": False,
        }

    def set_mandate_state(
        self, mandate_id: str, *, status: str, actor: str, reason: str
    ) -> dict[str, Any]:
        if status not in {"active", "paused", "revoked"}:
            raise ValueError("paper mandate state must be active, paused or revoked")
        if not reason.strip():
            raise ValueError("paper mandate state change requires a reason")
        if actor.casefold().split(":", 1)[0] in {
            "agent",
            "model",
            "planner",
            "runtime",
        }:
            raise PermissionError("an Agent or model cannot control a paper mandate")
        with self.db.session() as session:
            row = _mandate(session, mandate_id)
            row.status = status
            row.kill_switch = status in {"paused", "revoked"}
            control = {
                "status": status,
                "actor": actor,
                "reason": reason.strip(),
                "at": _now().isoformat(),
            }
            controls = dict(row.control_json)
            history = list(controls.get("history", []))
            row.control_json = {
                "latest": control,
                "history": [*history[-99:], control],
            }
        return self._projection(mandate_id)

    def get_member(self, member_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            return _member_dict(_member(session, member_id))

    def get(self, mandate_id: str) -> dict[str, Any]:
        return self._projection(mandate_id)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            ids = list(
                session.scalars(
                    select(PaperResearchMandate.id)
                    .order_by(desc(PaperResearchMandate.created_at))
                    .limit(max(1, min(limit, 500)))
                ).all()
            )
        return [self._projection(item) for item in ids]

    def _intake(self, mandate_id: str, *, actor: str) -> None:
        del actor
        with self.db.session() as session:
            mandate = _mandate(session, mandate_id)
            policy = dict(mandate.mandate_json)
            validation_ids = set(policy["validation_ids"])
            validations = session.scalars(
                select(UnifiedStrategyValidation).where(
                    UnifiedStrategyValidation.id.in_(validation_ids)
                )
            ).all()
            by_candidate = {row.candidate_id: row for row in validations}
            eligible_count = 0
            for candidate_id in policy["candidate_ids"]:
                validation = by_candidate.get(candidate_id)
                reasons: list[str] = []
                candidate_kind = validation.candidate_kind if validation else "unknown"
                manifest_id = validation.manifest_id if validation else ""
                execution_id = validation.experiment_execution_id if validation else ""
                bitpro_strategy_id = ""
                source_hash = validation.source_hash if validation else ""
                if validation is None:
                    reasons.append("validated_decision_missing")
                elif validation.status != "validated":
                    reasons.append(f"validation_status:{validation.status}")
                elif validation.fingerprint != policy["validation_fingerprints"].get(candidate_id):
                    reasons.append("validation_fingerprint_mismatch")
                if validation is not None:
                    candidate = (
                        session.get(StrategyEvolutionCandidate, candidate_id)
                        if candidate_kind == "evolution"
                        else session.get(StrategyDiscoveryCandidate, candidate_id)
                    )
                    if candidate is None:
                        reasons.append("candidate_missing")
                    else:
                        if isinstance(candidate, StrategyDiscoveryCandidate):
                            bitpro_strategy_id = str(candidate.bitpro_strategy_id)
                        if candidate.manifest_id != manifest_id:
                            reasons.append("candidate_manifest_hash_mismatch")
                    manifest = session.get(ExperimentManifest, manifest_id)
                    if manifest is None:
                        reasons.append("manifest_missing")
                    else:
                        manifest_payload = dict(manifest.canonical_json)
                        if not set(policy["symbols"]).issubset(
                            set(manifest_payload["strategy_spec"]["symbols"])
                        ):
                            reasons.append("mandate_symbol_outside_candidate")
                        if not bitpro_strategy_id:
                            bitpro_strategy_id = _bitpro_strategy_id(
                                str(manifest_payload.get("strategy_code_ref", ""))
                            )
                if not bitpro_strategy_id:
                    reasons.append("bitpro_strategy_id_missing")
                if not reasons and eligible_count >= int(policy["max_instances"]):
                    reasons.append("paper_instance_quota_exhausted")
                if not reasons:
                    eligible_count += 1
                session.add(
                    PaperIncubationMember(
                        mandate_id=mandate.id,
                        candidate_kind=candidate_kind,
                        candidate_id=candidate_id,
                        validation_id=validation.id if validation else "",
                        manifest_id=manifest_id,
                        experiment_execution_id=execution_id,
                        bitpro_strategy_id=bitpro_strategy_id,
                        status="eligible" if not reasons else "rejected",
                        source_hash=source_hash,
                        policy_hash=mandate.policy_hash,
                        rejection_reasons_json=sorted(set(reasons)),
                    )
                )

    def _authorize(
        self, mandate: PaperResearchMandate, member: PaperIncubationMember, action: str
    ) -> None:
        now = _now()
        policy = dict(mandate.mandate_json)
        safety_containment = (
            mandate.status == "revoked"
            and mandate.kill_switch
            and policy.get("revoke_mode") == "safe_pause"
            and action in {"pause", "retire"}
        )
        read_observation = action == "observe" and mandate.status in {"paused", "revoked"}
        if (
            (mandate.status != "active" or mandate.kill_switch)
            and not safety_containment
            and not read_observation
        ):
            raise PermissionError("paper mandate kill switch blocks new actions")
        if (
            not (_aware(mandate.valid_from) <= now < _aware(mandate.valid_until))
            and not safety_containment
            and not read_observation
        ):
            raise PermissionError("paper mandate is not currently valid")
        if action not in policy["allowed_actions"]:
            raise PermissionError("paper action is outside the approved mandate")
        if member.status == "rejected":
            raise PermissionError("rejected intake member cannot enter Paper")
        allowed_states = {
            "configure": {"eligible"},
            "start": {"configured"},
            "observe": {"observing", "paper_degraded", "paper_review_required"},
            "pause": {"observing", "paper_degraded", "paper_review_required", "effect_unknown"},
            "retire": {
                "configured",
                "observing",
                "paper_degraded",
                "paper_review_required",
                "paused",
                "effect_unknown",
            },
        }
        if member.status not in allowed_states.get(action, set()):
            raise ValueError(f"paper action {action} is invalid from {member.status}")

    @staticmethod
    def _arguments(
        mandate: PaperResearchMandate, member: PaperIncubationMember, action: str
    ) -> dict[str, Any]:
        policy = dict(mandate.mandate_json)
        return {
            "action": action,
            "mandate_id": mandate.id,
            "member_id": member.id,
            "strategy_id": int(member.bitpro_strategy_id),
            "paper_instance_id": member.paper_instance_id,
            "paper_capital": policy["paper_capital"],
            "symbols": policy["symbols"],
            "validation_id": member.validation_id,
            "source_hash": member.source_hash,
        }

    def _record_effect(
        self,
        action_id: str,
        status: str,
        external_operation_id: str,
        *,
        resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            row = _action(session, action_id)
            member = _member(session, row.member_id)
            row.status = status
            row.external_operation_id = external_operation_id
            if status == "effect_unknown":
                member.status = "effect_unknown"
            elif status in {"succeeded", "reconciled"}:
                member.status = {
                    "configure": "configured",
                    "start": "observing",
                    "pause": "paused",
                    "retire": "retired",
                }[row.action]
                if row.action == "configure":
                    member.paper_instance_id = external_operation_id
            elif status == "failed":
                member.status = "paper_review_required"
            after: dict[str, Any] = {
                "effect_status": status,
                "member": _member_state(member),
            }
            if resolution is not None:
                after["reconciliation"] = resolution
            row.after_json = after
            row.outcome_link = f"dispatch_intent:{row.dispatch_intent_id}"
            return _action_dict(row)

    def _projection(self, mandate_id: str, *, replay: str = "") -> dict[str, Any]:
        with self.db.session() as session:
            row = _mandate(session, mandate_id)
            members = session.scalars(
                select(PaperIncubationMember)
                .where(PaperIncubationMember.mandate_id == mandate_id)
                .order_by(PaperIncubationMember.created_at, PaperIncubationMember.id)
            ).all()
            actions = session.scalars(
                select(PaperIncubationAction)
                .where(PaperIncubationAction.mandate_id == mandate_id)
                .order_by(PaperIncubationAction.created_at, PaperIncubationAction.id)
            ).all()
            return {
                "id": row.id,
                "schema_version": row.schema_version,
                "status": row.status,
                "kill_switch": row.kill_switch,
                "policy_hash": row.policy_hash,
                "content_hash": row.content_hash,
                "mandate": dict(row.mandate_json),
                "control": dict(row.control_json),
                "approved_by": row.approved_by,
                "valid_from": row.valid_from.isoformat(),
                "valid_until": row.valid_until.isoformat(),
                "fixed_denominator": len(dict(row.mandate_json)["candidate_ids"]),
                "members": [_member_dict(item) for item in members],
                "actions": [_action_dict(item) for item in actions],
                "mutation_boundary": {
                    "paper_only": True,
                    "testnet_writes": False,
                    "live_writes": False,
                    "real_order_writes": False,
                    "capital_transfer_writes": False,
                },
                "replay": replay,
            }


def _paper_capability(action: str) -> Any:
    definition = CapabilityDefinitionV1(
        capability_id=f"paper.incubation.{action}",
        title=f"Paper incubation {action}",
        description="Mandate-bound BitPro Paper lifecycle action with reconciliation.",
        source_owner="hypertrade-paper-incubation",
        handler_key=f"paper.incubation.{action}",
        scope="paper_write",
        side_effect="idempotent_write",
        approval="required",
        idempotency="required",
        timeout_seconds=60,
    )
    return reviewed_snapshot(
        definition,
        snapshot_id=f"paper-incubation-{action}-v1",
        actor="sprint130_contract",
        freshness_seconds=3600,
    )


def _mandate(session: Any, mandate_id: str) -> PaperResearchMandate:
    row = session.get(PaperResearchMandate, mandate_id)
    if row is None:
        raise KeyError(mandate_id)
    return cast(PaperResearchMandate, row)


def _member(session: Any, member_id: str) -> PaperIncubationMember:
    row = session.get(PaperIncubationMember, member_id)
    if row is None:
        raise KeyError(member_id)
    return cast(PaperIncubationMember, row)


def _action(session: Any, action_id: str) -> PaperIncubationAction:
    row = session.get(PaperIncubationAction, action_id)
    if row is None:
        raise KeyError(action_id)
    return cast(PaperIncubationAction, row)


def _member_state(row: PaperIncubationMember) -> dict[str, Any]:
    return {
        "status": row.status,
        "paper_instance_id": row.paper_instance_id,
        "bitpro_strategy_id": row.bitpro_strategy_id,
    }


def _member_dict(row: PaperIncubationMember) -> dict[str, Any]:
    return {
        "id": row.id,
        "mandate_id": row.mandate_id,
        "candidate_kind": row.candidate_kind,
        "candidate_id": row.candidate_id,
        "validation_id": row.validation_id,
        "manifest_id": row.manifest_id,
        "experiment_execution_id": row.experiment_execution_id,
        "bitpro_strategy_id": row.bitpro_strategy_id,
        "paper_instance_id": row.paper_instance_id,
        "status": row.status,
        "source_hash": row.source_hash,
        "policy_hash": row.policy_hash,
        "rejection_reasons": list(row.rejection_reasons_json),
        "observation": dict(row.observation_json),
        "updated_at": row.updated_at.isoformat(),
    }


def _action_dict(row: PaperIncubationAction, *, replay: str = "") -> dict[str, Any]:
    return {
        "id": row.id,
        "mandate_id": row.mandate_id,
        "member_id": row.member_id,
        "action": row.action,
        "status": row.status,
        "idempotency_key": row.idempotency_key,
        "dispatch_intent_id": row.dispatch_intent_id,
        "tool_call_id": row.tool_call_id,
        "external_operation_id": row.external_operation_id,
        "reason": row.reason,
        "before": dict(row.before_json),
        "after": dict(row.after_json),
        "evidence": dict(row.evidence_json),
        "outcome_link": row.outcome_link,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "replay": replay,
    }


def _dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tool_calls")
    return (
        [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    )


def _strategy_id_from_scope(scope: tuple[str, ...]) -> int:
    for value in scope:
        if value.startswith("paper:strategy:"):
            return int(value.rsplit(":", 1)[-1])
    raise ValueError("paper strategy scope is missing")


def _paper_target_id(instance_id: str, strategy_id: int) -> int:
    """Use a numeric Paper instance when BitPro exposes one; otherwise use strategy."""
    try:
        return int(instance_id)
    except (TypeError, ValueError):
        return strategy_id


def _bitpro_strategy_id(code_ref: str) -> str:
    prefix = "bitpro:strategy:"
    if not code_ref.startswith(prefix):
        return ""
    return code_ref[len(prefix) :].split("@", 1)[0]


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except Exception:
        return None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
