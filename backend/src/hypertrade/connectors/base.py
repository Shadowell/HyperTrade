"""Connector contracts for trusted in-repo external providers.

Connectors describe external capability providers without exposing secret
material. Execution stays in server-owned code so Agent planning, tool policy,
and trace can remain the enforcement boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ConnectorAuthMetadata:
    type: str
    configured: bool
    header: str = ""
    token_env: str = ""
    token_source: str = "not_configured"
    secret_redacted: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "configured": self.configured,
            "header": self.header,
            "token_env": self.token_env,
            "token_source": self.token_source,
            "secret_redacted": self.secret_redacted,
        }


@dataclass(frozen=True)
class ConnectorToolDescriptor:
    name: str
    description: str
    scope: str
    safe_read: bool
    idempotency_required: bool
    source_of_truth: str
    connector_id: str
    requires_approval: bool = False
    parameters_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "scope": self.scope,
            "safe_read": self.safe_read,
            "idempotency_required": self.idempotency_required,
            "source_of_truth": self.source_of_truth,
            "connector_id": self.connector_id,
            "requires_approval": self.requires_approval,
            "parameters_schema": self.parameters_schema,
        }


@dataclass(frozen=True)
class ConnectorCapability:
    connector_id: str
    display_name: str
    health: dict[str, object]
    auth: ConnectorAuthMetadata
    supported_scopes: list[str]
    tools: list[ConnectorToolDescriptor]
    source_of_truth: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "display_name": self.display_name,
            "health": self.health,
            "auth": self.auth.to_dict(),
            "supported_scopes": self.supported_scopes,
            "tools": [tool.to_dict() for tool in self.tools],
            "idempotency_required_tools": [
                tool.name for tool in self.tools if tool.idempotency_required
            ],
            "source_of_truth": self.source_of_truth,
            "notes": self.notes,
        }


class Connector(Protocol):
    connector_id: str
    display_name: str

    def capabilities(self) -> ConnectorCapability:
        """Return redacted capability metadata without requiring live secrets."""
        ...

    def health(self) -> dict[str, object]:
        """Run the provider health check through trusted server code."""
        ...

    def list_tools(self) -> list[ConnectorToolDescriptor]:
        """Return provider tool descriptors."""
        ...

    def execute_read_tool(self, tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        """Execute a safe read-only provider tool."""
        ...
