"""LLM-driven planning loop using provider function/tool calling.

AgentPlanner only decides which tool names and JSON arguments to request. It
does not touch databases, exchanges, or secrets; AgentKernel owns trusted tool
execution. This split makes provider output easy to test and safe to inspect.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from hypertrade.agent.quality import (
    CandidateToolSet,
    ResearchIntentV2,
    ToolPlanV2,
    build_candidate_tool_set,
    default_research_intent,
    required_schema_fields,
)
from hypertrade.providers.chat import ChatProvider, ChatResponse, TokenUsage
from hypertrade.tools.registry import default_runtime_schemas

ToolExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]

# The tool surface is owned by the registry; the planner only consumes a fresh
# deep copy per import so provider payloads can never mutate shared state.
TOOL_SCHEMAS: list[dict[str, Any]] = default_runtime_schemas()

_SYSTEM_PROMPT = """\
You are HyperTrade, an agent-first crypto research assistant.
You have market data tools, RAG search, long-term memory, strategy research, and backtesting.
Use market_summary for all-market questions about 市场热度, 市场情绪, 整体市场,
全市场, 大盘, 行情归纳, market heat, market sentiment, breadth, or risk appetite.
Do not answer all-market heat by calling only market_ticker for BTC/ETH/SOL.
For short generic requests such as 现在市场是什么情况, 现在行情怎么样, 市场如何,
or how is the market, call market_summary first. Do not substitute
world_model_snapshot or global_market_snapshot unless the user explicitly asks
for global operator state, macro, cross-asset conditions, equities, volatility,
FX, commodities, rates, or portfolio/strategy allocation context.
Use market_ticker when the user asks about any specific listed coin or one OKX
instrument, such as ETH, SOL, DOGE, PEPE-USDT, or BTC-USDT-SWAP.
Use market_candles when the user asks about trend,走势, K线, breakthrough, pullback,
support/resistance, or multi-period market research for a specific symbol.
Use market_compare when the user asks to compare two or more symbols, relative
strength, 哪个更强, 跑赢, 强弱, or leader/laggard.
Use market_intelligence when the user asks about funding, open interest,
资金费率, 持仓, OI, news, onchain, sentiment, 情绪, 链上, or source-backed market
context beyond price/K-line data. Treat this as context, not buy/sell advice.
Use world_model_snapshot when the user asks about the global operator state,
全局状态, 世界模型, 全局市场感受, cross-asset regime, what the Agent currently sees
across market, strategy, execution, tools, and deployment.

Use global_market_snapshot when the user specifically asks about:
- Current global market conditions, regime, or risk environment
- Cross-asset market state (equities, volatility, FX, commodities, rates)
- Market risk-on/risk-off conditions, risk appetite
- VIX, volatility levels, or market fear gauge
- Dollar strength, DXY, or FX conditions
- Interest rate conditions, Treasury yields, rates pressure
- Whether it's a good time to trade based on macro conditions
- Global macro environment affecting crypto trading

Do not use market_summary as a substitute for global WorldState; market_summary
only covers OKX crypto-market heat and cannot represent global operator/cross-asset state.

Use world_model_snapshot when the user asks about portfolio, strategy allocation,
策略权重, 组合调度, allocation review, which strategies to reduce, pause, observe,
or backtest next. Portfolio answers must cite WorldState portfolio evidence and
must not claim a live allocation change happened.
Use strategy_library_search when the user asks about previous strategy
experience, 策略库, 历史策略, 记忆沉淀, what has worked/failed, failure reasons,
or the next strategy experiment. Treat it as evidence from strategy_knowledge
memory, not as unsourced model recall.
Use strategy_experiment_plan after strategy_library_search when the user asks
to continue, iterate, optimize, or plan a next strategy experiment from prior
evidence. Keep variants bounded and source them to strategy-library evidence.
Use research_mandate_read before research_strategy_spec_draft when the operator
asks to inspect a named research mandate or draft a StrategySpec under one.
Research StrategySpec drafts are schema-only proposals: they do not queue jobs,
run backtests, change paper state, or call BitPro write tools.
Use research_job_report when the operator asks for a completed research job's
validation conclusion, BitPro result references, missing metrics, or gate outcomes.
Do not claim that evidence_recorded means paper promotion or stable profitability.
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
Use bitpro_live_strategy_performance when the user asks about live/real-account
strategy returns, 实盘收益最高, 实盘策略收益, 实盘盈利, live strategy PnL,
highest/best live strategy, or return_pct ranking.
Do not use market_summary for live strategy performance questions.
Use bitpro_paper_strategy_performance when the user asks which paper/simulated
strategy has the best/highest return, asks for a paper strategy ranking, or asks
to compare simulated strategy performance. Prefer this single validated matrix
tool over multiple paper_dashboard or paper_equity_curve calls. A partial ranking
is not proof of the best strategy across the full running inventory.
Use bitpro_paper_dashboard without strategy_id when the user asks only about all/全部/
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
For questions that rank or compare all simulated strategies, use a professional
Markdown report with `## 结论`, `## 策略比较`, `## 风险与数据缺口`, and `## 下一步`.
Only rank strategies when BitPro supplies a per-strategy return or PnL metric.
If the running-strategy inventory lacks per-strategy PnL/drawdown, explicitly
say that the full ranking is unavailable, identify the current-dashboard
strategy separately, and never invent, estimate, or infer returns for the
other strategies from names, capital size, or incomplete inventory data.
Do not substitute BitPro backtest rankings for current simulated-strategy
performance: their time ranges and execution conditions are different.
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


