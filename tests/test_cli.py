from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
from hypertrade.cli import AgentApiClient, CliConfig, LocalAgentClient, main, run_chat


class FakeAgentClient:
    def __init__(self) -> None:
        self.logged_in = False
        self.prompts: list[str] = []

    def login(self) -> None:
        self.logged_in = True

    def run_agent(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        return {
            "id": "run_cli",
            "status": "completed",
            "report_markdown": "# CLI Report\n\nResearch only. Not investment advice.",
            "trace_events": [
                {"tool_name": "market.summary", "status": "completed"},
                {"tool_name": "memory.write", "status": "completed"},
            ],
        }


def test_ask_prints_agent_run_trace_and_report(capsys) -> None:
    client = FakeAgentClient()

    exit_code = main(["ask", "请做行情归纳"], client=client)

    assert exit_code == 0
    assert client.logged_in is True
    assert client.prompts == ["请做行情归纳"]
    output = capsys.readouterr().out
    assert "run_cli" in output
    assert "market.summary" in output
    assert "# CLI Report" in output


def test_chat_reuses_client_until_exit(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["研究趋势突破策略", "exit"])

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.logged_in is True
    assert client.prompts == ["研究趋势突破策略"]
    output = capsys.readouterr().out
    assert "run_cli" in output
    assert "memory.write" in output


def test_bare_command_starts_chat_loop(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["请做行情归纳", ":q"])

    exit_code = main([], client=client, input_fn=_next_input(inputs))

    assert exit_code == 0
    assert client.logged_in is True
    assert client.prompts == ["请做行情归纳"]
    output = capsys.readouterr().out
    assert "HyperTrade CLI chat" in output
    assert "run_cli" in output


def test_remote_flag_uses_api_client(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_USERNAME", "operator")
    monkeypatch.setenv("HYPERTRADE_PASSWORD", "secret")
    captured: list[tuple[CliConfig, bool]] = []

    exit_code = main(
        ["--remote", "http://remote.test:3333", "ask", "hello"],
        client_factory=lambda config, local: _capture_client(config, local, captured),
    )

    assert exit_code == 0
    assert captured == [
        (
            CliConfig(
                api_url="http://remote.test:3333",
                username="operator",
                password="secret",
            ),
            False,
        )
    ]


def test_local_agent_client_runs_kernel(tmp_path) -> None:
    from hypertrade.config import Settings
    from hypertrade.db import Database

    db = Database("sqlite:///:memory:")
    db.create_all()
    client = LocalAgentClient(
        settings=Settings(DATABASE_URL="sqlite:///:memory:", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )

    client.login()
    run = client.run_agent("请做行情归纳")

    assert run["status"] == "completed"
    assert run["trace_events"][0]["tool_name"] == "market.summary"


def test_api_client_logs_in_and_posts_agent_run() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {}
        if request.content:
            payload = dict(httpx.Response(200, content=request.content).json())
        seen.append((request.method, request.url.path, payload))
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(
            200,
            json={
                "id": "run_api",
                "status": "completed",
                "report_markdown": "ok",
                "trace_events": [],
            },
        )

    transport = httpx.MockTransport(handler)
    client = AgentApiClient(
        CliConfig(
            api_url="http://example.test/",
            username="admin",
            password="secret",
            timeout_seconds=3.0,
        ),
        http_client=httpx.Client(transport=transport),
    )

    client.login()
    run = client.run_agent("hello")

    assert run["id"] == "run_api"
    assert seen == [
        ("POST", "/api/auth/login", {"username": "admin", "password": "secret"}),
        ("POST", "/api/agent/runs", {"prompt": "hello"}),
    ]


def _next_input(values: Iterator[str]):
    def inner(_: str) -> str:
        return next(values)

    return inner


def _capture_client(
    config: CliConfig,
    local: bool,
    captured: list[tuple[CliConfig, bool]],
) -> FakeAgentClient:
    captured.append((config, local))
    return FakeAgentClient()
