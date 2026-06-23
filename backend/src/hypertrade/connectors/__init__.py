"""Trusted connector framework for external HyperTrade data/tool providers."""

from hypertrade.connectors.base import (
    Connector,
    ConnectorAuthMetadata,
    ConnectorCapability,
    ConnectorToolDescriptor,
)
from hypertrade.connectors.registry import ConnectorRegistry

__all__ = [
    "Connector",
    "ConnectorAuthMetadata",
    "ConnectorCapability",
    "ConnectorRegistry",
    "ConnectorToolDescriptor",
]
