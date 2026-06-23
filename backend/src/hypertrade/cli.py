"""Terminal harness for operating HyperTrade.

The CLI has two modes: local AgentKernel execution for development, and remote
API execution for the deployed server. Slash commands are intentionally mapped
to concrete API/service calls so an operator can test each tool without asking the
LLM to plan first.
"""

from __future__ import annotations

import argparse
import atexit
import getpass
import json
import os
import shlex
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO
from urllib.parse import quote

import httpx
from sqlalchemy import desc, select

from hypertrade.agent.kernel import AgentKernel, CompletedAgentRun
from hypertrade.backtest.service import BacktestService
from hypertrade.config import Settings, get_settings
from hypertrade.db import AgentRun, Database, TraceEvent
from hypertrade.evals.service import AgentEvalSuite
from hypertrade.memory.service import MemoryService
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.strategy.experiment import StrategyExperimentService
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolDefinition, ToolRegistry


class AgentClient(Protocol):
    """Shared interface implemented by local and remote CLI clients."""

    def login(self) -> None: ...

    def run_agent(self, prompt: str) -> dict[str, Any]: ...

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]: ...

    def list_tools(self) -> list[dict[str, Any]]: ...

    def list_runs(self) -> list[dict[str, Any]]: ...

    def list_memory(self) -> list[dict[str, Any]]: ...

    def search_memory(self, query: str) -> list[dict[str, Any]]: ...

    def disable_memory(self, memory_id: str) -> dict[str, Any]: ...

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]: ...

    def get_evals_status(self) -> dict[str, Any]: ...

    def list_strategy_research(self) -> list[dict[str, Any]]: ...

    def list_backtests(self) -> list[dict[str, Any]]: ...

    def create_strategy_research(self, prompt: str) -> dict[str, Any]: ...

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]: ...

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
    ) -> dict[str, Any]: ...

    def get_status(self) -> dict[str, Any]: ...

    def get_model_status(self) -> dict[str, Any]: ...

    def set_model(self, provider: str) -> dict[str, Any]: ...

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

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]: ...

    def list_live_order_intents(self) -> list[dict[str, Any]]: ...

    def create_live_order_intent(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]: ...

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]: ...

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]: ...


class AgentClientFactory(Protocol):
    def __call__(self, config: CliConfig, local: bool) -> AgentClient: ...


THINKING_FRAMES: tuple[str, ...] = ("|", "/", "-", "\\")
DEFAULT_REMOTE_API_URL = "http://47.79.36.92:3333"


SLASH_COMMAND_HELP: tuple[tuple[str, str], ...] = (
    ("/help", "Show this command list."),
    ("/status", "Show runtime, session, market, memory, and tool counts."),
    ("/model", "Show the active provider and model."),
    ("/model <provider>", "Switch the active chat provider for this CLI session."),
    ("/providers", "List configured providers and key status."),
    ("/tools", "List registered Agent tools with category, approval gate, and purpose."),
    ("/runs", "List recent Agent runs."),
    ("/memory", "List active audited memory."),
    ("/memory search <query>", "Search audited memory by text."),
    ("/memory disable <mem_id>", "Disable one memory item without deleting audit history."),
    ("/rag <query>", "Search project and trading knowledge chunks."),
    ("/evals", "Show deterministic Agent eval status."),
    ("/strategy", "List recent strategy research records."),
    ("/backtests", "List recent backtest runs."),
    ("/price ETH", "Fetch one exact OKX SWAP ticker without LLM planning."),
    ("/candles ETH --bar 1H --limit 100", "Fetch candles and derived trend features."),
    ("/compare ETH SOL --bar 4H --limit 100", "Compare relative strength for symbols."),
    ("/paper status", "Show the current paper trading session."),
    ("/paper pause|resume", "Pause or resume the local paper runtime."),
    ("/paper close [symbol]", "Close paper positions, optionally filtered by symbol."),
    ("/paper reset", "Start a fresh audited paper session."),
    ("/live intents", "List pending live/testnet order intents."),
    (
        "/live intent ETH buy 0.01 [--type limit --price 3500 --reason text]",
        "Create an approval-gated order intent.",
    ),
    ("/live approve loi_* [--reason text]", "Approve a pending order intent."),
    ("/live reject loi_* [--reason text]", "Reject a pending order intent."),
    ("/live execute loi_*", "Execute an approved Testnet intent through the configured adapter."),
    ("/research <prompt>", "Create strategy research from a prompt."),
    ("/experiment <prompt>", "Run research, backtest, critique, and revision workflow."),
    ("/backtest", "Run a backtest from the latest research record."),
    ("/backtest list", "List recent backtests."),
    ("/backtest latest|srch_*|<key>", "Run a specific backtest target."),
    ("/backtest --live --symbol ETH --bar 1H --limit 100", "Backtest with recent live candles."),
    ("/backtest --source bitpro_mcp --symbol ETH --bar 1H", "Backtest with BitPro MCP K-lines."),
)


@dataclass(frozen=True)
class CliConfig:
    api_url: str
    username: str
    password: str
    timeout_seconds: float = 20.0

    @classmethod
    def from_env(cls, *, api_url: str | None = None) -> CliConfig:
        saved = read_client_env()
        return cls(
            api_url=api_url
            or os.getenv("HYPERTRADE_API_URL")
            or saved.get("HYPERTRADE_API_URL")
            or "http://127.0.0.1:3334",
            username=os.getenv("HYPERTRADE_USERNAME")
            or saved.get("HYPERTRADE_USERNAME")
            or os.getenv("ADMIN_USERNAME")
            or "admin",
            password=os.getenv("HYPERTRADE_PASSWORD")
            or saved.get("HYPERTRADE_PASSWORD")
            or os.getenv("ADMIN_PASSWORD")
            or "hypertrade-admin",
            timeout_seconds=float(os.getenv("HYPERTRADE_TIMEOUT_SECONDS", "20")),
        )


@dataclass
class InteractiveHistory:
    enabled: bool
    readline_module: Any | None = None
    last_item: str = ""

    def add(self, item: str) -> None:
        value = item.strip()
        if not self.enabled or not value or value == self.last_item:
            return
        module = self.readline_module
        if module is None or not hasattr(module, "add_history"):
            return
        if hasattr(module, "get_current_history_length") and hasattr(
            module,
            "get_history_item",
        ):
            length = int(module.get_current_history_length())
            if length > 0 and module.get_history_item(length) == value:
                self.last_item = value
                return
        module.add_history(value)
        self.last_item = value


def configure_interactive_history(
    *,
    enabled: bool,
    history_path: Path | None = None,
    readline_module: Any | None = None,
    register_exit: Callable[..., Any] = atexit.register,
) -> InteractiveHistory:
    if not enabled:
        return InteractiveHistory(enabled=False)
    try:
        if readline_module is None:
            import readline

            module: Any = readline
        else:
            module = readline_module
    except ImportError:
        return InteractiveHistory(enabled=False)

    path = history_path or (Path.home() / ".hypertrade" / "history")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        path.parent.chmod(0o700)
    history_file = str(path)
    if hasattr(module, "set_history_length"):
        module.set_history_length(1000)
    if hasattr(module, "read_history_file"):
        with suppress(FileNotFoundError):
            module.read_history_file(history_file)
    if hasattr(module, "write_history_file"):
        register_exit(module.write_history_file, history_file)
    return InteractiveHistory(enabled=True, readline_module=module)


def client_env_path() -> Path:
    configured = os.getenv("HYPERTRADE_CLIENT_ENV")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".hypertrade" / "client.env"


def read_client_env() -> dict[str, str]:
    path = client_env_path()
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not parts or "=" not in parts[0]:
            continue
        key, value = parts[0].split("=", 1)
        if key in {"HYPERTRADE_API_URL", "HYPERTRADE_USERNAME", "HYPERTRADE_PASSWORD"}:
            values[key] = value
    return values


def write_client_env(config: CliConfig) -> Path:
    path = client_env_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    content = "\n".join(
        [
            f"HYPERTRADE_API_URL={_quote_shell_value(config.api_url)}",
            f"HYPERTRADE_USERNAME={_quote_shell_value(config.username)}",
            f"HYPERTRADE_PASSWORD={_quote_shell_value(config.password)}",
        ]
    )
    path.write_text(f"{content}\n")
    path.chmod(0o600)
    return path


