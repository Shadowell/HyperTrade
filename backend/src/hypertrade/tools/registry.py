"""Static catalog of tools exposed to the Agent and harness surfaces.

The registry is intentionally metadata-only. It tells the LLM, API, CLI, and
frontend what tools exist and which ones need approval, while the actual trusted
execution lives in `hypertrade.agent.kernel.AgentKernel`.
"""

from dataclasses import dataclass, field
from typing import Literal

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
            return ToolPolicy(
                scope="paper_write",
                approval="none",
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
    "rag_search": "rag.search",
    "memory_write": "memory.write",
    "memory_search": "memory.search",
    "strategy_draft": "strategy.draft",
    "strategy_library_search": "strategy.library_search",
    "strategy_experiment_plan": "strategy.experiment_plan",
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
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_start": _policy(
        scope="paper_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_pause": _policy(
        scope="paper_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_resume": _policy(
        scope="paper_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_stop": _policy(
        scope="paper_write",
        idempotency="required",
        source="bitpro_mcp",
        timeout="long",
        sample=1,
    ),
    "bitpro.paper_dashboard": _policy(source="bitpro_mcp", timeout="standard", sample=20),
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
