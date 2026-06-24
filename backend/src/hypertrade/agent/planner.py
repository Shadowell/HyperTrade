"""LLM-driven planning loop using provider function/tool calling.

AgentPlanner only decides which tool names and JSON arguments to request. It
does not touch databases, exchanges, or secrets; AgentKernel owns trusted tool
execution. This split makes provider output easy to test and safe to inspect.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hypertrade.providers.chat import ChatProvider
from hypertrade.providers.deepseek import ChatResponse

ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]

TOOL_SCHEMAS: list[dict[str, Any]] = [
    # These schemas are sent to OpenAI-compatible providers. Keep descriptions
    # specific: good tool descriptions are the first layer of tool-choice quality.
    {
        "type": "function",
        "function": {
            "name": "market_summary",
            "description": (
                "Fetch and summarize the latest OKX SWAP all-market state, including "
                "market heat, breadth, sentiment, top movers, and risk appetite."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "market_ticker",
            "description": (
                "Fetch one OKX SWAP ticker for any requested listed symbol, "
                "for example ETH, SOL-USDT, or PEPE-USDT-SWAP."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Coin symbol or OKX instrument id.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "market_candles",
            "description": (
                "Fetch recent OKX candlesticks for one SWAP instrument and calculate "
                "trend features such as return, range, moving averages, and close position."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Coin symbol or OKX instrument id.",
                    },
                    "bar": {
                        "type": "string",
                        "description": "OKX candle bar such as 15m, 1H, 4H, or 1D.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of candles to fetch, default 100.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "market_compare",
            "description": (
                "Compare relative strength across multiple OKX SWAP symbols using "
                "recent candle trend features."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Coin symbols or OKX instrument ids to compare.",
                    },
                    "bar": {
                        "type": "string",
                        "description": "OKX candle bar such as 15m, 1H, 4H, or 1D.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of candles to fetch per symbol, default 100.",
                    },
                },
                "required": ["symbols"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "market_intelligence",
            "description": (
                "Read-only multi-source market intelligence for one symbol, including "
                "OKX public funding, open interest, and curated market context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Coin symbol or OKX SWAP instrument id.",
                    },
                    "include_curated": {
                        "type": "boolean",
                        "description": "Include deterministic curated context, default true.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rag_search",
            "description": "Search the project knowledge base for relevant trading context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text"},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default 3)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_write",
            "description": "Persist an audited long-term memory item for future reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to remember"},
                    "kind": {
                        "type": "string",
                        "description": "Category such as market_summary or strategy_note",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": "Retrieve recent active long-term memory items.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "strategy_library_search",
            "description": (
                "Search aggregated strategy_knowledge memory evidence before proposing "
                "or iterating strategy research. Returns best/latest evidence, failures, "
                "next experiments, and source memory ids."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional keyword such as symbol, variant, failure, or note."
                        ),
                    },
                    "strategy_key": {
                        "type": "string",
                        "description": "Optional canonical strategy key filter.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum strategy summaries to return, default 10.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "strategy_experiment_plan",
            "description": (
                "Read strategy-library evidence and produce bounded candidate variants "
                "for the next strategy experiment without running paper, live, or "
                "BitPro write tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Strategy iteration prompt or operator goal.",
                    },
                    "strategy_key": {
                        "type": "string",
                        "description": "Optional canonical strategy key filter.",
                    },
                    "max_variants": {
                        "type": "integer",
                        "description": "Maximum bounded candidate variants to plan.",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "strategy_draft",
            "description": "Create a strategy research record from a hypothesis or question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Strategy research hypothesis or question",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "backtest_run",
            "description": "Run a Backtrader backtest against sample candles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "research_id": {
                        "type": "string",
                        "description": "Research record ID (srch_*). Empty = default strategy.",
                    },
                    "strategy_key": {
                        "type": "string",
                        "description": "Strategy key to run (default: momentum_breakout_v1)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_capabilities",
            "description": "Read BitPro MCP contract, tool groups, permissions, and data policy.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_health",
            "description": "Check BitPro API health before calling BitPro data tools.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_market_klines",
            "description": (
                "Read real K-line data from BitPro through the MCP tool contract. "
                "Use this when the user explicitly asks for BitPro, MCP, "
                "or BitPro data direct access."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Coin symbol or BitPro/OKX instrument id.",
                    },
                    "timeframe": {
                        "type": "string",
                        "description": "BitPro timeframe such as 1h, 4h, or 1d.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of candles to fetch, default 200.",
                    },
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_dashboard",
            "description": (
                "Read BitPro paper/simulation dashboard state. Read-only. "
                "When no strategy_id is provided, HyperTrade also returns the BitPro "
                "running strategy inventory so all/哪些/几个 paper strategy questions "
                "are not answered from the current dashboard instance alone."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {
                        "type": "integer",
                        "description": (
                            "Optional explicit BitPro strategy id filter. Omit this for all/"
                            "全部/哪些/几个 running paper strategy questions."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_events",
            "description": (
                "Read BitPro paper/simulation event stream. Read-only. Use this "
                "for paper errors, logs, lifecycle events, order rejects, and "
                "monitoring evidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {
                        "type": "integer",
                        "description": "Optional BitPro strategy id filter.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum events to request and show, default 50.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_equity_curve",
            "description": (
                "Read BitPro paper/simulation equity curve and drawdown samples. "
                "Read-only. Use this for paper PnL curve, equity drift, drawdown, "
                "and monitoring evidence."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {
                        "type": "integer",
                        "description": "Optional BitPro strategy id filter.",
                    },
                    "sample_limit": {
                        "type": "integer",
                        "description": (
                            "Maximum curve rows to include in the Agent output, default 50."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_monitor_snapshot",
            "description": (
                "Capture a durable BitPro paper/simulation monitoring snapshot. "
                "Read-only. Reads dashboard, event stream, and equity curve evidence, "
                "then compares it with the previous snapshot for drift."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {
                        "type": "integer",
                        "description": "Optional BitPro strategy id filter.",
                    },
                    "event_limit": {
                        "type": "integer",
                        "description": "Maximum paper events to request, default 50.",
                    },
                    "equity_sample_limit": {
                        "type": "integer",
                        "description": "Maximum equity curve rows to sample, default 50.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_live_positions",
            "description": "Read BitPro live account positions for diagnostics only. Never writes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exchange": {"type": "string", "description": "Exchange name, default okx."},
                    "symbol": {"type": "string", "description": "Optional symbol filter."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_live_order_history",
            "description": (
                "Read-only BitPro live account order history for diagnostics. Use this "
                "for recent/latest live orders, 最近一笔实盘订单, real-account order "
                "history, filled/rejected order audit, and strategy attribution. Never writes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exchange": {"type": "string", "description": "Exchange name, default okx."},
                    "symbol": {"type": "string", "description": "Optional symbol filter."},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum history rows to request, default 50.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_strategy_search",
            "description": (
                "Search BitPro strategy library before creating or selecting a strategy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Strategy name or keyword."},
                    "page": {"type": "integer", "description": "Result page, default 1."},
                    "per_page": {"type": "integer", "description": "Page size, default 18."},
                    "status": {"type": "string", "description": "Status filter, default all."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_strategy_generate",
            "description": (
                "Use BitPro strategy-generation skills to draft strategy code for research, "
                "backtesting, or paper validation. Not for live trading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Strategy idea or requirement."},
                    "symbol": {"type": "string", "description": "Trading symbol, default BTC."},
                    "timeframe": {
                        "type": "string",
                        "description": "Strategy timeframe, default 1h.",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_strategy_create",
            "description": "Create a BitPro strategy definition from generated or reviewed code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Strategy name."},
                    "script_content": {"type": "string", "description": "Strategy Python code."},
                    "description": {"type": "string", "description": "Optional strategy notes."},
                    "config": {"type": "object", "description": "Optional strategy config."},
                    "exchange": {"type": "string", "description": "Exchange, default okx."},
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Symbols the strategy supports.",
                    },
                },
                "required": ["name", "script_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_strategy_update",
            "description": (
                "Update BitPro strategy metadata or DB-backed strategy content, such as "
                "renaming a strategy to the canonical BitPro naming format. Not live trading."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "integer", "description": "BitPro strategy id."},
                    "name": {"type": "string", "description": "Canonical strategy name."},
                    "script_content": {
                        "type": "string",
                        "description": "Optional replacement strategy Python code.",
                    },
                    "description": {"type": "string", "description": "Optional strategy notes."},
                    "config": {"type": "object", "description": "Optional strategy config."},
                    "exchange": {"type": "string", "description": "Optional exchange."},
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional symbols the strategy supports.",
                    },
                },
                "required": ["strategy_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_backtest_start_job",
            "description": "Start a BitPro-owned backtest job for a strategy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "integer", "description": "BitPro strategy id."},
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD."},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD."},
                    "initial_capital": {
                        "type": "number",
                        "description": "Initial capital, default 10000.",
                    },
                    "exchange": {"type": "string", "description": "Exchange, default okx."},
                    "symbol": {"type": "string", "description": "Optional symbol override."},
                    "timeframe": {"type": "string", "description": "Optional timeframe override."},
                },
                "required": ["strategy_id", "start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_backtest_get_job",
            "description": "Read status/progress for a BitPro backtest job.",
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "Backtest job id."}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_backtest_list_results",
            "description": (
                "Read BitPro-owned backtest result records and filter by actual total "
                "backtest return. Use this for questions like 回测收益大于100%, "
                "best backtests, result ranking, or page parity. Do not use annualized "
                "return as total return."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "min_total_return_pct": {
                        "type": "number",
                        "description": "Optional minimum actual total return percent.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Backtest status filter, default completed.",
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Sort key for BitPro, default return.",
                    },
                    "sort_order": {
                        "type": "string",
                        "description": "Sort order asc or desc, default desc.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum records to inspect, default 100.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_backtest_get_result",
            "description": (
                "Read one BitPro-owned backtest result detail, including metrics, "
                "equity curve, trades, orders, fills, and drawdown artifact samples. "
                "Use this when the user asks for a specific result id or evidence details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "backtest_id": {
                        "type": "string",
                        "description": (
                            "BitPro backtest result id, usually from backtest list results."
                        ),
                    },
                    "sample_limit": {
                        "type": "integer",
                        "description": "Maximum rows to sample per artifact, default 20.",
                    },
                },
                "required": ["backtest_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_configure",
            "description": "Configure a BitPro paper/simulation instance for a strategy.",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "integer", "description": "BitPro strategy id."},
                    "initial_equity": {
                        "type": "number",
                        "description": "Paper equity, default 10000.",
                    },
                    "exchange": {"type": "string", "description": "Exchange, default okx."},
                    "loop_interval_sec": {
                        "type": "integer",
                        "description": "Loop interval seconds, default 60.",
                    },
                },
                "required": ["strategy_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_start",
            "description": "Start a specific BitPro paper/simulation instance. Not live trading.",
            "parameters": {
                "type": "object",
                "properties": {"strategy_id": {"type": "integer", "description": "Instance id."}},
                "required": ["strategy_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_pause",
            "description": "Pause a specific BitPro paper/simulation instance. Not live trading.",
            "parameters": {
                "type": "object",
                "properties": {"strategy_id": {"type": "integer", "description": "Instance id."}},
                "required": ["strategy_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_resume",
            "description": "Resume a specific BitPro paper/simulation instance. Not live trading.",
            "parameters": {
                "type": "object",
                "properties": {"strategy_id": {"type": "integer", "description": "Instance id."}},
                "required": ["strategy_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bitpro_paper_stop",
            "description": "Stop a specific BitPro paper/simulation instance. Not live trading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "integer", "description": "Instance id."},
                    "clear_metrics": {
                        "type": "boolean",
                        "description": "Whether BitPro should clear metrics.",
                    },
                },
                "required": ["strategy_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "live_order_intent",
            "description": (
                "Create a testnet/live order intent that must be approved by a human. "
                "This tool never executes an exchange order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Coin symbol or OKX instrument id.",
                    },
                    "side": {"type": "string", "enum": ["buy", "sell"]},
                    "size": {
                        "type": "string",
                        "description": "Contract/order size as decimal text.",
                    },
                    "order_type": {"type": "string", "enum": ["market", "limit"]},
                    "price": {
                        "type": "string",
                        "description": "Limit price, if order_type is limit.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this order is being proposed.",
                    },
                },
                "required": ["symbol", "side", "size"],
            },
        },
    },
]

_IDEMPOTENCY_REQUIRED_TOOL_NAMES = {
    "bitpro_strategy_generate",
    "bitpro_strategy_create",
    "bitpro_strategy_update",
    "bitpro_backtest_start_job",
    "bitpro_paper_configure",
    "bitpro_paper_start",
    "bitpro_paper_pause",
    "bitpro_paper_resume",
    "bitpro_paper_stop",
    "live_order_intent",
}

for schema in TOOL_SCHEMAS:
    function = schema.get("function", {})
    name = function.get("name")
    if name not in _IDEMPOTENCY_REQUIRED_TOOL_NAMES:
        continue
    parameters = function.get("parameters", {})
    properties = parameters.setdefault("properties", {})
    properties.setdefault(
        "idempotency_key",
        {
            "type": "string",
            "description": (
                "Unique key for this requested write action, for example "
                "run id + tool purpose."
            ),
        },
    )

_SYSTEM_PROMPT = """\
You are HyperTrade, an agent-first crypto research assistant.
You have market data tools, RAG search, long-term memory, strategy research, and backtesting.
Use market_summary for all-market questions about 市场热度, 市场情绪, 整体市场,
全市场, 大盘, 行情归纳, market heat, market sentiment, breadth, or risk appetite.
Do not answer all-market heat by calling only market_ticker for BTC/ETH/SOL.
Use market_ticker when the user asks about any specific listed coin or one OKX
instrument, such as ETH, SOL, DOGE, PEPE-USDT, or BTC-USDT-SWAP.
Use market_candles when the user asks about trend,走势, K线, breakthrough, pullback,
support/resistance, or multi-period market research for a specific symbol.
Use market_compare when the user asks to compare two or more symbols, relative
strength, 哪个更强, 跑赢, 强弱, or leader/laggard.
Use market_intelligence when the user asks about funding, open interest,
资金费率, 持仓, OI, news, onchain, sentiment, 情绪, 链上, or source-backed market
context beyond price/K-line data. Treat this as context, not buy/sell advice.
Use strategy_library_search when the user asks about previous strategy
experience, 策略库, 历史策略, 记忆沉淀, what has worked/failed, failure reasons,
or the next strategy experiment. Treat it as evidence from strategy_knowledge
memory, not as unsourced model recall.
Use strategy_experiment_plan after strategy_library_search when the user asks
to continue, iterate, optimize, or plan a next strategy experiment from prior
evidence. Keep variants bounded and source them to strategy-library evidence.
Use bitpro_capabilities and bitpro_health before BitPro-specific read tools.
Do not infer BitPro live runtime status from bitpro_capabilities.live_trading_enabled;
that flag is the HyperTrade MCP live write/order gate. Use bitpro_paper_dashboard
or BitPro live read tools to describe the connected BitPro runtime mode.
Do not summarize paper dashboard evidence as BitPro live trading disabled.
If dashboard data says mode=paper or dry_run=true, say the connected dashboard
or strategy is currently in paper/dry-run mode; do not infer global BitPro
platform live-trading configuration from that alone.
Use bitpro_market_klines when the user explicitly asks for BitPro MCP, BitPro data,
or BitPro direct K-line access. Keep BitPro live-position reads diagnostic-only.
Use bitpro_live_order_history when the user asks about live/real-account orders,
实盘订单, 最近一笔订单, 历史订单, filled/rejected live orders, or strategy
attribution for real-account orders.
Do not use market_summary for live account order-history questions.
Use bitpro_paper_dashboard without strategy_id when the user asks about all/全部/
哪些/几个 running paper or 模拟盘 strategies. Treat paper_scope.dashboard_scope=
current_instance as only the current BitPro dashboard view; use
running_strategies to list running strategies and never claim there is only one
paper strategy from the dashboard view alone.
Use bitpro_paper_events when the user asks about paper logs, events, errors,
exceptions, order rejects, or why a paper strategy behaved abnormally.
Use bitpro_paper_equity_curve when the user asks about paper equity, PnL curve,
drawdown, drift, or time-series monitoring evidence. Report missing rows as
unavailable; never synthesize paper event or curve rows.
Use bitpro_paper_monitor_snapshot when the user asks to monitor paper drift,
compare with the previous paper state, record a monitor snapshot, or ask what
changed since the last paper check. This is read-only evidence capture.
For BitPro paper monitoring/equity/event answers, summarize the conclusion and
core metrics only. Do not list raw strategy inventories, individual equity
points, or ordinary event rows unless the user explicitly asks for raw evidence.
Use bitpro_backtest_list_results when the user asks about BitPro backtest
performance, rankings, winners, or thresholds such as 回测收益大于100%. Report the
actual total_return_pct metric from BitPro backtest results; do not substitute
annual_return_pct, strategy descriptions, memory, or unstated assumptions.
Use bitpro_backtest_get_result when the user asks for one specific BitPro
backtest result id, detail evidence, equity curve, trades, orders, fills, or
drawdown artifacts. Report missing artifacts as unavailable; never synthesize
artifact rows.
When the user asks BitPro to develop, store, backtest, or paper-validate a strategy,
use BitPro strategy/backtest/paper tools. These are research/simulation writes,
not live trading writes.
For BitPro strategy/backtest/paper write tools and live_order_intent, include a
unique idempotency_key. Without it, trusted governance policy will deny execution.
Plan which tools to call, execute them, then write a concise Markdown report.
When the user asks to place or prepare an order, use live_order_intent only to
create a pending human approval item. Never claim that an exchange order was executed.
Do not append a fixed disclaimer to every response. Keep ordinary market and
tool reports concise, and state the research/risk boundary only for strategy,
backtest, testnet, live-order, or recommendation-like prompts.
""".strip()


@dataclass
class ToolCallRecord:
    tool_name: str
    input_json: dict[str, Any]
    output_json: dict[str, Any]


@dataclass
class PlannerResult:
    final_message: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


class AgentPlanner:
    MAX_ITERATIONS = 8

    def __init__(self, llm: ChatProvider) -> None:
        self._llm = llm

    def run(self, prompt: str, executor: ToolExecutor) -> PlannerResult:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        tool_calls: list[ToolCallRecord] = []

        for _ in range(self.MAX_ITERATIONS):
            response: ChatResponse = self._llm.chat(messages, tools=TOOL_SCHEMAS)

            if not response.tool_calls:
                return PlannerResult(final_message=response.content, tool_calls=tool_calls)

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            if response.reasoning_content:
                assistant_msg["reasoning_content"] = response.reasoning_content
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                try:
                    result = executor(tc.name, tc.arguments)
                except Exception as exc:  # noqa: BLE001 - preserve run traceability
                    result = _executor_error_payload(tc.name, exc)
                tool_calls.append(ToolCallRecord(tc.name, tc.arguments, result))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )

        return PlannerResult(
            final_message="Planning loop reached max iterations.",
            tool_calls=tool_calls,
        )


def _executor_error_payload(tool_name: str, exc: Exception) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "execution_status": "error",
        "unavailable_reason": "execution_error",
        "error": {
            "type": "execution_error",
            "message": str(exc)[:240],
            "retryable": True,
        },
        "missing_data": [
            {
                "field": "tool_result",
                "reason": "execution_error",
                "source_of_truth": "tool_executor",
            }
        ],
        "tool_name": tool_name,
    }