def _quote_shell_value(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


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
            timeout=_request_timeout(config.timeout_seconds),
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
            timeout=_stream_timeout(config=self.config),
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

    def search_memory(self, query: str) -> list[dict[str, Any]]:
        return self._get_list(f"/api/memory?query={quote(query)}", "items")

    def disable_memory(self, memory_id: str) -> dict[str, Any]:
        response = self.client.delete(self._url(f"/api/memory/{memory_id}"))
        response.raise_for_status()
        payload = response.json()
        return dict(payload) if isinstance(payload, dict) else {"status": "ok"}

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self._get_list(f"/api/rag/search?query={quote(query)}&limit={limit}", "hits")

    def get_evals_status(self) -> dict[str, Any]:
        return self._get_object("/api/evals/status")

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return self._get_list("/api/strategy/research", "items")

    def list_backtests(self) -> list[dict[str, Any]]:
        return self._get_list("/api/backtests", "items")

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        return self._post_object("/api/strategy/research", {"prompt": prompt})

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]:
        return self._post_object("/api/strategy/experiments", {"prompt": prompt})

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
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
                "candle_source": candle_source,
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

    def set_model(self, provider: str) -> dict[str, Any]:
        return self._post_object("/api/harness/provider-selection", {"provider": provider})

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

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"action": action}
        if symbol:
            body["symbol"] = symbol
        return self._post_object("/api/paper/control", body)

    def list_live_order_intents(self) -> list[dict[str, Any]]:
        return self._get_list("/api/live/order-intents", "items")

    def create_live_order_intent(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        return self._post_object(
            "/api/live/order-intents",
            {
                "symbol": symbol,
                "side": side,
                "size": size,
                "order_type": order_type,
                "price": price,
                "reason": reason,
            },
        )

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        return self._post_object(
            f"/api/live/order-intents/{intent_id}/{decision}",
            {"reason": reason},
        )

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]:
        return self._post_object(f"/api/live/order-intents/{intent_id}/execute", {})

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


def _request_timeout(timeout_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(timeout=timeout_seconds)


def _stream_timeout(*, config: CliConfig) -> httpx.Timeout:
    # Long-running tools such as BitPro backtests may be silent while the server
    # waits for the upstream job. Keep connect/write/pool bounded, but do not
    # abort an active SSE stream merely because no event arrived for a while.
    return httpx.Timeout(timeout=config.timeout_seconds, read=None)


class LocalAgentClient:
    def __init__(self, *, settings: Settings | None = None, db: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = db or Database(self.settings.database_url)
        self.selected_provider = self.settings.active_chat_provider

    def login(self) -> None:
        return None

    def run_agent(self, prompt: str) -> dict[str, Any]:
        run = AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
            provider_name=self.selected_provider,
        ).run_chat(prompt)
        return _completed_run_to_dict(run)

    def run_agent_events(self, prompt: str) -> Iterator[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        run = AgentKernel(
            self.db,
            knowledge_dir=str(self.settings.knowledge_dir),
            settings=self.settings,
            provider_name=self.selected_provider,
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
                "tags": item.tags,
                "usage_count": item.usage_count,
            }
            for item in MemoryService(self.db).list_active()[-10:]
        ]

    def search_memory(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "id": item.id,
                "kind": item.kind,
                "content": item.content,
                "source_run_id": item.source_run_id,
                "tags": item.tags,
                "usage_count": item.usage_count,
            }
            for item in MemoryService(self.db).search(query=query)
        ]

    def disable_memory(self, memory_id: str) -> dict[str, Any]:
        MemoryService(self.db).disable(memory_id)
        return {"status": "ok"}

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        from hypertrade.rag.service import RagService

        service = RagService(self.db, knowledge_dir=str(self.settings.knowledge_dir))
        service.scan_once()
        return [
            {
                "source_path": hit.source_path,
                "title": hit.title,
                "chunk_index": hit.chunk_index,
                "score": hit.score,
                "content_preview": hit.content_preview,
            }
            for hit in service.search(query, limit=limit)
        ]

    def get_evals_status(self) -> dict[str, Any]:
        return AgentEvalSuite().status()

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return StrategyResearchService(self.db).list_recent(limit=10)

    def list_backtests(self) -> list[dict[str, Any]]:
        return BacktestService(self.db).list_recent(limit=10)

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        return StrategyResearchService(self.db).create(prompt)

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]:
        return StrategyExperimentService(self.db).create(prompt)

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
    ) -> dict[str, Any]:
        return BacktestService(self.db, settings=self.settings).run(
            research_id=research_id,
            strategy_key=strategy_key,
            use_live_candles=use_live_candles,
            symbol=symbol,
            bar=bar,
            candle_limit=candle_limit,
            candle_source=candle_source,
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
        providers = ProviderRuntime(self.settings).list_providers(selected=self.selected_provider)
        provider = next(
            (
                item
                for item in providers
                if item.get("name") == self.selected_provider
            ),
            providers[0],
        )
        return {
            "default_provider": provider["name"],
            "model": provider["model"],
            "providers": providers,
        }

    def set_model(self, provider: str) -> dict[str, Any]:
        requested = provider.strip().lower()
        providers = ProviderRuntime(self.settings).list_providers(selected=requested)
        if requested not in {str(item.get("name")) for item in providers}:
            raise ValueError(f"unknown provider: {provider}")
        self.selected_provider = requested
        selected = next(item for item in providers if item.get("name") == requested)
        return {
            "default_provider": requested,
            "model": selected.get("model", ""),
            "providers": providers,
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

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]:
        from hypertrade.paper.service import PaperTradingService

        service = PaperTradingService(self.db, settings=self.settings)
        if action == "pause":
            return service.pause()
        if action == "resume":
            return service.resume()
        if action == "close":
            return service.close(symbol=symbol)
        if action == "reset":
            return service.reset()
        raise ValueError(f"unknown paper action: {action}")

    def list_live_order_intents(self) -> list[dict[str, Any]]:
        from hypertrade.live.service import LiveOrderIntentService

        return LiveOrderIntentService(self.db, settings=self.settings).list_recent()

    def create_live_order_intent(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        from hypertrade.live.service import LiveOrderIntentService

        return LiveOrderIntentService(self.db, settings=self.settings).create(
            symbol=symbol,
            side=side,
            size=size,
            order_type=order_type,
            price=price,
            reason=reason,
            source="cli",
        )

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        from hypertrade.live.service import LiveOrderIntentService

        service = LiveOrderIntentService(self.db, settings=self.settings)
        if decision == "approve":
            return service.approve(intent_id, reason=reason)
        if decision == "reject":
            return service.reject(intent_id, reason=reason)
        raise ValueError(f"unknown live order decision: {decision}")

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]:
        from hypertrade.live.service import LiveOrderIntentService

        return LiveOrderIntentService(self.db, settings=self.settings).execute(intent_id)


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
    if args.command in {"login", "/login"}:
        configure_remote_login(input_fn=input_fn, output=output)
        return 0
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


def configure_remote_login(
    *,
    input_fn: Callable[[str], str] = input,
    output: TextIO,
) -> CliConfig:
    api_url = input_fn(f"HyperTrade API URL [{DEFAULT_REMOTE_API_URL}]: ").strip()
    username = input_fn("HyperTrade username [admin]: ").strip()
    password = _read_password(input_fn)
    config = CliConfig(
        api_url=api_url or DEFAULT_REMOTE_API_URL,
        username=username or "admin",
        password=password,
    )
    if not config.password:
        raise SystemExit("HyperTrade password cannot be empty.")
    path = write_client_env(config)
    print(f"HyperTrade login saved: {path}", file=output)
    print("Next time you can run: ht", file=output)
    print('Or one-shot: ht ask "看下 ETH 行情"', file=output)
    return config


def _read_password(input_fn: Callable[[str], str]) -> str:
    if input_fn is input and sys.stdin.isatty():
        return getpass.getpass("HyperTrade password: ").strip()
    return input_fn("HyperTrade password: ").strip()


def run_chat(
    *,
    client: AgentClient,
    input_fn: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> None:
    output = output or sys.stdout
    client.login()
    render_welcome_banner(client=client, output=output)
    history = configure_interactive_history(
        enabled=input_fn is input and sys.stdin.isatty()
    )
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
        history.add(prompt)
        if prompt.startswith("/"):
            # Slash commands are deterministic shortcuts. They inspect or run a
            # specific tool surface without starting a free-form Agent run.
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
        f"{color['subtitle']}   A crypto trading agent for market research and execution   "
        f"{color['reset']}"
        f"{color['border']}║{color['reset']}",
        file=output,
    )
    print(
        f"{color['border']}╚══════════════════════════════════════════════════════════════╝{color['reset']}",
        file=output,
    )
    print(f"{color['section']}Quick Start{color['reset']}", file=output)
    print(f"{color['cmd']}- /status{color['reset']}        Runtime and session status", file=output)
    print(f"{color['cmd']}- /tools{color['reset']}         Registered tool catalog", file=output)
    print(f"{color['cmd']}- /price ETH{color['reset']}     Exact ticker shortcut", file=output)
    print(f"{color['cmd']}- /compare ETH SOL{color['reset']} Relative strength", file=output)
    print(f"{color['cmd']}- /paper status{color['reset']}  Paper trading state", file=output)
    print(f"{color['cmd']}- /paper close ETH{color['reset']} Close paper position", file=output)
    print(f"{color['cmd']}- /live intents{color['reset']} Pending order approvals", file=output)
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
    colors = _semantic_colors(output)
    return {
        "reset": colors["reset"],
        "border": colors["border"],
        "title": colors["title"],
        "subtitle": colors["subtitle"],
        "section": colors["section"],
        "cmd": colors["command"],
        "label": colors["label"],
        "value": colors["value"],
        "muted": colors["muted"],
    }


def _semantic_colors(output: TextIO) -> dict[str, str]:
    supports_color = not os.getenv("NO_COLOR") and bool(getattr(output, "isatty", lambda: False)())
    keys = (
        "reset",
        "border",
        "title",
        "subtitle",
        "section",
        "command",
        "tool",
        "category",
        "approval",
        "label",
        "value",
        "muted",
        "info",
        "success",
        "warning",
        "error",
    )
    if not supports_color:
        return dict.fromkeys(keys, "")
    return {
        "reset": "\033[0m",
        "border": "\033[38;5;81m",
        "title": "\033[1;38;5;45m",
        "subtitle": "\033[38;5;117m",
        "section": "\033[1;38;5;183m",
        "command": "\033[38;5;121m",
        "tool": "\033[38;5;111m",
        "category": "\033[38;5;110m",
        "approval": "\033[1;38;5;214m",
        "label": "\033[38;5;110m",
        "value": "\033[1;38;5;159m",
        "muted": "\033[38;5;246m",
        "info": "\033[38;5;117m",
        "success": "\033[38;5;120m",
        "warning": "\033[38;5;214m",
        "error": "\033[38;5;203m",
    }


def _paint(text: object, style: str, *, output: TextIO) -> str:
    value = str(text)
    colors = _semantic_colors(output)
    prefix = colors.get(style, "")
    reset = colors.get("reset", "")
    if not prefix:
        return value
    return f"{prefix}{value}{reset}"


def handle_slash_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    name = command.split(maxsplit=1)[0].lower()
    # Keep this dispatcher flat and explicit so CLI -> Agent/tool/API wiring is
    # easy to audit during production operations.
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
        handle_memory_command(command, client=client, output=output)
    elif name == "/rag":
        handle_rag_command(command, client=client, output=output)
    elif name in {"/evals", "/eval"}:
        render_evals_status(client.get_evals_status(), output=output)
    elif name in {"/strategy", "/strategies"}:
        render_strategy_research(client.list_strategy_research(), output=output)
    elif name == "/backtests":
        render_backtests(client.list_backtests(), output=output)
    elif name == "/backtest":
        handle_backtest_command(command, client=client, output=output)
    elif name in {"/research", "/sr"}:
        handle_research_command(command, client=client, output=output)
    elif name in {"/experiment", "/exp"}:
        handle_experiment_command(command, client=client, output=output)
    elif name in {"/price", "/ticker"}:
        handle_price_command(command, client=client, output=output)
    elif name in {"/candles", "/kline", "/klines"}:
        handle_candles_command(command, client=client, output=output)
    elif name == "/compare":
        handle_compare_command(command, client=client, output=output)
    elif name == "/paper":
        handle_paper_command(command, client=client, output=output)
    elif name == "/live":
        handle_live_command(command, client=client, output=output)
    else:
        print(f"Unknown command: {name}", file=output)
        render_slash_help(output=output)


def render_slash_help(*, output: TextIO) -> None:
    print(_paint("Slash commands:", "section", output=output), file=output)
    command_width = max(len(command) for command, _ in SLASH_COMMAND_HELP)
    for command, description in SLASH_COMMAND_HELP:
        padded_command = f"{command:<{command_width}}"
        print(
            f"- {_paint(padded_command, 'command', output=output)}  "
            f"{_paint(description, 'muted', output=output)}",
            file=output,
        )


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


def handle_experiment_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=1)
    if len(parts) == 1:
        print("Usage: /experiment <prompt>", file=output)
        print("Example: /experiment 研究ETH趋势突破并给出回测改进建议", file=output)
        return
    try:
        experiment = client.create_strategy_experiment(parts[1].strip())
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Experiment failed: {exc}", file=output)
        return
    render_strategy_experiment_result(experiment, output=output)


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
            candle_source=str(options["candle_source"]),
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
    if subcommand == "close":
        symbol = parts[2] if len(parts) > 2 else None
        try:
            result = client.control_paper("close", symbol=symbol)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper close failed: {exc}", file=output)
            return
        print(f"Paper close: {result.get('closed_count', 0)} positions", file=output)
        closed = result.get("closed", [])
        if isinstance(closed, list):
            for row in closed[:10]:
                if not isinstance(row, dict):
                    continue
                print(
                    "- {inst_id} {side} exit={exit_price} realized_pnl={realized_pnl}".format(
                        inst_id=row.get("inst_id", "unknown"),
                        side=row.get("side", "unknown"),
                        exit_price=row.get("exit_price", "n/a"),
                        realized_pnl=row.get("realized_pnl", "n/a"),
                    ),
                    file=output,
                )
        return
    if subcommand == "reset":
        try:
            result = client.control_paper("reset")
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Paper reset failed: {exc}", file=output)
            return
        session = result.get("session", {})
        session_id = session.get("id", "unknown") if isinstance(session, dict) else "unknown"
        print(f"Paper reset: new session {session_id}", file=output)
        return
    print("Usage: /paper status|pause|resume|close [symbol]|reset", file=output)


