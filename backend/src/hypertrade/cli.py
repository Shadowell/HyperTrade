from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator, Sequence
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

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]: ...

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
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
    ) -> dict[str, Any]: ...

    def get_status(self) -> dict[str, Any]: ...

    def get_model_status(self) -> dict[str, Any]: ...

    def get_market_ticker(self, symbol: str) -> dict[str, Any]: ...

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]: ...

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]: ...

    def get_paper_status(self) -> dict[str, Any]: ...

    def control_paper(self, action: str) -> dict[str, Any]: ...


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

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]:
        with self.client.stream(
            "POST",
            self._url("/api/agent/runs/stream"),
            json={"prompt": prompt},
        ) as response:
            response.raise_for_status()
            event_name = "message"
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line == "":
                    if data_lines:
                        yield _parse_sse_event(event_name, data_lines)
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
            if data_lines:
                yield _parse_sse_event(event_name, data_lines)

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
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
    ) -> dict[str, Any]:
        return self._post_object(
            "/api/backtests",
            {
                "research_id": research_id,
                "strategy_key": strategy_key,
                "initial_cash": "100000",
                "use_live_candles": use_live_candles,
                "symbol": symbol,
                "bar": bar,
                "candle_limit": candle_limit,
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

    def get_market_ticker(self, symbol: str) -> dict[str, Any]:
        return self._get_object(f"/api/market/ticker/{symbol}")

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._get_object(f"/api/market/candles/{symbol}?bar={bar}&limit={limit}")

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]:
        body = {"symbols": symbols, "bar": bar, "limit": limit}
        return self._post_object("/api/market/compare", body)

    def get_paper_status(self) -> dict[str, Any]:
        return self._get_object("/api/paper/status")

    def control_paper(self, action: str) -> dict[str, Any]:
        return self._post_object("/api/paper/control", {"action": action})

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
        run = AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        ).run_chat(prompt)
        return _completed_run_to_dict(run)

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        run = AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        ).run_chat_with_events(prompt, event_sink=events.append)
        yield from events
        yield {"event": "final", "run": _completed_run_to_dict(run)}

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
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
    ) -> dict[str, Any]:
        return BacktestService(self.db).run(
            research_id=research_id,
            strategy_key=strategy_key,
            use_live_candles=use_live_candles,
            symbol=symbol,
            bar=bar,
            candle_limit=candle_limit,
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

    def get_market_ticker(self, symbol: str) -> dict[str, Any]:
        return AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        )._market_ticker_payload(symbol)

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        )._market_candles_payload(symbol=symbol, bar=bar, limit=limit)

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]:
        return AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
        )._market_compare_payload(symbols=symbols, bar=bar, limit=limit)

    def get_paper_status(self) -> dict[str, Any]:
        from hypertrade.paper.service import PaperTradingService

        return PaperTradingService(self.db, settings=self.settings).status()

    def control_paper(self, action: str) -> dict[str, Any]:
        from hypertrade.paper.service import PaperTradingService

        service = PaperTradingService(self.db, settings=self.settings)
        if action == "pause":
            return service.pause()
        if action == "resume":
            return service.resume()
        raise ValueError(f"unknown paper action: {action}")


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
        render_run_stream(agent_client, prompt, output=output)
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
        render_run_stream(client, prompt, output=output)


