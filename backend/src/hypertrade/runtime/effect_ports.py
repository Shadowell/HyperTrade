from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from hypertrade.runtime.domain.effects import (
    ApprovalGrantV1,
    ApprovalRequestV1,
    DispatchIntentV1,
    EffectAckV1,
    EffectAuditEventV1,
    EffectResolutionV1,
    PersistentCircuitStateV1,
    PolicyDecisionV1,
    ToolCallV1,
)


class EffectGovernanceStore(Protocol):
    async def save_decision(self, decision: PolicyDecisionV1) -> None: ...

    async def decision(self, decision_id: str) -> PolicyDecisionV1: ...

    async def create_approval(self, request: ApprovalRequestV1) -> None: ...

    async def approval(
        self, request_id: str
    ) -> tuple[ApprovalRequestV1, ApprovalGrantV1 | None]: ...

    async def set_approval(
        self,
        request: ApprovalRequestV1,
        grant: ApprovalGrantV1 | None,
        *,
        expected: set[str],
    ) -> None: ...

    async def create_dispatch(
        self,
        intent: DispatchIntentV1,
        call: ToolCallV1,
        *,
        approval_request_id: str = "",
        approval_token_hash: str = "",
    ) -> tuple[DispatchIntentV1, ToolCallV1]: ...

    async def dispatch(self, intent_id: str) -> tuple[DispatchIntentV1, ToolCallV1]: ...

    async def set_dispatch(
        self,
        intent: DispatchIntentV1,
        call: ToolCallV1,
        *,
        expected_call_status: set[str],
    ) -> None: ...

    async def append_audit(
        self,
        aggregate_id: str,
        event_type: str,
        *,
        actor: str,
        payload: dict[str, Any],
    ) -> EffectAuditEventV1: ...

    async def audit_events(self, aggregate_id: str) -> Sequence[EffectAuditEventV1]: ...

    async def circuit(self, capability_id: str) -> PersistentCircuitStateV1: ...

    async def set_circuit(
        self,
        state: PersistentCircuitStateV1,
        *,
        expected_version: int,
    ) -> None: ...


class EffectAdapter(Protocol):
    async def dispatch(
        self,
        intent: DispatchIntentV1,
        arguments: dict[str, Any],
    ) -> EffectAckV1: ...

    async def reconcile(self, intent: DispatchIntentV1) -> EffectResolutionV1: ...
