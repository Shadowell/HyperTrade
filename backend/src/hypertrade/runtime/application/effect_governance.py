"""Approval-gated write-ahead dispatch and external-effect reconciliation."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from hypertrade.runtime.domain.capabilities import CapabilitySnapshotV1
from hypertrade.runtime.domain.effects import (
    ApprovalGrantV1,
    ApprovalRequestV1,
    DispatchIntentV1,
    EffectPublicItemV1,
    EffectResolutionV1,
    IssuedApprovalV1,
    PersistentCircuitStateV1,
    PolicyDecisionV1,
    ToolCallV1,
    effect_hash,
)
from hypertrade.runtime.effect_ports import EffectAdapter, EffectGovernanceStore


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EffectReconciliationRequired(RuntimeError):
    pass


class EffectDispatchUnknown(RuntimeError):
    pass


class EffectNotCommitted(RuntimeError):
    pass


class InjectedEffectCrash(RuntimeError):
    """Test-only crash boundary; production callers never request one."""


class PersistentCircuitOpen(RuntimeError):
    pass


class EffectGovernanceService:
    def __init__(
        self,
        store: EffectGovernanceStore,
        *,
        enabled_write_environments: frozenset[str] = frozenset({"isolated"}),
        circuit_failure_threshold: int = 2,
        circuit_cooldown_seconds: int = 30,
    ) -> None:
        self.store = store
        self.enabled_write_environments = enabled_write_environments
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds

    async def evaluate(
        self,
        snapshot: CapabilitySnapshotV1,
        arguments: dict[str, Any],
        *,
        mission_id: str,
        subject: str,
        account: str,
        environment: Literal["isolated", "paper", "testnet", "production"],
        role: str,
        budget: dict[str, Any],
        policy_snapshot: dict[str, Any],
    ) -> PolicyDecisionV1:
        definition = snapshot.definition
        decision: Literal["allow", "ask", "deny"] = "allow"
        reason = "reviewed capability and policy allow dispatch"
        if not snapshot.executable():
            decision, reason = "deny", "capability snapshot is not reviewed, healthy and fresh"
        elif definition.approval == "blocked":
            decision, reason = "deny", "capability policy permanently blocks dispatch"
        elif (
            definition.side_effect != "none"
            and environment not in self.enabled_write_environments
        ):
            decision, reason = "deny", "write environment is not enabled by the runtime"
        elif definition.approval == "required":
            decision, reason = "ask", "exact parameter approval is required before dispatch"
        value = PolicyDecisionV1(
            decision_id=f"pdec_{uuid4().hex[:20]}",
            mission_id=mission_id,
            decision=decision,
            capability_id=definition.capability_id,
            capability_version=definition.version,
            contract_hash=snapshot.contract_hash,
            policy_hash=snapshot.policy_hash,
            arguments_hash=effect_hash(arguments),
            subject=subject,
            account=account,
            environment=environment,
            role=role,
            budget_hash=effect_hash(budget),
            policy_snapshot_hash=effect_hash(policy_snapshot),
            reason=reason,
        )
        await self.store.save_decision(value)
        await self.store.append_audit(
            value.decision_id,
            "policy.decided",
            actor="policy_engine",
            payload={"decision": value.decision, "reason": value.reason},
        )
        return value

    async def request_approval(
        self,
        decision_id: str,
        *,
        resource_scope: tuple[str, ...],
        maximum_amount: str,
        requested_by: str,
        ttl_seconds: int = 900,
    ) -> ApprovalRequestV1:
        decision = await self.store.decision(decision_id)
        if decision.decision != "ask":
            raise PermissionError("only an ask decision can create an approval request")
        now = _now()
        request = ApprovalRequestV1(
            request_id=f"apreq_{uuid4().hex[:20]}",
            decision_id=decision.decision_id,
            mission_id=decision.mission_id,
            capability_id=decision.capability_id,
            capability_version=decision.capability_version,
            contract_hash=decision.contract_hash,
            policy_hash=decision.policy_hash,
            arguments_hash=decision.arguments_hash,
            subject=decision.subject,
            account=decision.account,
            environment=decision.environment,
            role=decision.role,
            resource_scope=resource_scope,
            maximum_amount=maximum_amount,
            policy_snapshot_hash=decision.policy_snapshot_hash,
            requested_by=requested_by,
            requested_at=now,
            expires_at=now + timedelta(seconds=max(1, ttl_seconds)),
        )
        await self.store.create_approval(request)
        await self.store.append_audit(
            request.request_id,
            "approval.requested",
            actor=requested_by,
            payload={"capability_id": request.capability_id, "expires_at": request.expires_at},
        )
        return request

    async def grant_approval(
        self,
        request_id: str,
        *,
        actor: str,
        reason: str,
    ) -> IssuedApprovalV1:
        if actor.lower().split(":", 1)[0] in {"agent", "model", "runtime", "planner"}:
            raise PermissionError("an Agent or model cannot grant its own approval")
        request, existing = await self.store.approval(request_id)
        if existing is not None:
            raise ValueError("approval request already has a decision")
        if _aware(request.expires_at) <= _now():
            expired = request.model_copy(update={"status": "expired"})
            await self.store.set_approval(expired, None, expected={"requested", "pending"})
            raise PermissionError("approval request expired")
        token = secrets.token_urlsafe(32)
        grant = ApprovalGrantV1(
            grant_id=f"apg_{uuid4().hex[:20]}",
            request_id=request.request_id,
            decision_id=request.decision_id,
            capability_id=request.capability_id,
            capability_version=request.capability_version,
            contract_hash=request.contract_hash,
            policy_hash=request.policy_hash,
            arguments_hash=request.arguments_hash,
            subject=request.subject,
            account=request.account,
            environment=request.environment,
            role=request.role,
            resource_scope=request.resource_scope,
            maximum_amount=request.maximum_amount,
            policy_snapshot_hash=request.policy_snapshot_hash,
            token_hash=effect_hash(token),
            approved_by=actor,
            reason=reason,
            expires_at=request.expires_at,
        )
        approved = request.model_copy(update={"status": "approved"})
        await self.store.set_approval(
            approved, grant, expected={"requested", "pending"}
        )
        await self.store.append_audit(
            request.request_id,
            "approval.approved",
            actor=actor,
            payload={"grant_id": grant.grant_id, "expires_at": grant.expires_at},
        )
        return IssuedApprovalV1(grant=grant, consumption_token=token)

    async def deny_approval(self, request_id: str, *, actor: str, reason: str) -> None:
        request, grant = await self.store.approval(request_id)
        if grant is not None:
            raise ValueError("approved request must be revoked, not denied")
        denied = request.model_copy(update={"status": "denied"})
        await self.store.set_approval(denied, None, expected={"requested", "pending"})
        await self.store.append_audit(
            request_id, "approval.denied", actor=actor, payload={"reason": reason}
        )

    async def revoke_approval(self, request_id: str, *, actor: str, reason: str) -> None:
        request, grant = await self.store.approval(request_id)
        if grant is None:
            raise ValueError("approval grant not found")
        revoked_request = request.model_copy(update={"status": "revoked"})
        revoked_grant = grant.model_copy(update={"status": "revoked"})
        await self.store.set_approval(revoked_request, revoked_grant, expected={"approved"})
        await self.store.append_audit(
            request_id, "approval.revoked", actor=actor, payload={"reason": reason}
        )

    async def prepare_dispatch(
        self,
        decision_id: str,
        arguments: dict[str, Any],
        *,
        operation_scope: tuple[str, ...],
        idempotency_key: str,
        fencing_token: int,
        reconciliation_policy: Literal[
            "operation_id", "idempotency_key", "read_state", "manual_only"
        ],
        approval_request_id: str = "",
        approval_grant_id: str = "",
        approval_token: str = "",
    ) -> tuple[DispatchIntentV1, ToolCallV1]:
        decision = await self.store.decision(decision_id)
        if decision.decision == "deny":
            raise PermissionError("deny decisions cannot be overridden by approval")
        arguments_hash = effect_hash(arguments)
        if arguments_hash != decision.arguments_hash:
            raise PermissionError("arguments changed after policy decision")
        if decision.decision == "ask":
            if not approval_request_id or not approval_grant_id or not approval_token:
                raise PermissionError("dispatch requires an exact one-time approval")
            request, grant = await self.store.approval(approval_request_id)
            if grant is None:
                raise PermissionError("approval grant not found")
            if _aware(grant.expires_at) <= _now():
                await self.store.set_approval(
                    request.model_copy(update={"status": "expired"}),
                    grant.model_copy(update={"status": "expired"}),
                    expected={"approved"},
                )
                await self.store.append_audit(
                    request.request_id,
                    "approval.expired",
                    actor="effect_governance",
                    payload={"grant_id": grant.grant_id},
                )
                raise PermissionError("approval expired")
            binding = (
                request.decision_id == decision.decision_id
                and grant.decision_id == decision.decision_id
                and grant.arguments_hash == arguments_hash
                and grant.capability_id == decision.capability_id
                and grant.capability_version == decision.capability_version
                and grant.contract_hash == decision.contract_hash
                and grant.policy_hash == decision.policy_hash
                and grant.subject == decision.subject
                and grant.account == decision.account
                and grant.environment == decision.environment
                and grant.role == decision.role
                and grant.policy_snapshot_hash == decision.policy_snapshot_hash
                and set(operation_scope) <= set(grant.resource_scope)
            )
            if not binding:
                raise PermissionError("approval does not match dispatch parameters or scope")
        tool_call_id = f"tcall_{uuid4().hex[:20]}"
        basis = {
            "mission_id": decision.mission_id,
            "decision_id": decision.decision_id,
            "approval_grant_id": approval_grant_id,
            "capability_id": decision.capability_id,
            "capability_version": decision.capability_version,
            "contract_hash": decision.contract_hash,
            "policy_hash": decision.policy_hash,
            "arguments_hash": arguments_hash,
            "operation_scope": operation_scope,
            "idempotency_key": idempotency_key,
            "fencing_token": fencing_token,
            "reconciliation_policy": reconciliation_policy,
        }
        intent = DispatchIntentV1(
            intent_id=f"dint_{uuid4().hex[:20]}",
            mission_id=decision.mission_id,
            tool_call_id=tool_call_id,
            decision_id=decision.decision_id,
            approval_grant_id=approval_grant_id,
            capability_id=decision.capability_id,
            capability_version=decision.capability_version,
            contract_hash=decision.contract_hash,
            policy_hash=decision.policy_hash,
            arguments_hash=arguments_hash,
            operation_scope=operation_scope,
            idempotency_key=idempotency_key,
            payload_hash=effect_hash(basis),
            fencing_token=fencing_token,
            reconciliation_policy=reconciliation_policy,
        )
        call = ToolCallV1(
            tool_call_id=tool_call_id,
            intent_id=intent.intent_id,
            mission_id=intent.mission_id,
            capability_id=intent.capability_id,
        )
        try:
            stored = await self.store.create_dispatch(
                intent,
                call,
                approval_request_id=approval_request_id,
                approval_token_hash=effect_hash(approval_token) if approval_token else "",
            )
        except (PermissionError, ValueError) as exc:
            if approval_request_id:
                await self.store.append_audit(
                    approval_request_id,
                    "approval.consumption_rejected",
                    actor="effect_governance",
                    payload={"reason": str(exc)[:500]},
                )
            raise
        created = stored[0].intent_id == intent.intent_id
        if approval_request_id and created:
            await self.store.append_audit(
                approval_request_id,
                "approval.consumed",
                actor="effect_governance",
                payload={"intent_id": stored[0].intent_id},
            )
        if created:
            await self.store.append_audit(
                stored[0].intent_id,
                "dispatch.prepared",
                actor="effect_governance",
                payload={
                    "tool_call_id": stored[1].tool_call_id,
                    "capability_id": stored[0].capability_id,
                },
            )
        return stored

    async def execute(
        self,
        intent_id: str,
        arguments: dict[str, Any],
        adapter: EffectAdapter,
        *,
        crash_after: Literal["", "dispatch_persisted", "adapter_return", "ack"] = "",
    ) -> ToolCallV1:
        intent, call = await self.store.dispatch(intent_id)
        if effect_hash(arguments) != intent.arguments_hash:
            raise PermissionError("dispatch arguments do not match write-ahead intent")
        if call.status in {"succeeded", "failed", "reconciled"}:
            return call
        if call.status == "acknowledged":
            return await self._transition(
                intent, call, status="succeeded", intent_status="terminal", actor="recovery"
            )
        if call.status != "prepared":
            raise EffectReconciliationRequired(
                "a dispatched write cannot be retried before reconciliation"
            )
        await self.circuit_preflight(intent.capability_id)
        call = await self._transition(
            intent, call, status="dispatched", intent_status="dispatched", actor="dispatcher"
        )
        intent, call = await self.store.dispatch(intent_id)
        if crash_after == "dispatch_persisted":
            raise InjectedEffectCrash("crash after persisted dispatch and before adapter call")
        try:
            ack = await adapter.dispatch(intent, arguments)
        except TimeoutError:
            timed_out = await self._transition(
                intent,
                call,
                status="timed_out",
                intent_status="effect_unknown",
                actor="dispatcher",
                error_category="timeout",
            )
            await self.circuit_failure(intent.capability_id)
            return await self._transition(
                intent,
                timed_out,
                status="effect_unknown",
                intent_status="effect_unknown",
                actor="dispatcher",
                error_category="timeout",
            )
        except EffectNotCommitted:
            return await self._transition(
                intent,
                call,
                status="failed",
                intent_status="terminal",
                actor="dispatcher",
                error_category="not_committed",
            )
        except Exception as exc:
            await self.circuit_failure(intent.capability_id)
            return await self._transition(
                intent,
                call,
                status="effect_unknown",
                intent_status="effect_unknown",
                actor="dispatcher",
                error_category=type(exc).__name__[:96],
            )
        if crash_after == "adapter_return":
            raise InjectedEffectCrash("crash after adapter return and before ack persistence")
        call = await self._transition(
            intent,
            call,
            status="acknowledged",
            intent_status="acknowledged",
            actor="dispatcher",
            external_operation_id=ack.external_operation_id,
            result_hash=effect_hash(ack.result),
        )
        if crash_after == "ack":
            raise InjectedEffectCrash("crash after acknowledgement persistence")
        await self.circuit_success(intent.capability_id)
        return await self._transition(
            intent,
            call,
            status="succeeded",
            intent_status="terminal",
            actor="dispatcher",
        )

    async def reconcile(
        self,
        intent_id: str,
        adapter: EffectAdapter,
        *,
        actor: str = "effect_reconciler",
    ) -> tuple[ToolCallV1, EffectResolutionV1]:
        intent, call = await self.store.dispatch(intent_id)
        if call.status not in {"dispatched", "timed_out", "effect_unknown"}:
            raise ValueError("tool call does not require reconciliation")
        resolution = (
            EffectResolutionV1(
                outcome="unknown",
                reason="adapter requires manual reconciliation",
            )
            if intent.reconciliation_policy == "manual_only"
            else await adapter.reconcile(intent)
        )
        if resolution.outcome == "unknown":
            if call.status != "effect_unknown":
                call = await self._transition(
                    intent,
                    call,
                    status="effect_unknown",
                    intent_status="effect_unknown",
                    actor=actor,
                    error_category="reconciliation_unknown",
                )
            await self.store.append_audit(
                intent.intent_id,
                "effect.reconciliation_unknown",
                actor=actor,
                payload={"reason": resolution.reason},
            )
            return call, resolution
        call = await self._transition(
            intent,
            call,
            status="reconciled",
            intent_status="reconciled",
            actor=actor,
            external_operation_id=resolution.external_operation_id,
            result_hash=effect_hash(resolution.result),
            reconciliation_outcome=resolution.outcome,
        )
        await self.circuit_success(intent.capability_id)
        return call, resolution

    async def recover_orphan(
        self,
        intent_id: str,
        adapter: EffectAdapter,
    ) -> tuple[ToolCallV1, EffectResolutionV1 | None]:
        """Recover without redispatching a write whose boundary is uncertain."""

        intent, call = await self.store.dispatch(intent_id)
        if call.status == "acknowledged":
            completed = await self._transition(
                intent,
                call,
                status="succeeded",
                intent_status="terminal",
                actor="orphan_recovery",
            )
            return completed, None
        if call.status in {"dispatched", "timed_out", "effect_unknown"}:
            return await self.reconcile(intent_id, adapter, actor="orphan_recovery")
        return call, None

    async def circuit_preflight(self, capability_id: str) -> PersistentCircuitStateV1:
        state = await self.store.circuit(capability_id)
        now = _now()
        override_active = (
            state.override_expires_at is not None
            and _aware(state.override_expires_at) > now
        )
        if state.state == "open" and state.retry_after and _aware(state.retry_after) <= now:
            updated = state.model_copy(
                update={"state": "half_open", "version": state.version + 1, "updated_at": now}
            )
            await self.store.set_circuit(updated, expected_version=state.version)
            await self.store.append_audit(
                capability_id,
                "circuit.half_open",
                actor="effect_governance",
                payload={"previous_version": state.version},
            )
            return updated
        if state.state == "open" and not override_active:
            raise PersistentCircuitOpen(f"persistent circuit open: {capability_id}")
        return state

    async def circuit_failure(self, capability_id: str) -> PersistentCircuitStateV1:
        for _ in range(3):
            current = await self.store.circuit(capability_id)
            failures = current.consecutive_failures + 1
            now = _now()
            updates: dict[str, Any] = {
                "consecutive_failures": failures,
                "version": current.version + 1,
                "updated_at": now,
            }
            if failures >= self.circuit_failure_threshold:
                updates.update(
                    state="open",
                    opened_at=now,
                    retry_after=now + timedelta(seconds=self.circuit_cooldown_seconds),
                )
            updated = current.model_copy(update=updates)
            try:
                await self.store.set_circuit(updated, expected_version=current.version)
                await self.store.append_audit(
                    capability_id,
                    "circuit.failure",
                    actor="effect_governance",
                    payload={
                        "state": updated.state,
                        "consecutive_failures": updated.consecutive_failures,
                    },
                )
                return updated
            except ValueError:
                continue
        raise RuntimeError("persistent circuit update conflict")

    async def circuit_success(self, capability_id: str) -> PersistentCircuitStateV1:
        current = await self.store.circuit(capability_id)
        updated = PersistentCircuitStateV1(
            capability_id=capability_id,
            version=current.version + 1,
        )
        await self.store.set_circuit(updated, expected_version=current.version)
        await self.store.append_audit(
            capability_id,
            "circuit.closed",
            actor="effect_governance",
            payload={"previous_state": current.state},
        )
        return updated

    async def override_circuit(
        self,
        capability_id: str,
        *,
        actor: str,
        reason: str,
        ttl_seconds: int,
    ) -> PersistentCircuitStateV1:
        if not actor.strip() or len(reason.strip()) < 3:
            raise ValueError("circuit override requires actor and reason")
        if ttl_seconds < 1 or ttl_seconds > 3_600:
            raise ValueError("circuit override ttl must be between 1 and 3600 seconds")
        current = await self.store.circuit(capability_id)
        now = _now()
        updated = current.model_copy(
            update={
                "version": current.version + 1,
                "override_actor": actor.strip(),
                "override_reason": reason.strip(),
                "override_expires_at": now + timedelta(seconds=ttl_seconds),
                "updated_at": now,
            }
        )
        await self.store.set_circuit(updated, expected_version=current.version)
        await self.store.append_audit(
            capability_id,
            "circuit.overridden",
            actor=actor,
            payload={"reason": reason, "expires_at": updated.override_expires_at},
        )
        return updated

    async def _transition(
        self,
        intent: DispatchIntentV1,
        call: ToolCallV1,
        *,
        status: str,
        intent_status: str,
        actor: str,
        external_operation_id: str = "",
        result_hash: str = "",
        error_category: str = "",
        reconciliation_outcome: str = "",
    ) -> ToolCallV1:
        allowed = {
            "prepared": {"dispatched"},
            "dispatched": {
                "acknowledged",
                "failed",
                "timed_out",
                "effect_unknown",
                "reconciled",
            },
            "timed_out": {"effect_unknown", "reconciled"},
            "effect_unknown": {"reconciled"},
            "acknowledged": {"succeeded"},
        }
        if status not in allowed.get(call.status, set()):
            raise ValueError(f"invalid ToolCall transition: {call.status} -> {status}")
        now = _now()
        next_call = call.model_copy(
            update={
                "status": status,
                "external_operation_id": external_operation_id or call.external_operation_id,
                "result_hash": result_hash or call.result_hash,
                "error_category": error_category or call.error_category,
                "reconciliation_outcome": (
                    reconciliation_outcome or call.reconciliation_outcome
                ),
                "updated_at": now,
            }
        )
        next_intent = intent.model_copy(
            update={
                "status": intent_status,
                "external_operation_id": (
                    external_operation_id or intent.external_operation_id
                ),
                "updated_at": now,
            }
        )
        await self.store.set_dispatch(
            next_intent, next_call, expected_call_status={call.status}
        )
        await self.store.append_audit(
            intent.intent_id,
            f"tool_call.{status}",
            actor=actor,
            payload={"tool_call_id": call.tool_call_id, "status": status},
        )
        return next_call


def public_effect_item(
    *,
    mission_id: str,
    approval: ApprovalRequestV1 | None = None,
    call: ToolCallV1 | None = None,
) -> EffectPublicItemV1:
    if approval is not None:
        if approval.status in {"requested", "pending", "approved"}:
            return EffectPublicItemV1(
                mission_id=mission_id,
                status="waiting_approval",
                message="This action is waiting for a bounded operator approval.",
                requires_operator_action=True,
                approval_request_id=approval.request_id,
            )
        return EffectPublicItemV1(
            mission_id=mission_id,
            status="denied",
            message=f"The requested action is {approval.status}.",
            requires_operator_action=False,
            approval_request_id=approval.request_id,
        )
    if call is None:
        raise ValueError("approval or tool call is required")
    if call.status in {"dispatched", "timed_out", "effect_unknown"}:
        return EffectPublicItemV1(
            mission_id=mission_id,
            status="effect_unknown",
            message="The external effect is unknown and requires reconciliation.",
            requires_operator_action=True,
            tool_call_id=call.tool_call_id,
        )
    return EffectPublicItemV1(
        mission_id=mission_id,
        status="resolved",
        message="The external effect has a reconciled terminal state.",
        requires_operator_action=False,
        tool_call_id=call.tool_call_id,
    )