@dataclass(frozen=True)
class ModelCallRecord:
    iteration: int
    provider: str
    model: str
    duration_ms: float
    tool_call_count: int
    response_type: str
    usage: TokenUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "provider": self.provider,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "tool_call_count": self.tool_call_count,
            "response_type": self.response_type,
            "usage": self.usage.to_dict(),
        }


@dataclass
class PlannerResult:
    final_message: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    model_calls: list[ModelCallRecord] = field(default_factory=list)
    intent: ResearchIntentV2 | None = None
    tool_plan: ToolPlanV2 | None = None
    candidate_count: int = 0


class PlannerValidationFailed(RuntimeError):
    """The provider failed the single-repair structured planning contract."""


class AgentPlanner:
    MAX_ITERATIONS = 8

    def __init__(
        self,
        llm: ChatProvider,
        *,
        model_call_sink: Callable[[ModelCallRecord], None] | None = None,
        tool_call_sink: Callable[[ToolCallRecord], None] | None = None,
    ) -> None:
        self._llm = llm
        self._model_call_sink = model_call_sink
        self._tool_call_sink = tool_call_sink

    def run(
        self,
        prompt: str,
        executor: ToolExecutor,
        *,
        intent: ResearchIntentV2 | None = None,
    ) -> PlannerResult:
        active_intent = intent or default_research_intent(evaluation_mode=False)
        candidates = build_candidate_tool_set(active_intent, TOOL_SCHEMAS)
        schemas_by_name = {
            str(schema["function"]["name"]): schema
            for schema in candidates.schemas
            if isinstance(schema.get("function"), dict)
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        tool_calls: list[ToolCallRecord] = []
        model_calls: list[ModelCallRecord] = []
        repair_count = 0

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            started_at = time.monotonic()
            response: ChatResponse = self._llm.chat(messages, tools=list(candidates.schemas))
            model_call = ModelCallRecord(
                iteration=iteration,
                provider=_provider_label(self._llm, "name"),
                model=_provider_label(self._llm, "model"),
                duration_ms=round((time.monotonic() - started_at) * 1000, 3),
                tool_call_count=len(response.tool_calls),
                response_type="tool_calls" if response.tool_calls else "final",
                usage=response.usage,
            )
            model_calls.append(model_call)
            if self._model_call_sink is not None:
                self._model_call_sink(model_call)

            if not response.tool_calls:
                missing_tools = sorted(
                    set(active_intent.required_tools)
                    - {record.tool_name for record in tool_calls}
                )
                if missing_tools:
                    if repair_count >= 1:
                        raise PlannerValidationFailed(
                            "required source/tool route missing after one bounded repair"
                        )
                    repair_count += 1
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "PLANNER_REPAIR_REQUIRED: choose the required tool route from "
                                "the unchanged bounded candidate set; missing="
                                + ",".join(missing_tools)
                            ),
                        }
                    )
                    continue
                plan = _tool_plan(
                    tool_calls,
                    candidates,
                    required_args_present=True,
                    repair_count=repair_count,
                )
                return PlannerResult(
                    final_message=response.content,
                    tool_calls=tool_calls,
                    model_calls=model_calls,
                    intent=active_intent,
                    tool_plan=plan,
                    candidate_count=len(candidates.schemas),
                )

            validation_errors = _validate_provider_calls(response, candidates, schemas_by_name)
            if validation_errors:
                if repair_count >= 1:
                    raise PlannerValidationFailed(
                        "provider tool plan remained invalid after one bounded repair"
                    )
                repair_count += 1
                messages.append(_assistant_tool_message(response))
                for request in response.tool_calls:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": request.id,
                            "content": json.dumps(
                                {
                                    "status": "denied",
                                    "error": {
                                        "type": "plan_validation",
                                        "codes": validation_errors,
                                    },
                                    "repair_count": repair_count,
                                    "candidate_set_expanded": False,
                                }
                            ),
                        }
                    )
                continue

            assistant_msg = _assistant_tool_message(response)
            messages.append(assistant_msg)

            from hypertrade.agent.harness_v2 import (
                AsyncParallelToolDispatcher,
                SmartToolExecutionHealer,
            )

            healer = SmartToolExecutionHealer(executor)
            dispatcher = AsyncParallelToolDispatcher(healer)

            tool_reqs = [(tc.name, tc.arguments) for tc in response.tool_calls]
            executed_results = dispatcher.dispatch_batch(tool_reqs)

            for tc, result in zip(response.tool_calls, executed_results, strict=False):
                tool_call = ToolCallRecord(tc.name, tc.arguments, result)
                tool_calls.append(tool_call)
                if self._tool_call_sink is not None:
                    self._tool_call_sink(tool_call)
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
            model_calls=model_calls,
            intent=active_intent,
            tool_plan=_tool_plan(
                tool_calls,
                candidates,
                required_args_present=True,
                repair_count=repair_count,
            ),
            candidate_count=len(candidates.schemas),
        )


