from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TextIO

import httpx
from sqlalchemy import desc, select

from hypertrade.agent.kernel import AgentKernel, CompletedAgentRun
from hypertrade.backtest.service import BacktestService
from hypertrade.config import Settings, get_settings
from hypertrade.db import AgentRun, Database, TraceEvent
from hypertrade.memory.service import MemoryService
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolDefinition, ToolRegistry


class AgentClient(Protocol):
    def login(self) -> None: ...

    def run_agent(self, prompt: str) -> dict[str, Any]: ...

    def list_tools(self) -> list[dict[str, Any]]: ...

    def list_runs(self) -> list[dict[str, Any]]: ...

    def list_memory(self) -> list[dict[str, Any]]: ...

    def list_strategy_research(self) -> list[dict[str, Any]]: ...

    def list_backtests(self) -> list[dict[str, Any]]: ...

    def create_strategy_research(self, prompt: str) -> dict[str, Any]: ...

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
    ) -> dict[str, Any]: ...

    def get_status(self) -> dict[str, Any]: ...

    def get_model_status(self) -> dict[str, Any]: ...


class AgentClientFactory(Protocol):
    def __call__(self, config: CliConfig, local: bool) -> AgentClient: ...


@dataclass(frozen=True)
class CliConfig:
    api_url: str
    username: str
    password: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls, *, api_url: str | None = None) -> CliConfig:
        return cls(
            api_url=api_url
            or os.getenv("HYPERTRADE_API_URL")
            or "http://127.0.0.1:3334",
            username=os.getenv("HYPERTRADE_USERNAME")
            or os.getenv("ADMIN_USERNAME")
            or "admin",
            password=os.getenv("HYPERTRADE_PASSWORD")
            or os.getenv("ADMIN_PASSWORD")
            or "hypertrade-admin",
            timeout_seconds=float(os.getenv("HYPERTRADE_TIMEOUT_SECONDS", "20")),
        )


