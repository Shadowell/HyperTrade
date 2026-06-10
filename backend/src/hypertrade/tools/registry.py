"""Static catalog of tools exposed to the Agent and harness surfaces.

The registry is intentionally metadata-only. It tells the LLM, API, CLI, and
frontend what tools exist and which ones need approval, while the actual trusted
execution lives in `hypertrade.agent.kernel.AgentKernel`.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    requires_approval: bool = False


class ToolRegistry:
    def __init__(self, tools: list[ToolDefinition]) -> None:
        self._tools = {tool.name: tool for tool in tools}

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
                    "market.tickers",
                    "Read latest OKX SWAP ticker snapshots.",
                    "market",
                ),
                ToolDefinition("rag.search", "Search project and trading knowledge.", "rag"),
                ToolDefinition("memory.write", "Write audited long-term memory.", "memory"),
                ToolDefinition("memory.search", "Read active long-term memory.", "memory"),
                ToolDefinition("strategy.draft", "Draft runtime strategy artifacts.", "strategy"),
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
                    "bitpro.live_positions",
                    "Read BitPro live account positions for diagnostics only.",
                    "bitpro",
                ),
                ToolDefinition("paper.session", "Control paper trading sessions.", "paper"),
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
