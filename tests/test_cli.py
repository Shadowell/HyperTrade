from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
from hypertrade.cli import AgentApiClient, CliConfig, LocalAgentClient, main, run_chat


class FakeAgentClient:
    def __init__(self) -> None:
        self.logged_in = False
        self.prompts: list[str] = []
        self.research_prompts: list[str] = []
        self.backtest_calls: list[tuple[str, str]] = []

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

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "market.summary",
                "category": "market",
                "requires_approval": False,
                "description": "Summarize market.",
            },
            {
                "name": "live.order_intent",
                "category": "live",
                "requires_approval": True,
                "description": "Create order intent.",
            },
        ]

    def list_runs(self) -> list[dict[str, Any]]:
        return [{"id": "run_recent", "status": "completed", "prompt": "请做行情归纳"}]

    def list_memory(self) -> list[dict[str, Any]]:
        return [{"id": "mem_recent", "kind": "market_summary", "content": "BTC was reviewed"}]

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return [{"id": "srch_recent", "strategy_key": "momentum_breakout_v1", "title": "趋势突破"}]

    def list_backtests(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "bt_recent",
                "strategy_key": "momentum_breakout_v1",
                "status": "completed",
                "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
            }
        ]

    def get_status(self) -> dict[str, Any]:
        return {
            "mode": "test",
            "database_url": "sqlite:///:memory:",
            "agent_runs": 1,
            "memory_items": 1,
            "tools": 2,
        }

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        self.research_prompts.append(prompt)
        return {
            "id": "srch_cli",
            "strategy_key": "momentum_breakout_v1",
            "title": "趋势突破",
            "report_markdown": "# Research\n\nBTC breakout study.",
        }

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
    ) -> dict[str, Any]:
        self.backtest_calls.append((research_id, strategy_key))
        return {
            "id": "bt_cli",
            "research_id": research_id,
            "strategy_key": strategy_key,
            "status": "completed",
            "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
            "report_markdown": "# Backtest\n\nReturn 1.9%.",
        }

    def get_model_status(self) -> dict[str, Any]:
        return {
            "default_provider": "deepseek",
            "model": "deepseek-v4-flash",
            "providers": [
                {
                    "name": "deepseek",
                    "display_name": "DeepSeek",
                    "model": "deepseek-v4-flash",
                    "enabled": True,
                    "default": True,
                    "key_status": "configured",
                }
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


def test_chat_handles_slash_commands_without_agent_run(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(
        [
            "/help",
            "/commands",
            "/status",
            "/model",
            "/model gpt-5",
            "/providers",
            "/tools",
            "/runs",
            "/memory",
            "/strategy",
            "/backtests",
            "exit",
        ]
    )

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.logged_in is True
    assert client.prompts == []
    output = capsys.readouterr().out
    assert "/tools" in output
    assert "Status:" in output
    assert "Model:" in output
    assert "model switching is not implemented" in output
    assert "Providers:" in output
    assert "market.summary" in output
    assert "live.order_intent" in output
    assert "run_recent" in output
    assert "mem_recent" in output
    assert "srch_recent" in output
    assert "bt_recent" in output


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
        settings=Settings(
            DATABASE_URL="sqlite:///:memory:",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
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


def test_chat_runs_research_and_backtest_shortcuts(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(
        [
            "/research 研究BTC趋势突破",
            "/backtest latest",
            "exit",
        ]
    )

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.research_prompts == ["研究BTC趋势突破"]
    assert client.backtest_calls == [("srch_recent", "momentum_breakout_v1")]
    output = capsys.readouterr().out
    assert "srch_cli" in output
    assert "Strategy research created" in output
    assert "bt_cli" in output
    assert "Backtest completed" in output
    assert "Return 1.9%" in output


def test_api_client_creates_research_and_backtest() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {}
        if request.content:
            payload = dict(httpx.Response(200, content=request.content).json())
        seen.append((request.method, request.url.path, payload))
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/strategy/research":
            return httpx.Response(
                200,
                json={
                    "id": "srch_api_new",
                    "strategy_key": "momentum_breakout_v1",
                    "title": "趋势突破",
                    "report_markdown": "# Research",
                },
            )
        if request.url.path == "/api/backtests":
            return httpx.Response(
                200,
                json={
                    "id": "bt_api_new",
                    "research_id": payload.get("research_id", ""),
                    "strategy_key": payload.get("strategy_key", ""),
                    "status": "completed",
                    "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
                    "report_markdown": "# Backtest",
                },
            )
        raise AssertionError(request.url.path)

    client = AgentApiClient(
        CliConfig(api_url="http://example.test/", username="admin", password="secret"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    research = client.create_strategy_research("研究ETH动量")
    backtest = client.run_backtest(research_id="srch_api_new")

    assert research["id"] == "srch_api_new"
    assert backtest["id"] == "bt_api_new"
    assert ("POST", "/api/strategy/research", {"prompt": "研究ETH动量"}) in seen
    backtest_call = next(item for item in seen if item[1] == "/api/backtests")
    assert backtest_call[2]["research_id"] == "srch_api_new"


def test_local_client_runs_strategy_workflow(tmp_path) -> None:
    from hypertrade.config import Settings
    from hypertrade.db import Database

    db = Database("sqlite:///:memory:")
    db.create_all()
    client = LocalAgentClient(
        settings=Settings(DATABASE_URL="sqlite:///:memory:", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )

    research = client.create_strategy_research("研究SOL突破")
    backtest = client.run_backtest(research_id=str(research["id"]))

    assert research["id"].startswith("srch_")
    assert backtest["id"].startswith("bt_")
    assert backtest["research_id"] == research["id"]
    assert backtest["metrics"]["trade_count"] == 1


def test_api_client_lists_slash_command_resources() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        payloads: dict[str, dict[str, Any]] = {
            "/api/harness/tools": {"tools": [{"name": "market.summary"}]},
            "/api/agent/runs": {"runs": [{"id": "run_api"}]},
            "/api/memory": {"items": [{"id": "mem_api"}]},
            "/api/strategy/research": {"items": [{"id": "srch_api"}]},
            "/api/backtests": {"items": [{"id": "bt_api"}]},
            "/api/harness/overview": {
                "agent_runs": {"total_count": 2},
                "memory": {"active_count": 1},
                "tools": [{"name": "market.summary"}],
                "market": {"ticker_count": 344, "latest_update_age_seconds": 3},
                "providers": [
                    {
                        "name": "deepseek",
                        "display_name": "DeepSeek",
                        "model": "deepseek-v4-flash",
                        "enabled": True,
                        "default": True,
                        "key_status": "configured",
                    }
                ],
            },
        }
        return httpx.Response(200, json=payloads[request.url.path])

    client = AgentApiClient(
        CliConfig(api_url="http://example.test/", username="admin", password="secret"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_tools()[0]["name"] == "market.summary"
    assert client.list_runs()[0]["id"] == "run_api"
    assert client.list_memory()[0]["id"] == "mem_api"
    assert client.list_strategy_research()[0]["id"] == "srch_api"
    assert client.list_backtests()[0]["id"] == "bt_api"
    assert client.get_status()["agent_runs"] == 2
    assert client.get_model_status()["model"] == "deepseek-v4-flash"
    assert seen == [
        ("GET", "/api/harness/tools"),
        ("GET", "/api/agent/runs"),
        ("GET", "/api/memory"),
        ("GET", "/api/strategy/research"),
        ("GET", "/api/backtests"),
        ("GET", "/api/harness/overview"),
        ("GET", "/api/harness/overview"),
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
