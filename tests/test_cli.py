from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import redirect_stdout
from io import StringIO
from typing import Any

import httpx
from hypertrade.cli import (
    SLASH_COMMAND_HELP,
    AgentApiClient,
    CliConfig,
    LocalAgentClient,
    _compact_markdown_report,
    _slash_command_candidates,
    _slash_command_completion_matches,
    _strip_report_icons,
    configure_interactive_history,
    handle_slash_command,
    main,
    render_backtest_result,
    render_connectors,
    render_evals_status,
    render_run,
    render_run_stream,
    render_slash_help,
    render_strategy_research_result,
    render_tools,
    render_welcome_banner,
    run_chat,
)


class TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class FakeReadline:
    def __init__(self) -> None:
        self.history_length: int | None = None
        self.read_path = ""
        self.write_path = ""
        self.added: list[str] = []
        self.completer: Any | None = None
        self.display_hook: Any | None = None
        self.bindings: list[str] = []
        self.line_buffer = ""
        self.redisplay_count = 0

    def read_history_file(self, path: str) -> None:
        self.read_path = path

    def write_history_file(self, path: str) -> None:
        self.write_path = path

    def set_history_length(self, length: int) -> None:
        self.history_length = length

    def add_history(self, item: str) -> None:
        self.added.append(item)

    def get_current_history_length(self) -> int:
        return len(self.added)

    def get_history_item(self, index: int) -> str | None:
        if index < 1 or index > len(self.added):
            return None
        return self.added[index - 1]

    def set_completer(self, completer: Any) -> None:
        self.completer = completer

    def set_completion_display_matches_hook(self, hook: Any) -> None:
        self.display_hook = hook

    def get_line_buffer(self) -> str:
        return self.line_buffer

    def redisplay(self) -> None:
        self.redisplay_count += 1

    def parse_and_bind(self, binding: str) -> None:
        self.bindings.append(binding)


class FakeAgentClient:
    def __init__(self) -> None:
        self.logged_in = False
        self.prompts: list[str] = []
        self.research_prompts: list[str] = []
        self.experiment_prompts: list[str] = []
        self.iteration_prompts: list[str] = []
        self.backtest_calls: list[dict[str, Any]] = []
        self.strategy_library_queries: list[str] = []
        self.price_symbols: list[str] = []
        self.candle_calls: list[dict[str, Any]] = []
        self.compare_calls: list[dict[str, Any]] = []
        self.paper_actions: list[str] = []
        self.live_decisions: list[dict[str, str]] = []
        self.selected_model = "deepseek"
        self.selected_provider_model = "deepseek-v4-flash"
        self.disabled_memory_ids: list[str] = []
        self.requested_run_ids: list[str] = []

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

    def run_agent_events(self, prompt: str):
        self.prompts.append(prompt)
        yield {"event": "run_started", "run_id": "pending", "status": "running"}
        yield {"event": "tool_started", "tool_name": "market.summary"}
        yield {"event": "tool_completed", "tool_name": "market.summary", "status": "completed"}
        yield {
            "event": "run_completed",
            "run": {
                "id": "run_cli",
                "status": "completed",
                "report_markdown": "# CLI Report\n\nResearch only. Not investment advice.",
                "trace_events": [
                    {"tool_name": "market.summary", "status": "completed"},
                    {"tool_name": "memory.write", "status": "completed"},
                ],
            },
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

    def list_connectors(self) -> dict[str, Any]:
        return {
            "connectors": {
                "bitpro": {
                    "display_name": "BitPro MCP",
                    "health": {"status": "not_checked"},
                    "auth": {"configured": True, "secret_redacted": True},
                    "supported_scopes": ["read", "research_backtest_paper_mutation"],
                    "tools": [
                        {
                            "name": "market_klines",
                            "scope": "read",
                            "safe_read": True,
                            "idempotency_required": False,
                        },
                        {
                            "name": "paper_start",
                            "scope": "research_backtest_paper_mutation",
                            "safe_read": False,
                            "idempotency_required": True,
                        },
                    ],
                }
            }
        }

    def list_runs(self) -> list[dict[str, Any]]:
        return [{"id": "run_recent", "status": "completed", "prompt": "请做行情归纳"}]

    def get_run(self, run_id: str) -> dict[str, Any]:
        self.requested_run_ids.append(run_id)
        if run_id != "run_recent":
            raise KeyError(run_id)
        return {
            "id": run_id,
            "status": "completed",
            "report_markdown": "# Historical Report\n\nRecovered through /run.",
            "trace_events": [],
        }

    def list_memory(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "mem_recent",
                "kind": "market_summary",
                "content": "BTC was reviewed",
                "tags": ["market_summary"],
                "usage_count": 1,
            }
        ]

    def search_memory(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "mem_search",
                "kind": "user_preference",
                "content": f"Memory match for {query}",
                "tags": ["preference"],
                "usage_count": 2,
            }
        ]

    def disable_memory(self, memory_id: str) -> dict[str, Any]:
        self.disabled_memory_ids.append(memory_id)
        return {"status": "ok"}

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "source_path": "docs/knowledge/rag-usage.md",
                "title": "RAG Usage",
                "chunk_index": 0,
                "score": 1.25,
                "content_preview": f"Knowledge match for {query}",
            }
        ]

    def get_evals_status(self) -> dict[str, Any]:
        return {
            "status": "passed",
            "cases": [
                {"name": "tool_selection", "status": "passed"},
                {"name": "rag_citation", "status": "passed"},
            ],
        }

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return [{"id": "srch_recent", "strategy_key": "momentum_breakout_v1", "title": "趋势突破"}]

    def list_strategy_library(self, query: str = "") -> dict[str, Any]:
        self.strategy_library_queries.append(query)
        return {
            "source": "memory.strategy_knowledge",
            "memory_count": 2,
            "items": [
                {
                    "strategy_key": "momentum_breakout_v1",
                    "evidence_count": 2,
                    "passed_count": 1,
                    "failed_count": 1,
                    "best": {
                        "memory_id": "mem_fast",
                        "experiment_id": "exp_fast",
                        "backtest_id": "bt_fast",
                        "variant_id": "fast",
                        "total_return_pct": "12.5",
                        "max_drawdown_pct": "3.1",
                        "trade_count": 8,
                        "score": "11.75",
                    },
                    "failure_reasons": ["require_non_negative_return"],
                    "next_experiments": ["Test adjacent SMA windows around 3."],
                    "source_memory_ids": ["mem_slow", "mem_fast"],
                }
            ],
        }

    def list_backtests(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "bt_recent",
                "strategy_key": "momentum_breakout_v1",
                "status": "completed",
                "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
            }
        ]

    def get_paper_status(self) -> dict[str, Any]:
        return {
            "session": {
                "id": "paper_cli",
                "status": "running",
                "cash": "100000",
                "equity": "100250",
                "realized_pnl": "12.5",
            },
            "positions": [
                {
                    "inst_id": "ETH-USDT-SWAP",
                    "side": "long",
                    "quantity": "1.2",
                    "entry_price": "1900",
                    "mark_price": "1980",
                    "notional": "2376",
                    "unrealized_pnl": "96",
                }
            ],
            "recent_fills": [
                {
                    "inst_id": "ETH-USDT-SWAP",
                    "side": "long",
                    "quantity": "1.2",
                    "price": "1900",
                    "fee": "1.14",
                    "created_at": "2026-06-02T08:00:00+00:00",
                }
            ],
            "recent_events": [
                {
                    "kind": "fill",
                    "message": "Paper long fill for ETH-USDT-SWAP",
                    "created_at": "2026-06-02T08:00:00+00:00",
                }
            ],
        }

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]:
        self.paper_actions.append(action)
        if action == "close":
            return {
                "session": {
                    "id": "paper_cli",
                    "status": "running",
                    "cash": "100050",
                    "equity": "100050",
                    "realized_pnl": "50",
                },
                "closed_count": 1,
                "closed": [
                    {
                        "inst_id": f"{(symbol or 'ETH').upper()}-USDT-SWAP",
                        "side": "long",
                        "exit_price": "2000",
                        "realized_pnl": "50",
                    }
                ],
            }
        if action == "reset":
            return {
                "session": {
                    "id": "paper_new",
                    "status": "running",
                    "cash": "100000",
                    "equity": "100000",
                    "realized_pnl": "0",
                }
            }
        return {
            "session": {
                "id": "paper_cli",
                "status": "paused" if action == "pause" else "running",
                "cash": "100000",
                "equity": "100250",
                "realized_pnl": "12.5",
            }
        }

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

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]:
        self.experiment_prompts.append(prompt)
        return {
            "id": "exp_cli",
            "status": "completed",
            "research_id": "srch_cli",
            "backtest_id": "bt_cli",
            "report_markdown": "# Experiment\n\nCritique and next experiment. 不构成投资建议。",
        }

    def create_strategy_iteration(self, prompt: str) -> dict[str, Any]:
        self.iteration_prompts.append(prompt)
        return {
            "id": "exp_iter_cli",
            "status": "completed",
            "research_id": "srch_iter_cli",
            "backtest_id": "bt_iter_cli",
            "report_markdown": "# Iteration\n\nPrior Evidence. 未声称改进。不构成投资建议。",
        }

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
        self.backtest_calls.append(
            {
                "research_id": research_id,
                "strategy_key": strategy_key,
                "use_live_candles": use_live_candles,
                "symbol": symbol,
                "bar": bar,
                "candle_limit": candle_limit,
                "candle_source": candle_source,
            }
        )
        return {
            "id": "bt_cli",
            "research_id": research_id,
            "strategy_key": strategy_key,
            "status": "completed",
            "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
            "report_markdown": "# Backtest\n\nReturn 1.9%.",
        }

    def get_market_ticker(self, symbol: str) -> dict[str, Any]:
        self.price_symbols.append(symbol)
        return {
            "found": True,
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "last": "3500.000000000000",
            "change_utc0_pct": "1.230000",
            "volume_ccy_24h": "987654.000000000000",
            "data_source": "okx_rest",
            "as_of_utc": "2026-06-02T08:00:00+00:00",
        }

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        self.candle_calls.append({"symbol": symbol, "bar": bar, "limit": limit})
        return {
            "found": True,
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "bar": bar,
            "candle_count": limit,
            "return_pct": "2.400000",
            "range_pct": "7.500000",
            "close_position_pct": "72.000000",
            "ma20": "2000.000000000000",
            "ma60": "1975.000000000000",
            "trend_bias": "up",
            "data_source": "okx_rest",
            "as_of_utc": "2026-06-02T08:00:00+00:00",
        }

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]:
        self.compare_calls.append({"symbols": symbols, "bar": bar, "limit": limit})
        return {
            "found": True,
            "bar": bar,
            "leader": "ETH-USDT-SWAP",
            "rankings": [
                {
                    "rank": 1,
                    "inst_id": "ETH-USDT-SWAP",
                    "strength_score": "75.000000",
                    "return_pct": "2.500000",
                    "close_position_pct": "70.000000",
                    "trend_bias": "up",
                },
                {
                    "rank": 2,
                    "inst_id": "SOL-USDT-SWAP",
                    "strength_score": "20.000000",
                    "return_pct": "-3.000000",
                    "close_position_pct": "25.000000",
                    "trend_bias": "down",
                },
            ],
            "data_source": "okx_rest",
            "as_of_utc": "2026-06-02T08:00:00+00:00",
        }

    def get_model_status(self) -> dict[str, Any]:
        codex_model = self.selected_provider_model if self.selected_model == "codex" else "gpt-5.4"
        providers = [
            {
                "name": "deepseek",
                "display_name": "DeepSeek",
                "model": "deepseek-v4-flash",
                "model_options": ["deepseek-v4-flash"],
                "enabled": True,
                "default": self.selected_model == "deepseek",
                "key_status": "configured",
            },
            {
                "name": "codex",
                "display_name": "Codex",
                "model": codex_model,
                "model_options": ["gpt-5.4", "gpt-5.4-mini"],
                "enabled": True,
                "default": self.selected_model == "codex",
                "key_status": "configured",
            },
        ]
        selected = next(
            (provider for provider in providers if provider["name"] == self.selected_model),
            providers[0],
        )
        return {
            "default_provider": self.selected_model,
            "model": selected["model"],
            "providers": providers,
        }

    def set_model(self, provider: str, model: str = "") -> dict[str, Any]:
        self.selected_model = provider
        if model:
            self.selected_provider_model = model
        elif provider == "codex":
            self.selected_provider_model = "gpt-5.4"
        else:
            self.selected_provider_model = "deepseek-v4-flash"
        return self.get_model_status()

    def list_live_order_intents(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "loi_recent",
                "environment": "testnet",
                "status": "pending_approval",
                "inst_id": "ETH-USDT-SWAP",
                "side": "buy",
                "order_type": "market",
                "size": "0.01",
                "price": None,
                "reason": "test intent",
            }
        ]

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
        return {
            "id": "loi_new",
            "environment": "testnet",
            "status": "pending_approval",
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "side": side,
            "order_type": order_type,
            "size": size,
            "price": price,
            "reason": reason,
        }

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        self.live_decisions.append({"intent_id": intent_id, "decision": decision, "reason": reason})
        return {
            "id": intent_id,
            "environment": "testnet",
            "status": "approved" if decision == "approve" else "rejected",
            "inst_id": "ETH-USDT-SWAP",
            "side": "buy",
            "order_type": "market",
            "size": "0.01",
            "price": None,
            "reason": "test intent",
            "decision_reason": reason,
        }

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]:
        return {
            "id": intent_id,
            "environment": "testnet",
            "status": "execution_failed",
            "inst_id": "ETH-USDT-SWAP",
            "side": "buy",
            "order_type": "market",
            "size": "0.01",
            "price": None,
            "reason": "test intent",
            "risk_status": "allowed",
            "exchange_order_id": "",
        }


