from __future__ import annotations

from typing import Any

import pytest
from hypertrade.tui.models import TaskEventCursor, WorkbenchStore


class RecoveryClient:
    def __init__(self) -> None:
        self.events = [
            {"sequence": 1, "event": "task_created", "actor": "operator"},
            {"sequence": 2, "event": "task_status_changed", "actor": "worker"},
        ]
        self.control_requests: list[tuple[str, str, str]] = []

    def list_agent_sessions(self) -> list[dict[str, Any]]:
        return [{"id": "sess_1", "title": "Research"}]

    def create_agent_session(self, title: str) -> dict[str, Any]:
        return {"id": "sess_new", "title": title}

    def list_agent_tasks(self) -> list[dict[str, Any]]:
        return [self.get_agent_task("task_1")]

    def create_agent_task(
        self, session_id: str, objective: str, *, kind: str = "chat_run"
    ) -> dict[str, Any]:
        return {
            "id": "task_new",
            "session_id": session_id,
            "objective": objective,
            "kind": kind,
            "status": "queued",
        }

    def get_agent_task(self, task_id: str) -> dict[str, Any]:
        return {
            "id": task_id,
            "session_id": "sess_1",
            "objective": "bounded research",
            "kind": "chat_run",
            "status": "running",
            "usage": {"tokens": 100},
            "budget": {"max_tokens": 1000},
        }

    def list_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> list[dict[str, Any]]:
        return [event for event in self.events if int(event["sequence"]) > after]

    def stream_agent_task_events(self, task_id: str, *, after: int = 0) -> Any:
        raise ConnectionError("simulated disconnect")

    def get_research_graph(self, task_id: str) -> dict[str, Any]:
        return {}

    def list_experiment_manifests(self) -> list[dict[str, Any]]:
        return []

    def list_robustness_validations(self) -> list[dict[str, Any]]:
        return []

    def list_paper_promotions(self) -> list[dict[str, Any]]:
        return []

    def list_research_triggers(self) -> dict[str, Any]:
        return {"feature_enabled": False, "control": {}, "items": []}

    def list_research_trigger_fires(self, trigger_id: str = "") -> list[dict[str, Any]]:
        return []

    def set_research_trigger_enabled(
        self, trigger_id: str, *, enabled: bool, reason: str
    ) -> dict[str, Any]:
        return {"id": trigger_id, "enabled": enabled}

    def set_research_trigger_control(
        self, *, kill_switch: bool, reason: str
    ) -> dict[str, Any]:
        return {"kill_switch": kill_switch}

    def fire_research_trigger(
        self, trigger_id: str, *, reason: str = "operator_run_now"
    ) -> dict[str, Any]:
        return {"id": "rfire_1", "status": "created"}

    def control_agent_task(
        self, task_id: str, action: str, *, reason: str
    ) -> dict[str, Any]:
        self.control_requests.append((task_id, action, reason))
        return {**self.get_agent_task(task_id), "status": "pause_requested"}


def test_cursor_deduplicates_replay_and_surfaces_gap() -> None:
    cursor = TaskEventCursor()

    assert cursor.consume({"sequence": 1, "event": "one"}) is True
    assert cursor.consume({"sequence": 1, "event": "replay"}) is False
    assert cursor.consume({"sequence": 3, "event": "three"}) is True

    assert cursor.after == 3
    assert cursor.gaps == [(2, 2)]
    assert cursor.needs_snapshot_refresh is True
    assert [event["event"] for event in cursor.events] == ["one", "three"]


def test_disconnect_reconciles_from_high_water_cursor_without_duplicates() -> None:
    client = RecoveryClient()
    store = WorkbenchStore(client)
    store.refresh_index()
    store.select_task("task_1")
    assert store.state.cursor.after == 2

    store.mark_disconnected(ConnectionError("lost"))
    client.events.extend(
        [
            {"sequence": 2, "event": "replayed", "actor": "worker"},
            {"sequence": 3, "event": "node_started", "actor": "role"},
        ]
    )
    store.refresh_after_disconnect()

    assert store.state.cursor.after == 3
    assert [event["sequence"] for event in store.state.cursor.events] == [1, 2, 3]
    assert store.state.connection_status == "snapshot"


def test_control_requires_reason_and_delegates_to_server_client() -> None:
    client = RecoveryClient()
    store = WorkbenchStore(client)
    store.refresh_index()
    store.select_task("task_1")

    with pytest.raises(ValueError, match="reason"):
        store.control_selected("pause", "  ")
    result = store.control_selected("pause", "operator review")

    assert result["status"] == "pause_requested"
    assert client.control_requests == [("task_1", "pause", "operator review")]
