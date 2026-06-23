"""Deterministic governance checks for Agent tool execution.

The planner can ask for any registered tool, but this policy service is the
trusted boundary that decides whether the request is allowed, approval-gated,
or denied before the executor reaches databases, BitPro, or exchange paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hypertrade.tools.registry import ToolPolicy, ToolRegistry


@dataclass(frozen=True)
class GovernanceDecision:
    requested_tool_name: str
    registry_tool_name: str
    policy: ToolPolicy
    allowed: bool
    status: str
    missing_fields: list[str]
    denial_reason: str = ""

    @property
    def requires_approval(self) -> bool:
        return self.policy.approval == "required"

    @property
    def requires_idempotency(self) -> bool:
        return self.policy.idempotency == "required"

    def as_trace_payload(self) -> dict[str, Any]:
        return {
            "requested_tool_name": self.requested_tool_name,
            "registry_tool_name": self.registry_tool_name,
            "status": self.status,
            "policy_outcome": self.status,
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "requires_idempotency": self.requires_idempotency,
            "missing_fields": list(self.missing_fields),
            "denial_reason": self.denial_reason,
            "policy": self.policy.as_dict(),
        }


class RiskGovernancePolicy:
    """Evaluate Agent tool requests against static tool policy metadata."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry.default()

    def evaluate(self, tool_name: str, args: dict[str, Any] | None = None) -> GovernanceDecision:
        request_args = args or {}
        try:
            tool = self.registry.get_for_runtime_name(tool_name)
        except KeyError:
            blocked_policy = ToolPolicy(
                scope="live_write",
                approval="blocked",
                idempotency="required",
                source_of_truth="unknown",
                timeout_class="quick",
                safe_sample_limit=0,
                failure_behavior="return_structured_error",
            )
            return GovernanceDecision(
                requested_tool_name=tool_name,
                registry_tool_name=tool_name,
                policy=blocked_policy,
                allowed=False,
                status="denied",
                missing_fields=[],
                denial_reason="unknown tool is not registered for Agent execution",
            )

        missing_fields = self._missing_required_fields(tool.policy, request_args)
        if tool.policy.approval == "blocked":
            return GovernanceDecision(
                requested_tool_name=tool_name,
                registry_tool_name=tool.name,
                policy=tool.policy,
                allowed=False,
                status="denied",
                missing_fields=missing_fields,
                denial_reason="tool scope is blocked by governance policy",
            )
        if missing_fields:
            joined = ", ".join(missing_fields)
            return GovernanceDecision(
                requested_tool_name=tool_name,
                registry_tool_name=tool.name,
                policy=tool.policy,
                allowed=False,
                status="denied",
                missing_fields=missing_fields,
                denial_reason=f"missing required field: {joined}",
            )

        status = "approval_required" if tool.policy.approval == "required" else "allowed"
        return GovernanceDecision(
            requested_tool_name=tool_name,
            registry_tool_name=tool.name,
            policy=tool.policy,
            allowed=True,
            status=status,
            missing_fields=[],
        )

    @staticmethod
    def _missing_required_fields(policy: ToolPolicy, args: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        if policy.idempotency == "required" and not _has_text(args.get("idempotency_key")):
            missing.append("idempotency_key")
        if policy.scope == "live_write" and not _has_text(args.get("operator_confirmation")):
            missing.append("operator_confirmation")
        return missing


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())