def test_configure_interactive_history_reads_and_writes_history(tmp_path) -> None:
    fake_readline = FakeReadline()
    registered: list[tuple[Any, tuple[Any, ...]]] = []

    history = configure_interactive_history(
        enabled=True,
        history_path=tmp_path / "history",
        readline_module=fake_readline,
        register_exit=lambda fn, *args: registered.append((fn, args)),
    )

    assert history.enabled is True
    assert fake_readline.history_length == 1000
    assert fake_readline.read_path == str(tmp_path / "history")
    assert registered == [(fake_readline.write_history_file, (str(tmp_path / "history"),))]
    assert fake_readline.completer is not None
    assert fake_readline.display_hook is not None
    assert "tab: complete" in fake_readline.bindings

    history.add("看下ETH行情")
    history.add("")
    history.add("看下ETH行情")
    history.add("/tools")

    assert fake_readline.added == ["看下ETH行情", "/tools"]


def test_configure_interactive_history_skips_invalid_persistence_path(tmp_path) -> None:
    fake_readline = FakeReadline()
    registered: list[tuple[Any, tuple[Any, ...]]] = []
    history_path = tmp_path / "history"
    history_path.mkdir()

    history = configure_interactive_history(
        enabled=True,
        history_path=history_path,
        readline_module=fake_readline,
        register_exit=lambda fn, *args: registered.append((fn, args)),
    )

    assert history.enabled is True
    assert fake_readline.read_path == ""
    assert registered == []
    assert fake_readline.completer is not None

    history.add("看下ETH行情")

    assert fake_readline.added == ["看下ETH行情"]


def test_slash_command_completion_matches_commands_and_subcommands() -> None:
    root_matches = _slash_command_completion_matches(line="/", text="/", begidx=0)
    model_matches = _slash_command_completion_matches(line="/m", text="/m", begidx=0)
    paper_matches = _slash_command_completion_matches(
        line="/paper ",
        text="",
        begidx=len("/paper "),
    )
    live_matches = _slash_command_completion_matches(
        line="/live e",
        text="e",
        begidx=len("/live "),
    )

    assert "/help " in root_matches
    assert "/tools " in root_matches
    assert "/model " in model_matches
    assert "/memory " in model_matches
    assert "status " in paper_matches
    assert "pause " in paper_matches
    assert "execute " in live_matches
    assert _slash_command_completion_matches(line="看下 ETH", text="ETH", begidx=3) == []


def test_slash_command_candidates_filter_partial_prefix_with_descriptions() -> None:
    candidates = _slash_command_candidates("/st")

    command_names = [command for command, _ in candidates]
    assert "/status" in command_names
    assert "/strategy" in command_names
    assert "/strategy library [query]" in command_names
    assert "/tools" not in command_names
    assert any(
        command == "/strategy" and "strategy research" in description
        for command, description in candidates
    )


def test_slash_command_candidates_render_for_partial_command() -> None:
    output = StringIO()

    handle_slash_command("/st", client=FakeAgentClient(), output=output)

    rendered = output.getvalue()
    assert "Slash command candidates for /st:" in rendered
    assert "/status" in rendered
    assert "/strategy" in rendered
    assert "Unknown command" not in rendered


def test_slash_command_candidate_can_be_selected_by_number() -> None:
    client = FakeAgentClient()
    output = StringIO()
    inputs = iter(["1"])

    handle_slash_command(
        "/st",
        client=client,
        output=output,
        input_fn=_next_input(inputs),
    )

    rendered = output.getvalue()
    assert "Slash command candidates for /st:" in rendered
    assert "1. /status" in rendered
    assert "Status:" in rendered
    assert "Unknown command" not in rendered


def test_slash_command_display_hook_renders_filtered_candidates(tmp_path) -> None:
    fake_readline = FakeReadline()
    fake_readline.line_buffer = "/me"
    configure_interactive_history(
        enabled=True,
        history_path=tmp_path / "history",
        readline_module=fake_readline,
    )
    assert fake_readline.display_hook is not None
    output = StringIO()

    with redirect_stdout(output):
        fake_readline.display_hook("/me", ["/memory "], len("/memory "))

    rendered = output.getvalue()
    assert "Slash command candidates for /me:" in rendered
    assert "/memory" in rendered
    assert "Search audited memory" in rendered
    assert fake_readline.redisplay_count == 1


def test_slash_command_display_hook_renders_argument_candidates(tmp_path) -> None:
    fake_readline = FakeReadline()
    fake_readline.line_buffer = "/model c"
    configure_interactive_history(
        enabled=True,
        history_path=tmp_path / "history",
        readline_module=fake_readline,
    )
    assert fake_readline.display_hook is not None
    output = StringIO()

    with redirect_stdout(output):
        fake_readline.display_hook("c", ["codex "], len("codex "))

    rendered = output.getvalue()
    assert "Slash argument candidates for /model c:" in rendered
    assert "codex" in rendered
    assert "No slash command matches" not in rendered
    assert fake_readline.redisplay_count == 1


def test_slash_partial_argument_renders_candidates_without_dispatch() -> None:
    client = FakeAgentClient()
    output = StringIO()

    handle_slash_command("/model c", client=client, output=output)

    rendered = output.getvalue()
    assert "Slash argument candidates for /model c:" in rendered
    assert "codex" in rendered
    assert "Model switch failed" not in rendered
    assert client.selected_model == "deepseek"