def render_welcome_banner(*, client: AgentClient, output: TextIO) -> None:
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
        f"{color['muted']}风险提示：本工具仅用于研究与学习，不构成投资建议。{color['reset']}",
        file=output,
    )
    print("", file=output)
    print(f"{color['section']}Quick Start{color['reset']}", file=output)
    print(f"{color['cmd']}- /status{color['reset']}        Runtime and session status", file=output)
    print(f"{color['cmd']}- /tools{color['reset']}         Registered tool catalog", file=output)
    print(f"{color['cmd']}- /price ETH{color['reset']}     Exact ticker shortcut", file=output)
    print(f"{color['cmd']}- /compare ETH SOL{color['reset']} Relative strength", file=output)
    print(f"{color['cmd']}- /paper status{color['reset']}  Paper trading state", file=output)
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
    elif name in {"/price", "/ticker"}:
        handle_price_command(command, client=client, output=output)
    elif name in {"/candles", "/kline", "/klines"}:
        handle_candles_command(command, client=client, output=output)
    elif name == "/compare":
        handle_compare_command(command, client=client, output=output)
    elif name == "/paper":
        handle_paper_command(command, client=client, output=output)
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
    print("- /price ETH   Fetch exact ticker without LLM planning.", file=output)
    print("- /candles ETH --bar 1H --limit 100", file=output)
    print("- /compare ETH SOL --bar 4H --limit 100", file=output)
    print("- /paper status|pause|resume", file=output)
    print("- /research    Create strategy research from a prompt.", file=output)
    print("- /backtest    Run backtest on latest research.", file=output)
    print("- /backtest list                 List recent backtests.", file=output)
    print("- /backtest latest|srch_*|<key>  Run a specific backtest.", file=output)
    print("- /backtest --live --symbol ETH --bar 1H --limit 100", file=output)


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
    options = _parse_backtest_options(parts)
    positional = options["positionals"]
    if len(parts) == 1:
        _run_backtest_for_target(client, target="latest", options=options, output=output)
        return
    subcommand = str(positional[1]).lower() if len(positional) > 1 else ""
    if subcommand in {"list", "ls"}:
        render_backtests(client.list_backtests(), output=output)
        return
    if subcommand == "run":
        target = str(positional[2]) if len(positional) > 2 else "latest"
        _run_backtest_for_target(client, target=target, options=options, output=output)
        return
    target = str(positional[1]) if len(positional) > 1 else "latest"
    _run_backtest_for_target(client, target=target, options=options, output=output)


def _run_backtest_for_target(
    client: AgentClient,
    *,
    target: str,
    options: dict[str, Any],
    output: TextIO,
) -> None:
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
        result = client.run_backtest(
            research_id=research_id,
            strategy_key=strategy_key,
            use_live_candles=bool(options["use_live_candles"]),
            symbol=str(options["symbol"]),
            bar=str(options["bar"]),
            candle_limit=int(options["candle_limit"]),
        )
    except KeyError:
        print(f"Research not found: {research_id}", file=output)
        return
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Backtest failed: {exc}", file=output)
        return
    render_backtest_result(result, output=output)


def handle_price_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    if len(parts) < 2:
        print("Usage: /price <symbol>", file=output)
        print("Example: /price ETH", file=output)
        return
    try:
        render_market_ticker(client.get_market_ticker(parts[1]), output=output)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Price lookup failed: {exc}", file=output)


def handle_candles_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    if len(parts) < 2:
        print("Usage: /candles <symbol> [--bar 1H] [--limit 100]", file=output)
        print("Example: /candles ETH --bar 1H --limit 100", file=output)
        return
    options = _parse_market_options(parts[2:], default_bar="1H", default_limit=100)
    try:
        payload = client.get_market_candles(
            symbol=parts[1],
            bar=str(options["bar"]),
            limit=int(options["limit"]),
        )
        render_market_candles(payload, output=output)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Candle lookup failed: {exc}", file=output)


def handle_compare_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    symbols: list[str] = []
    option_parts: list[str] = []
    index = 1
    while index < len(parts):
        part = parts[index]
        if part.startswith("--"):
            option_parts.extend(parts[index:])
            break
        symbols.append(part)
        index += 1
    if len(symbols) < 2:
        print("Usage: /compare <symbol> <symbol> [more...] [--bar 4H] [--limit 100]", file=output)
        print("Example: /compare ETH SOL --bar 4H --limit 100", file=output)
        return
    options = _parse_market_options(option_parts, default_bar="4H", default_limit=100)
    try:
        payload = client.compare_markets(
            symbols=symbols,
            bar=str(options["bar"]),
            limit=int(options["limit"]),
        )
        render_market_compare(payload, output=output)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Compare failed: {exc}", file=output)