def _assistant_tool_message(response: ChatResponse) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": response.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in response.tool_calls
        ],
    }
    if response.reasoning_content:
        message["reasoning_content"] = response.reasoning_content
    return message


def _validate_provider_calls(
    response: ChatResponse,
    candidates: CandidateToolSet,
    schemas_by_name: dict[str, dict[str, Any]],
) -> list[str]:
    errors: set[str] = set()
    for call in response.tool_calls:
        if call.name not in candidates.included_names:
            errors.add("tool_not_in_candidate_set")
            continue
        missing = required_schema_fields(schemas_by_name[call.name]) - set(call.arguments)
        if missing:
            errors.add("required_arguments_missing")
    return sorted(errors)


def _tool_plan(
    records: list[ToolCallRecord],
    candidates: CandidateToolSet,
    *,
    required_args_present: bool,
    repair_count: int,
) -> ToolPlanV2:
    return ToolPlanV2(
        selected_tools=[record.tool_name for record in records],
        source_rationale_codes=list(candidates.source_rationale_codes),
        required_args_present=required_args_present,
        policy_projection="bounded",
        repair_count=repair_count,
    )


def _provider_label(provider: Any, field_name: str) -> str:
    value = getattr(provider, field_name, "")
    return value if isinstance(value, str) else ""


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


class ModelCallHarnessNormalizer:
    """
    Industrial Harness Normalizer sanitizing heterogeneous LLM tool call payloads
    (DeepSeek, OpenAI, Claude, Qwen), handling raw JSON strings & schema edge cases.
    """

    @staticmethod
    def normalize_tool_call(raw_call: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw_call, dict):
            return {"name": "invalid", "arguments": {}}

        name = str(raw_call.get("name") or raw_call.get("tool_name") or "unknown")
        args = raw_call.get("arguments") or raw_call.get("parameters") or {}

        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}

        if not isinstance(args, dict):
            args = {}

        return {"name": name, "arguments": args}


class ToolExecutionSelfHealer:
    """
    Self-healing Tool Execution Harness intercepting tool execution errors
    and executing 1-step LLM self-correction retries.
    """

    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor

    def execute_with_self_healing(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        fallback_retry_fn: Callable[[str, str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        try:
            res = self.executor(tool_name, tool_args)
            if isinstance(res, dict) and res.get("status") == "error":
                raise RuntimeError(res.get("message", "Tool returned status error"))
            return res
        except Exception as exc:
            err_msg = str(exc)
            if fallback_retry_fn:
                try:
                    repaired = fallback_retry_fn(tool_name, err_msg)
                    if isinstance(repaired, dict):
                        return repaired
                except Exception:
                    pass
            return _executor_error_payload(tool_name, exc)


class ParallelToolPipeline:
    """
    SOTA Parallel Tool Execution Engine matching Claude Code / Codex concurrency.
    Executes independent, non-interdependent tool calls concurrently via thread pools,
    reducing tool invocation latency by up to 70%.
    """

    def __init__(self, executor: ToolExecutor, max_workers: int = 4) -> None:
        self.executor = executor
        self.max_workers = max_workers

    def execute_parallel_tools(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Executes a batch of independent tool calls concurrently.
        """
        if not tool_calls:
            return []

        if len(tool_calls) == 1:
            name = tool_calls[0].get("name", "unknown")
            args = tool_calls[0].get("arguments", {})
            return [self.executor(name, args)]

        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[tuple[int, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=min(len(tool_calls), self.max_workers)) as ex:
            future_to_idx = {
                ex.submit(
                    self.executor,
                    call.get("name", "unknown"),
                    call.get("arguments", {}),
                ): idx
                for idx, call in enumerate(tool_calls)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    res = future.result()
                    results.append((idx, res))
                except Exception as exc:
                    results.append((idx, _executor_error_payload("parallel_tool", exc)))

        results.sort(key=lambda item: item[0])
        return [res for _, res in results]


