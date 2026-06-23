"""Deterministic connector fixtures used by tests and future evals."""

from __future__ import annotations

from typing import Any

from hypertrade.connectors.base import (
    ConnectorAuthMetadata,
    ConnectorCapability,
    ConnectorToolDescriptor,
)


class FixtureConnector:
    connector_id = "fixture"
    display_name = "Fixture Connector"

    def capabilities(self) -> ConnectorCapability:
        return ConnectorCapability(
            connector_id=self.connector_id,
            display_name=self.display_name,
            health=self.health(),
            auth=ConnectorAuthMetadata(type="none", configured=False),
            supported_scopes=["read"],
            tools=self.list_tools(),
            source_of_truth="fixture_connector",
            notes=["Deterministic local connector for tests; not enabled by default."],
        )

    def health(self) -> dict[str, object]:
        return {"status": "ok", "checked": True}

    def list_tools(self) -> list[ConnectorToolDescriptor]:
        return [
            ConnectorToolDescriptor(
                name="fixture_echo",
                description="Return a deterministic echo payload.",
                scope="read",
                safe_read=True,
                idempotency_required=False,
                source_of_truth="fixture_connector",
                connector_id=self.connector_id,
            )
        ]

    def execute_read_tool(self, tool_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if tool_name != "fixture_echo":
            raise KeyError(f"Unknown fixture connector tool: {tool_name}")
        return {
            "status": "ok",
            "connector_id": self.connector_id,
            "tool": tool_name,
            "message": str(parameters.get("message", "")),
            "source": "fixture_connector",
        }