def handle_paper_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    subcommand = parts[1].lower() if len(parts) > 1 else "status"
    if subcommand in {"status", "show"}:
        try:
            render_paper_status(client.get_paper_status(), output=output)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper status failed: {exc}", file=output)
        return
    if subcommand in {"pause", "resume"}:
        try:
            result = client.control_paper(subcommand)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper control failed: {exc}", file=output)
            return
        session = result.get("session", {})
        status = session.get("status", "unknown") if isinstance(session, dict) else "unknown"
        print(f"Paper control: {status}", file=output)
        return
    print("Usage: /paper status|pause|resume", file=output)


def _parse_backtest_options(parts: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "positionals": [],
        "use_live_candles": False,
        "symbol": "BTC",
        "bar": "1H",
        "candle_limit": 100,
    }
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "--live":
            options["use_live_candles"] = True
        elif part == "--symbol" and index + 1 < len(parts):
            index += 1
            options["symbol"] = parts[index]
        elif part == "--bar" and index + 1 < len(parts):
            index += 1
            options["bar"] = parts[index]
        elif part == "--limit" and index + 1 < len(parts):
            index += 1
            options["candle_limit"] = int(parts[index])
        else:
            options["positionals"].append(part)
        index += 1
    return options


def _parse_market_options(
    parts: list[str],
    *,
    default_bar: str,
    default_limit: int,
) -> dict[str, Any]:
    options: dict[str, Any] = {"bar": default_bar, "limit": default_limit}
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "--bar" and index + 1 < len(parts):
            index += 1
            options["bar"] = parts[index]
        elif part == "--limit" and index + 1 < len(parts):
            index += 1
            options["limit"] = int(parts[index])
        index += 1
    return options


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


