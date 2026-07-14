from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from hypertrade.tui.app import ControlConfirmScreen, ResearchWorkbenchApp
from textual.widgets import Input, Static, TextArea


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeWorkbenchClient:
    def __init__(self) -> None:
        self.controls: list[tuple[str, str, str]] = []
        self.created: list[str] = []

    def list_agent_sessions(self) -> list[dict[str, Any]]:
        return [{"id": "sess_1", "title": "TUI session", "status": "active"}]

    def create_agent_session(self, title: str) -> dict[str, Any]:
        self.created.append(title)
        return {"id": "sess_new", "title": title}

    def list_agent_tasks(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "task_1",
                "session_id": "sess_1",
                "objective": "Research bounded BTC trend",
                "kind": "research_graph",
                "status": "completed",
                "usage": {"tokens": 250},
                "budget": {"max_tokens": 1000},
            }
        ]

    def create_agent_task(
        self, session_id: str, objective: str, *, kind: str = "chat_run"
    ) -> dict[str, Any]:
        return {
            "id": "task_new",
            "session_id": session_id,
            "objective": objective,
            "kind": kind,
            "status": "queued",
            "usage": {},
            "budget": {},
        }

    def get_agent_task(self, task_id: str) -> dict[str, Any]:
        if task_id == "task_new":
            return {
                "id": "task_new",
                "session_id": "sess_new",
                "objective": self.created[-1],
                "kind": "chat_run",
                "status": "queued",
                "usage": {},
                "budget": {},
            }
        return self.list_agent_tasks()[0]

    def list_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> list[dict[str, Any]]:
        events = [
            {"sequence": 1, "event": "task_created", "actor": "operator"},
            {"sequence": 2, "event": "task_status_changed", "actor": "worker"},
        ]
        return [event for event in events if int(event["sequence"]) > after]

    def stream_agent_task_events(
        self, task_id: str, *, after: int = 0
    ) -> Iterator[dict[str, Any]]:
        return iter(())

    def get_research_graph(self, task_id: str) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_key": "market_regime",
                    "role_key": "market_regime",
                    "status": "completed",
                    "attempt": 1,
                }
            ],
            "evidence": [
                {
                    "id": "ev_1",
                    "evidence_type": "market_fact",
                    "lifecycle_status": "active",
                }
            ],
        }

    def list_experiment_manifests(self) -> list[dict[str, Any]]:
        return [{"fingerprint": "abc", "status": "completed"}]

    def list_robustness_validations(self) -> list[dict[str, Any]]:
        return [{"id": "v_1", "final_status": "rejected"}]

    def list_paper_promotions(self) -> list[dict[str, Any]]:
        return [{"id": "p_1", "status": "pending_review"}]

    def control_agent_task(
        self, task_id: str, action: str, *, reason: str
    ) -> dict[str, Any]:
        self.controls.append((task_id, action, reason))
        return {**self.get_agent_task(task_id), "status": "pause_requested"}


@pytest.mark.anyio
async def test_tui_renders_graph_evidence_metrics_and_compact_layout() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        assert "TASKS\n1" in str(app.query_one("#metric-tasks", Static).content)
        assert "market_regime" in str(app.query_one("#graph-view", Static).content)
        assert "market_fact" in str(app.query_one("#evidence-view", Static).content)
        assert "cursor=2" in str(app.query_one("#timeline-view", Static).content)

        await pilot.resize_terminal(80, 36)
        await pilot.pause()
        assert app.has_class("compact")


@pytest.mark.anyio
async def test_tui_control_modal_requires_reason_and_dispatches_request() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(120, 42)) as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, ControlConfirmScreen)
        app.screen.query_one("#control-reason", Input).value = "manual review"
        await pilot.click("#control-submit")
        await pilot.pause()

    assert client.controls == [("task_1", "pause", "manual review")]


@pytest.mark.anyio
async def test_tui_multiline_prompt_creates_new_session_and_task() -> None:
    client = FakeWorkbenchClient()
    app = ResearchWorkbenchApp(client=client)

    async with app.run_test(size=(120, 42)) as pilot:
        prompt = app.query_one("#task-prompt", TextArea)
        prompt.load_text("Research ETH\nwith bounded evidence")
        await pilot.click("#start-task")
        await pilot.pause()

    assert client.created == ["Research ETH\nwith bounded evidence"]