def test_slash_partial_argument_can_be_selected_by_number() -> None:
    client = FakeAgentClient()
    output = StringIO()
    inputs = iter(["1", "2"])

    handle_slash_command(
        "/model c",
        client=client,
        output=output,
        input_fn=_next_input(inputs),
    )

    rendered = output.getvalue()
    assert "Slash argument candidates for /model c:" in rendered
    assert "1. codex" in rendered
    assert "Select Codex model:" in rendered
    assert "Model switched: codex" in rendered
    assert "- Model: gpt-5.4-mini" in rendered
    assert client.selected_model == "codex"
    assert client.selected_provider_model == "gpt-5.4-mini"


def test_slash_candidate_selection_blank_cancels() -> None:
    client = FakeAgentClient()
    output = StringIO()
    inputs = iter([""])

    handle_slash_command(
        "/st",
        client=client,
        output=output,
        input_fn=_next_input(inputs),
    )

    rendered = output.getvalue()
    assert "Candidate selection canceled." in rendered
    assert "Status:" not in rendered


def test_model_command_selects_provider_and_codex_model_from_numbered_lists() -> None:
    client = FakeAgentClient()
    output = StringIO()
    inputs = iter(["2", "2"])

    handle_slash_command(
        "/model",
        client=client,
        output=output,
        input_fn=_next_input(inputs),
    )

    rendered = output.getvalue()
    assert "Select provider:" in rendered
    assert "1. deepseek" in rendered
    assert "2. codex" in rendered
    assert "Select Codex model:" in rendered
    assert "Model switched: codex" in rendered
    assert "- Model: gpt-5.4-mini" in rendered
    assert client.selected_model == "codex"
    assert client.selected_provider_model == "gpt-5.4-mini"


def test_model_command_blank_provider_selection_cancels() -> None:
    client = FakeAgentClient()
    output = StringIO()
    inputs = iter([""])

    handle_slash_command(
        "/model",
        client=client,
        output=output,
        input_fn=_next_input(inputs),
    )

    rendered = output.getvalue()
    assert "Model selection canceled." in rendered
    assert client.selected_model == "deepseek"


def test_slash_command_root_displays_help_without_unknown_message() -> None:
    output = StringIO()

    handle_slash_command("/", client=FakeAgentClient(), output=output)

    rendered = output.getvalue()
    assert "Slash commands:" in rendered
    assert "/tools" in rendered
    assert "Unknown command" not in rendered


def test_compact_markdown_report_removes_excess_spacing_and_rules() -> None:
    compact = _compact_markdown_report("# 标题\n\n\n正文\n\n---\n\n\n## 小节\n\n\n- 项目\n\n\n")

    assert compact == "# 标题\n\n正文\n\n## 小节\n\n- 项目"


def test_report_cleanup_hides_citations_and_keycap_icons() -> None:
    cleaned = _strip_report_icons(
        "## 引用来源\n\n1. docs/a.md#0\n\n## 📟 Ticker 是什么？\n\n### 1️⃣ 交易代码\n\n正文 😊"
    )

    assert "引用来源" not in cleaned
    assert "docs/a.md" not in cleaned
    assert "Ticker 是什么？" in cleaned
    assert "### 1 交易代码" in cleaned
    assert "📟" not in cleaned
    assert "1️⃣" not in cleaned
    assert "😊" not in cleaned


def test_interactive_history_does_not_duplicate_readline_auto_added_item(tmp_path) -> None:
    fake_readline = FakeReadline()
    history = configure_interactive_history(
        enabled=True,
        history_path=tmp_path / "history",
        readline_module=fake_readline,
    )

    fake_readline.added.append("看下ETH行情")
    history.add("看下ETH行情")
    history.add("/tools")

    assert fake_readline.added == ["看下ETH行情", "/tools"]


def test_ask_prints_agent_run_trace_and_report(capsys) -> None:
    client = FakeAgentClient()

    exit_code = main(["ask", "请做行情归纳"], client=client)

    assert exit_code == 0
    assert client.logged_in is True
    assert client.prompts == ["请做行情归纳"]
    output = capsys.readouterr().out
    assert "Run:" not in output
    assert "Tools:" not in output
    assert "Agent: running" in output
    assert "Agent status: executing tool market.summary" not in output
    assert "# CLI Report" in output


def test_render_run_prefers_structured_market_summary_over_raw_markdown(capsys) -> None:
    render_run(
        {
            "id": "run_structured",
            "status": "completed",
            "report_markdown": "# Raw Markdown Should Not Render",
            "report_json": {
                "market_scope": "OKX SWAP",
                "trigger": "user_request",
                "data_source": "okx_rest",
                "as_of_utc": "2026-06-02T08:00:00+00:00",
                "heat_summary": {
                    "sample_count": 3,
                    "advancers_count": 1,
                    "decliners_count": 2,
                    "advancers_pct": "33.333333",
                    "decliners_pct": "66.666667",
                    "average_change_pct": "-2.300000",
                    "top_gainer": "ETH-USDT-SWAP (1.230000%)",
                    "top_loser": "SOL-USDT-SWAP (-4.100000%)",
                    "conclusion": "风险偏弱：样本平均涨跌幅 -2.300000%。",
                },
                "top_movers": [
                    {
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                    }
                ],
                "rag_hits": [{"source_path": "docs/knowledge/risk.md", "score": 0.91}],
                "disclaimer": "Research output only. Not investment advice.",
            },
            "trace_events": [
                {"tool_name": "market.summary", "status": "completed"},
                {"tool_name": "rag.search", "status": "completed"},
            ],
        }
    )

    output = capsys.readouterr().out
    assert "Market Report" in output
    assert "Scope: OKX SWAP" in output
    assert "Source: okx_rest" in output
    assert "Market heat:" in output
    assert "风险偏弱" in output
    assert "Top movers:" in output
    assert "ETH-USDT-SWAP" in output
    assert "Knowledge hits:" in output
    assert "Raw Markdown Should Not Render" not in output
    assert "Research output only. Not investment advice." not in output


