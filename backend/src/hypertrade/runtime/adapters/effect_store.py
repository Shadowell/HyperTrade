"""Persistent stores for approval, dispatch and reconciliation state."""

from __future__ import annotations

import asyncio
import hmac
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hypertrade.db import (
    AgentApproval,
    AgentDispatchIntent,
    AgentEffectAuditEvent,
    AgentEffectCircuit,
    AgentPolicyDecision,
    AgentToolCall,
)
from hypertrade.runtime.adapters.sql_store import async_database_url
from hypertrade.runtime.domain.effects import (
    ApprovalGrantV1,
    ApprovalRequestV1,
    DispatchIntentV1,
    EffectAuditEventV1,
    PersistentCircuitStateV1,
    PolicyDecisionV1,
    ToolCallV1,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _json_payload(value: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(value, default=str)))


def _grant_payload(grant: ApprovalGrantV1) -> dict[str, Any]:
    # token_hash is excluded from public model dumps but required for durable
    # one-time consumption checks.
    return grant.model_dump(mode="json") | {"token_hash": grant.token_hash}


class InMemoryEffectGovernanceStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._decisions: dict[str, PolicyDecisionV1] = {}
        self._approvals: dict[str, tuple[ApprovalRequestV1, ApprovalGrantV1 | None]] = {}
        self._intents: dict[str, DispatchIntentV1] = {}
        self._calls: dict[str, ToolCallV1] = {}
        self._idempotency: dict[str, str] = {}
        self._mission_fencing: dict[str, int] = {}
        self._events: dict[str, list[EffectAuditEventV1]] = defaultdict(list)
        self._circuits: dict[str, PersistentCircuitStateV1] = {}

    async def save_decision(self, decision: PolicyDecisionV1) -> None:
        async with self._lock:
            current = self._decisions.get(decision.decision_id)
            if current is not None and current != decision:
                raise ValueError("policy decision id is content-bound")
            self._decisions[decision.decision_id] = decision

    async def decision(self, decision_id: str) -> PolicyDecisionV1:
        try:
            return self._decisions[decision_id]
        except KeyError as exc:
            raise KeyError("policy decision not found") from exc

    async def create_approval(self, request: ApprovalRequestV1) -> None:
        async with self._lock:
            current = self._approvals.get(request.request_id)
            if current is not None and current[0] != request:
                raise ValueError("approval request id is content-bound")
            self._approvals[request.request_id] = (request, None)

    async def approval(
        self, request_id: str
    ) -> tuple[ApprovalRequestV1, ApprovalGrantV1 | None]:
        try:
            return self._approvals[request_id]
        except KeyError as exc:
            raise KeyError("approval request not found") from exc

    async def set_approval(
        self,
        request: ApprovalRequestV1,
        grant: ApprovalGrantV1 | None,
        *,
        expected: set[str],
    ) -> None:
        async with self._lock:
            current, _ = await self.approval(request.request_id)
            if current.status not in expected:
                raise ValueError(
                    f"approval status is {current.status}, expected {sorted(expected)}"
                )
            self._approvals[request.request_id] = (request, grant)

    async def create_dispatch(
        self,
        intent: DispatchIntentV1,
        call: ToolCallV1,
        *,
        approval_request_id: str = "",
        approval_token_hash: str = "",
    ) -> tuple[DispatchIntentV1, ToolCallV1]:
        async with self._lock:
            existing_id = self._idempotency.get(intent.idempotency_key)
            if existing_id:
                existing = self._intents[existing_id]
                if existing.payload_hash != intent.payload_hash:
                    raise ValueError("idempotency key is bound to different dispatch payload")
                return existing, self._calls[existing.tool_call_id]
            current_fencing = self._mission_fencing.get(intent.mission_id, 0)
            if intent.fencing_token < current_fencing:
                raise PermissionError("stale dispatch fencing token")
            if approval_request_id:
                request, grant = await self.approval(approval_request_id)
                if grant is None or request.status != "approved" or grant.status != "approved":
                    raise PermissionError("approval is not consumable")
                if _aware(grant.expires_at) <= _now():
                    self._approvals[request.request_id] = (
                        request.model_copy(update={"status": "expired"}),
                        grant.model_copy(update={"status": "expired"}),
                    )
                    raise PermissionError("approval expired")
                if not hmac.compare_digest(grant.token_hash, approval_token_hash):
                    raise PermissionError("approval consumption token mismatch")
                if grant.grant_id != intent.approval_grant_id:
                    raise PermissionError("approval grant does not match dispatch")
                consumed_at = _now()
                self._approvals[request.request_id] = (
                    request.model_copy(update={"status": "consumed"}),
                    grant.model_copy(
                        update={
                            "status": "consumed",
                            "consumed_at": consumed_at,
                            "consumed_intent_id": intent.intent_id,
                        }
                    ),
                )
            self._intents[intent.intent_id] = intent
            self._calls[call.tool_call_id] = call
            self._idempotency[intent.idempotency_key] = intent.intent_id
            self._mission_fencing[intent.mission_id] = max(
                current_fencing, intent.fencing_token
            )
            return intent, call

    async def dispatch(self, intent_id: str) -> tuple[DispatchIntentV1, ToolCallV1]:
        try:
            intent = self._intents[intent_id]
            return intent, self._calls[intent.tool_call_id]
        except KeyError as exc:
            raise KeyError("dispatch intent not found") from exc

    async def set_dispatch(
        self,
        intent: DispatchIntentV1,
        call: ToolCallV1,
        *,
        expected_call_status: set[str],
    ) -> None:
        async with self._lock:
            current_intent, current_call = await self.dispatch(intent.intent_id)
            if current_call.status not in expected_call_status:
                raise ValueError(
                    f"tool call status is {current_call.status}, expected "
                    f"{sorted(expected_call_status)}"
                )
            if current_intent.tool_call_id != call.tool_call_id:
                raise ValueError("tool call does not belong to dispatch intent")
            self._intents[intent.intent_id] = intent
            self._calls[call.tool_call_id] = call

    async def append_audit(
        self,
        aggregate_id: str,
        event_type: str,
        *,
        actor: str,
        payload: dict[str, Any],
    ) -> EffectAuditEventV1:
        async with self._lock:
            rows = self._events[aggregate_id]
            event = EffectAuditEventV1(
                event_id=f"eevt_{uuid4().hex[:20]}",
                aggregate_id=aggregate_id,
                sequence=len(rows) + 1,
                event_type=event_type,
                actor=actor,
                payload=_json_payload(payload),
            )
            rows.append(event)
            return event

    async def audit_events(self, aggregate_id: str) -> Sequence[EffectAuditEventV1]:
        return tuple(self._events.get(aggregate_id, ()))

    async def circuit(self, capability_id: str) -> PersistentCircuitStateV1:
        return self._circuits.get(
            capability_id, PersistentCircuitStateV1(capability_id=capability_id)
        )

    async def set_circuit(
        self,
        state: PersistentCircuitStateV1,
        *,
        expected_version: int,
    ) -> None:
        async with self._lock:
            current = await self.circuit(state.capability_id)
            if current.version != expected_version:
                raise ValueError("circuit version conflict")
            self._circuits[state.capability_id] = state


