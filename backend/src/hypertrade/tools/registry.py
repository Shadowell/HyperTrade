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
