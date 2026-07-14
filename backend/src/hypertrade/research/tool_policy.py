"""Role/registry/operator policy intersection before any research tool dispatch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from hypertrade.research.roles.definitions import RoleDefinition
from hypertrade.research.roles.schemas import RoleToolCall
from hypertrade.tools.registry import ToolDefinition, ToolRegistry

_FORBIDDEN_ARGUMENT_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "password",
    "private_reasoning",
    "secret",
    "token",
}


class RoleToolDenied(PermissionError):
    def __init__(self, role_key: str, tool_name: str, reason: str) -> None:
        super().__init__(f"role {role_key} cannot dispatch {tool_name}: {reason}")
        self.role_key = role_key
        self.tool_name = tool_name
        self.reason = reason


@dataclass(frozen=True)
class RoleToolPolicy:
    role_key: str
    allowed: tuple[ToolDefinition, ...]
    catalog_hash: str

    def projection(self) -> dict[str, Any]:
        return {
            "role_key": self.role_key,
            "allowed_tools": [tool.name for tool in self.allowed],
            "catalog_hash": self.catalog_hash,
            "scope": "read_only_intersection",
            "paper_live_writes": "blocked",
        }


class RoleToolPolicyResolver:
    """Fail-closed intersection; role prompts cannot expand their own permissions."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry.default()

    def resolve(
        self,
        role: RoleDefinition,
        *,
        operator_allowlist: set[str] | None = None,
    ) -> RoleToolPolicy:
        operator_allowed = operator_allowlist or set(role.allowed_tools)
        allowed: list[ToolDefinition] = []
        for name in role.allowed_tools:
            if name not in operator_allowed:
                continue
            try:
                tool = self.registry.get(name)
            except KeyError:
                continue
            if tool.policy.scope != "read" or tool.policy.approval != "none":
                continue
            allowed.append(tool)
        serialized = json.dumps(
            [
                {"name": tool.name, "policy": tool.policy.to_dict()}
                for tool in sorted(allowed, key=lambda item: item.name)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return RoleToolPolicy(
            role_key=role.key,
            allowed=tuple(allowed),
            catalog_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        )

    def authorize(self, policy: RoleToolPolicy, calls: list[RoleToolCall]) -> None:
        allowed = {tool.name: tool for tool in policy.allowed}
        for call in calls:
            tool = allowed.get(call.name)
            if tool is None:
                raise RoleToolDenied(policy.role_key, call.name, "not_in_read_only_intersection")
            if tool.policy.scope != "read" or tool.policy.approval != "none":
                raise RoleToolDenied(policy.role_key, call.name, "non_read_or_approval_tool")
            serialized = json.dumps(call.arguments, ensure_ascii=False, default=str)
            if len(serialized) > 8_000:
                raise RoleToolDenied(policy.role_key, call.name, "arguments_too_large")
            if _contains_forbidden_key(call.arguments):
                raise RoleToolDenied(policy.role_key, call.name, "secret_or_reasoning_argument")


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _FORBIDDEN_ARGUMENT_KEYS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple):
        return any(_contains_forbidden_key(item) for item in value)
    return False