class AgentApiClient:
    def __init__(
        self,
        config: CliConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self.client = http_client or httpx.Client(
            base_url=config.api_url.rstrip("/"),
            timeout=config.timeout_seconds,
        )

    def login(self) -> None:
        response = self.client.post(
            self._url("/api/auth/login"),
            json={"username": self.config.username, "password": self.config.password},
        )
        response.raise_for_status()

    def run_agent(self, prompt: str) -> dict[str, Any]:
        response = self.client.post(self._url("/api/agent/runs"), json={"prompt": prompt})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Agent run response must be a JSON object")
        return payload

    def list_tools(self) -> list[dict[str, Any]]:
        return self._get_list("/api/harness/tools", "tools")

    def list_runs(self) -> list[dict[str, Any]]:
        return self._get_list("/api/agent/runs", "runs")

    def list_memory(self) -> list[dict[str, Any]]:
        return self._get_list("/api/memory", "items")

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return self._get_list("/api/strategy/research", "items")

    def list_backtests(self) -> list[dict[str, Any]]:
        return self._get_list("/api/backtests", "items")

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        return self._post_object("/api/strategy/research", {"prompt": prompt})

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
    ) -> dict[str, Any]:
        return self._post_object(
            "/api/backtests",
            {
                "research_id": research_id,
                "strategy_key": strategy_key,
                "initial_cash": "100000",
            },
        )

    def get_status(self) -> dict[str, Any]:
        overview = self._get_object("/api/harness/overview")
        return {
            "mode": "remote",
            "api_url": self.config.api_url,
            "agent_runs": _nested_int(overview, "agent_runs", "total_count"),
            "memory_items": _nested_int(overview, "memory", "active_count"),
            "tools": len(overview.get("tools", []))
            if isinstance(overview.get("tools"), list)
            else 0,
            "tickers": _nested_int(overview, "market", "ticker_count"),
            "latest_market_age_seconds": _nested_value(
                overview,
                "market",
                "latest_update_age_seconds",
            ),
        }

    def get_model_status(self) -> dict[str, Any]:
        overview = self._get_object("/api/harness/overview")
        providers = overview.get("providers", [])
        if not isinstance(providers, list):
            providers = []
        default_provider = next(
            (
                provider
                for provider in providers
                if isinstance(provider, dict) and provider.get("default")
            ),
            providers[0] if providers and isinstance(providers[0], dict) else {},
        )
        return {
            "default_provider": default_provider.get("name", "unknown"),
            "model": default_provider.get("model", "unknown"),
            "providers": [dict(provider) for provider in providers if isinstance(provider, dict)],
        }

    def _url(self, path: str) -> str:
        return f"{self.config.api_url.rstrip('/')}{path}"

    def _get_list(self, path: str, key: str) -> list[dict[str, Any]]:
        payload = self._get_object(path)
        items = payload.get(key, [])
        if not isinstance(items, list):
            raise TypeError(f"{path}.{key} must be a list")
        return [dict(item) for item in items if isinstance(item, dict)]

    def _get_object(self, path: str) -> dict[str, Any]:
        response = self.client.get(self._url(path))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError(f"{path} response must be a JSON object")
        return dict(payload)

    def _post_object(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(self._url(path), json=body)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError(f"{path} response must be a JSON object")
        return dict(payload)


class LocalAgentClient:
    def __init__(self, *, settings: Settings | None = None, db: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = db or Database(self.settings.database_url)

    def login(self) -> None:
        return None

    def run_agent(self, prompt: str) -> dict[str, Any]:
        run = AgentKernel(self.db, knowledge_dir=str(self.settings.knowledge_dir)).run_chat(prompt)
        return _completed_run_to_dict(run)

    def list_tools(self) -> list[dict[str, Any]]:
        return [_tool_to_dict(tool) for tool in ToolRegistry.default().list_tools()]

    def list_runs(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            runs = session.scalars(select(AgentRun).order_by(desc(AgentRun.created_at)).limit(10))
            return [
                {
                    "id": run.id,
                    "status": run.status,
                    "prompt": run.prompt,
                    "created_at": run.created_at.isoformat(),
                }
                for run in runs
            ]

    def list_memory(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "kind": item.kind,
                "content": item.content,
                "source_run_id": item.source_run_id,
            }
            for item in MemoryService(self.db).list_active()[-10:]
        ]

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return StrategyResearchService(self.db).list_recent(limit=10)

    def list_backtests(self) -> list[dict[str, Any]]:
        return BacktestService(self.db).list_recent(limit=10)

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        return StrategyResearchService(self.db).create(prompt)

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
    ) -> dict[str, Any]:
        return BacktestService(self.db).run(
            research_id=research_id,
            strategy_key=strategy_key,
        )

    def get_status(self) -> dict[str, Any]:
        return {
            "mode": "local",
            "database_url": _redact_database_url(self.settings.database_url),
            "agent_runs": len(self.list_runs()),
            "memory_items": len(self.list_memory()),
            "tools": len(self.list_tools()),
        }

    def get_model_status(self) -> dict[str, Any]:
        provider = {
            "name": "deepseek",
            "display_name": "DeepSeek",
            "model": self.settings.deepseek_model,
            "enabled": bool(self.settings.deepseek_api_key),
            "default": True,
            "key_status": "configured" if self.settings.deepseek_api_key else "missing",
        }
        return {
            "default_provider": provider["name"],
            "model": provider["model"],
            "providers": [provider],
        }


def main(
    argv: Sequence[str] | None = None,
    *,
    client: AgentClient | None = None,
    client_factory: AgentClientFactory | None = None,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> int:
    output = output or sys.stdout
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = CliConfig.from_env(api_url=args.remote)
    local = _use_local_runtime(args)
    factory = client_factory or _default_client_factory
    agent_client = client or factory(config, local)

    if args.command == "ask":
        prompt = " ".join(args.prompt).strip()
        if not prompt:
            parser.error("ask requires a prompt")
        agent_client.login()
        render_run(agent_client.run_agent(prompt), output=output)
        return 0

    run_chat(client=agent_client, input_fn=input_fn, output=output)
    return 0


def run_chat(
    *,
    client: AgentClient,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> None:
    output = output or sys.stdout
    client.login()
    render_welcome_banner(client=client, output=output)
    while True:
        try:
            prompt = input_fn("hypertrade> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("", file=output)
            return
        if prompt.lower() in {"exit", "quit", ":q"}:
            return
        if not prompt:
            continue
        if prompt.startswith("/"):
            handle_slash_command(prompt, client=client, output=output)
            continue
        render_run(client.run_agent(prompt), output=output)


def render_welcome_banner(*, client: AgentClient, output: TextIO) -> None:
    status = client.get_status()
    mode = str(status.get("mode", "unknown"))
    endpoint = status.get("api_url") or status.get("database_url") or "n/a"
    color = _banner_colors(output)
    print(
        f"{color['border']}╔══════════════════════════════════════════════════════════════╗{color['reset']}",
        file=output,
    )
    print(
        f"{color['border']}║{color['reset']}"
        f"{color['title']}                         HyperTrade                          "
        f"{color['reset']}"
        f"{color['border']}║{color['reset']}",
        file=output,
    )
    print(
        f"{color['border']}║{color['reset']}"
        f"{color['subtitle']}         Agent-First Crypto Research and Execution CLI       "
        f"{color['reset']}"
        f"{color['border']}║{color['reset']}",
        file=output,
    )
    print(
        f"{color['border']}╚══════════════════════════════════════════════════════════════╝{color['reset']}",
        file=output,
    )
    print(
        f"{color['muted']}Research only. Not investment advice.{color['reset']}",
        file=output,
    )
    print(
        f"{color['label']}Runtime:{color['reset']} {color['value']}{mode}{color['reset']} | "
        f"{color['label']}Endpoint:{color['reset']} {color['value']}{endpoint}{color['reset']}",
        file=output,
    )
    print("", file=output)
    print(f"{color['section']}Quick Start{color['reset']}", file=output)
    print(f"{color['cmd']}- /status{color['reset']}        Runtime and session status", file=output)
    print(f"{color['cmd']}- /tools{color['reset']}         Registered tool catalog", file=output)
    print(f"{color['cmd']}- /research ...{color['reset']}  Create strategy research", file=output)
    print(
        f"{color['cmd']}- /backtest{color['reset']}      Run backtest from latest research",
        file=output,
    )
    print(
        f"{color['cmd']}- /help{color['reset']}          Show full slash command list",
        file=output,
    )
    print("", file=output)
    print(
        f"{color['muted']}HyperTrade CLI chat. Type exit, quit, or :q to leave.{color['reset']}",
        file=output,
    )


def _banner_colors(output: TextIO) -> dict[str, str]:
    supports_color = not os.getenv("NO_COLOR") and bool(getattr(output, "isatty", lambda: False)())
    if not supports_color:
        return dict.fromkeys(
            ("reset", "border", "title", "subtitle", "section", "cmd", "label", "value", "muted"),
            "",
        )
    return {
        "reset": "\033[0m",
        "border": "\033[38;5;81m",
        "title": "\033[1;38;5;45m",
        "subtitle": "\033[38;5;117m",
        "section": "\033[1;38;5;183m",
        "cmd": "\033[38;5;121m",
        "label": "\033[38;5;110m",
        "value": "\033[1;38;5;159m",
        "muted": "\033[38;5;246m",
    }


def handle_slash_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    name = command.split(maxsplit=1)[0].lower()
    if name in {"/help", "/?", "/commands", "/command"}:
        render_slash_help(output=output)
    elif name == "/status":
        render_status(client.get_status(), output=output)
    elif name == "/model":
        render_model(command, client=client, output=output)
    elif name in {"/provider", "/providers"}:
        render_providers(client.get_model_status(), output=output)
    elif name == "/tools":
        render_tools(client.list_tools(), output=output)
    elif name == "/runs":
        render_runs(client.list_runs(), output=output)
    elif name == "/memory":
        render_memory(client.list_memory(), output=output)
    elif name in {"/strategy", "/strategies"}:
        render_strategy_research(client.list_strategy_research(), output=output)
    elif name == "/backtests":
        render_backtests(client.list_backtests(), output=output)
    elif name == "/backtest":
        handle_backtest_command(command, client=client, output=output)
    elif name in {"/research", "/sr"}:
        handle_research_command(command, client=client, output=output)
    else:
        print(f"Unknown command: {name}", file=output)
        render_slash_help(output=output)


def render_slash_help(*, output: TextIO) -> None:
    print("Slash commands:", file=output)
    print("- /help        Show this command list.", file=output)
    print("- /status      Show runtime/session status.", file=output)
    print("- /model       Show active provider/model.", file=output)
    print("- /providers   List configured providers.", file=output)
    print("- /tools       List registered Agent tools.", file=output)
    print("- /runs        List recent Agent runs.", file=output)
    print("- /memory      List active audited memory.", file=output)
    print("- /strategy    List recent strategy research.", file=output)
    print("- /backtests   List recent backtest runs.", file=output)
    print("- /research    Create strategy research from a prompt.", file=output)
    print("- /backtest    Run backtest on latest research.", file=output)
    print("- /backtest list                 List recent backtests.", file=output)
    print("- /backtest latest|srch_*|<key>  Run a specific backtest.", file=output)


def handle_research_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=1)
    if len(parts) == 1:
        print("Usage: /research <prompt>", file=output)
        print("Example: /research 研究BTC趋势突破策略", file=output)
        return
    try:
        research = client.create_strategy_research(parts[1].strip())
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Research failed: {exc}", file=output)
        return
    render_strategy_research_result(research, output=output)


def handle_backtest_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    if len(parts) == 1:
        _run_backtest_for_target(client, target="latest", output=output)
        return
    subcommand = parts[1].lower()
    if subcommand in {"list", "ls"}:
        render_backtests(client.list_backtests(), output=output)
        return
    if subcommand == "run":
        target = parts[2] if len(parts) > 2 else "latest"
        _run_backtest_for_target(client, target=target, output=output)
        return
    _run_backtest_for_target(client, target=parts[1], output=output)


def _run_backtest_for_target(client: AgentClient, *, target: str, output: TextIO) -> None:
    research_id = ""
    strategy_key = "momentum_breakout_v1"
    if target.startswith("srch_"):
        research_id = target
    elif target == "latest":
        latest = _latest_strategy_research(client)
        if latest is None:
            print("No strategy research found. Run /research <prompt> first.", file=output)
            return
        research_id = str(latest["id"])
    else:
        strategy_key = target
    try:
        result = client.run_backtest(research_id=research_id, strategy_key=strategy_key)
    except KeyError:
        print(f"Research not found: {research_id}", file=output)
        return
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Backtest failed: {exc}", file=output)
        return
    render_backtest_result(result, output=output)


def _latest_strategy_research(client: AgentClient) -> dict[str, Any] | None:
    items = client.list_strategy_research()
    return items[0] if items else None


def render_strategy_research_result(research: dict[str, Any], *, output: TextIO) -> None:
    print("Strategy research created:", file=output)
    print(f"- ID: {research.get('id', 'unknown')}", file=output)
    print(f"- Strategy: {research.get('strategy_key', 'unknown')}", file=output)
    print(f"- Title: {research.get('title', '')}", file=output)
    print("- Next: /backtest latest", file=output)
    print("", file=output)
    print(str(research.get("report_markdown", "")), file=output)


def render_backtest_result(result: dict[str, Any], *, output: TextIO) -> None:
    metrics = result.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    print("Backtest completed:", file=output)
    print(f"- ID: {result.get('id', 'unknown')}", file=output)
    print(f"- Research: {result.get('research_id') or 'n/a'}", file=output)
    print(f"- Strategy: {result.get('strategy_key', 'unknown')}", file=output)
    print(f"- Return: {metrics.get('total_return_pct', 'n/a')}%", file=output)
    print(f"- Trades: {metrics.get('trade_count', 'n/a')}", file=output)
    print("", file=output)
    print(str(result.get("report_markdown", "")), file=output)


def render_status(status: dict[str, Any], *, output: TextIO) -> None:
    print("Status:", file=output)
    print(f"- Mode: {status.get('mode', 'unknown')}", file=output)
    if status.get("api_url"):
        print(f"- API: {status.get('api_url')}", file=output)
    if status.get("database_url"):
        print(f"- Database: {status.get('database_url')}", file=output)
    print(f"- Agent runs: {status.get('agent_runs', 'n/a')}", file=output)
    print(f"- Memory items: {status.get('memory_items', 'n/a')}", file=output)
    print(f"- Tools: {status.get('tools', 'n/a')}", file=output)
    if status.get("tickers") is not None:
        print(f"- Tickers: {status.get('tickers')}", file=output)


def render_model(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=1)
    status = client.get_model_status()
    if len(parts) == 1:
        print("Model:", file=output)
        print(f"- Provider: {status.get('default_provider', 'unknown')}", file=output)
        print(f"- Model: {status.get('model', 'unknown')}", file=output)
        print("- Switch: /model <name> is not implemented yet.", file=output)
        return
    requested = parts[1].strip()
    print(
        f"Model switch requested for '{requested}', but model switching is not implemented yet.",
        file=output,
    )


def render_providers(status: dict[str, Any], *, output: TextIO) -> None:
    print("Providers:", file=output)
    providers = status.get("providers", [])
    if not isinstance(providers, list) or not providers:
        print("- none", file=output)
        return
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        default = " default" if provider.get("default") else ""
        enabled = "enabled" if provider.get("enabled") else "disabled"
        print(
            f"- {provider.get('name', 'unknown')} {provider.get('model', 'unknown')} "
            f"{enabled}{default}",
            file=output,
        )


def render_tools(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Tools:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items:
        gate = " approval" if item.get("requires_approval") else ""
        print(
            f"- {item.get('name', 'unknown')} [{item.get('category', 'unknown')}]{gate}",
            file=output,
        )


def render_runs(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Recent runs:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        print(
            f"- {item.get('id', 'unknown')} {item.get('status', 'unknown')}: "
            f"{str(item.get('prompt', ''))[:80]}",
            file=output,
        )


def render_memory(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Memory:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        print(
            f"- {item.get('id', 'unknown')} [{item.get('kind', 'unknown')}] "
            f"{str(item.get('content', ''))[:100]}",
            file=output,
        )


def render_strategy_research(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Strategy research:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        print(
            f"- {item.get('id', 'unknown')} {item.get('strategy_key', 'unknown')}: "
            f"{item.get('title', '')}",
            file=output,
        )


def render_backtests(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Backtests:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        metrics = item.get("metrics", {})
        return_pct = metrics.get("total_return_pct", "n/a") if isinstance(metrics, dict) else "n/a"
        trades = metrics.get("trade_count", "n/a") if isinstance(metrics, dict) else "n/a"
        print(
            f"- {item.get('id', 'unknown')} {item.get('strategy_key', 'unknown')} "
            f"{item.get('status', 'unknown')} return={return_pct}% trades={trades}",
            file=output,
        )


def render_run(run: dict[str, Any], *, output: TextIO | None = None) -> None:
    output = output or sys.stdout
    print(f"Run: {run.get('id', 'unknown')}", file=output)
    print(f"Status: {run.get('status', 'unknown')}", file=output)
    trace_events = run.get("trace_events", [])
    if isinstance(trace_events, list) and trace_events:
        print("Tools:", file=output)
        for event in trace_events:
            if not isinstance(event, dict):
                continue
            print(
                f"- {event.get('tool_name', 'unknown')}: {event.get('status', 'unknown')}",
                file=output,
            )
    print("", file=output)
    print(str(run.get("report_markdown", "")), file=output)


def entrypoint() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hypertrade",
        description="HyperTrade Agent CLI conversation harness.",
    )
    runtime_group = parser.add_mutually_exclusive_group()
    runtime_group.add_argument(
        "--remote",
        metavar="URL",
        help="Connect to a running HyperTrade API instead of using the local Agent runtime.",
    )
    runtime_group.add_argument(
        "--local",
        action="store_true",
        help="Force the local standalone Agent runtime.",
    )
    subparsers = parser.add_subparsers(dest="command")
    ask = subparsers.add_parser("ask", help="Run one Agent prompt through the HyperTrade API.")
    ask.add_argument("prompt", nargs="+")
    subparsers.add_parser("chat", help="Start an interactive Agent conversation loop.")
    return parser


def _use_local_runtime(args: argparse.Namespace) -> bool:
    if args.local:
        return True
    if args.remote:
        return False
    return "HYPERTRADE_API_URL" not in os.environ


def _default_client_factory(config: CliConfig, local: bool) -> AgentClient:
    if local:
        return LocalAgentClient()
    return AgentApiClient(config)


def _completed_run_to_dict(run: CompletedAgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "report_markdown": run.report_markdown,
        "report_json": run.report_json,
        "trace_events": [_trace_to_dict(event) for event in run.trace_events],
    }


def _tool_to_dict(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "category": tool.category,
        "requires_approval": tool.requires_approval,
    }


def _nested_value(payload: dict[str, Any], section: str, key: str) -> Any:
    value = payload.get(section, {})
    if not isinstance(value, dict):
        return None
    return value.get(key)


def _nested_int(payload: dict[str, Any], section: str, key: str) -> int:
    value = _nested_value(payload, section, key)
    return int(value) if isinstance(value, int | float | str) and str(value).isdigit() else 0


def _redact_database_url(database_url: str) -> str:
    if "@" not in database_url or "://" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.rsplit("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _trace_to_dict(event: TraceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "tool_name": event.tool_name,
        "status": event.status,
        "input_json": event.input_json,
        "output_json": event.output_json,
        "created_at": event.created_at.isoformat(),
    }