def render_market_ticker(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Price:", file=output)
    if not payload.get("found", True):
        print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
        reason = payload.get("unavailable_reason", "not found")
        print(f"- Status: unavailable ({reason})", file=output)
        return
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Last: {payload.get('last', 'n/a')}", file=output)
    print(f"- UTC0 change: {payload.get('change_utc0_pct', 'n/a')}%", file=output)
    print(f"- 24h volume: {payload.get('volume_ccy_24h', 'n/a')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)
    print(f"- As of UTC: {payload.get('as_of_utc', 'n/a')}", file=output)
    print("Research output only. Not investment advice.", file=output)


def render_market_candles(payload: dict[str, Any], *, output: TextIO) -> None:
    print("K-line trend:", file=output)
    if not payload.get("found", True):
        print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
        reason = payload.get("unavailable_reason", "not found")
        print(f"- Status: unavailable ({reason})", file=output)
        return
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Candles: {payload.get('candle_count', 'n/a')}", file=output)
    print(f"- Return: {payload.get('return_pct', 'n/a')}%", file=output)
    print(f"- Range: {payload.get('range_pct', 'n/a')}%", file=output)
    print(f"- Close position: {payload.get('close_position_pct', 'n/a')}%", file=output)
    print(f"- MA20: {payload.get('ma20', 'n/a')}", file=output)
    print(f"- MA60: {payload.get('ma60', 'n/a')}", file=output)
    print(f"- Bias: {payload.get('trend_bias', 'unknown')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)
    print("Research output only. Not investment advice.", file=output)


def render_market_compare(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Relative strength:", file=output)
    if not payload.get("found", True):
        print("- Status: unavailable", file=output)
        return
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Leader: {payload.get('leader', 'unknown')}", file=output)
    rankings = payload.get("rankings", [])
    if isinstance(rankings, list):
        for row in rankings:
            if not isinstance(row, dict):
                continue
            print(
                "- {rank}. {inst_id}: score={score}, return={return_pct}%, "
                "close_position={close_position_pct}%, bias={trend_bias}".format(
                    rank=row.get("rank", "?"),
                    inst_id=row.get("inst_id", "unknown"),
                    score=row.get("strength_score", "n/a"),
                    return_pct=row.get("return_pct", "n/a"),
                    close_position_pct=row.get("close_position_pct", "n/a"),
                    trend_bias=row.get("trend_bias", "unknown"),
                ),
                file=output,
            )
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)
    print("Research output only. Not investment advice.", file=output)


def render_paper_status(payload: dict[str, Any], *, output: TextIO) -> None:
    session = payload.get("session", {})
    if not isinstance(session, dict):
        session = {}
    print("Paper trading:", file=output)
    print(f"- Session: {session.get('id', 'unknown')}", file=output)
    print(f"- Status: {session.get('status', 'unknown')}", file=output)
    print(f"- Cash: {session.get('cash', 'n/a')}", file=output)
    print(f"- Equity: {session.get('equity', 'n/a')}", file=output)
    print(f"- Realized PnL: {session.get('realized_pnl', 'n/a')}", file=output)

    positions = payload.get("positions", [])
    print("Positions:", file=output)
    if isinstance(positions, list) and positions:
        for row in positions[:10]:
            if not isinstance(row, dict):
                continue
            print(
                "- {inst_id} {side} qty={quantity} entry={entry} mark={mark} pnl={pnl}".format(
                    inst_id=row.get("inst_id", "unknown"),
                    side=row.get("side", "unknown"),
                    quantity=row.get("quantity", "n/a"),
                    entry=row.get("entry_price", "n/a"),
                    mark=row.get("mark_price", "n/a"),
                    pnl=row.get("unrealized_pnl", "n/a"),
                ),
                file=output,
            )
    else:
        print("- none", file=output)

    fills = payload.get("recent_fills", [])
    print("Recent fills:", file=output)
    if isinstance(fills, list) and fills:
        for row in fills[:5]:
            if not isinstance(row, dict):
                continue
            print(
                "- {inst_id} {side} qty={quantity} price={price} fee={fee}".format(
                    inst_id=row.get("inst_id", "unknown"),
                    side=row.get("side", "unknown"),
                    quantity=row.get("quantity", "n/a"),
                    price=row.get("price", "n/a"),
                    fee=row.get("fee", "n/a"),
                ),
                file=output,
            )
    else:
        print("- none", file=output)

    events = payload.get("recent_events", [])
    print("Recent events:", file=output)
    if isinstance(events, list) and events:
        for row in events[:5]:
            if not isinstance(row, dict):
                continue
            print(f"- {row.get('kind', 'event')}: {row.get('message', '')}", file=output)
    else:
        print("- none", file=output)


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
    if _should_render_rich(output) and _render_rich_run(run, output=output):
        return
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
    if _render_structured_report(run, output=output):
        return
    print(str(run.get("report_markdown", "")), file=output)


def _should_render_rich(output: TextIO) -> bool:
    renderer = os.getenv("HYPERTRADE_RENDERER", "auto").strip().lower()
    if renderer in {"plain", "text"}:
        return False
    if renderer == "rich":
        return True
    return bool(getattr(output, "isatty", lambda: False)())


def _render_rich_run(run: dict[str, Any], *, output: TextIO) -> bool:
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        return False

    console = Console(file=output, force_terminal=True, color_system=None, width=120)
    trace_events = run.get("trace_events", [])
    report = run.get("report_json", {})
    has_structured_market_summary = isinstance(report, dict) and isinstance(
        report.get("top_movers"),
        list,
    )
    has_structured_tools = isinstance(trace_events, list) and _has_structured_market_tool_output(
        trace_events
    )
    if not has_structured_market_summary and not has_structured_tools:
        return False

    header = Table.grid(expand=True)
    header.add_column(ratio=1)
    header.add_column(justify="right")
    header.add_row(
        Text(str(run.get("id", "unknown")), style="bold"),
        Text(str(run.get("status", "unknown")), style="green"),
    )
    console.print(Panel(header, title="HyperTrade Run", border_style="cyan"))

    if isinstance(trace_events, list) and trace_events:
        tools = Table(title="Tool Trace", show_header=True, header_style="bold")
        tools.add_column("Tool")
        tools.add_column("Status")
        for event in trace_events:
            if not isinstance(event, dict):
                continue
            tools.add_row(str(event.get("tool_name", "unknown")), str(event.get("status", "n/a")))
        console.print(tools)

    if has_structured_market_summary and isinstance(report, dict):
        _render_rich_market_summary(report, console=console)
    elif has_structured_tools and isinstance(trace_events, list):
        _render_rich_tool_report(trace_events, report=report, console=console)

    disclaimer = "Research output only. Not investment advice."
    if isinstance(report, dict):
        disclaimer = str(report.get("disclaimer", disclaimer))
    console.print(Panel(disclaimer, border_style="yellow"))
    return True


def _render_rich_market_summary(report: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    meta = Table.grid(expand=True)
    meta.add_column()
    meta.add_column()
    meta.add_row("Scope", str(report.get("market_scope", "unknown")))
    meta.add_row("Source", str(report.get("data_source", "unknown")))
    meta.add_row("As of UTC", str(report.get("as_of_utc", "n/a")))
    console.print(Panel(meta, title="Market Report", border_style="green"))

    movers = Table(title="Top Movers", show_header=True, header_style="bold")
    movers.add_column("Instrument")
    movers.add_column("Last", justify="right")
    movers.add_column("UTC0 %", justify="right")
    movers.add_column("24h Volume", justify="right")
    raw_movers = report.get("top_movers", [])
    if isinstance(raw_movers, list):
        for mover in raw_movers[:10]:
            if not isinstance(mover, dict):
                continue
            movers.add_row(
                str(mover.get("inst_id", "unknown")),
                str(mover.get("last", "n/a")),
                str(mover.get("change_utc0_pct", "n/a")),
                str(mover.get("volume_ccy_24h", "n/a")),
            )
    console.print(movers)


def _render_rich_tool_report(
    trace_events: list[Any],
    *,
    report: object,
    console: Any,
) -> None:
    from rich.panel import Panel

    console.print(Panel("Agent Report", border_style="green"))
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        payload = event.get("output_json", {})
        if not isinstance(payload, dict) or not payload.get("found", True):
            continue
        tool_name = str(event.get("tool_name", ""))
        if tool_name == "market_ticker":
            _render_rich_ticker(payload, console=console)
        elif tool_name == "market_candles":
            _render_rich_candles(payload, console=console)
        elif tool_name == "market_compare":
            _render_rich_compare(payload, console=console)


def _render_rich_ticker(payload: dict[str, Any], *, console: Any) -> None:
    from rich.table import Table

    table = Table(title="Ticker", show_header=True, header_style="bold")
    table.add_column("Instrument")
    table.add_column("Last", justify="right")
    table.add_column("UTC0 %", justify="right")
    table.add_column("24h Volume", justify="right")
    table.add_column("Source")
    table.add_row(
        str(payload.get("inst_id", "unknown")),
        str(payload.get("last", "n/a")),
        str(payload.get("change_utc0_pct", "n/a")),
        str(payload.get("volume_ccy_24h", "n/a")),
        str(payload.get("data_source", "unknown")),
    )
    console.print(table)


def _render_rich_candles(payload: dict[str, Any], *, console: Any) -> None:
    from rich.table import Table

    table = Table(title=f"Trend {payload.get('bar', 'n/a')}", show_header=True, header_style="bold")
    table.add_column("Instrument")
    table.add_column("Candles", justify="right")
    table.add_column("Return %", justify="right")
    table.add_column("Bias")
    table.add_column("Source")
    table.add_row(
        str(payload.get("inst_id", "unknown")),
        str(payload.get("candle_count", "n/a")),
        str(payload.get("return_pct", "n/a")),
        str(payload.get("trend_bias", "unknown")),
        str(payload.get("data_source", "unknown")),
    )
    console.print(table)


def _render_rich_compare(payload: dict[str, Any], *, console: Any) -> None:
    from rich.table import Table

    table = Table(title="Relative Strength", show_header=True, header_style="bold")
    table.add_column("Rank", justify="right")
    table.add_column("Instrument")
    table.add_column("Score", justify="right")
    table.add_column("Return %", justify="right")
    table.add_column("Bias")
    rankings = payload.get("rankings", [])
    if isinstance(rankings, list):
        for row in rankings:
            if not isinstance(row, dict):
                continue
            table.add_row(
                str(row.get("rank", "?")),
                str(row.get("inst_id", "unknown")),
                str(row.get("strength_score", "n/a")),
                str(row.get("return_pct", "n/a")),
                str(row.get("trend_bias", "unknown")),
            )
    console.print(table)


def _render_structured_report(run: dict[str, Any], *, output: TextIO) -> bool:
    report = run.get("report_json", {})
    if not isinstance(report, dict) or not report:
        return False
    if isinstance(report.get("top_movers"), list):
        _render_structured_market_summary(report, output=output)
        return True
    trace_events = run.get("trace_events", [])
    if isinstance(trace_events, list) and _has_structured_market_tool_output(trace_events):
        _render_structured_tool_report(trace_events, report=report, output=output)
        return True
    return False


def _render_structured_market_summary(report: dict[str, Any], *, output: TextIO) -> None:
    print("Market Report", file=output)
    print(f"Scope: {report.get('market_scope', 'unknown')}", file=output)
    print(f"Trigger: {report.get('trigger', 'unknown')}", file=output)
    print(f"Source: {report.get('data_source', 'unknown')}", file=output)
    print(f"As of UTC: {report.get('as_of_utc', 'n/a')}", file=output)
    print("", file=output)

    movers = report.get("top_movers", [])
    print("Top movers:", file=output)
    if isinstance(movers, list) and movers:
        for mover in movers[:10]:
            if not isinstance(mover, dict):
                continue
            print(
                "- {inst_id}: last={last}, utc0_change={change}%, volume_24h={volume}".format(
                    inst_id=mover.get("inst_id", "unknown"),
                    last=mover.get("last", "n/a"),
                    change=mover.get("change_utc0_pct", "n/a"),
                    volume=mover.get("volume_ccy_24h", "n/a"),
                ),
                file=output,
            )
    else:
        reason = report.get("unavailable_reason", "no movers available")
        print(f"- unavailable: {reason}", file=output)

    hits = report.get("rag_hits", [])
    if isinstance(hits, list) and hits:
        print("", file=output)
        print("Knowledge hits:", file=output)
        for hit in hits[:5]:
            if not isinstance(hit, dict):
                continue
            print(
                f"- {hit.get('source_path', 'unknown')} score={hit.get('score', 'n/a')}",
                file=output,
            )

    disclaimer = str(report.get("disclaimer", "Research output only. Not investment advice."))
    print("", file=output)
    print(disclaimer, file=output)


def _has_structured_market_tool_output(trace_events: list[Any]) -> bool:
    supported_tools = {"market_ticker", "market_candles", "market_compare"}
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        if event.get("tool_name") in supported_tools and isinstance(event.get("output_json"), dict):
            return True
    return False


def _render_structured_tool_report(
    trace_events: list[Any],
    *,
    report: dict[str, Any],
    output: TextIO,
) -> None:
    print("Agent Report", file=output)
    for event in trace_events:
        if not isinstance(event, dict):
            continue
        payload = event.get("output_json", {})
        if not isinstance(payload, dict) or not payload.get("found", True):
            continue
        tool_name = str(event.get("tool_name", ""))
        if tool_name == "market_ticker":
            _render_tool_ticker_block(payload, output=output)
        elif tool_name == "market_candles":
            _render_tool_candles_block(payload, output=output)
        elif tool_name == "market_compare":
            _render_tool_compare_block(payload, output=output)
    disclaimer = str(report.get("disclaimer", "Research output only. Not investment advice."))
    print("", file=output)
    print(disclaimer, file=output)


def _render_tool_ticker_block(payload: dict[str, Any], *, output: TextIO) -> None:
    print("", file=output)
    print("Ticker:", file=output)
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Last: {payload.get('last', 'n/a')}", file=output)
    print(f"- UTC0 change: {payload.get('change_utc0_pct', 'n/a')}%", file=output)
    print(f"- 24h volume: {payload.get('volume_ccy_24h', 'n/a')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)


def _render_tool_candles_block(payload: dict[str, Any], *, output: TextIO) -> None:
    print("", file=output)
    print("Trend:", file=output)
    print(f"- Instrument: {payload.get('inst_id', 'unknown')}", file=output)
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Candles: {payload.get('candle_count', 'n/a')}", file=output)
    print(f"- Return: {payload.get('return_pct', 'n/a')}%", file=output)
    print(f"- Bias: {payload.get('trend_bias', 'unknown')}", file=output)
    print(f"- Source: {payload.get('data_source', 'unknown')}", file=output)


def _render_tool_compare_block(payload: dict[str, Any], *, output: TextIO) -> None:
    print("", file=output)
    print("Relative strength:", file=output)
    print(f"- Bar: {payload.get('bar', 'n/a')}", file=output)
    print(f"- Leader: {payload.get('leader', 'unknown')}", file=output)
    rankings = payload.get("rankings", [])
    if isinstance(rankings, list):
        for row in rankings:
            if not isinstance(row, dict):
                continue
            print(
                "- {rank}. {inst_id}: score={score}, return={return_pct}%, bias={bias}".format(
                    rank=row.get("rank", "?"),
                    inst_id=row.get("inst_id", "unknown"),
                    score=row.get("strength_score", "n/a"),
                    return_pct=row.get("return_pct", "n/a"),
                    bias=row.get("trend_bias", "unknown"),
                ),
                file=output,
            )


def render_run_stream(
    client: AgentClient,
    prompt: str,
    *,
    output: TextIO | None = None,
) -> None:
    output = output or sys.stdout
    try:
        events = client.run_agent_events(prompt)
    except AttributeError:
        render_run(client.run_agent(prompt), output=output)
        return
    final_run: dict[str, Any] | None = None
    for event in events:
        if not isinstance(event, dict):
            continue
        event_name = str(event.get("event", "message"))
        if event_name == "run_started":
            print(f"Agent status: run created ({event.get('run_id', 'pending')})", file=output)
            print("Agent status: planning next tool call", file=output)
        elif event_name == "tool_started":
            print(
                f"Agent status: executing tool {event.get('tool_name', 'unknown')}",
                file=output,
            )
        elif event_name == "tool_completed":
            print(
                f"Agent status: tool {event.get('tool_name', 'unknown')} "
                f"{event.get('status', 'completed')}",
                file=output,
            )
            print("Agent status: planning next step", file=output)
        elif event_name == "run_completed":
            print("Agent status: generating final report", file=output)
            print(f"Agent status: run completed ({event.get('run_id', 'unknown')})", file=output)
            if isinstance(event.get("run"), dict):
                final_run = dict(event["run"])
        elif event_name == "final" and isinstance(event.get("run"), dict):
            final_run = dict(event["run"])
        elif event_name == "error":
            print(f"Run failed: {event.get('error', 'unknown error')}", file=output)
    if final_run is not None:
        print("", file=output)
        render_run(final_run, output=output)
    else:
        print("Run stream ended without final report.", file=output)


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


def _parse_sse_event(event_name: str, data_lines: list[str]) -> dict[str, Any]:
    payload = json.loads("\n".join(data_lines))
    if isinstance(payload, dict):
        payload.setdefault("event", event_name)
        return payload
    return {"event": event_name, "data": payload}