def handle_live_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split()
    subcommand = parts[1].lower() if len(parts) > 1 else "intents"
    if subcommand in {"intents", "list", "ls"}:
        try:
            render_live_order_intents(client.list_live_order_intents(), output=output)
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live intents failed: {exc}", file=output)
        return
    if subcommand == "intent":
        if len(parts) < 5:
            print(
                "Usage: /live intent <symbol> <buy|sell> <size> [--type market|limit]",
                file=output,
            )
            return
        options = _parse_live_intent_options(parts[5:])
        try:
            intent = client.create_live_order_intent(
                symbol=parts[2],
                side=parts[3],
                size=parts[4],
                order_type=str(options["order_type"]),
                price=options["price"],
                reason=str(options["reason"]),
            )
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live intent failed: {exc}", file=output)
            return
        render_live_order_intent(intent, output=output)
        return
    if subcommand in {"approve", "reject"}:
        if len(parts) < 3:
            print(f"Usage: /live {subcommand} <intent_id> [--reason text]", file=output)
            return
        options = _parse_reason_option(parts[3:])
        try:
            intent = client.decide_live_order_intent(
                parts[2],
                decision=subcommand,
                reason=str(options["reason"]),
            )
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live {subcommand} failed: {exc}", file=output)
            return
        render_live_order_intent(intent, output=output)
        return
    if subcommand == "execute":
        if len(parts) < 3:
            print("Usage: /live execute <intent_id>", file=output)
            return
        try:
            intent = client.execute_live_order_intent(parts[2])
        except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
            print(f"Live execute failed: {exc}", file=output)
            return
        render_live_order_intent(intent, output=output)
        return
    print("Usage: /live intents|intent|approve|reject|execute", file=output)


