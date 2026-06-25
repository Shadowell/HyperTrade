"""Shared constants for the v1 WorldState contract."""

from typing import Any

WORLD_STATE_SCHEMA_VERSION = "world_state.v1"

ReadOnlyAction = dict[str, Any]
WorldStatePayload = dict[str, Any]
