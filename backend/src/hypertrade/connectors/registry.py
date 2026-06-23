"""Connector registry and redacted capability service."""

from __future__ import annotations

from typing import Any

from hypertrade.config import Settings, get_settings
from hypertrade.connectors.base import Connector
from hypertrade.connectors.bitpro import BitProConnector


class ConnectorRegistry:
    def __init__(self, connectors: list[Connector]) -> None:
        self._connectors = {connector.connector_id: connector for connector in connectors}

    @classmethod
    def default(cls, *, settings: Settings | None = None) -> ConnectorRegistry:
        return cls([BitProConnector(settings=settings or get_settings())])

    def list_connectors(self) -> list[Connector]:
        return list(self._connectors.values())

    def get(self, connector_id: str) -> Connector:
        return self._connectors[connector_id]

    def capabilities_payload(self) -> dict[str, object]:
        return {
            "connectors": {
                connector.connector_id: connector.capabilities().to_dict()
                for connector in self.list_connectors()
            }
        }

    def execute_read(
        self,
        connector_id: str,
        tool_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.get(connector_id).execute_read_tool(tool_name, dict(parameters or {}))
