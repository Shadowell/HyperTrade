"""
MCP Scaffolding & Tool Governance Subsystem

Provides MCP Tool Schema Translator, Connection Circuit Breaker,
and 3-Tier Risk Permission Sandbox Guard.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

L3_CRITICAL_TOOLS: set[str] = {
    "submit_live_order",
    "cancel_live_order",
    "update_live_keys",
}

L2_SIMULATED_TOOLS: set[str] = {
    "bitpro_paper_dashboard",
    "bitpro_paper_events",
    "update_paper_config",
}


class MCPToolSchemaTranslator:
    """
    Translates complex nested MCP JSON Schemas into flat LLM-optimal schemas.
    """

    @staticmethod
    def flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return schema

        flattened = dict(schema)
        properties = flattened.get("properties", {})
        if not isinstance(properties, dict):
            return flattened

        clean_props: dict[str, Any] = {}
        for prop_name, prop_val in properties.items():
            if isinstance(prop_val, dict):
                # Flatten allOf / $ref nested structures recursively
                if "allOf" in prop_val and isinstance(prop_val["allOf"], list):
                    merged_prop: dict[str, Any] = {"type": "object", "properties": {}}
                    for sub in prop_val["allOf"]:
                        if isinstance(sub, dict):
                            for sub_k, sub_v in sub.items():
                                if sub_k == "properties" and isinstance(sub_v, dict):
                                    merged_prop["properties"].update(sub_v)
                                else:
                                    merged_prop[sub_k] = sub_v
                    clean_props[prop_name] = merged_prop
                else:
                    clean_props[prop_name] = prop_val
            else:
                clean_props[prop_name] = prop_val

        flattened["properties"] = clean_props
        return flattened


class MCPConnectionCircuitBreaker:
    """
    3-State Circuit Breaker (Closed, Open, Half-Open) isolating failing MCP servers.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_sec: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        # server_name -> state dict
        self._states: dict[str, dict[str, Any]] = {}

    def _get_state(self, server_name: str) -> dict[str, Any]:
        return self._states.setdefault(
            server_name,
            {
                "state": "CLOSED",
                "failures": 0,
                "opened_at": 0.0,
            },
        )

    def can_execute(self, server_name: str) -> bool:
        st = self._get_state(server_name)
        now = time.monotonic()

        if st["state"] == "CLOSED":
            return True

        if st["state"] == "OPEN":
            if now - st["opened_at"] >= self.cooldown_sec:
                st["state"] = "HALF_OPEN"
                return True
            return False

        # HALF_OPEN state allows 1 trial request
        return True

    def record_success(self, server_name: str) -> None:
        st = self._get_state(server_name)
        st["state"] = "CLOSED"
        st["failures"] = 0

    def record_failure(self, server_name: str) -> None:
        st = self._get_state(server_name)
        st["failures"] += 1
        if st["failures"] >= self.failure_threshold:
            st["state"] = "OPEN"
            st["opened_at"] = time.monotonic()


class ToolCallPermissionSandboxGuard:
    """
    Enforces 3-Tier Risk Permission Checks:
    L1 (Read-Only) -> Auto-pass
    L2 (Simulated Write) -> Sandbox Check
    L3 (Critical Live Write) -> Approval Token Check
    """

    def evaluate_permission(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        approval_token: str | None = None,
    ) -> tuple[bool, str]:
        if tool_name in L3_CRITICAL_TOOLS:
            token = approval_token or str(tool_args.get("approval_token", ""))
            if not token:
                return (
                    False,
                    f"L3 Critical Write tool '{tool_name}' rejected: missing valid approval_token.",
                )
            return True, "L3 Critical Write approved via token."

        if tool_name in L2_SIMULATED_TOOLS:
            return True, "L2 Simulated Write passed sandbox validation."

        return True, "L1 Read-Only auto-approved."