def _parse_backtest_options(parts: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {
        "positionals": [],
        "use_live_candles": False,
        "symbol": "BTC",
        "bar": "1H",
        "candle_limit": 100,
        "candle_source": "sample",
    }
    index = 0
    while index < len(parts):
        part = parts[index]
        if part == "--live":
            options["use_live_candles"] = True
            options["candle_source"] = "okx"
        elif part == "--source" and index + 1 < len(parts):
            index += 1
            options["candle_source"] = parts[index].strip().lower()
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


def _parse_live_intent_options(parts: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {"order_type": "market", "price": None, "reason": ""}
    index = 0
    while index < len(parts):
        part = parts[index]
        if part in {"--type", "--order-type"} and index + 1 < len(parts):
            index += 1
            options["order_type"] = parts[index]
        elif part == "--price" and index + 1 < len(parts):
            index += 1
            options["price"] = parts[index]
        elif part == "--reason" and index + 1 < len(parts):
            options["reason"] = " ".join(parts[index + 1 :])
            break
        index += 1
    return options


def _parse_reason_option(parts: list[str]) -> dict[str, Any]:
    options: dict[str, Any] = {"reason": ""}
    if "--reason" in parts:
        index = parts.index("--reason")
        options["reason"] = " ".join(parts[index + 1 :])
    return options


def handle_memory_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=2)
    if len(parts) == 1:
        render_memory(client.list_memory(), output=output)
        return
    subcommand = parts[1].lower()
    if subcommand == "search":
        if len(parts) < 3 or not parts[2].strip():
            print("Usage: /memory search <query>", file=output)
            return
        render_memory(client.search_memory(parts[2].strip()), output=output)
        return
    if subcommand == "disable":
        if len(parts) < 3 or not parts[2].strip():
            print("Usage: /memory disable <mem_id>", file=output)
            return
        result = client.disable_memory(parts[2].strip())
        print(f"Memory disable: {result.get('status', 'ok')}", file=output)
        return
    print("Usage: /memory [search <query>|disable <mem_id>]", file=output)


def handle_rag_command(command: str, *, client: AgentClient, output: TextIO) -> None:
    parts = command.split(maxsplit=1)
    if len(parts) == 1 or not parts[1].strip():
        print("Usage: /rag <query>", file=output)
        return
    render_rag_hits(client.search_rag(parts[1].strip()), output=output)


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
    _render_markdown_report(
        str(research.get("report_markdown", "")),
        output=output,
        title="Strategy Research",
    )


def render_strategy_experiment_result(experiment: dict[str, Any], *, output: TextIO) -> None:
    print("Strategy experiment completed:", file=output)
    print(f"- ID: {experiment.get('id', 'unknown')}", file=output)
    print(f"- Research: {experiment.get('research_id', 'n/a')}", file=output)
    print(f"- Backtest: {experiment.get('backtest_id', 'n/a')}", file=output)
    print(f"- Status: {experiment.get('status', 'unknown')}", file=output)
    print("", file=output)
    _render_markdown_report(
        str(experiment.get("report_markdown", "")),
        output=output,
        title="Strategy Experiment",
    )


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
    _render_markdown_report(
        str(result.get("report_markdown", "")),
        output=output,
        title="Backtest Report",
    )


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


def render_live_order_intents(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("Live order intents:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:20]:
        render_live_order_intent(item, output=output)


def render_live_order_intent(intent: dict[str, Any], *, output: TextIO) -> None:
    print(
        "- {id} {status} {environment} {inst_id} {side} {size} {order_type}{price}".format(
            id=intent.get("id", "unknown"),
            status=intent.get("status", "unknown"),
            environment=intent.get("environment", "unknown"),
            inst_id=intent.get("inst_id", "unknown"),
            side=intent.get("side", "unknown"),
            size=intent.get("size", "n/a"),
            order_type=intent.get("order_type", "market"),
            price=f" price={intent.get('price')}" if intent.get("price") else "",
        ),
        file=output,
    )
    reason = intent.get("reason")
    if reason:
        print(f"  reason: {reason}", file=output)
    decision_reason = intent.get("decision_reason")
    if decision_reason:
        print(f"  decision: {decision_reason}", file=output)
    risk_status = intent.get("risk_status")
    if risk_status:
        print(f"  risk: {risk_status}", file=output)
    exchange_order_id = intent.get("exchange_order_id")
    if exchange_order_id:
        print(f"  exchange_order_id: {exchange_order_id}", file=output)


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
        print("- Switch: /model <provider>", file=output)
        return
    requested = parts[1].strip()
    try:
        switched = client.set_model(requested)
    except Exception as exc:  # noqa: BLE001 - surface CLI-friendly errors
        print(f"Model switch failed: {exc}", file=output)
        return
    print(f"Model switched: {switched.get('default_provider', requested)}", file=output)
    print(f"- Model: {switched.get('model', 'unknown')}", file=output)


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
    print(_paint("Tools:", "section", output=output), file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items:
        description = str(item.get("description") or "No description configured.")
        gate = (
            f" {_paint('approval', 'approval', output=output)}"
            if item.get("requires_approval")
            else ""
        )
        name = _paint(item.get("name", "unknown"), "tool", output=output)
        category = _paint(f"[{item.get('category', 'unknown')}]", "category", output=output)
        print(
            f"- {name} {category}{gate}: "
            f"{_paint(description, 'muted', output=output)}",
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
        tags = item.get("tags", [])
        tag_text = ",".join(str(tag) for tag in tags) if isinstance(tags, list) else ""
        print(
            f"- {item.get('id', 'unknown')} [{item.get('kind', 'unknown')}] "
            f"{str(item.get('content', ''))[:100]}",
            file=output,
        )
        if tag_text:
            print(
                f"  tags: {tag_text} usage={item.get('usage_count', 0)}",
                file=output,
            )


def render_rag_hits(items: list[dict[str, Any]], *, output: TextIO) -> None:
    print("RAG hits:", file=output)
    if not items:
        print("- none", file=output)
        return
    for item in items[:10]:
        print(
            "- {title} {source_path}#{chunk_index} score={score}".format(
                title=item.get("title", "Knowledge"),
                source_path=item.get("source_path", "unknown"),
                chunk_index=item.get("chunk_index", 0),
                score=item.get("score", "n/a"),
            ),
            file=output,
        )
        preview = str(item.get("content_preview", "")).replace("\n", " ")[:160]
        if preview:
            print(f"  {preview}", file=output)


def render_evals_status(payload: dict[str, Any], *, output: TextIO) -> None:
    print("Eval suite:", file=output)
    print(f"- Status: {payload.get('status', 'unknown')}", file=output)
    cases = payload.get("cases", [])
    if not isinstance(cases, list) or not cases:
        print("- no cases", file=output)
        return
    for case in cases:
        if not isinstance(case, dict):
            continue
        print(
            f"- {case.get('name', 'unknown')} {case.get('status', 'unknown')}",
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
    _render_markdown_report(
        str(run.get("report_markdown", "")),
        output=output,
        title="Agent Report",
    )


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
        from rich.markdown import Markdown
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        return False

    console = Console(
        file=output,
        force_terminal=True,
        color_system=_rich_color_system(),
        width=120,
    )
    trace_events = run.get("trace_events", [])
    report = run.get("report_json", {})
    has_structured_market_summary = isinstance(report, dict) and isinstance(
        report.get("top_movers"),
        list,
    )
    has_structured_tools = isinstance(trace_events, list) and _has_structured_market_tool_output(
        trace_events
    )
    raw_markdown = _strip_report_icons(str(run.get("report_markdown", ""))).strip()
    if not has_structured_market_summary and not has_structured_tools and not raw_markdown:
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
        _render_rich_trace_summary(trace_events, console=console)

    if has_structured_market_summary and isinstance(report, dict):
        _render_rich_market_summary(report, console=console)
    elif has_structured_tools and isinstance(trace_events, list):
        _render_rich_tool_report(trace_events, report=report, console=console)
    else:
        console.print(
            Panel(Markdown(raw_markdown), title="Agent Report", border_style="green")
        )

    return True


def _render_rich_trace_summary(trace_events: list[Any], *, console: Any) -> None:
    from rich.table import Table
    from rich.text import Text

    full_trace = _show_full_trace()
    visible_events, folded_events = _partition_trace_events(trace_events, full_trace=full_trace)
    if not visible_events and folded_events:
        console.print(
            Text(
                "Trace folded: "
                f"{len(folded_events)} internal events hidden "
                "(graph/preflight/nested BitPro). "
                "Set HYPERTRADE_TRACE=full to show all.",
                style="dim",
            )
        )
        return

    title = "Tool Trace" if full_trace else "Tool Trace Summary"
    tools = Table(title=title, show_header=True, header_style="bold")
    tools.add_column("Tool")
    tools.add_column("Status")
    if not full_trace:
        tools.add_column("Calls", justify="right")
        for row in _aggregate_trace_events(visible_events):
            tools.add_row(row["tool"], row["status"], str(row["count"]))
    else:
        for event in visible_events:
            tools.add_row(str(event.get("tool_name", "unknown")), str(event.get("status", "n/a")))
    console.print(tools)
    if folded_events:
        console.print(
            Text(
                "Trace folded: "
                f"{len(folded_events)} internal events hidden "
                "(graph/preflight/nested BitPro). "
                "Set HYPERTRADE_TRACE=full to show all.",
                style="dim",
            )
        )


def _show_full_trace() -> bool:
    value = os.getenv("HYPERTRADE_TRACE", "summary").strip().lower()
    return value in {"all", "debug", "full", "verbose"}


def _partition_trace_events(
    trace_events: list[Any],
    *,
    full_trace: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = [event for event in trace_events if isinstance(event, dict)]
    if full_trace:
        return events, []
    high_level_bitpro = {
        str(event.get("tool_name", ""))
        for event in events
        if str(event.get("tool_name", "")).startswith("bitpro_")
    }
    visible: list[dict[str, Any]] = []
    folded: list[dict[str, Any]] = []
    for event in events:
        if _is_folded_trace_event(event, high_level_bitpro=high_level_bitpro):
            folded.append(event)
        else:
            visible.append(event)
    return visible, folded


def _is_folded_trace_event(
    event: dict[str, Any],
    *,
    high_level_bitpro: set[str],
) -> bool:
    tool_name = str(event.get("tool_name", ""))
    if tool_name.startswith("graph."):
        return True
    if tool_name in {
        "bitpro.capabilities",
        "bitpro.health",
        "bitpro_capabilities",
        "bitpro_health",
    }:
        return True
    return tool_name.startswith("bitpro.") and bool(high_level_bitpro)


def _aggregate_trace_events(trace_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for event in trace_events:
        tool_name = str(event.get("tool_name", "unknown"))
        status = str(event.get("status", "n/a"))
        key = (tool_name, status)
        if key not in index:
            row = {"tool": tool_name, "status": status, "count": 0}
            index[key] = row
            rows.append(row)
        index[key]["count"] += 1
    return rows


def _render_markdown_report(markdown: str, *, output: TextIO, title: str) -> None:
    markdown = _strip_report_icons(markdown)
    if _should_render_rich(output) and _render_rich_markdown(markdown, output=output, title=title):
        return
    print(markdown, file=output)


def _render_rich_markdown(markdown: str, *, output: TextIO, title: str) -> bool:
    markdown = _strip_report_icons(markdown).strip()
    if not markdown:
        return False
    try:
        from rich.console import Console
        from rich.markdown import Markdown
        from rich.panel import Panel
    except ImportError:
        return False

    console = Console(
        file=output,
        force_terminal=True,
        color_system=_rich_color_system(),
        width=120,
    )
    console.print(Panel(Markdown(markdown), title=title, border_style="green"))
    return True


def _rich_color_system() -> Literal["standard"] | None:
    return None if os.getenv("NO_COLOR") else "standard"


def _strip_report_icons(markdown: str) -> str:
    lines = [
        "".join(ch for ch in line if not _is_report_icon_char(ch))
        for line in markdown.splitlines()
    ]
    return "\n".join(_normalize_markdown_line_spacing(line) for line in lines)


def _is_report_icon_char(ch: str) -> bool:
    codepoint = ord(ch)
    return (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0xFE00 <= codepoint <= 0xFE0F
    )


def _normalize_markdown_line_spacing(line: str) -> str:
    if not line:
        return line
    if line.startswith("#"):
        marker_length = 0
        while marker_length < len(line) and line[marker_length] == "#":
            marker_length += 1
        marker = line[:marker_length]
        body = line[marker_length:].strip()
        return f"{marker} {body}" if body else marker
    if line.startswith("-"):
        body = line[1:].strip()
        return f"- {body}" if body else "-"
    return line


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
        elif tool_name == "bitpro_backtest_list_results":
            _render_rich_bitpro_backtest_results(payload, console=console)
        elif tool_name == "bitpro_backtest_get_result":
            _render_rich_bitpro_backtest_detail(payload, console=console)
        elif tool_name == "bitpro_paper_dashboard":
            _render_rich_bitpro_paper_dashboard(payload, console=console)
        elif tool_name == "bitpro_paper_events":
            _render_rich_bitpro_paper_events(payload, console=console)
        elif tool_name == "bitpro_paper_equity_curve":
            _render_rich_bitpro_paper_equity_curve(payload, console=console)


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


def _render_rich_bitpro_paper_dashboard(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    dashboard = payload.get("dashboard")
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    system = dashboard.get("system")
    system = system if isinstance(system, dict) else {}
    equity = dashboard.get("equity")
    equity = equity if isinstance(equity, dict) else {}
    performance = dashboard.get("performance")
    performance = performance if isinstance(performance, dict) else {}
    scope = payload.get("paper_scope")
    scope = scope if isinstance(scope, dict) else {}
    running = payload.get("running_strategies")
    running = running if isinstance(running, dict) else {}
    monitor = payload.get("monitor_summary")
    monitor = monitor if isinstance(monitor, dict) else {}
    inventory = monitor.get("running_inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    alerts = monitor.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    data_gaps = monitor.get("data_gaps")
    data_gaps = data_gaps if isinstance(data_gaps, list) else []
    actions = monitor.get("recommended_actions")
    actions = actions if isinstance(actions, list) else []

    listed = inventory.get("listed_count", 0)
    total = inventory.get("reported_total", running.get("total", listed))
    coverage = "truncated" if inventory.get("is_truncated") else "complete"
    summary = "\n".join(
        [
            f"合同: {payload.get('contract_version', 'unknown')}",
            f"范围: {scope.get('dashboard_scope', 'unknown')}",
            (
                "当前: strategy_id={strategy_id}, {name}, state={state}, "
                "mode={mode}, uptime={uptime}"
            ).format(
                strategy_id=system.get("strategy_id", "n/a"),
                name=system.get("strategy", "n/a"),
                state=system.get("state", "n/a"),
                mode=system.get("mode", "n/a"),
                uptime=system.get("uptime", "n/a"),
            ),
            (
                "绩效: equity={equity}, pnl={pnl}, sharpe={sharpe}, drawdown={drawdown}"
            ).format(
                equity=_format_number(equity.get("current")),
                pnl=_format_percent(performance.get("total_pnl_pct")),
                sharpe=_format_number(performance.get("sharpe_ratio"), digits=4),
                drawdown=_format_percent(performance.get("max_drawdown")),
            ),
            (
                f"监控: {monitor.get('mode', 'unknown')} | "
                f"running listed={listed}, total={total}, {coverage}"
            ),
        ]
    )
    console.print(Panel(summary, title="BitPro 模拟盘监控", border_style="green"))

    if alerts or data_gaps or actions:
        table = Table(title="Monitor Findings", show_header=True, header_style="bold", expand=True)
        table.add_column("Type", ratio=2)
        table.add_column("Code", ratio=3)
        table.add_column("Message", ratio=7, overflow="fold")
        for alert in alerts:
            if isinstance(alert, dict):
                table.add_row(
                    str(alert.get("level", "info")),
                    str(alert.get("code", "unknown")),
                    str(alert.get("message", "n/a")),
                )
        for gap in data_gaps:
            table.add_row("gap", "-", str(gap))
        for action in actions:
            if isinstance(action, dict):
                table.add_row(
                    "action",
                    str(action.get("action", "observe")),
                    str(action.get("message", "n/a")),
                )
        console.print(table)


def _render_rich_bitpro_paper_events(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    summary = payload.get("event_summary")
    summary = summary if isinstance(summary, dict) else {}
    events = payload.get("events")
    events = events if isinstance(events, list) else []
    summary_text = "\n".join(
        [
            f"策略: {payload.get('strategy_id', 'all')}",
            (
                "事件: count={count}, sample={sample}, errors={errors}, latest={latest}"
            ).format(
                count=summary.get("count", len(events)),
                sample=summary.get("sample_count", len(events)),
                errors=summary.get("error_count", 0),
                latest=summary.get("latest_event_at", "n/a"),
            ),
            f"合同: {payload.get('contract_version', 'unknown')}",
        ]
    )
    console.print(Panel(summary_text, title="BitPro 模拟盘事件", border_style="yellow"))
    if events:
        table = Table(title="Paper Events", show_header=True, header_style="bold", expand=True)
        table.add_column("ID", ratio=1)
        table.add_column("Level", ratio=1)
        table.add_column("Type", ratio=2)
        table.add_column("Message", ratio=5, overflow="fold")
        table.add_column("Time", ratio=2)
        for event in events[:10]:
            if not isinstance(event, dict):
                continue
            table.add_row(
                str(event.get("id", "n/a")),
                str(event.get("level", "info")),
                str(event.get("type", "event")),
                str(event.get("message", "n/a")),
                str(event.get("timestamp", "n/a")),
            )
        console.print(table)


def _render_rich_bitpro_paper_equity_curve(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    summary = payload.get("equity_summary")
    summary = summary if isinstance(summary, dict) else {}
    points = payload.get("equity_curve")
    points = points if isinstance(points, list) else []
    summary_text = "\n".join(
        [
            f"策略: {payload.get('strategy_id', 'all')}",
            (
                "权益: points={count}, sample={sample}, latest={latest}, "
                "latest_drawdown={latest_dd}, max_drawdown={max_dd}"
            ).format(
                count=summary.get("count", len(points)),
                sample=summary.get("sample_count", len(points)),
                latest=summary.get("latest_equity", "n/a"),
                latest_dd=_format_percent(summary.get("latest_drawdown_pct")),
                max_dd=_format_percent(summary.get("max_drawdown_pct")),
            ),
            f"合同: {payload.get('contract_version', 'unknown')}",
        ]
    )
    console.print(Panel(summary_text, title="BitPro 模拟盘权益曲线", border_style="cyan"))
    if points:
        table = Table(
            title="Paper Equity Curve",
            show_header=True,
            header_style="bold",
            expand=True,
        )
        table.add_column("Time", ratio=2)
        table.add_column("Equity", justify="right", ratio=2)
        table.add_column("Drawdown", justify="right", ratio=2)
        for point in points[:10]:
            if not isinstance(point, dict):
                continue
            table.add_row(
                str(point.get("timestamp", "n/a")),
                str(point.get("equity", "n/a")),
                _format_percent(point.get("drawdown_pct")),
            )
        console.print(table)


def _render_rich_bitpro_backtest_results(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    result_filter = payload.get("filter")
    result_filter = result_filter if isinstance(result_filter, dict) else {}
    metric = str(result_filter.get("metric", "total_return_pct"))
    min_return = result_filter.get("min_total_return_pct")
    filter_text = (
        f"{metric} > {_format_percent(min_return)}"
        if min_return is not None
        else "未设置收益阈值"
    )
    results = payload.get("results")
    results = results if isinstance(results, list) else []
    top_result = next((row for row in results if isinstance(row, dict)), None)
    top_line = "最高: n/a"
    if top_result is not None:
        top_line = (
            "最高: result #{id} / strategy #{strategy_id} | "
            "总收益 {total_return} | 回撤 {drawdown} | 交易 {trades}"
        ).format(
            id=top_result.get("id", "n/a"),
            strategy_id=top_result.get("strategy_id", "n/a"),
            total_return=_format_percent(top_result.get("total_return_pct")),
            drawdown=_format_percent(top_result.get("max_drawdown_pct")),
            trades=top_result.get("trade_count", "n/a"),
        )
    summary = "\n".join(
        [
            f"总收益口径: {metric}",
            f"筛选: {filter_text}",
            (
                f"命中 {payload.get('result_count', 0)} / "
                f"原始 {payload.get('raw_result_count', 'n/a')}"
            ),
            top_line,
            f"合同: {payload.get('contract_version', 'unknown')}",
        ]
    )
    console.print(Panel(summary, title="BitPro 回测排行", border_style="green"))

    if not results:
        console.print(Panel("没有匹配的 BitPro 回测结果。", border_style="yellow"))
        return

    table = Table(title="Top Results", show_header=True, header_style="bold", expand=True)
    table.add_column("#", justify="right", no_wrap=True, ratio=1)
    table.add_column("策略", ratio=6, overflow="fold")
    table.add_column("收益", ratio=2, overflow="fold")
    table.add_column("风险/质量", ratio=3, overflow="fold")
    table.add_column("区间", ratio=3, overflow="fold")
    for index, row in enumerate(results[:20], start=1):
        if not isinstance(row, dict):
            continue
        table.add_row(
            str(index),
            (
                f"result #{row.get('id', 'n/a')} / strategy #{row.get('strategy_id', 'n/a')}\n"
                f"{_format_strategy_name(row.get('strategy_name', 'n/a'))}"
            ),
            (
                f"总 {_format_percent(row.get('total_return_pct'))}\n"
                f"年 {_format_percent(row.get('annual_return_pct'))}"
            ),
            (
                f"回撤 {_format_percent(row.get('max_drawdown_pct'))}\n"
                f"夏普 {_format_number(row.get('sharpe_ratio'))}\n"
                f"胜率 {_format_percent(row.get('win_rate_pct'))}\n"
                f"交易 {row.get('trade_count', 'n/a')}"
            ),
            _format_period(row.get("start_date"), row.get("end_date")),
        )
    console.print(table)


_BITPRO_ARTIFACT_LABELS = {
    "equity_curve": "权益曲线",
    "trades": "交易",
    "orders": "订单",
    "fills": "成交",
    "drawdown_series": "回撤序列",
}


def _render_rich_bitpro_backtest_detail(payload: dict[str, Any], *, console: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    result = payload.get("result")
    result = result if isinstance(result, dict) else {}
    metrics = result.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    summary = "\n".join(
        [
            (
                f"result #{result.get('id', payload.get('backtest_id', 'n/a'))} / "
                f"strategy #{result.get('strategy_id', 'n/a')}"
            ),
            _format_strategy_name(result.get("strategy_name", "n/a")),
            (
                f"状态 {result.get('status', 'n/a')} | 周期 {result.get('timeframe', 'n/a')} | "
                f"区间 {_format_period(result.get('start_date'), result.get('end_date'))}"
            ),
        ]
    )
    console.print(Panel(summary, title="BitPro 回测详情", border_style="green"))

    metric_table = Table(title="核心指标", show_header=True, header_style="bold")
    metric_table.add_column("指标", no_wrap=True)
    metric_table.add_column("数值", justify="right")
    metric_table.add_row(
        "收益",
        Text(
            _format_percent(metrics.get("total_return_pct")),
            style=_rich_numeric_style(metrics.get("total_return_pct"), positive="green"),
        ),
    )
    metric_table.add_row(
        "最大回撤",
        Text(
            _format_percent(metrics.get("max_drawdown_pct")),
            style=_rich_drawdown_style(metrics.get("max_drawdown_pct")),
        ),
    )
    metric_table.add_row(
        "夏普",
        Text(
            _format_number(metrics.get("sharpe_ratio")),
            style=_rich_numeric_style(metrics.get("sharpe_ratio"), positive="cyan"),
        ),
    )
    metric_table.add_row(
        "胜率",
        Text(_format_percent(metrics.get("win_rate_pct")), style="cyan"),
    )
    metric_table.add_row("交易次数", Text(str(metrics.get("trade_count", "n/a")), style="white"))
    console.print(metric_table)

    artifact_summary = payload.get("artifact_summary")
    artifact_summary = artifact_summary if isinstance(artifact_summary, dict) else {}
    if not artifact_summary:
        return
    table = Table(title="数据样本", show_header=True, header_style="bold")
    table.add_column("数据")
    table.add_column("状态")
    table.add_column("条数", justify="right")
    table.add_column("展示", justify="right")
    for key, label in _BITPRO_ARTIFACT_LABELS.items():
        info = artifact_summary.get(key)
        if not isinstance(info, dict):
            continue
        table.add_row(
            label,
            "可用" if info.get("available") else "不可用",
            str(info.get("count", 0)),
            str(info.get("sample_count", 0)),
        )
    console.print(table)


def _rich_numeric_style(value: object, *, positive: str) -> str:
    number = _coerce_float(value)
    if number is None:
        return "dim"
    if number > 0:
        return positive
    if number < 0:
        return "red"
    return "white"


def _rich_drawdown_style(value: object) -> str:
    number = _coerce_float(value)
    if number is None:
        return "dim"
    if abs(number) <= 5:
        return "green"
    if abs(number) <= 15:
        return "yellow"
    return "red"


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


def _has_structured_market_tool_output(trace_events: list[Any]) -> bool:
    supported_tools = {
        "market_ticker",
        "market_candles",
        "market_compare",
        "bitpro_backtest_list_results",
        "bitpro_backtest_get_result",
        "bitpro_paper_dashboard",
        "bitpro_paper_events",
        "bitpro_paper_equity_curve",
    }
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
        elif tool_name == "bitpro_backtest_list_results":
            _render_tool_bitpro_backtest_block(payload, output=output)
        elif tool_name == "bitpro_backtest_get_result":
            _render_tool_bitpro_backtest_detail_block(payload, output=output)
        elif tool_name == "bitpro_paper_dashboard":
            _render_tool_bitpro_paper_block(payload, output=output)
        elif tool_name == "bitpro_paper_events":
            _render_tool_bitpro_paper_events_block(payload, output=output)
        elif tool_name == "bitpro_paper_equity_curve":
            _render_tool_bitpro_paper_equity_block(payload, output=output)

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


def _render_tool_bitpro_paper_block(payload: dict[str, Any], *, output: TextIO) -> None:
    dashboard = payload.get("dashboard")
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    system = dashboard.get("system")
    system = system if isinstance(system, dict) else {}
    equity = dashboard.get("equity")
    equity = equity if isinstance(equity, dict) else {}
    performance = dashboard.get("performance")
    performance = performance if isinstance(performance, dict) else {}
    scope = payload.get("paper_scope")
    scope = scope if isinstance(scope, dict) else {}
    running = payload.get("running_strategies")
    running = running if isinstance(running, dict) else {}
    monitor = payload.get("monitor_summary")
    monitor = monitor if isinstance(monitor, dict) else {}
    inventory = monitor.get("running_inventory")
    inventory = inventory if isinstance(inventory, dict) else {}
    alerts = monitor.get("alerts")
    alerts = alerts if isinstance(alerts, list) else []
    data_gaps = monitor.get("data_gaps")
    data_gaps = data_gaps if isinstance(data_gaps, list) else []
    actions = monitor.get("recommended_actions")
    actions = actions if isinstance(actions, list) else []

    print("", file=output)
    print("BitPro Paper Monitor:", file=output)
    print(f"- Contract: {payload.get('contract_version', 'unknown')}", file=output)
    print(f"- Dashboard scope: {scope.get('dashboard_scope', 'unknown')}", file=output)
    print(
        "- Current dashboard: strategy_id={strategy_id}, {name}, "
        "state={state}, mode={mode}, uptime={uptime}".format(
            strategy_id=system.get("strategy_id", "n/a"),
            name=system.get("strategy", "n/a"),
            state=system.get("state", "n/a"),
            mode=system.get("mode", "n/a"),
            uptime=system.get("uptime", "n/a"),
        ),
        file=output,
    )
    print(
        "- Performance: equity={equity}, pnl={pnl}, sharpe={sharpe}, drawdown={drawdown}".format(
            equity=_format_number(equity.get("current")),
            pnl=_format_percent(performance.get("total_pnl_pct")),
            sharpe=_format_number(performance.get("sharpe_ratio"), digits=4),
            drawdown=_format_percent(performance.get("max_drawdown")),
        ),
        file=output,
    )
    if monitor:
        listed = inventory.get("listed_count", 0)
        total = inventory.get("reported_total", running.get("total", listed))
        state = "truncated" if inventory.get("is_truncated") else "complete"
        print(f"- Monitor: {monitor.get('mode', 'unknown')}", file=output)
        print(
            f"- Running coverage: listed={listed}, reported_total={total}, state={state}",
            file=output,
        )
        if alerts:
            print("- Alerts:", file=output)
            for alert in alerts:
                if isinstance(alert, dict):
                    print(
                        "  - {level}/{code}: {message}".format(
                            level=alert.get("level", "info"),
                            code=alert.get("code", "unknown"),
                            message=alert.get("message", "n/a"),
                        ),
                        file=output,
                    )
        if data_gaps:
            print("- Data gaps:", file=output)
            for gap in data_gaps:
                print(f"  - {gap}", file=output)
        if actions:
            print("- Suggested read-only actions:", file=output)
            for action in actions:
                if isinstance(action, dict):
                    print(
                        "  - {action}: {message}".format(
                            action=action.get("action", "observe"),
                            message=action.get("message", "n/a"),
                        ),
                        file=output,
                    )


def _render_tool_bitpro_paper_events_block(payload: dict[str, Any], *, output: TextIO) -> None:
    summary = payload.get("event_summary")
    summary = summary if isinstance(summary, dict) else {}
    events = payload.get("events")
    events = events if isinstance(events, list) else []

    print("", file=output)
    print("BitPro Paper Events:", file=output)
    print(f"- Strategy: {payload.get('strategy_id', 'all')}", file=output)
    print(
        "- Events: count={count}, sample={sample}, errors={errors}, latest={latest}".format(
            count=summary.get("count", len(events)),
            sample=summary.get("sample_count", len(events)),
            errors=summary.get("error_count", 0),
            latest=summary.get("latest_event_at", "n/a"),
        ),
        file=output,
    )
    for event in events[:10]:
        if not isinstance(event, dict):
            continue
        print(
            "- {id} {level}/{type}: {message} ({timestamp})".format(
                id=event.get("id", "n/a"),
                level=event.get("level", "info"),
                type=event.get("type", "event"),
                message=event.get("message", "n/a"),
                timestamp=event.get("timestamp", "n/a"),
            ),
            file=output,
        )


def _render_tool_bitpro_paper_equity_block(payload: dict[str, Any], *, output: TextIO) -> None:
    summary = payload.get("equity_summary")
    summary = summary if isinstance(summary, dict) else {}
    points = payload.get("equity_curve")
    points = points if isinstance(points, list) else []

    print("", file=output)
    print("BitPro Paper Equity Curve:", file=output)
    print(f"- Strategy: {payload.get('strategy_id', 'all')}", file=output)
    print(
        "- Equity: points={count}, sample={sample}, latest={latest}, "
        "max_drawdown={max_drawdown}%".format(
            count=summary.get("count", len(points)),
            sample=summary.get("sample_count", len(points)),
            latest=summary.get("latest_equity", "n/a"),
            max_drawdown=summary.get("max_drawdown_pct", "n/a"),
        ),
        file=output,
    )
    for point in points[:10]:
        if not isinstance(point, dict):
            continue
        print(
            "- {timestamp}: equity={equity}, drawdown={drawdown}%".format(
                timestamp=point.get("timestamp", "n/a"),
                equity=point.get("equity", "n/a"),
                drawdown=point.get("drawdown_pct", "n/a"),
            ),
            file=output,
        )


def _render_tool_bitpro_backtest_block(payload: dict[str, Any], *, output: TextIO) -> None:
    result_filter = payload.get("filter")
    result_filter = result_filter if isinstance(result_filter, dict) else {}
    metric = str(result_filter.get("metric", "total_return_pct"))
    min_return = result_filter.get("min_total_return_pct")
    filter_text = (
        f"{metric} > {_format_percent(min_return)}"
        if min_return is not None
        else "no return threshold"
    )
    print("", file=output)
    print("BitPro backtest ranking:", file=output)
    print(f"- Metric: {metric} (actual total backtest return)", file=output)
    print(f"- Filter: {filter_text}", file=output)
    print(
        "- Matches: {result_count} / raw {raw_count}".format(
            result_count=payload.get("result_count", 0),
            raw_count=payload.get("raw_result_count", "n/a"),
        ),
        file=output,
    )
    results = payload.get("results")
    results = results if isinstance(results, list) else []
    if not results:
        print("- No matching BitPro backtest results.", file=output)
        return
    print("Top results:", file=output)
    for index, row in enumerate(results[:20], start=1):
        if not isinstance(row, dict):
            continue
        print(
            (
                "- {rank}. result #{id} / strategy #{strategy_id}: {name} | "
                "return {total_return}, annual {annual_return}, "
                "drawdown {drawdown}, sharpe {sharpe}, win {win_rate}, "
                "trades {trades}, period {period}"
            ).format(
                rank=index,
                id=row.get("id", "n/a"),
                strategy_id=row.get("strategy_id", "n/a"),
                name=row.get("strategy_name", "n/a"),
                total_return=_format_percent(row.get("total_return_pct")),
                annual_return=_format_percent(row.get("annual_return_pct")),
                drawdown=_format_percent(row.get("max_drawdown_pct")),
                sharpe=_format_number(row.get("sharpe_ratio")),
                win_rate=_format_percent(row.get("win_rate_pct")),
                trades=row.get("trade_count", "n/a"),
                period=_format_period(row.get("start_date"), row.get("end_date")),
            ),
            file=output,
        )


def _render_tool_bitpro_backtest_detail_block(
    payload: dict[str, Any],
    *,
    output: TextIO,
) -> None:
    result = payload.get("result")
    result = result if isinstance(result, dict) else {}
    metrics = result.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    print("", file=output)
    print("BitPro 回测详情:", file=output)
    print(
        "- 结果: #{id} / strategy #{strategy_id}: {name}".format(
            id=result.get("id", payload.get("backtest_id", "n/a")),
            strategy_id=result.get("strategy_id", "n/a"),
            name=_format_strategy_name(result.get("strategy_name", "n/a")),
        ),
        file=output,
    )
    print(
        "- 状态: {status} | 周期: {timeframe} | 区间: {period}".format(
            status=result.get("status", "n/a"),
            timeframe=result.get("timeframe", "n/a"),
            period=_format_period(result.get("start_date"), result.get("end_date")),
        ),
        file=output,
    )
    print("- 核心指标:", file=output)
    print(f"  - 收益: {_format_percent(metrics.get('total_return_pct'))}", file=output)
    print(f"  - 最大回撤: {_format_percent(metrics.get('max_drawdown_pct'))}", file=output)
    print(f"  - 夏普: {_format_number(metrics.get('sharpe_ratio'))}", file=output)
    print(f"  - 胜率: {_format_percent(metrics.get('win_rate_pct'))}", file=output)
    print(f"  - 交易次数: {metrics.get('trade_count', 'n/a')}", file=output)
    artifact_summary = payload.get("artifact_summary")
    artifact_summary = artifact_summary if isinstance(artifact_summary, dict) else {}
    if artifact_summary:
        print("- 数据样本:", file=output)
        for key, label in _BITPRO_ARTIFACT_LABELS.items():
            info = artifact_summary.get(key)
            if not isinstance(info, dict):
                continue
            state = "可用" if info.get("available") else "不可用"
            print(
                "  - {label}: {state}，{count} 条，展示 {sample_count} 条样本".format(
                    label=label,
                    state=state,
                    count=info.get("count", 0),
                    sample_count=info.get("sample_count", 0),
                ),
                file=output,
            )


def _format_number(value: object, *, digits: int = 2) -> str:
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "n/a"}:
        return "n/a"
    number = _coerce_float(value)
    if number is None:
        return str(value)
    formatted = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _coerce_float(value: object) -> float | None:
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "n/a"}:
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _format_percent(value: object, *, digits: int = 2) -> str:
    text = _format_number(value, digits=digits)
    if text == "n/a":
        return text
    return f"{text}%"


def _format_strategy_name(value: object) -> str:
    text = str(value or "n/a").strip()
    parts = [part.strip() for part in text.split("·") if part.strip()]
    if len(parts) >= 2:
        return f"{parts[0]}\n{' · '.join(parts[1:])}"
    return text


def _format_period(start: object, end: object) -> str:
    start_text = str(start or "n/a")
    end_text = str(end or "n/a")
    if start_text == "n/a" and end_text == "n/a":
        return "n/a"
    return f"{start_text}\n{end_text}"


def render_run_stream(
    client: AgentClient,
    prompt: str,
    *,
    output: TextIO | None = None,
) -> None:
    output = output or sys.stdout
    animator = _ThinkingAnimator(output)
    try:
        events = client.run_agent_events(prompt)
    except AttributeError:
        animator.start("Thinking")
        try:
            run = client.run_agent(prompt)
        except httpx.HTTPError as exc:
            animator.stop()
            _print_remote_api_error(exc, output=output)
            return
        finally:
            animator.stop()
        render_run(run, output=output)
        return
    final_run: dict[str, Any] | None = None
    stream_failed = False
    animator.start("Thinking")
    try:
        for event in events:
            if not isinstance(event, dict):
                continue
            event_name = str(event.get("event", "message"))
            if event_name == "run_started":
                animator.print_line(
                    _status_line(
                        f"Agent status: run created ({event.get('run_id', 'pending')})",
                        "info",
                        output=output,
                    )
                )
                animator.print_line(
                    _status_line(
                        "Agent status: planning next tool call",
                        "muted",
                        output=output,
                    )
                )
                animator.update("Planning next tool call")
            elif event_name == "tool_started":
                tool_name = event.get("tool_name", "unknown")
                animator.print_line(
                    _status_line(
                        f"Agent status: executing tool {tool_name}",
                        "tool",
                        output=output,
                    )
                )
                animator.update(f"Executing tool {tool_name}")
            elif event_name == "tool_completed":
                tool_name = event.get("tool_name", "unknown")
                status = event.get("status", "completed")
                style = "success" if status == "completed" else "warning"
                animator.print_line(
                    _status_line(
                        f"Agent status: tool {tool_name} {status}",
                        style,
                        output=output,
                    )
                )
                animator.print_line(
                    _status_line("Agent status: planning next step", "muted", output=output)
                )
                animator.update("Planning next step")
            elif event_name == "run_completed":
                animator.print_line(
                    _status_line(
                        "Agent status: generating final report",
                        "info",
                        output=output,
                    )
                )
                animator.print_line(
                    _status_line(
                        f"Agent status: run completed ({event.get('run_id', 'unknown')})",
                        "success",
                        output=output,
                    )
                )
                animator.update("Generating final report")
                if isinstance(event.get("run"), dict):
                    final_run = dict(event["run"])
            elif event_name == "final" and isinstance(event.get("run"), dict):
                animator.update("Rendering final report")
                final_run = dict(event["run"])
            elif event_name == "error":
                animator.print_line(
                    _status_line(
                        f"Run failed: {event.get('error', 'unknown error')}",
                        "error",
                        output=output,
                    )
                )
    except httpx.HTTPError as exc:
        stream_failed = True
        animator.print_line(_status_line(_format_remote_api_error(exc), "error", output=output))
    finally:
        animator.stop()
    if stream_failed:
        return
    if final_run is not None:
        print("", file=output)
        render_run(final_run, output=output)
    else:
        print(
            _paint("Run stream ended without final report.", "warning", output=output),
            file=output,
        )


def _status_line(text: str, style: str, *, output: TextIO) -> str:
    return _paint(text, style, output=output)


def _format_remote_api_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code == 401:
            return (
                "Remote API request failed (401). "
                "Run ht /login again and confirm the username/password."
            )
        return (
            f"Remote API request failed ({status_code}). "
            "The service may be deploying, or the credentials may be invalid."
        )
    if isinstance(exc, httpx.ReadTimeout):
        return (
            "Remote API connection timed out while waiting for the run. "
            "The run may still be continuing remotely; retry in a moment or check /runs."
        )
    return (
        "Remote API connection failed. The run may still be continuing remotely; "
        "the network or service may have restarted. Retry in a moment or check /runs."
    )


def _print_remote_api_error(exc: httpx.HTTPError, *, output: TextIO) -> None:
    print(_paint(_format_remote_api_error(exc), "error", output=output), file=output)


class _ThinkingAnimator:
    def __init__(self, output: TextIO, *, interval_seconds: float = 0.12) -> None:
        self.output = output
        self.interval_seconds = interval_seconds
        self.enabled = _should_render_thinking_animation(output)
        self.started_at = 0.0
        self.frame_index = 0
        self.message = "Thinking"
        self.rendered = False
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def start(self, message: str) -> None:
        self.message = message
        self.started_at = time.monotonic()
        if not self.enabled:
            return
        self.thread = threading.Thread(target=self._run, daemon=True)
        with self.lock:
            self._render_locked()
        self.thread.start()

    def update(self, message: str) -> None:
        self.message = message
        if not self.enabled:
            return
        with self.lock:
            self._render_locked()

    def print_line(self, text: str) -> None:
        if not self.enabled:
            print(text, file=self.output)
            return
        with self.lock:
            self._clear_locked()
            print(text, file=self.output)
            self._render_locked()

    def stop(self) -> None:
        if not self.enabled:
            return
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=self.interval_seconds * 2)
        with self.lock:
            self._clear_locked()
            self.output.flush()

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            with self.lock:
                self.frame_index += 1
                self._render_locked()

    def _render_locked(self) -> None:
        elapsed_ms = int((time.monotonic() - self.started_at) * 1000)
        frame = THINKING_FRAMES[self.frame_index % len(THINKING_FRAMES)]
        first = f"+ Thought: {elapsed_ms}ms"
        second = f": {frame} {self.message}"
        if self.rendered:
            self.output.write("\x1b[2A")
        self.output.write(f"\r\x1b[2K{first}\n")
        self.output.write(f"\r\x1b[2K{second}\n")
        self.output.flush()
        self.rendered = True

    def _clear_locked(self) -> None:
        if not self.rendered:
            return
        self.output.write("\x1b[2A\r\x1b[2K\x1b[1B\r\x1b[2K\x1b[1A\r")
        self.output.flush()
        self.rendered = False


def _should_render_thinking_animation(output: TextIO) -> bool:
    override = os.getenv("HYPERTRADE_THINKING_ANIMATION", "").strip().lower()
    if override in {"0", "false", "off", "no"}:
        return False
    if override in {"1", "true", "on", "yes"}:
        return True
    return bool(getattr(output, "isatty", lambda: False)())


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
    subparsers.add_parser("login", help="Save remote HyperTrade API login for this machine.")
    subparsers.add_parser("/login", help="Save remote HyperTrade API login for this machine.")
    return parser


def _use_local_runtime(args: argparse.Namespace) -> bool:
    if args.local:
        return True
    if args.remote:
        return False
    return "HYPERTRADE_API_URL" not in os.environ and "HYPERTRADE_API_URL" not in read_client_env()


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
        "run_state_json": run.run_state_json,
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
