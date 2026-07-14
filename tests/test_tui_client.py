from __future__ import annotations

import json
from typing import Any

import httpx
from hypertrade.cli import AgentApiClient, CliConfig, main


def test_remote_tui_client_creates_resources_and_resumes_sse_cursor() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/agent/sessions":
            payload = json.loads(request.content)
            assert payload["surface"] == "tui"
            return httpx.Response(200, json={"id": "sess_1", **payload})
        if request.url.path == "/api/agent/sessions/sess_1/tasks":
            payload = json.loads(request.content)
            assert payload["kind"] == "chat_run"
            assert payload["idempotency_key"].startswith("tui_task_")
            return httpx.Response(200, json={"id": "task_1", "session_id": "sess_1", **payload})
        if request.url.path == "/api/agent/tasks/task_1/stream":
            assert request.url.params["after"] == "7"
            assert request.headers["Last-Event-ID"] == "7"
            return httpx.Response(
                200,
                text=(
                    "id: 8\n"
                    "event: task_status_changed\n"
                    'data: {"sequence":8,"event":"task_status_changed","actor":"worker"}\n\n'
                ),
                headers={"content-type": "text/event-stream"},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://hypertrade.test",
    )
    client = AgentApiClient(
        CliConfig(api_url="http://hypertrade.test", username="admin", password="secret"),
        http_client=http_client,
    )

    session = client.create_agent_session("TUI research")
    task = client.create_agent_task(session["id"], "bounded objective")
    events = list(client.stream_agent_task_events(task["id"], after=7))

    assert events == [
        {
            "event": "task_status_changed",
            "sequence": 8,
            "actor": "worker",
        }
    ]
    assert len(requests) == 3


class TuiCommandClient:
    def __init__(self) -> None:
        self.logged_in = False

    def login(self) -> None:
        self.logged_in = True


def test_cli_tui_command_authenticates_and_passes_initial_session(monkeypatch: Any) -> None:
    client = TuiCommandClient()
    launched: list[tuple[object, str]] = []
    monkeypatch.setattr(
        "hypertrade.tui.launch_tui",
        lambda active_client, *, session_id="": launched.append((active_client, session_id)),
    )

    status = main(
        ["--remote", "http://hypertrade.test", "tui", "--session", "sess_42"],
        client=client,  # type: ignore[arg-type]
    )

    assert status == 0
    assert client.logged_in is True
    assert launched == [(client, "sess_42")]
