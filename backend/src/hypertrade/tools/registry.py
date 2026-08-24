"""Static catalog of tools exposed to the Agent and harness surfaces.

The registry is intentionally metadata-only. It tells the LLM, API, CLI, and
frontend what tools exist and which ones need approval, while the actual trusted
execution lives in `hypertrade.agent.kernel.AgentKernel`.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

ToolScope = Literal[
    "read",
    "research_write",
    "paper_write",
    "testnet_write",
    "live_diagnostic_read",
    "live_write",
]
ApprovalPolicy = Literal["none", "required", "blocked"]
IdempotencyPolicy = Literal["not_required", "required"]
TimeoutClass = Literal["quick", "standard", "long"]


@dataclass(frozen=True)
class ToolPolicy:
    scope: ToolScope = "read"
    approval: ApprovalPolicy = "none"
    idempotency: IdempotencyPolicy = "not_required"
    source_of_truth: str = "hypertrade_db"
    timeout_class: TimeoutClass = "standard"
    safe_sample_limit: int = 0
    failure_behavior: str = "return_structured_error"

    def to_dict(self) -> dict[str, str | int]:
        return {
            "scope": self.scope,
            "approval": self.approval,
            "idempotency": self.idempotency,
            "source_of_truth": self.source_of_truth,
            "timeout_class": self.timeout_class,
            "safe_sample_limit": self.safe_sample_limit,
            "failure_behavior": self.failure_behavior,
        }

    def as_dict(self) -> dict[str, str | int]:
        return self.to_dict()


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    requires_approval: bool = False
    policy: ToolPolicy = field(default_factory=ToolPolicy)
    connector_origin: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.policy == ToolPolicy():
            object.__setattr__(
                self,
                "policy",
                _default_policy_for(
                    name=self.name,
                    category=self.category,
                    requires_approval=self.requires_approval,
                ),
            )
        if self.connector_origin is None and self.name.startswith("bitpro."):
            object.__setattr__(
                self,
                "connector_origin",
                {"connector_id": "bitpro", "tool": self.name.removeprefix("bitpro.")},
            )


class ToolRegistry:
    def __init__(self, tools: list[ToolDefinition]) -> None:
        enriched_tools = [_with_default_policy(tool) for tool in tools]
        self._tools = {tool.name: tool for tool in enriched_tools}

    @classmethod
    def default(cls) -> "ToolRegistry":
        # Dot-separated names are used by the harness UI. The planner uses
        # snake_case function names, and AgentKernel maps between the two worlds.
        return cls(
            [
                ToolDefinition("market.summary", "Summarize OKX SWAP market state.", "market"),
                ToolDefinition(
                    "market.ticker",
                    "Read one OKX SWAP ticker by symbol or instrument id.",
                    "market",
                ),
                ToolDefinition(
                    "market.candles",
                    "Read OKX SWAP candles and derived trend features.",
                    "market",
                ),
                ToolDefinition(
                    "market.compare",
                    "Compare relative strength across OKX SWAP symbols.",
                    "market",
                ),
                ToolDefinition(
                    "market.intelligence",
                    "Read funding, open-interest, and curated market context evidence.",
                    "market",
                ),
                ToolDefinition(
                    "world_model.snapshot",
                    (
                        "Read global operator WorldState across market, strategy, "
                        "execution, tools, and deployment."
                    ),
                    "world_model",
                ),
                ToolDefinition(
                    "global_market.snapshot",
                    (
                        "Read current global market regime state across equities, "
                        "volatility, FX, commodities, and rates."
                    ),
                    "global_market",
                ),
                ToolDefinition(
                    "market.tickers",
                    "Read latest OKX SWAP ticker snapshots.",
                    "market",
                ),
                ToolDefinition("rag.search", "Search project and trading knowledge.", "rag"),
                ToolDefinition("memory.write", "Write audited long-term memory.", "memory"),
                ToolDefinition("memory.search", "Read active long-term memory.", "memory"),
                ToolDefinition("strategy.draft", "Draft runtime strategy artifacts.", "strategy"),
                ToolDefinition(
                    "strategy.library_search",
                    "Search aggregated strategy_knowledge memory evidence.",
                    "strategy",
                ),
                ToolDefinition(
                    "strategy.experiment_plan",
                    "Plan bounded strategy experiment variants from prior evidence.",
                    "strategy",
                ),
                ToolDefinition(
                    "research.mandate_read",
                    "Read an operator-approved research mandate and its immutable safety bounds.",
                    "research",
                ),
                ToolDefinition(
                    "research.strategy_spec_draft",
                    (
                        "Draft a schema-valid StrategySpec within an active research "
                        "mandate; never queues work or writes to BitPro."
                    ),
                    "research",
                ),
                ToolDefinition(
                    "research.job_report",
                    "Read persisted bounded BitPro research evidence and gate outcomes.",
                    "research",
                ),
                ToolDefinition(
                    "research.validation_gate",
                    (
                        "Evaluate BitPro backtest result rows against the "
                        "operator-locked mandate validation criteria."
                    ),
                    "research",
                ),
                ToolDefinition(
                    "paper.promotion_request",
                    (
                        "Request operator approval to promote fully passing "
                        "validation evidence onto the BitPro paper market."
                    ),
                    "paper",
                ),
                ToolDefinition(
                    "mcp.discover",
                    (
                        "List configured standard MCP servers and dynamically "
                        "discovered tools via tools/list."
                    ),
                    "mcp",
                ),
                ToolDefinition(
                    "mcp.invoke_tool",
                    (
                        "Invoke one tool on a configured standard MCP server "
                        "via tools/call."
                    ),
                    "mcp",
                ),
                ToolDefinition(
                    "workspace.write_file",
                    "Write one strategy/test file into the governed sandbox workspace.",
                    "workspace",
                ),
                ToolDefinition(
                    "workspace.read_file",
                    "Read one file from the sandbox workspace.",
                    "workspace",
                ),
                ToolDefinition(
                    "workspace.list_files",
                    "List files in the sandbox workspace.",
                    "workspace",
                ),
                ToolDefinition(
                    "workspace.run",
                    "Run a whitelisted command (ruff/pytest) inside the sandbox.",
                    "workspace",
                ),
                ToolDefinition(
                    "research.evidence_read",
                    "Read active, source-bound Evidence V2 records for the current Task.",
                    "research",
                ),
                ToolDefinition("backtest.run", "Run Backtrader strategy backtests.", "backtest"),
                ToolDefinition(
                    "bitpro.capabilities",
                    "Read BitPro MCP contract, tool groups, and data policy.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.health",
                    "Check BitPro API health before data access.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.market_klines",
                    "Read real BitPro K-line data through the MCP tool contract.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.strategy_search",
                    "Search BitPro strategy library.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.strategy_generate",
                    "Generate a BitPro strategy draft for research workflows.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.strategy_create",
                    "Create a BitPro strategy definition for research and validation.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.strategy_update",
                    "Update BitPro strategy metadata or DB-backed content for research workflows.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.backtest_start_job",
                    "Start a BitPro-owned backtest job.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.backtest_get_job",
                    "Read BitPro backtest job status.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.backtest_list_results",
                    "List BitPro backtest result records using actual total return metrics.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.backtest_get_result",
                    "Read one BitPro backtest result with bounded artifact samples.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_configure",
                    "Configure a BitPro paper/simulation instance.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_start",
                    "Start a BitPro paper/simulation instance.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_pause",
                    "Pause a BitPro paper/simulation instance.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_resume",
                    "Resume a BitPro paper/simulation instance.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_stop",
                    "Stop a BitPro paper/simulation instance.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_dashboard",
                    "Read BitPro paper/simulation dashboard state.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_snapshot",
                    "Read one immutable, strategy-scoped BitPro paper evidence snapshot.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_strategy_performance",
                    "Read validated BitPro paper strategy performance ranking.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_events",
                    "Read BitPro paper/simulation events and errors.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_equity_curve",
                    "Read BitPro paper/simulation equity curve samples.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.paper_monitor_snapshot",
                    "Capture a read-only BitPro paper monitor snapshot and drift.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.live_positions",
                    "Read BitPro live account positions for diagnostics only.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.live_order_history",
                    "Read BitPro live account order history for diagnostics only.",
                    "bitpro",
                ),
                ToolDefinition(
                    "bitpro.live_strategy_performance",
                    "Read BitPro live strategy performance ranking for diagnostics only.",
                    "bitpro",
                ),
                ToolDefinition("paper.session", "Control paper trading sessions.", "paper"),
                ToolDefinition(
                    "world_model.defensive_action",
                    "Execute an explicitly allowlisted defensive world-model action.",
                    "world_model",
                ),
                ToolDefinition(
                    "live.order_intent",
                    "Create a live/testnet order intent for human approval.",
                    "live",
                    requires_approval=True,
                ),
            ]
        )

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get(self, name: str) -> ToolDefinition:
        return self._tools[name]

    def get_for_runtime_name(self, name: str) -> ToolDefinition:
        return self.get(_RUNTIME_TO_REGISTRY_NAME.get(name, name))


# The planner-facing OpenAI function schemas. This is the single source of
# truth for the tool surface: registry policy, runtime names and provider
# schemas are all derived from the definitions in this module.
RUNTIME_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
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
            "name": "world_model_snapshot",
            "description": (
                "Read-only global operator WorldState snapshot across market, strategy, "
                "execution, tool health, deployment, missing data, source refs, and "
                "safe candidate actions, plus portfolio scheduling recommendations. "
                "Use for global/cross-asset world-model state and portfolio review."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "global_market_snapshot",
            "description": (
                "Read current global market regime classifications across equities, "
                "volatility, FX, commodities, and rates. Returns risk_regime, "
                "volatility_regime, dollar_pressure, rates_pressure, cross_asset_signal, "
                "and ticker data for S&P 500, Nasdaq, VIX, DXY, Gold, Oil, Treasuries."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
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
            "description": (
                "Persist an audited long-term memory item for future reference. "
                "Use kind for the category and importance (0..1) for how much "
                "future runs should weight this observation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to remember"},
                    "kind": {
                        "type": "string",
                        "description": "Category such as market_summary or strategy_note",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional short lowercase tags for later filtering.",
                    },
                    "importance": {
                        "type": "number",
                        "description": "Weight for future recall, between 0 and 1.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence in the observation, between 0 and 1.",
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
            "description": (
                "Search active long-term memory by free-text query, kind, or tag. "
                "Always search memory before answering from prior observations; "
                "an empty query returns the most recent items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text query matched against content, kind and tags.",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Optional exact kind filter such as risk_note.",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Optional tag filter.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of items to return (default 10).",
                    },
                },
                "required": [],
            },
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
            "name": "research_mandate_read",
            "description": (
                "Read an operator-approved research mandate before drafting a "
                "research StrategySpec."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mandate_id": {"type": "string", "description": "Research mandate id."}
                },
                "required": ["mandate_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_strategy_spec_draft",
            "description": (
                "Draft a schema-valid StrategySpec within an active research mandate. "
                "This tool cannot queue jobs, run backtests, or write to BitPro."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mandate_id": {"type": "string", "description": "Active research mandate id."},
                    "prompt": {
                        "type": "string",
                        "description": "Bounded research hypothesis or strategy question.",
                    },
                },
                "required": ["mandate_id", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_job_report",
            "description": (
                "Read a persisted Sprint 82 research job report, including BitPro "
                "references and deterministic gate outcomes. This is read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {"job_id": {"type": "string", "description": "Research job id."}},
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "research_validation_gate",
            "description": (
                "Run the deterministic validation gates over BitPro backtest result "
                "rows using the operator-locked criteria from one research mandate. "
                "Advisory self-check for strategy research: thresholds always come "
                "from the mandate and cannot be supplied or weakened by the model. "
                "Authoritative gating still happens server-side when evidence is "
                "recorded. This is read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mandate_id": {
                        "type": "string",
                        "description": "Research mandate id owning the locked criteria.",
                    },
                    "results": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "Backtest result rows shaped like bitpro_backtest_get_result "
                            "samples: each row carries window/label plus metrics with "
                            "total_return_pct, max_drawdown_pct, trade_count."
                        ),
                    },
                    "data_complete": {
                        "type": "boolean",
                        "description": "Whether real data coverage was adequate, default true.",
                    },
                    "costs_declared": {
                        "type": "boolean",
                        "description": "Whether cost assumptions were declared, default true.",
                    },
                },
                "required": ["mandate_id", "results"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "paper_promotion_request",
            "description": (
                "Request operator approval to promote one fully passing research "
                "evidence record onto the BitPro paper market. Only evidence in "
                "status evidence_recorded with all validation gates passed qualifies; "
                "the request creates a pending approval item and never configures or "
                "starts anything by itself. Never claim paper trading started before "
                "an operator approved."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "evidence_id": {
                        "type": "string",
                        "description": "Passing research experiment evidence id.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this candidate deserves paper incubation.",
                    },
                },
                "required": ["evidence_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_discover",
            "description": (
                "List configured standard MCP servers and their dynamically "
                "discovered tools (tools/list). Use this before mcp_invoke_tool "
                "to learn each tool's name, purpose and argument schema. "
                "Set force_refresh when a server may have deployed new tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {
                        "type": "string",
                        "description": "Optional server name; omit to list all servers.",
                    },
                    "force_refresh": {
                        "type": "boolean",
                        "description": "Bypass the discovery cache, default false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_invoke_tool",
            "description": (
                "Invoke one tool on a configured standard MCP server (tools/call). "
                "Arguments must match the tool's input schema from mcp_discover. "
                "External tools are treated as potentially mutating: include a "
                "unique idempotency_key."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {
                        "type": "string",
                        "description": "Configured MCP server name.",
                    },
                    "tool": {
                        "type": "string",
                        "description": "Tool name as returned by mcp_discover.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments matching the tool input schema.",
                    },
                },
                "required": ["server", "tool"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_write_file",
            "description": (
                "Write one file into the governed sandbox workspace. Paths must "
                "start with strategies/ or tests/ and end with .py, .json, .yaml "
                "or .yml; Python sources may not import network/process modules "
                "or use eval/exec. Rejected writes return the reason immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path."},
                    "content": {"type": "string", "description": "Full file content."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_read_file",
            "description": "Read one file back from the sandbox workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Workspace-relative path."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_list_files",
            "description": (
                "List workspace files with sizes and content hashes. Use before "
                "workspace_run to confirm what will execute."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_run",
            "description": (
                "Run one whitelisted command (ruff or pytest) inside the governed "
                "sandbox over the whole workspace. No network, resource-limited; "
                "identical content replays the same persisted run. Read the "
                "output_preview to iterate on failures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "ruff or pytest.",
                        "enum": ["ruff", "pytest", "limited_backtest"],
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Bounded arguments without path separators (sandbox "
                            "contract); bare pytest auto-discovers tests/."
                        ),
                    },
                },
                "required": ["command"],
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
            "name": "bitpro_paper_snapshot",
            "description": (
                "Read one immutable BitPro paper evidence snapshot by strategy "
                "or instance id. Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy_id": {"type": "integer"},
                    "instance_id": {"type": "string"},
                },
                "required": [],
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
            "name": "bitpro_paper_strategy_performance",
            "description": (
                "Read and rank running BitPro paper/simulation strategy performance. "
                "Read-only. Use this for best/highest-return paper strategy questions. "
                "The tool rejects dashboard evidence whose returned strategy id does not "
                "match the requested strategy and reports comparison coverage explicitly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum running strategies to validate, default 20.",
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
            "name": "bitpro_live_strategy_performance",
            "description": (
                "Read-only BitPro live strategy performance ranking for diagnostics. Use this "
                "for highest/best live strategy return, 实盘收益最高, 实盘策略收益, "
                "live strategy PnL, and return_pct ranking questions. Never writes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "exchange": {"type": "string", "description": "Exchange name, default okx."},
                    "limit": {
                        "type": "integer",
                        "description": "Maximum ranked strategy rows to request, default 20.",
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
)


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
    "paper_promotion_request",
    "mcp_invoke_tool",
    "live_order_intent",
}

# Write tools must carry an idempotency_key in their planner schema so the
# model is nudged to supply one; governance still denies missing keys.
for schema in RUNTIME_TOOL_SCHEMAS:
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
                "Unique key for this requested write action, for example run id + tool purpose."
            ),
        },
    )


def default_runtime_schemas() -> list[dict[str, Any]]:
    """Deep-copied planner-facing schemas; callers may safely mutate results."""

    return list(deepcopy(RUNTIME_TOOL_SCHEMAS))


def read_only_runtime_tool_names() -> frozenset[str]:
    """Runtime tool names whose trusted policy scope is read-only.

    Derived from registry policy instead of a hand-maintained list so parallel
    dispatch can never widen beyond what governance considers safe to run
    concurrently.
    """

    registry = ToolRegistry.default()
    names: set[str] = set()
    for schema in RUNTIME_TOOL_SCHEMAS:
        name = str(schema.get("function", {}).get("name", ""))
        if not name:
            continue
        try:
            definition = registry.get_for_runtime_name(name)
        except KeyError:
            continue
        if definition.policy.scope in ("read", "live_diagnostic_read"):
            names.add(name)
    return frozenset(names)



def _default_policy_for(
    *,
    name: str,
    category: str,
    requires_approval: bool,
) -> ToolPolicy:
    if name.startswith("market."):
        return ToolPolicy(
            scope="read",
            approval="none",
            idempotency="not_required",
            source_of_truth="okx_rest",
            timeout_class="standard",
            safe_sample_limit=10,
            failure_behavior="return_unavailable",
        )
    if name.startswith("bitpro."):
        bitpro_tool = name.removeprefix("bitpro.")
        if bitpro_tool in {
            "live_positions",
            "live_order_history",
            "live_strategy_performance",
        }:
            return ToolPolicy(
                scope="live_diagnostic_read",
                approval="none",
                idempotency="not_required",
                source_of_truth="bitpro_mcp",
                timeout_class="standard",
                safe_sample_limit=20,
                failure_behavior="return_unavailable",
            )
        if bitpro_tool in {
            "paper_configure",
            "paper_start",
            "paper_pause",
            "paper_resume",
            "paper_stop",
        }:
            # Paper lifecycle writes are deliberately not Agent-executable. Sprint 83
            # routes configure/start through an explicit administrator approval record;
            # observation remains available through the read-only paper tools.
            return ToolPolicy(
                scope="paper_write",
                approval="blocked",
                idempotency="required",
                source_of_truth="bitpro_mcp",
                timeout_class="long",
                safe_sample_limit=20,
                failure_behavior="return_structured_error",
            )
        if bitpro_tool in {
            "strategy_generate",
            "strategy_create",
            "strategy_update",
            "backtest_start_job",
        }:
            return ToolPolicy(
                scope="research_write",
                approval="none",
                idempotency="required",
                source_of_truth="bitpro_mcp",
                timeout_class="long",
                safe_sample_limit=20,
                failure_behavior="return_structured_error",
            )
        return ToolPolicy(
            scope="read",
            approval="none",
            idempotency="not_required",
            source_of_truth="bitpro_mcp",
            timeout_class="standard",
            safe_sample_limit=20,
            failure_behavior="return_unavailable",
        )
    if name == "live.order_intent":
        return ToolPolicy(
            scope="testnet_write",
            approval="required" if requires_approval else "none",
            idempotency="required",
            source_of_truth="hypertrade_db",
            timeout_class="quick",
            safe_sample_limit=1,
            failure_behavior="return_structured_error",
        )
    if category == "memory" and name.endswith(".write"):
        return ToolPolicy(
            scope="research_write",
            approval="none",
            idempotency="not_required",
            source_of_truth="hypertrade_db",
            timeout_class="standard",
            safe_sample_limit=1,
            failure_behavior="return_structured_error",
        )
    if category == "paper":
        return ToolPolicy(
            scope="paper_write",
            approval="none",
            idempotency="required",
            source_of_truth="hypertrade_db",
            timeout_class="standard",
            safe_sample_limit=10,
            failure_behavior="return_structured_error",
        )
    return ToolPolicy()

_RUNTIME_TO_REGISTRY_NAME = {
    "market_summary": "market.summary",
    "market_ticker": "market.ticker",
    "market_candles": "market.candles",
    "market_compare": "market.compare",
    "market_intelligence": "market.intelligence",
    "world_model_snapshot": "world_model.snapshot",
    "global_market_snapshot": "global_market.snapshot",
    "rag_search": "rag.search",
    "memory_write": "memory.write",
    "memory_search": "memory.search",
    "strategy_draft": "strategy.draft",
    "strategy_library_search": "strategy.library_search",
    "strategy_experiment_plan": "strategy.experiment_plan",
    "research_mandate_read": "research.mandate_read",
    "research_strategy_spec_draft": "research.strategy_spec_draft",
    "research_job_report": "research.job_report",
    "research_validation_gate": "research.validation_gate",
    "paper_promotion_request": "paper.promotion_request",
    "mcp_discover": "mcp.discover",
    "mcp_invoke_tool": "mcp.invoke_tool",
    "workspace_write_file": "workspace.write_file",
    "workspace_read_file": "workspace.read_file",
    "workspace_list_files": "workspace.list_files",
    "workspace_run": "workspace.run",
    "backtest_run": "backtest.run",
    "bitpro_capabilities": "bitpro.capabilities",
    "bitpro_health": "bitpro.health",
    "bitpro_market_klines": "bitpro.market_klines",
    "bitpro_strategy_search": "bitpro.strategy_search",
    "bitpro_strategy_generate": "bitpro.strategy_generate",
    "bitpro_strategy_create": "bitpro.strategy_create",
    "bitpro_strategy_update": "bitpro.strategy_update",
    "bitpro_backtest_start_job": "bitpro.backtest_start_job",
    "bitpro_backtest_get_job": "bitpro.backtest_get_job",
    "bitpro_backtest_list_results": "bitpro.backtest_list_results",
    "bitpro_backtest_get_result": "bitpro.backtest_get_result",
    "bitpro_paper_configure": "bitpro.paper_configure",
    "bitpro_paper_start": "bitpro.paper_start",
    "bitpro_paper_pause": "bitpro.paper_pause",
    "bitpro_paper_resume": "bitpro.paper_resume",
    "bitpro_paper_stop": "bitpro.paper_stop",
    "bitpro_paper_dashboard": "bitpro.paper_dashboard",
    "bitpro_paper_snapshot": "bitpro.paper_snapshot",
    "bitpro_paper_strategy_performance": "bitpro.paper_strategy_performance",
    "bitpro_paper_events": "bitpro.paper_events",
    "bitpro_paper_equity_curve": "bitpro.paper_equity_curve",
    "bitpro_paper_monitor_snapshot": "bitpro.paper_monitor_snapshot",
    "bitpro_live_positions": "bitpro.live_positions",
    "bitpro_live_order_history": "bitpro.live_order_history",
    "bitpro_live_strategy_performance": "bitpro.live_strategy_performance",
    "world_model_defensive_action": "world_model.defensive_action",
    "live_order_intent": "live.order_intent",
}


def _with_default_policy(tool: ToolDefinition) -> ToolDefinition:
    policy = _DEFAULT_TOOL_POLICIES.get(tool.name, tool.policy)
    return ToolDefinition(
        name=tool.name,
        description=tool.description,
        category=tool.category,
        requires_approval=tool.requires_approval or policy.approval == "required",
        policy=policy,
        connector_origin=tool.connector_origin,
    )


def _policy(
    *,
    scope: ToolScope = "read",
    approval: ApprovalPolicy = "none",
    idempotency: IdempotencyPolicy = "not_required",
    source: str = "hypertrade_db",
    timeout: TimeoutClass = "standard",
    sample: int = 0,
    failure: str = "return_structured_error",
) -> ToolPolicy:
    return ToolPolicy(
        scope=scope,
        approval=approval,
        idempotency=idempotency,
        source_of_truth=source,
        timeout_class=timeout,
        safe_sample_limit=sample,
        failure_behavior=failure,
    )


_DEFAULT_TOOL_POLICIES: dict[str, ToolPolicy] = {
    "market.summary": _policy(
        source="okx_rest",
        timeout="standard",
        sample=10,
        failure="return_unavailable",
    ),
    "market.ticker": _policy(
        source="okx_rest",
        timeout="quick",
        sample=1,
        failure="return_unavailable",
    ),
    "market.candles": _policy(
        source="okx_rest",
        timeout="quick",
        sample=300,
        failure="return_unavailable",
    ),
    "market.compare": _policy(
        source="okx_rest",
        timeout="standard",
        sample=6,
        failure="return_unavailable",
    ),
    "world_model.snapshot": _policy(
        source="hypertrade_db+connector_registry",
        timeout="standard",
        sample=1,
        failure="return_structured_error",
    ),
    "global_market.snapshot": _policy(
        source="yfinance+alpha_vantage",
        timeout="long",
        sample=20,
        failure="return_unavailable",
    ),
    "market.tickers": _policy(source="hypertrade_db", timeout="quick", sample=50),
    "rag.search": _policy(source="rag_index", timeout="quick", sample=5),
    "memory.write": _policy(
        scope="research_write",
        source="hypertrade_db",
        timeout="quick",
        sample=1,
    ),
    "memory.search": _policy(source="hypertrade_db", timeout="quick", sample=10),
    "strategy.draft": _policy(scope="research_write", source="hypertrade_db", sample=1),
    "strategy.library_search": _policy(source="hypertrade_db", timeout="quick", sample=10),
    "strategy.experiment_plan": _policy(
        scope="research_write",
        source="hypertrade_db",
        timeout="standard",
        sample=3,
    ),
    "research.mandate_read": _policy(source="hypertrade_db", timeout="quick", sample=1),
    "research.strategy_spec_draft": _policy(source="hypertrade_db", timeout="quick", sample=1),
    "research.job_report": _policy(source="hypertrade_db", timeout="quick", sample=3),
    "research.validation_gate": _policy(
        source="hypertrade_db+model_input",
        timeout="quick",
        sample=20,
        failure="return_structured_error",
    ),
    "paper.promotion_request": _policy(
        scope="paper_write",
        idempotency="required",
        source="hypertrade_db",
        timeout="standard",
        sample=1,
    ),
    "mcp.discover": _policy(
        source="mcp_servers",
        timeout="standard",
        sample=50,
        failure="return_unavailable",
    ),
    "mcp.invoke_tool": _policy(
        scope="research_write",
        idempotency="required",
        source="mcp_servers",
        timeout="long",
        sample=1,
    ),
    "workspace.write_file": _policy(
        scope="research_write",
        source="sandbox_workspace",
        timeout="quick",
        sample=1,
    ),
    "workspace.read_file": _policy(source="sandbox_workspace", timeout="quick", sample=1),
    "workspace.list_files": _policy(source="sandbox_workspace", timeout="quick", sample=50),
    "workspace.run": _policy(
        scope="research_write",
        source="sandbox_workspace",
        timeout="long",
        sample=1,
    ),
    "backtest.run": _policy(
        scope="research_write",
        source="hypertrade_db",
        timeout="long",
        sample=1,
    ),
    "bitpro.capabilities": _policy(source="bitpro_mcp", timeout="quick", sample=1),
    "bitpro.health": _policy(source="bitpro_mcp", timeout="quick", sample=1),
    "bitpro.market_klines": _policy(source="bitpro_mcp", timeout="standard", sample=200),
    "bitpro.strategy_search": _policy(source="bitpro_mcp", timeout="standard", sample=18),
    "bitpro.strategy_generate": _policy(
        scope="research_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.strategy_create": _policy(
        scope="research_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.strategy_update": _policy(
        scope="research_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.backtest_start_job": _policy(
        scope="research_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.backtest_get_job": _policy(source="bitpro_mcp", timeout="standard", sample=1),
    "bitpro.backtest_list_results": _policy(source="bitpro_mcp", timeout="standard", sample=100),
    "bitpro.backtest_get_result": _policy(source="bitpro_mcp", timeout="standard", sample=20),
    "bitpro.paper_configure": _policy(
        scope="paper_write",
        approval="blocked",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_start": _policy(
        scope="paper_write",
        approval="blocked",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_pause": _policy(
        scope="paper_write",
        approval="blocked",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_resume": _policy(
        scope="paper_write",
        approval="blocked",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_stop": _policy(
        scope="paper_write",
        approval="blocked",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_dashboard": _policy(source="bitpro_mcp", timeout="standard", sample=20),
    "bitpro.paper_strategy_performance": _policy(
        source="bitpro_mcp", timeout="long", sample=50, failure="return_unavailable"
    ),
    "bitpro.paper_events": _policy(source="bitpro_mcp", timeout="standard", sample=50),
    "bitpro.paper_equity_curve": _policy(source="bitpro_mcp", timeout="standard", sample=50),
    "bitpro.paper_monitor_snapshot": _policy(
        scope="research_write",
        source="bitpro_mcp+hypertrade_db",
        timeout="long",
        sample=1,
        failure="return_unavailable",
    ),
    "bitpro.live_positions": _policy(
        scope="live_diagnostic_read",
        source="bitpro_mcp",
        timeout="standard",
        sample=20,
    ),
    "paper.session": _policy(
        scope="paper_write",
        idempotency="required",
        source="hypertrade_db",
        timeout="quick",
        sample=1,
    ),
    "world_model.defensive_action": _policy(
        scope="research_write",
        idempotency="required",
        source="hypertrade_db",
        timeout="quick",
        sample=1,
    ),
    "live.order_intent": _policy(
        scope="testnet_write",
        approval="required",
        idempotency="required",
        source="hypertrade_db",
        timeout="quick",
        sample=1,
    ),
}