def test_render_run_prefers_final_market_summary_over_detail_tables(capsys) -> None:
    render_run(
        {
            "id": "run_tools",
            "status": "completed",
            "report_markdown": "## 总结\n\n- 当前市场热度偏冷，BTC/ETH/SOL 同步回落。",
            "report_json": {
                "planner": "deepseek",
                "disclaimer": "Research output only. Not investment advice.",
            },
            "trace_events": [
                {
                    "tool_name": "market_ticker",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                        "data_source": "okx_rest",
                    },
                },
                {
                    "tool_name": "market_candles",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "bar": "1H",
                        "candle_count": 100,
                        "return_pct": "2.400000",
                        "trend_bias": "up",
                        "data_source": "okx_rest",
                    },
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "当前市场热度偏冷" in output
    assert "Ticker:" not in output
    assert "Trend:" not in output
    assert "Research output only. Not investment advice." not in output


def test_render_run_prefers_final_market_answer_over_world_model_audit_blocks(capsys) -> None:
    render_run(
        {
            "id": "run_world_model_market",
            "status": "completed",
            "report_markdown": "## 市场总结\n\n当前市场温热，涨跌家数偏多，但宏观信号仍混合。",
            "report_json": {
                "tool_calls": [{"tool": "world_model_snapshot", "input": {}}],
                "report_blocks": [
                    {
                        "block_type": "summary",
                        "title": "Global WorldState",
                        "notes": ["raw WorldState audit detail"],
                    },
                    {
                        "block_type": "scenario_comparison",
                        "title": "Global WorldState Scenario Comparison",
                        "rows": [{"action_id": "run_monitor", "score": 56.4}],
                    },
                ],
            },
            "trace_events": [{"tool_name": "world_model_snapshot", "status": "completed"}],
        }
    )

    output = capsys.readouterr().out
    assert "当前市场温热" in output
    assert "Global WorldState" not in output
    assert "raw WorldState audit detail" not in output


def test_render_run_can_force_world_model_audit_blocks(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "audit")
    render_run(
        {
            "id": "run_world_model_audit",
            "status": "completed",
            "report_markdown": "## 市场总结\n\n当前市场温热。",
            "report_json": {
                "tool_calls": [{"tool": "world_model_snapshot", "input": {}}],
                "report_blocks": [
                    {
                        "block_type": "summary",
                        "title": "Global WorldState",
                        "notes": ["audit detail"],
                    }
                ],
            },
            "trace_events": [{"tool_name": "world_model_snapshot", "status": "completed"}],
        }
    )

    output = capsys.readouterr().out
    assert "Global WorldState" in output
    assert "当前市场温热" not in output


def test_render_run_can_force_structured_market_tool_outputs(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "tools")
    render_run(
        {
            "id": "run_tools",
            "status": "completed",
            "report_markdown": "## 总结\n\n- 当前市场热度偏冷，BTC/ETH/SOL 同步回落。",
            "report_json": {
                "planner": "deepseek",
                "disclaimer": "Research output only. Not investment advice.",
            },
            "trace_events": [
                {
                    "tool_name": "market_ticker",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                        "data_source": "okx_rest",
                    },
                },
                {
                    "tool_name": "market_candles",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "bar": "1H",
                        "candle_count": 100,
                        "return_pct": "2.400000",
                        "trend_bias": "up",
                        "data_source": "okx_rest",
                    },
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "Ticker:" in output
    assert "Trend:" in output
    assert "ETH-USDT-SWAP" in output
    assert "当前市场热度偏冷" not in output
    assert "Research output only. Not investment advice." not in output


def test_render_run_structured_output_keeps_bitpro_paper_monitor(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "tools")
    render_run(
        {
            "id": "run_paper_monitor",
            "status": "completed",
            "report_markdown": "## BitPro 模拟盘状态\n\n- 监控结论: read_only",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "market_ticker",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                        "data_source": "okx_rest",
                    },
                },
                {
                    "tool_name": "bitpro_paper_dashboard",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "contract_version": "bitpro-mcp-v1",
                        "dashboard": {
                            "system": {
                                "strategy_id": 105,
                                "strategy": "SOL EMA monitor",
                                "state": "running",
                                "mode": "paper",
                                "uptime": "29D",
                            },
                            "equity": {"current": "104.36"},
                            "performance": {
                                "total_pnl_pct": "4.36",
                                "sharpe_ratio": "1.3222",
                                "max_drawdown": "4.29",
                            },
                        },
                        "paper_scope": {"dashboard_scope": "current_instance"},
                        "running_strategies": {"total": 11},
                        "monitor_summary": {
                            "mode": "read_only",
                            "running_inventory": {
                                "listed_count": 11,
                                "reported_total": 11,
                                "is_truncated": False,
                            },
                            "alerts": [],
                            "data_gaps": [
                                "running strategy inventory lacks per-strategy PnL/drawdown metrics"
                            ],
                            "recommended_actions": [
                                {
                                    "action": "continue_read_only_monitoring",
                                    "message": "No write action was suggested.",
                                }
                            ],
                        },
                    },
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "Ticker:" in output
    assert "BitPro Paper Monitor:" in output
    assert "Monitor: read_only" in output
    assert "Running coverage: listed=11, reported_total=11, state=complete" in output
    assert "Data gaps:" in output
    assert "Suggested read-only actions:" in output


def test_render_run_structured_output_renders_bitpro_paper_evidence(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "tools")
    render_run(
        {
            "id": "run_paper_evidence",
            "status": "completed",
            "report_markdown": "## BitPro 模拟盘状态\n\n- raw fallback",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_events",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": 105,
                        "events": [
                            {
                                "id": 9001,
                                "level": "error",
                                "type": "order_rejected",
                                "message": "insufficient paper balance",
                                "timestamp": "2026-06-23T09:10:00Z",
                            }
                        ],
                        "event_summary": {
                            "count": 1,
                            "sample_count": 1,
                            "error_count": 1,
                            "latest_event_at": "2026-06-23T09:10:00Z",
                        },
                    },
                },
                {
                    "tool_name": "bitpro_paper_equity_curve",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": 105,
                        "equity_curve": [
                            {
                                "timestamp": "2026-06-23T08:00:00Z",
                                "equity": "101.25",
                                "drawdown_pct": "1.5",
                            }
                        ],
                        "equity_summary": {
                            "count": 3,
                            "sample_count": 1,
                            "latest_at": "2026-06-23T09:00:00Z",
                            "latest_equity": "102.5",
                            "latest_drawdown_pct": "0.8",
                            "max_drawdown_pct": "1.5",
                        },
                    },
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro Paper Events:" in output
    assert "Events: count=1, sample=1, errors=1" in output
    assert "9001 error/order_rejected: insufficient paper balance" in output
    assert "BitPro Paper Equity Curve:" in output
    assert "Equity: points=3, sample=1, latest=102.5, max_drawdown=1.5%" in output


def test_render_run_prefers_final_paper_summary_by_default(capsys) -> None:
    render_run(
        {
            "id": "run_paper_summary",
            "status": "completed",
            "report_markdown": "## BitPro 模拟盘总结\n\n- 核心结论：权益稳定，暂无新增错误。",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_equity_curve",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": 105,
                        "equity_curve": [
                            {
                                "timestamp": "2026-06-23T08:00:00Z",
                                "equity": "101.25",
                                "drawdown_pct": "1.5",
                            }
                        ],
                        "equity_summary": {
                            "count": 400,
                            "sample_count": 5,
                            "latest_equity": "107.14",
                        },
                    },
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "核心结论：权益稳定，暂无新增错误。" in output
    assert "BitPro Paper Equity Curve:" not in output
    assert "Paper Equity Curve" not in output
    assert "2026-06-23T08:00:00Z" not in output


def test_rich_render_run_prefers_final_paper_summary_by_default(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    render_run(
        {
            "id": "run_rich_paper_summary",
            "status": "completed",
            "report_markdown": "## BitPro 模拟盘总结\n\n- 核心结论：权益稳定，暂无新增错误。",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_equity_curve",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": 105,
                        "equity_curve": [
                            {
                                "timestamp": "2026-06-23T08:00:00Z",
                                "equity": "101.25",
                                "drawdown_pct": "1.5",
                            }
                        ],
                        "equity_summary": {
                            "count": 400,
                            "sample_count": 5,
                            "latest_equity": "107.14",
                        },
                    },
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "核心结论：权益稳定，暂无新增错误。" in output
    assert "BitPro 模拟盘权益曲线" not in output
    assert "Paper Equity Curve" not in output
    assert "2026-06-23T08:00:00Z" not in output


def test_render_run_prefers_final_strategy_comparison_over_report_blocks(capsys) -> None:
    render_run(
        {
            "id": "run_paper_comparison",
            "status": "completed",
            "report_markdown": (
                "## 结论\n\n"
                "- 当前无法对全部模拟盘策略按收益排名。\n\n"
                "## 策略比较\n\n"
                "| 策略 | 已确认收益 | 状态 |\n"
                "| --- | ---: | --- |\n"
                "| SOL EMA 5/20 | +4.55% | 当前 dashboard |\n"
                "| 其余 7 个策略 | 数据未提供 | 运行中 |\n\n"
                "## 下一步\n\n"
                "- 补齐逐策略 PnL/回撤后再做全量排名。"
            ),
            "report_json": {
                "report_blocks": [
                    {
                        "block_type": "metric_table",
                        "title": "BitPro Paper Monitor",
                        "metrics": {"equity": "104.55", "total_pnl_pct": "4.55"},
                    },
                    {
                        "block_type": "missing_data",
                        "title": "BitPro Paper Missing Data",
                        "missing": ["per-strategy PnL unavailable"],
                    },
                ]
            },
            "trace_events": [],
        }
    )

    output = capsys.readouterr().out
    assert "当前无法对全部模拟盘策略按收益排名" in output
    assert "SOL EMA 5/20" in output
    assert "BitPro Paper Monitor:" not in output
    assert "BitPro Paper Missing Data:" not in output


def test_rich_render_run_prefers_final_strategy_comparison_over_report_blocks(
    monkeypatch, capsys
) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    render_run(
        {
            "id": "run_rich_paper_comparison",
            "status": "completed",
            "report_markdown": "## 结论\n\n- 当前无法对全部模拟盘策略按收益排名。",
            "report_json": {
                "report_blocks": [
                    {
                        "block_type": "metric_table",
                        "title": "BitPro Paper Monitor",
                        "metrics": {"equity": "104.55"},
                    }
                ]
            },
            "trace_events": [],
        }
    )

    output = capsys.readouterr().out
    assert "当前无法对全部模拟盘策略按收益排名" in output
    assert "BitPro Paper Monitor" not in output


def test_render_run_can_request_report_blocks_for_strategy_comparison(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "audit")
    render_run(
        {
            "id": "run_paper_comparison_audit",
            "status": "completed",
            "report_markdown": "## 结论\n\n- 当前无法对全部模拟盘策略按收益排名。",
            "report_json": {
                "report_blocks": [
                    {
                        "block_type": "missing_data",
                        "title": "BitPro Paper Missing Data",
                        "missing": ["per-strategy PnL unavailable"],
                    }
                ]
            },
            "trace_events": [],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro Paper Missing Data:" in output
    assert "per-strategy PnL unavailable" in output
    assert "当前无法对全部模拟盘策略按收益排名" not in output


def test_render_run_compacts_paper_tools_without_final_report(capsys) -> None:
    render_run(
        {
            "id": "run_paper_compact",
            "status": "completed",
            "report_markdown": "",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_dashboard",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "dashboard": {
                            "system": {
                                "strategy_id": 104,
                                "state": "running",
                                "mode": "paper",
                            },
                            "equity": {"current": "100.0"},
                            "performance": {
                                "total_pnl_pct": "0.0",
                                "max_drawdown": "1.0",
                            },
                        },
                    },
                },
                {
                    "tool_name": "bitpro_paper_dashboard",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "dashboard": {
                            "system": {
                                "strategy_id": 105,
                                "state": "running",
                                "mode": "paper",
                            },
                            "equity": {"current": "107.11"},
                            "performance": {
                                "total_pnl_pct": "7.11",
                                "max_drawdown": "6.3",
                            },
                        },
                        "monitor_summary": {
                            "running_inventory": {
                                "listed_count": 9,
                                "reported_total": 9,
                                "is_truncated": False,
                            },
                            "data_gaps": [
                                "running strategy inventory does not include per-strategy PnL"
                            ],
                        },
                    },
                },
                {
                    "tool_name": "bitpro_paper_equity_curve",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": None,
                        "equity_curve": [
                            {
                                "timestamp": "2026-06-08T13:00:07.397000+00:00",
                                "equity": "107.83386112695017",
                                "drawdown_pct": None,
                            }
                        ],
                        "equity_summary": {
                            "count": 400,
                            "sample_count": 50,
                            "latest_equity": "107.14019134255034",
                            "latest_drawdown_pct": None,
                            "max_drawdown_pct": None,
                        },
                    },
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro 模拟盘摘要:" in output
    assert "strategy_id=105" in output
    assert "strategy_id=104" not in output
    assert "权益曲线: strategy=all, points=400, latest=107.14" in output
    assert "BitPro Paper Equity Curve:" not in output
    assert "Paper Equity Curve" not in output
    assert "2026-06-08T13:00:07.397000+00:00" not in output


def test_render_run_compacts_noisy_paper_markdown(capsys) -> None:
    render_run(
        {
            "id": "run_paper_noisy_markdown",
            "status": "completed",
            "report_markdown": (
                "## BitPro 模拟盘状态\n\n"
                "- 权益曲线证据: strategy_id=None, points=400\n"
                "- 权益点 2026-06-08T13:00:07.397000+00:00: equity=107.83\n"
                "- 还有 390 个权益点未展开。"
            ),
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_equity_curve",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": None,
                        "equity_curve": [
                            {
                                "timestamp": "2026-06-08T13:00:07.397000+00:00",
                                "equity": "107.83386112695017",
                                "drawdown_pct": None,
                            }
                        ],
                        "equity_summary": {
                            "count": 400,
                            "latest_equity": "107.14019134255034",
                            "latest_drawdown_pct": None,
                            "max_drawdown_pct": None,
                        },
                    },
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro 模拟盘摘要:" in output
    assert "权益曲线: strategy=all, points=400, latest=107.14" in output
    assert "权益点 2026-06-08" not in output
    assert "还有 390" not in output


def test_render_run_compacts_table_like_paper_markdown(capsys) -> None:
    render_run(
        {
            "id": "run_paper_table_markdown",
            "status": "completed",
            "report_markdown": (
                "## BitPro 模拟盘状态\n\n"
                "# BitPro 模拟盘权益曲线总结\n"
                "| 指标 | 数值 |\n"
                "| --- | --- |\n"
                "| 当前权益 | 107.14 |"
            ),
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_equity_curve",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": None,
                        "equity_curve": [],
                        "equity_summary": {
                            "count": 400,
                            "latest_equity": "107.14019134255034",
                            "latest_drawdown_pct": None,
                            "max_drawdown_pct": None,
                        },
                    },
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro 模拟盘摘要:" in output
    assert "权益曲线: strategy=all, points=400, latest=107.14" in output
    assert "| 指标 |" not in output


def test_rich_render_run_compacts_paper_tools_without_final_report(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    render_run(
        {
            "id": "run_rich_paper_compact",
            "status": "completed",
            "report_markdown": "",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_equity_curve",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "strategy_id": None,
                        "equity_curve": [
                            {
                                "timestamp": "2026-06-08T13:00:07.397000+00:00",
                                "equity": "107.83386112695017",
                                "drawdown_pct": None,
                            }
                        ],
                        "equity_summary": {
                            "count": 400,
                            "sample_count": 50,
                            "latest_equity": "107.14019134255034",
                            "latest_drawdown_pct": None,
                            "max_drawdown_pct": None,
                        },
                    },
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro 模拟盘摘要" in output
    assert "权益曲线: strategy=all, points=400, latest=107.14" in output
    assert "Paper Equity Curve" not in output
    assert "2026-06-08T13:00:07.397000+00:00" not in output


def test_render_run_structured_output_renders_bitpro_paper_monitor_snapshot(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "tools")
    render_run(
        {
            "id": "run_paper_snapshot",
            "status": "completed",
            "report_markdown": "## raw fallback",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_paper_monitor_snapshot",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "contract_version": "bitpro-mcp-v1",
                        "snapshot_id": "bpms_second",
                        "previous_snapshot_id": "bpms_first",
                        "scope_key": "105",
                        "strategy_id": 105,
                        "metrics": {
                            "latest_equity": "101.5",
                            "total_pnl_pct": "1.5",
                            "max_drawdown_pct": "5.2",
                            "event_count": 2,
                            "error_count": 2,
                        },
                        "drift": {
                            "mode": "compared",
                            "equity_delta": "-2.5",
                            "total_pnl_delta_pct": "-2.5",
                            "max_drawdown_delta_pct": "3.2",
                            "error_count_delta": 2,
                            "alerts": [
                                {
                                    "level": "warning",
                                    "code": "pnl_drop",
                                    "message": "total_pnl_pct dropped by -2.5%",
                                }
                            ],
                            "data_gaps": [],
                        },
                    },
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro Paper Monitor Snapshot:" in output
    assert "Snapshot: bpms_second, strategy=105, previous=bpms_first" in output
    assert "Metrics: equity=101.5, pnl=1.5%, drawdown=5.2%, errors=2" in output
    assert (
        "Drift: mode=compared, equity_delta=-2.5, pnl_delta=-2.5%, "
        "drawdown_delta=3.2%, error_delta=2"
    ) in output
    assert "warning/pnl_drop: total_pnl_pct dropped by -2.5%" in output


def test_welcome_banner_prioritizes_tasks_and_operator_controls() -> None:
    output = StringIO()

    render_welcome_banner(client=FakeAgentClient(), output=output)

    rendered = output.getvalue()
    assert "HyperTrade / Operator Console" in rendered
    assert "deepseek / deepseek-v4-flash" in rendered
    assert "START WITH A TASK" in rendered
    assert "OPERATOR CONTROLS" in rendered
    assert "MAINNET  BLOCKED" in rendered
    assert "/tasks" in rendered
    assert "/live intents" in rendered
    assert "System posture, risk gates, and session" in rendered
    assert "Mission queue and safe-point controls" in rendered
    assert "Research evidence and trace drill-down" in rendered
    assert "Review pending Testnet execution intents" in rendered
    assert "Inspect the active model and provider" in rendered
    assert "Commands, syntax, and safety guardrails" in rendered
    assert "Inspect or change this session's provider" not in rendered
    assert "/paper close" not in rendered
    assert "Exact ticker shortcut" not in rendered
    assert "风险提示：本工具输出仅用于研究辅助，不构成投资建议。" not in rendered
    assert "Research only. Not investment advice." not in rendered


def test_render_run_can_use_rich_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "tools")
    output = StringIO()

    render_run(
        {
            "id": "run_rich",
            "status": "completed",
            "report_markdown": "# Rich Markdown Should Not Render",
            "report_json": {
                "planner": "deepseek",
                "disclaimer": "Research output only. Not investment advice.",
            },
            "trace_events": [
                {
                    "tool_name": "market_ticker",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                        "data_source": "okx_rest",
                    },
                }
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "┏" in rendered
    assert "ETH-USDT-SWAP" in rendered
    assert "HyperTrade Run" not in rendered
    assert "Tool Trace" not in rendered
    assert "Agent Report" not in rendered
    assert "Rich Markdown Should Not Render" not in rendered


def test_rich_run_hides_trace_shell_by_default(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    monkeypatch.delenv("HYPERTRADE_TRACE", raising=False)
    output = StringIO()

    render_run(
        {
            "id": "run_folded",
            "status": "completed",
            "report_markdown": "# Report\n\nok",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {"tool_name": "graph.intent_classify", "status": "completed"},
                {"tool_name": "graph.plan_tools", "status": "completed"},
                {"tool_name": "bitpro.capabilities", "status": "completed"},
                {"tool_name": "bitpro.health", "status": "completed"},
                {"tool_name": "bitpro.strategy_search", "status": "completed"},
                {"tool_name": "bitpro_strategy_search", "status": "completed"},
                {"tool_name": "bitpro_strategy_search", "status": "completed"},
                {"tool_name": "memory_search", "status": "completed"},
                {"tool_name": "graph.final_report", "status": "completed"},
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Report" in rendered
    assert "ok" in rendered
    assert "HyperTrade Run" not in rendered
    assert "Tool Trace Summary" not in rendered
    assert "bitpro_strategy_search" not in rendered
    assert "memory_search" not in rendered
    assert "Trace folded" not in rendered
    assert "graph.intent_classify" not in rendered
    assert "bitpro.capabilities" not in rendered
    assert "bitpro.strategy_search" not in rendered


def test_rich_run_can_show_trace_summary(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    monkeypatch.setenv("HYPERTRADE_TRACE", "summary")
    output = StringIO()

    render_run(
        {
            "id": "run_folded",
            "status": "completed",
            "report_markdown": "# Report\n\nok",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {"tool_name": "graph.intent_classify", "status": "completed"},
                {"tool_name": "bitpro.capabilities", "status": "completed"},
                {"tool_name": "bitpro_strategy_search", "status": "completed"},
                {"tool_name": "memory_search", "status": "completed"},
                {"tool_name": "graph.final_report", "status": "completed"},
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "HyperTrade Run" in rendered
    assert "Tool Trace Summary" in rendered
    assert "bitpro_strategy_search" in rendered
    assert "memory_search" in rendered
    assert "Trace folded" in rendered


def test_rich_run_can_show_full_trace(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    monkeypatch.setenv("HYPERTRADE_TRACE", "full")
    output = StringIO()

    render_run(
        {
            "id": "run_full_trace",
            "status": "completed",
            "report_markdown": "# Report\n\nok",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {"tool_name": "graph.intent_classify", "status": "completed"},
                {"tool_name": "bitpro.capabilities", "status": "completed"},
                {"tool_name": "bitpro_strategy_search", "status": "completed"},
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "HyperTrade Run" in rendered
    assert "Tool Trace" in rendered
    assert "Tool Trace Summary" not in rendered
    assert "graph.intent_classify" in rendered
    assert "bitpro.capabilities" in rendered
    assert "Trace folded" not in rendered


def test_trace_summary_renders_redacted_flight_recorder(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "plain")
    monkeypatch.setenv("HYPERTRADE_TRACE", "summary")
    output = StringIO()

    render_run(
        {
            "id": "run_observed",
            "status": "completed",
            "report_markdown": "# Report\n\nVisible answer only.",
            "run_state_json": {
                "observability": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "duration_ms": 14131.983,
                    "usage": {
                        "input_tokens": 30184,
                        "output_tokens": 655,
                        "cached_input_tokens": 6272,
                        "reasoning_tokens": 251,
                        "total_tokens": 30839,
                        "request_count": 2,
                        "reported": True,
                    },
                    "tools": {
                        "call_count": 2,
                        "error_count": 0,
                        "total_execution_ms": 5035.876,
                        "slowest": {"tool_name": "world_model_snapshot", "execution_ms": 5010.712},
                    },
                    "memory": {"read_count": 1, "write_count": 1},
                }
            },
            "trace_events": [
                {
                    "tool_name": "graph.model_call",
                    "status": "completed",
                    "output_json": {"duration_ms": 120, "secret": "must-not-render"},
                }
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Flight Recorder:" in rendered
    assert "deepseek / deepseek-v4-flash · duration=14.13s" in rendered
    assert "total=30839 input=30184 output=655 cached=6272 reasoning=251 model_calls=2" in rendered
    assert "slowest=world_model_snapshot (5.01s)" in rendered
    assert "memory: read=1 written=1" in rendered
    assert "graph.model_call: completed · 120ms" in rendered
    assert "must-not-render" not in rendered


def test_trace_summary_marks_unreported_usage_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "plain")
    monkeypatch.setenv("HYPERTRADE_TRACE", "summary")
    output = StringIO()

    render_run(
        {
            "id": "run_usage_missing",
            "status": "completed",
            "report_markdown": "ok",
            "report_json": {
                "observability": {
                    "provider": "provider_unavailable",
                    "usage": {"request_count": 1, "reported": False},
                    "tools": {},
                    "memory": {},
                }
            },
            "trace_events": [],
        },
        output=output,
    )

    assert "tokens: unavailable · model_calls=1" in output.getvalue()


def test_enhanced_renderer_supports_standard_run_envelope(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "enhanced")
    monkeypatch.setenv("HYPERTRADE_TRACE", "summary")
    output = StringIO()

    render_run(
        {
            "id": "run_enhanced",
            "status": "completed",
            "report_markdown": "# Structured Answer\n\n- ✓ completed safely",
            "run_state_json": {
                "observability": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "duration_ms": 250,
                    "usage": {"request_count": 1, "reported": False},
                    "tools": {},
                    "memory": {},
                }
            },
            "trace_events": [{"tool_name": "graph.final_report", "status": "completed"}],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "HyperTrade Run" in rendered
    assert "Flight Recorder" in rendered
    assert "Structured Answer" in rendered
    assert "completed safely" in rendered
    assert "Trace folded" in rendered


def test_slash_run_renders_persisted_run_and_explains_missing_id() -> None:
    client = FakeAgentClient()
    output = StringIO()

    handle_slash_command("/run run_recent", client=client, output=output)
    handle_slash_command("/run", client=client, output=output)
    handle_slash_command("/run run_missing", client=client, output=output)

    rendered = output.getvalue()
    assert client.requested_run_ids == ["run_recent", "run_missing"]
    assert "Historical Report" in rendered
    assert "Usage: /run <run_id>" in rendered
    assert "Run not found: run_missing" in rendered


def test_render_run_uses_rich_markdown_for_unknown_report(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_run(
        {
            "id": "run_markdown",
            "status": "completed",
            "report_markdown": (
                "# HyperTrade 技能清单\n\n"
                "| 技能 | 说明 |\n"
                "|---|---|\n"
                "| market_summary | 获取 OKX 行情概览 |\n"
            ),
            "report_json": {"planner": "deepseek"},
            "trace_events": [{"tool_name": "graph.final_report", "status": "completed"}],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "HyperTrade 技能清单" in rendered
    assert "market_summary" in rendered
    assert "Agent Report" not in rendered
    assert "HyperTrade Run" not in rendered
    assert "Tool Trace" not in rendered
    assert "# HyperTrade" not in rendered
    assert "|---|---|" not in rendered


def test_render_run_strips_emoji_icons_from_rich_markdown_report(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_run(
        {
            "id": "run_markdown_icons",
            "status": "completed",
            "report_markdown": "# 📊 总览\n\n- ✅ 数据源: BitPro\n- ⚠️ 风险: 回撤偏高",
            "report_json": {"planner": "deepseek"},
            "trace_events": [{"tool_name": "graph.final_report", "status": "completed"}],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "总览" in rendered
    assert "数据源" in rendered
    assert "风险" in rendered
    assert "📊" not in rendered
    assert "✅" not in rendered
    assert "⚠" not in rendered


def test_render_run_uses_rich_bitpro_backtest_result_table(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_run(
        {
            "id": "run_bitpro_results",
            "status": "completed",
            "report_markdown": (
                "## BitPro 回测结果\n\n"
                "- result #161, strategy #178: [合约][1D][CTA] ETH · "
                "Donchian89/EMA89趋势跟踪稳健版 · 100U; "
                "收益 305.53878586955756%, 年化 80.6615%, 回撤 30.4763%"
            ),
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {"tool_name": "graph.final_report", "status": "completed"},
                {
                    "tool_name": "bitpro_backtest_list_results",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "contract_version": "bitpro-mcp-v1",
                        "filter": {
                            "metric": "total_return_pct",
                            "min_total_return_pct": 100,
                            "status": "completed",
                            "sort_by": "return",
                            "sort_order": "desc",
                            "limit": 40,
                        },
                        "result_count": 2,
                        "raw_result_count": 21,
                        "results": [
                            {
                                "id": 161,
                                "strategy_id": 178,
                                "strategy_name": (
                                    "[合约][1D][CTA] ETH · Donchian89/EMA89趋势跟踪稳健版 · 100U"
                                ),
                                "total_return_pct": "305.53878586955756",
                                "annual_return_pct": "80.6615",
                                "max_drawdown_pct": "30.4763",
                                "sharpe_ratio": "1.1422",
                                "win_rate_pct": "87.5",
                                "trade_count": 8,
                                "start_date": "2024-01-01",
                                "end_date": "2026-05-15",
                            },
                            {
                                "id": 193,
                                "strategy_id": 162,
                                "strategy_name": (
                                    "[合约][1H][CTA] ETH · Heikin Ashi趋势跟踪低频版 · 100U"
                                ),
                                "total_return_pct": "141.83713784801657",
                                "annual_return_pct": "142.4246",
                                "max_drawdown_pct": "14.5667",
                                "sharpe_ratio": "0.3969",
                                "win_rate_pct": "50.63",
                                "trade_count": 239,
                                "start_date": "2025-06-08",
                                "end_date": "2026-06-07",
                            },
                        ],
                        "tool_calls": [
                            {"tool": "bitpro_capabilities", "status": "success"},
                            {"tool": "bitpro_health", "status": "success"},
                            {"tool": "backtest_list_results", "status": "success"},
                        ],
                    },
                },
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "BitPro 回测排行" in rendered
    assert "总收益口径" in rendered
    assert "命中 2 / 原始 21" in rendered
    assert "305.54%" in rendered
    assert "30.48%" in rendered
    assert "Heikin Ashi趋势跟踪低频版" in rendered
    assert "305.53878586955756%" not in rendered
    assert "result #161, strategy #178" not in rendered


def test_render_run_structured_output_includes_bitpro_backtest_detail(capsys) -> None:
    render_run(
        {
            "id": "run_bitpro_detail",
            "status": "completed",
            "report_markdown": "## BitPro 回测详情\n\n- result #199",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_backtest_list_results",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "filter": {"metric": "total_return_pct", "min_total_return_pct": 0},
                        "result_count": 1,
                        "raw_result_count": 1,
                        "results": [
                            {
                                "id": 199,
                                "strategy_id": 292,
                                "strategy_name": "[合约][4H][CTA] Top20 · 波动压缩突破",
                                "total_return_pct": "9.701471818245139",
                                "annual_return_pct": "25.0842",
                                "max_drawdown_pct": "5.6088",
                                "sharpe_ratio": "0.5117",
                                "win_rate_pct": "56.52",
                                "trade_count": 23,
                                "start_date": "2026-01-01",
                                "end_date": "2026-06-01",
                            }
                        ],
                    },
                },
                {
                    "tool_name": "bitpro_backtest_get_result",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "backtest_id": "199",
                        "result": {
                            "id": 199,
                            "strategy_id": 292,
                            "strategy_name": "[合约][4H][CTA] Top20 · 波动压缩突破",
                            "status": "completed",
                            "timeframe": "4h",
                            "start_date": "2026-01-01",
                            "end_date": "2026-06-01",
                            "metrics": {
                                "total_return_pct": "9.701471818245139",
                                "max_drawdown_pct": "5.6088",
                                "sharpe_ratio": "0.5117",
                                "win_rate_pct": "56.52",
                                "trade_count": 23,
                            },
                        },
                        "artifact_summary": {
                            "equity_curve": {
                                "available": True,
                                "count": 907,
                                "sample_count": 30,
                            },
                            "trades": {"available": True, "count": 46, "sample_count": 30},
                        },
                    },
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "BitPro backtest ranking:" in output
    assert "BitPro 回测详情:" in output
    assert "结果: #199 / strategy #292" in output
    assert "核心指标:" in output
    assert "收益: 9.7%" in output
    assert "最大回撤: 5.61%" in output
    assert "权益曲线: 可用，907 条，展示 30 条样本" in output


def test_render_run_uses_rich_bitpro_backtest_detail_panel(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_run(
        {
            "id": "run_bitpro_detail_rich",
            "status": "completed",
            "report_markdown": "## BitPro 回测详情\n\n- result #199",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {
                    "tool_name": "bitpro_backtest_get_result",
                    "status": "completed",
                    "output_json": {
                        "status": "ok",
                        "backtest_id": "199",
                        "result": {
                            "id": 199,
                            "strategy_id": 292,
                            "strategy_name": "[合约][4H][CTA] Top20 · 波动压缩突破",
                            "status": "completed",
                            "timeframe": "4h",
                            "start_date": "2026-01-01",
                            "end_date": "2026-06-01",
                            "metrics": {
                                "total_return_pct": "9.701471818245139",
                                "max_drawdown_pct": "5.6088",
                                "sharpe_ratio": "0.5117",
                                "win_rate_pct": "56.52",
                                "trade_count": 23,
                            },
                        },
                        "artifact_summary": {
                            "equity_curve": {
                                "available": True,
                                "count": 907,
                                "sample_count": 30,
                            }
                        },
                    },
                }
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "BitPro 回测详情" in rendered
    assert "result #199 / strategy #292" in rendered
    assert "核心指标" in rendered
    assert "9.7%" in rendered
    assert "数据样本" in rendered
    assert "权益曲线" in rendered
    assert "可用" in rendered
    assert "available" not in rendered
    assert "\x1b[" in rendered


def test_render_run_keeps_plain_markdown_when_renderer_plain(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "plain")
    output = StringIO()

    render_run(
        {
            "id": "run_plain",
            "status": "completed",
            "report_markdown": "# Plain Report\n\n| A | B |\n|---|---|\n| 1 | 2 |",
            "trace_events": [],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "# Plain Report" in rendered
    assert "|---|---|" in rendered


def test_workflow_results_use_rich_markdown_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_strategy_research_result(
        {
            "id": "srch_cli",
            "strategy_key": "momentum_breakout_v1",
            "title": "突破研究",
            "report_markdown": "# Research\n\n| Item | Value |\n|---|---|\n| bias | up |",
        },
        output=output,
    )
    render_backtest_result(
        {
            "id": "bt_cli",
            "research_id": "srch_cli",
            "strategy_key": "momentum_breakout_v1",
            "metrics": {"total_return_pct": "1.2", "trade_count": 3},
            "report_markdown": "# Backtest\n\n- pass",
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Strategy Research" not in rendered
    assert "Backtest Report" not in rendered
    assert "Research" in rendered
    assert "Backtest" in rendered
    assert "# Research" not in rendered
    assert "|---|---|" not in rendered


def test_ask_streams_agent_run_progress(capsys) -> None:
    client = FakeAgentClient()

    exit_code = main(["ask", "请做行情归纳"], client=client)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Agent: running" in output
    assert "Agent: completed" in output
    assert "executing tool" not in output
    assert "tool market.summary completed" not in output
    assert "planning next" not in output
    assert "# CLI Report" in output
    assert "+ Thought:" not in output


def test_run_stream_can_show_full_progress_when_requested(monkeypatch, capsys) -> None:
    monkeypatch.setenv("HYPERTRADE_PROGRESS", "full")
    client = FakeAgentClient()

    exit_code = main(["ask", "请做行情归纳"], client=client)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Agent status: run created" in output
    assert "Agent status: executing tool market.summary" in output
    assert "Agent status: tool market.summary completed" in output
    assert "Agent status: generating final report" in output


def test_run_stream_shows_thinking_animation_for_tty() -> None:
    client = FakeAgentClient()
    output = TtyStringIO()

    render_run_stream(client, "你会哪些技能？", output=output)

    rendered = output.getvalue()
    assert "+ Thought:" in rendered
    assert "Thinking" in rendered
    assert "Agent: running" in rendered
    assert "executing tool" not in rendered
    assert "CLI Report" in rendered
    assert "# CLI Report" not in rendered


def test_run_stream_preserves_final_report_when_market_symbol_is_not_found(
    monkeypatch,
) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")

    class MissingMarketClient:
        def run_agent_events(self, prompt: str):
            yield {"event": "run_started", "run_id": "run_missing_market"}
            yield {"event": "run_completed", "run_id": "run_missing_market"}
            yield {
                "event": "final",
                "run": {
                    "id": "run_missing_market",
                    "status": "completed",
                    "report_markdown": (
                        "## 结果\n\n"
                        "未找到 MUUSDT-USDT-SWAP；请确认 OKX 标准合约代码。"
                    ),
                    "trace_events": [
                        {
                            "tool_name": "market_ticker",
                            "status": "completed",
                            "output_json": {"found": False},
                        }
                    ],
                },
            }

    output = TtyStringIO()

    render_run_stream(MissingMarketClient(), "看下 MUUSDT 合约的行情", output=output)

    rendered = output.getvalue()
    assert "Agent: completed (run_missing_market)" in rendered
    assert "未找到 MUUSDT-USDT-SWAP；请确认 OKX 标准合约代码。" in rendered


def test_evals_renderer_summarizes_research_os_without_dumping_cases() -> None:
    output = StringIO()

    render_evals_status(
        {
            "status": "passed",
            "cases": [{"name": "tool_selection", "status": "passed"}],
            "research_os": {
                "status": "passed",
                "suite_version": "research_os_golden_v1",
                "case_count": 24,
                "categories": {"safety": 6, "normal": 4},
            },
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Research OS: passed suite=research_os_golden_v1 cases=24" in rendered
    assert "normal=4 safety=6" in rendered


def test_chat_reuses_client_until_exit(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["研究趋势突破策略", "exit"])

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.logged_in is True
    assert client.prompts == ["研究趋势突破策略"]
    output = capsys.readouterr().out
    assert "Run:" not in output
    assert "Tools:" not in output
    assert "# CLI Report" in output


def test_chat_handles_slash_commands_without_agent_run(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(
        [
            "/help",
            "/commands",
            "/status",
            "/model",
            "",
            "/model deepseek",
            "/providers",
            "/tools",
            "/connectors",
            "/runs",
            "/memory",
            "/memory search 风控",
            "/memory disable mem_recent",
            "/rag 风控",
            "/evals",
            "/strategy",
            "/strategy library momentum",
            "/backtests",
            "/price ETH",
            "/candles ETH --bar 1H --limit 50",
            "/compare ETH SOL --bar 4H --limit 100",
            "/experiment 研究ETH突破",
            "/experiment iterate 继续优化 momentum_breakout_v1",
            "/paper status",
            "/paper pause",
            "/paper resume",
            "/paper close ETH",
            "/paper reset",
            "/live intents",
            "/live intent ETH buy 0.01 --reason test order",
            "/live approve loi_new --reason checked",
            "/live execute loi_new",
            "/live reject loi_old --reason no",
            "exit",
        ]
    )

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.logged_in is True
    assert client.prompts == []
    output = capsys.readouterr().out
    assert "/tools" in output
    assert "List registered Agent tools with category, approval gate, and purpose." in output
    assert "Status:" in output
    assert "Model:" in output
    assert "Model switched: deepseek" in output
    assert "Providers:" in output
    assert "market.summary" in output
    assert "Summarize market." in output
    assert "live.order_intent" in output
    assert "Create order intent." in output
    assert "Connectors:" in output
    assert "bitpro BitPro MCP health=not_checked auth=configured" in output
    assert "market_klines scope=read safe_read=yes idempotency=not_required" in output
    assert "run_recent" in output
    assert "mem_recent" in output
    assert "mem_search" in output
    assert "Memory disable: ok" in output
    assert "RAG hits:" in output
    assert "rag-usage.md" in output
    assert "Eval suite:" in output
    assert "tool_selection passed" in output
    assert client.disabled_memory_ids == ["mem_recent"]
    assert "srch_recent" in output
    assert "Strategy library:" in output
    assert "momentum_breakout_v1" in output
    assert "best: memory=mem_fast experiment=exp_fast backtest=bt_fast winner=fast" in output
    assert client.strategy_library_queries == ["momentum"]
    assert "bt_recent" in output
    assert "ETH-USDT-SWAP" in output
    assert "K-line trend:" in output
    assert "Relative strength:" in output
    assert "Strategy experiment completed" in output
    assert "Strategy iteration completed" in output
    assert client.experiment_prompts == ["研究ETH突破"]
    assert client.iteration_prompts == ["继续优化 momentum_breakout_v1"]
    assert client.price_symbols == ["ETH"]
    assert client.candle_calls == [{"symbol": "ETH", "bar": "1H", "limit": 50}]
    assert client.compare_calls == [{"symbols": ["ETH", "SOL"], "bar": "4H", "limit": 100}]
    assert client.paper_actions == ["pause", "resume", "close", "reset"]
    assert "Paper trading:" in output
    assert "paper_cli" in output
    assert "ETH-USDT-SWAP" in output
    assert "Paper control: paused" in output
    assert "Paper control: running" in output
    assert "Paper close: 1 positions" in output
    assert "Paper reset: new session paper_new" in output
    assert "Live order intents:" in output
    assert "loi_recent" in output
    assert "loi_new pending_approval testnet ETH-USDT-SWAP buy 0.01 market" in output
    assert "loi_new approved testnet ETH-USDT-SWAP buy 0.01 market" in output
    assert "loi_new execution_failed testnet ETH-USDT-SWAP buy 0.01 market" in output
    assert "risk: allowed" in output
    assert "loi_old rejected testnet ETH-USDT-SWAP buy 0.01 market" in output


def test_slash_help_describes_every_command() -> None:
    output = StringIO()

    render_slash_help(output=output)

    rendered = output.getvalue()
    lines = [line for line in rendered.splitlines() if line.startswith("- ")]
    assert lines
    assert len(lines) == len(SLASH_COMMAND_HELP)
    for command, description in SLASH_COMMAND_HELP:
        assert command in rendered
        assert description in rendered
    assert any(
        "/memory search <query>" in line and "Search audited memory" in line for line in lines
    )
    assert any(
        "/backtest --source bitpro_mcp" in line and "BitPro MCP K-lines" in line for line in lines
    )


def test_slash_help_uses_semantic_colors_for_tty(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = TtyStringIO()

    render_slash_help(output=output)

    rendered = output.getvalue()
    assert "/help" in rendered
    assert "Show this command list." in rendered
    assert len(set(re.findall(r"\x1b\[[0-9;]+m", rendered))) >= 3


def test_slash_help_keeps_plain_text_for_non_tty() -> None:
    output = StringIO()

    render_slash_help(output=output)

    rendered = output.getvalue()
    assert "\x1b[" not in rendered


def test_render_tools_includes_tool_descriptions() -> None:
    output = StringIO()

    render_tools(
        [
            {
                "name": "market.summary",
                "category": "market",
                "requires_approval": False,
                "description": "Summarize market.",
                "policy": {
                    "scope": "read",
                    "approval": "none",
                    "idempotency": "not_required",
                    "source_of_truth": "okx_rest",
                    "timeout_class": "standard",
                    "safe_sample_limit": 10,
                    "failure_behavior": "return_unavailable",
                },
            },
            {
                "name": "live.order_intent",
                "category": "live",
                "requires_approval": True,
                "description": "Create order intent.",
                "policy": {
                    "scope": "testnet_write",
                    "approval": "required",
                    "idempotency": "required",
                    "source_of_truth": "hypertrade_db",
                    "timeout_class": "quick",
                    "safe_sample_limit": 1,
                    "failure_behavior": "return_structured_error",
                },
            },
        ],
        output=output,
    )

    rendered = output.getvalue()
    assert (
        "- market.summary [market] scope=read approval=none idempotency=not_required: "
        "Summarize market."
    ) in rendered
    assert (
        "- live.order_intent [live] scope=testnet_write approval=required "
        "idempotency=required: Create order intent."
    ) in rendered


def test_render_connectors_shows_origin_scope_and_secret_status() -> None:
    output = StringIO()

    render_connectors(
        {
            "connectors": {
                "fixture": {
                    "display_name": "Fixture Connector",
                    "health": {"status": "ok"},
                    "auth": {"configured": False, "secret_redacted": True},
                    "supported_scopes": ["read"],
                    "tools": [
                        {
                            "name": "fixture_echo",
                            "scope": "read",
                            "safe_read": True,
                            "idempotency_required": False,
                        }
                    ],
                }
            }
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Connectors:" in rendered
    assert "- fixture Fixture Connector health=ok auth=not_configured scopes=read" in rendered
    assert "fixture_echo scope=read safe_read=yes idempotency=not_required" in rendered


def test_render_tools_uses_distinct_tty_colors(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    output = TtyStringIO()

    render_tools(
        [
            {
                "name": "market.summary",
                "category": "market",
                "requires_approval": False,
                "description": "Summarize market.",
                "policy": {
                    "scope": "read",
                    "approval": "none",
                    "idempotency": "not_required",
                    "source_of_truth": "okx_rest",
                    "timeout_class": "standard",
                    "safe_sample_limit": 10,
                    "failure_behavior": "return_unavailable",
                },
            },
            {
                "name": "live.order_intent",
                "category": "live",
                "requires_approval": True,
                "description": "Create order intent.",
                "policy": {
                    "scope": "testnet_write",
                    "approval": "required",
                    "idempotency": "required",
                    "source_of_truth": "hypertrade_db",
                    "timeout_class": "quick",
                    "safe_sample_limit": 1,
                    "failure_behavior": "return_structured_error",
                },
            },
        ],
        output=output,
    )

    rendered = output.getvalue()
    assert "market.summary" in rendered
    assert "live.order_intent" in rendered
    assert "approval" in rendered
    assert len(set(re.findall(r"\x1b\[[0-9;]+m", rendered))) >= 4


def test_run_stream_uses_status_colors_for_tty(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("HYPERTRADE_THINKING_ANIMATION", "0")
    client = FakeAgentClient()
    output = TtyStringIO()

    render_run_stream(client, "看下ETH行情", output=output)

    rendered = output.getvalue()
    assert "Agent: running" in rendered
    assert "Agent: completed" in rendered
    assert "executing tool" not in rendered
    assert len(set(re.findall(r"\x1b\[[0-9;]+m", rendered))) >= 2


def test_bare_command_starts_chat_loop(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["请做行情归纳", ":q"])

    exit_code = main([], client=client, input_fn=_next_input(inputs))

    assert exit_code == 0
    assert client.logged_in is True
    assert client.prompts == ["请做行情归纳"]
    output = capsys.readouterr().out
    assert "HyperTrade / Operator Console" in output
    assert "Run:" not in output
    assert "Tools:" not in output
    assert "# CLI Report" in output


def test_chat_continues_after_remote_stream_disconnect(capsys) -> None:
    class DisconnectingClient(FakeAgentClient):
        def run_agent_events(self, prompt: str):
            self.prompts.append(prompt)
            raise httpx.ConnectError("connection refused")
            yield {}

    client = DisconnectingClient()
    inputs = iter(["看下ETH行情", ":q"])
    prompts: list[str] = []

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return next(inputs)

    exit_code = main([], client=client, input_fn=input_fn)

    assert exit_code == 0
    assert client.prompts == ["看下ETH行情"]
    assert prompts == ["ht> ", "ht> "]
    output = capsys.readouterr().out
    assert "Remote API connection failed" in output


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


def test_login_command_writes_remote_client_config(tmp_path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "client.env"
    monkeypatch.setenv("HYPERTRADE_CLIENT_ENV", str(config_path))
    inputs = iter(["http://remote.test:3333", "operator", "secret"])

    exit_code = main(["/login"], input_fn=_next_input(inputs))

    assert exit_code == 0
    assert config_path.exists()
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert config_path.read_text() == (
        "HYPERTRADE_API_URL='http://remote.test:3333'\n"
        "HYPERTRADE_USERNAME='operator'\n"
        "HYPERTRADE_PASSWORD='secret'\n"
    )
    output = capsys.readouterr().out
    assert "HyperTrade login saved" in output
    assert str(config_path) in output


def test_saved_login_config_makes_remote_mode_default(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "client.env"
    config_path.write_text(
        "HYPERTRADE_API_URL='http://remote.test:3333'\n"
        "HYPERTRADE_USERNAME='operator'\n"
        "HYPERTRADE_PASSWORD='secret'\n"
    )
    monkeypatch.setenv("HYPERTRADE_CLIENT_ENV", str(config_path))
    captured: list[tuple[CliConfig, bool]] = []

    exit_code = main(
        ["ask", "hello"],
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
    trace_names = [event["tool_name"] for event in run["trace_events"]]
    assert trace_names[0] == "graph.intent_classify"
    assert "market.summary" not in trace_names
    assert run["report_json"]["status"] == "provider_unavailable"
    assert run["report_json"]["tool_calls"] == []
    assert run["run_state_json"]["current_node"] == "final_report"

    restored = client.get_run(str(run["id"]))
    assert restored["id"] == run["id"]
    assert restored["report_markdown"] == run["report_markdown"]


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


def test_api_client_loads_one_persisted_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/agent/runs/run_saved"
        return httpx.Response(
            200,
            json={
                "id": "run_saved",
                "status": "completed",
                "report_markdown": "# Persisted",
                "trace_events": [],
            },
        )

    client = AgentApiClient(
        CliConfig(api_url="http://example.test/", username="admin", password="secret"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.get_run("run_saved")["id"] == "run_saved"


def test_api_client_stream_keeps_read_open_for_long_tools() -> None:
    captured: dict[str, Any] = {}

    class StreamResponse:
        def __enter__(self) -> StreamResponse:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_lines(self) -> Iterator[str]:
            yield "event: run_completed"
            yield 'data: {"run": {"id": "run_api", "status": "completed"}}'
            yield ""

    class CapturingStreamClient:
        def stream(self, method: str, url: str, **kwargs: Any) -> StreamResponse:
            captured["method"] = method
            captured["url"] = url
            captured["timeout"] = kwargs.get("timeout")
            return StreamResponse()

    client = AgentApiClient(
        CliConfig(
            api_url="http://example.test/",
            username="admin",
            password="secret",
            timeout_seconds=3.0,
        ),
        http_client=CapturingStreamClient(),  # type: ignore[arg-type]
    )

    events = list(client.run_agent_events("hello"))

    timeout = captured["timeout"]
    assert captured["method"] == "POST"
    assert captured["url"] == "http://example.test/api/agent/runs/stream"
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 3.0
    assert timeout.write == 3.0
    assert timeout.pool == 3.0
    assert timeout.read is None
    assert events == [{"event": "run_completed", "run": {"id": "run_api", "status": "completed"}}]


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
    assert client.backtest_calls == [
        {
            "research_id": "srch_recent",
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": False,
            "symbol": "BTC",
            "bar": "1H",
            "candle_limit": 100,
            "candle_source": "sample",
        }
    ]
    output = capsys.readouterr().out
    assert "srch_cli" in output
    assert "Strategy research created" in output
    assert "bt_cli" in output
    assert "Backtest completed" in output
    assert "Return 1.9%" in output


def test_chat_runs_live_candle_backtest_shortcut(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["/backtest --live --symbol ETH --bar 1H --limit 24", "exit"])

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.backtest_calls == [
        {
            "research_id": "srch_recent",
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": True,
            "symbol": "ETH",
            "bar": "1H",
            "candle_limit": 24,
            "candle_source": "okx",
        }
    ]
    assert "Backtest completed" in capsys.readouterr().out


def test_chat_runs_bitpro_archive_backtest_shortcut(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["/backtest --source bitpro --symbol ETH --bar 1H --limit 24", "exit"])

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.backtest_calls == [
        {
            "research_id": "srch_recent",
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": False,
            "symbol": "ETH",
            "bar": "1H",
            "candle_limit": 24,
            "candle_source": "bitpro",
        }
    ]
    assert "Backtest completed" in capsys.readouterr().out


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