class SqlEffectGovernanceStore:
    """SQL outbox store; state transitions commit before adapters are invoked."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(async_database_url(database_url))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def save_decision(self, decision: PolicyDecisionV1) -> None:
        async with self.sessions.begin() as session:
            current = await session.get(AgentPolicyDecision, decision.decision_id)
            payload = decision.model_dump(mode="json")
            if current is not None:
                if current.payload_json != payload:
                    raise ValueError("policy decision id is content-bound")
                return
            session.add(
                AgentPolicyDecision(
                    id=decision.decision_id,
                    mission_id=decision.mission_id,
                    decision=decision.decision,
                    payload_json=payload,
                    created_at=decision.created_at,
                )
            )

    async def decision(self, decision_id: str) -> PolicyDecisionV1:
        async with self.sessions() as session:
            row = await session.get(AgentPolicyDecision, decision_id)
            if row is None:
                raise KeyError("policy decision not found")
            return PolicyDecisionV1.model_validate(row.payload_json)

    async def create_approval(self, request: ApprovalRequestV1) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(AgentApproval, request.request_id)
            payload = request.model_dump(mode="json")
            if row is not None:
                if row.request_json != payload:
                    raise ValueError("approval request id is content-bound")
                return
            session.add(
                AgentApproval(
                    id=request.request_id,
                    decision_id=request.decision_id,
                    mission_id=request.mission_id,
                    status=request.status,
                    request_json=payload,
                    grant_json={},
                    token_hash="",
                    expires_at=request.expires_at,
                    updated_at=request.requested_at,
                )
            )

    async def approval(
        self, request_id: str
    ) -> tuple[ApprovalRequestV1, ApprovalGrantV1 | None]:
        async with self.sessions() as session:
            row = await session.get(AgentApproval, request_id)
            if row is None:
                raise KeyError("approval request not found")
            grant = (
                ApprovalGrantV1.model_validate(row.grant_json)
                if row.grant_json
                else None
            )
            return ApprovalRequestV1.model_validate(row.request_json), grant

    async def set_approval(
        self,
        request: ApprovalRequestV1,
        grant: ApprovalGrantV1 | None,
        *,
        expected: set[str],
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(AgentApproval)
                .where(AgentApproval.id == request.request_id)
                .with_for_update()
            )
            if row is None:
                raise KeyError("approval request not found")
            if row.status not in expected:
                raise ValueError(f"approval status is {row.status}, expected {sorted(expected)}")
            row.status = request.status
            row.request_json = request.model_dump(mode="json")
            row.grant_json = _grant_payload(grant) if grant is not None else {}
            row.token_hash = grant.token_hash if grant is not None else ""
            row.updated_at = _now()

    async def create_dispatch(
        self,
        intent: DispatchIntentV1,
        call: ToolCallV1,
        *,
        approval_request_id: str = "",
        approval_token_hash: str = "",
    ) -> tuple[DispatchIntentV1, ToolCallV1]:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(AgentDispatchIntent)
                .where(AgentDispatchIntent.idempotency_key == intent.idempotency_key)
                .with_for_update()
            )
            if existing is not None:
                if existing.payload_hash != intent.payload_hash:
                    raise ValueError("idempotency key is bound to different dispatch payload")
                call_row = await session.scalar(
                    select(AgentToolCall).where(AgentToolCall.intent_id == existing.id)
                )
                assert call_row is not None
                return (
                    DispatchIntentV1.model_validate(existing.intent_json),
                    ToolCallV1.model_validate(call_row.call_json),
                )
            current_fencing = await session.scalar(
                select(func.max(AgentDispatchIntent.fencing_token)).where(
                    AgentDispatchIntent.mission_id == intent.mission_id
                )
            )
            if intent.fencing_token < int(current_fencing or 0):
                raise PermissionError("stale dispatch fencing token")
            if approval_request_id:
                approval = await session.scalar(
                    select(AgentApproval)
                    .where(AgentApproval.id == approval_request_id)
                    .with_for_update()
                )
                if approval is None or not approval.grant_json:
                    raise PermissionError("approval grant not found")
                request = ApprovalRequestV1.model_validate(approval.request_json)
                grant = ApprovalGrantV1.model_validate(approval.grant_json)
                if approval.status != "approved" or grant.status != "approved":
                    raise PermissionError("approval is not consumable")
                if _aware(grant.expires_at) <= _now():
                    request = request.model_copy(update={"status": "expired"})
                    grant = grant.model_copy(update={"status": "expired"})
                    approval.status = "expired"
                    approval.request_json = request.model_dump(mode="json")
                    approval.grant_json = _grant_payload(grant)
                    raise PermissionError("approval expired")
                if not hmac.compare_digest(approval.token_hash, approval_token_hash):
                    raise PermissionError("approval consumption token mismatch")
                if grant.grant_id != intent.approval_grant_id:
                    raise PermissionError("approval grant does not match dispatch")
                now = _now()
                request = request.model_copy(update={"status": "consumed"})
                grant = grant.model_copy(
                    update={
                        "status": "consumed",
                        "consumed_at": now,
                        "consumed_intent_id": intent.intent_id,
                    }
                )
                approval.status = "consumed"
                approval.request_json = request.model_dump(mode="json")
                approval.grant_json = _grant_payload(grant)
                approval.updated_at = now
            session.add(
                AgentDispatchIntent(
                    id=intent.intent_id,
                    mission_id=intent.mission_id,
                    tool_call_id=intent.tool_call_id,
                    idempotency_key=intent.idempotency_key,
                    payload_hash=intent.payload_hash,
                    fencing_token=intent.fencing_token,
                    status=intent.status,
                    intent_json=intent.model_dump(mode="json"),
                    created_at=intent.created_at,
                    updated_at=intent.updated_at,
                )
            )
            session.add(
                AgentToolCall(
                    id=call.tool_call_id,
                    intent_id=call.intent_id,
                    mission_id=call.mission_id,
                    capability_id=call.capability_id,
                    status=call.status,
                    call_json=call.model_dump(mode="json"),
                    created_at=call.created_at,
                    updated_at=call.updated_at,
                )
            )
            return intent, call

    async def dispatch(self, intent_id: str) -> tuple[DispatchIntentV1, ToolCallV1]:
        async with self.sessions() as session:
            intent = await session.get(AgentDispatchIntent, intent_id)
            if intent is None:
                raise KeyError("dispatch intent not found")
            call = await session.scalar(
                select(AgentToolCall).where(AgentToolCall.intent_id == intent_id)
            )
            if call is None:
                raise KeyError("tool call not found")
            return (
                DispatchIntentV1.model_validate(intent.intent_json),
                ToolCallV1.model_validate(call.call_json),
            )

    async def set_dispatch(
        self,
        intent: DispatchIntentV1,
        call: ToolCallV1,
        *,
        expected_call_status: set[str],
    ) -> None:
        async with self.sessions.begin() as session:
            call_row = await session.scalar(
                select(AgentToolCall)
                .where(AgentToolCall.id == call.tool_call_id)
                .with_for_update()
            )
            intent_row = await session.scalar(
                select(AgentDispatchIntent)
                .where(AgentDispatchIntent.id == intent.intent_id)
                .with_for_update()
            )
            if call_row is None or intent_row is None:
                raise KeyError("dispatch state not found")
            if call_row.status not in expected_call_status:
                raise ValueError(
                    f"tool call status is {call_row.status}, expected "
                    f"{sorted(expected_call_status)}"
                )
            call_row.status = call.status
            call_row.call_json = call.model_dump(mode="json")
            call_row.updated_at = call.updated_at
            intent_row.status = intent.status
            intent_row.intent_json = intent.model_dump(mode="json")
            intent_row.updated_at = intent.updated_at

    async def append_audit(
        self,
        aggregate_id: str,
        event_type: str,
        *,
        actor: str,
        payload: dict[str, Any],
    ) -> EffectAuditEventV1:
        async with self.sessions.begin() as session:
            latest = await session.scalar(
                select(func.max(AgentEffectAuditEvent.sequence)).where(
                    AgentEffectAuditEvent.aggregate_id == aggregate_id
                )
            )
            event = EffectAuditEventV1(
                event_id=f"eevt_{uuid4().hex[:20]}",
                aggregate_id=aggregate_id,
                sequence=int(latest or 0) + 1,
                event_type=event_type,
                actor=actor,
                payload=_json_payload(payload),
            )
            session.add(
                AgentEffectAuditEvent(
                    id=event.event_id,
                    aggregate_id=aggregate_id,
                    sequence=event.sequence,
                    event_type=event.event_type,
                    actor=event.actor,
                    payload_json=event.payload,
                    created_at=event.created_at,
                )
            )
            return event

    async def audit_events(self, aggregate_id: str) -> Sequence[EffectAuditEventV1]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(AgentEffectAuditEvent)
                    .where(AgentEffectAuditEvent.aggregate_id == aggregate_id)
                    .order_by(AgentEffectAuditEvent.sequence)
                )
            ).all()
            return tuple(
                EffectAuditEventV1(
                    event_id=row.id,
                    aggregate_id=row.aggregate_id,
                    sequence=row.sequence,
                    event_type=row.event_type,
                    actor=row.actor,
                    payload=row.payload_json,
                    created_at=_aware(row.created_at),
                )
                for row in rows
            )

    async def circuit(self, capability_id: str) -> PersistentCircuitStateV1:
        async with self.sessions() as session:
            row = await session.get(AgentEffectCircuit, capability_id)
            if row is None:
                return PersistentCircuitStateV1(capability_id=capability_id)
            return PersistentCircuitStateV1.model_validate(row.state_json)

    async def set_circuit(
        self,
        state: PersistentCircuitStateV1,
        *,
        expected_version: int,
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(AgentEffectCircuit)
                .where(AgentEffectCircuit.capability_id == state.capability_id)
                .with_for_update()
            )
            if row is None:
                if expected_version != 1:
                    raise ValueError("circuit version conflict")
                session.add(
                    AgentEffectCircuit(
                        capability_id=state.capability_id,
                        version=state.version,
                        state_json=state.model_dump(mode="json"),
                        updated_at=state.updated_at,
                    )
                )
                return
            if row.version != expected_version:
                raise ValueError("circuit version conflict")
            row.version = state.version
            row.state_json = state.model_dump(mode="json")
            row.updated_at = state.updated_at
