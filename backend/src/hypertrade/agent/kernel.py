"""Observable Agent runtime used by API, CLI, and streaming endpoints.

This module is the runtime boundary for the HyperTrade Agent flow.
`AgentKernel` keeps one public interface (`run_chat`) while the internals look
like a small graph: classify intent, plan tools, check approval, execute tools,
reflect, and write the final report. Every graph node is persisted as trace so
the frontend harness and CLI can show what the Agent is doing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from hypertrade.agent.planner import (
    AgentPlanner,
    ModelCallRecord,
    PlannerResult,
    ToolCallRecord,
    ToolExecutor,
)
from hypertrade.agent.quality import research_intent_for_prompt
from hypertrade.backtest.service import BacktestService
from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter
from hypertrade.bitpro.paper_monitor import BitProPaperMonitorService
from hypertrade.config import Settings, get_settings
from hypertrade.db import AgentRun, Database, TraceEvent, utc_now
from hypertrade.evals.langfuse import LangfuseTraceExporter
from hypertrade.live.service import LiveOrderIntentService
from hypertrade.market.analysis import summarize_candles
from hypertrade.market.client import OkxRestClient
from hypertrade.market.intelligence import MarketIntelligenceService
from hypertrade.market.okx import OkxCandle
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.rag.service import RagService
from hypertrade.reporting.blocks import build_report_blocks_from_tool_calls
from hypertrade.research.service import ResearchProgramService
from hypertrade.risk.governance import GovernanceDecision, RiskGovernancePolicy
from hypertrade.strategy.iteration import StrategyIterationService
from hypertrade.strategy.library import StrategyLibraryService
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolPolicy, ToolRegistry
from hypertrade.world_model.service import WorldModelService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompletedAgentRun:
    id: str
    status: str
    report_markdown: str
    report_json: dict[str, Any]
    run_state_json: dict[str, Any]
    trace_events: list[TraceEvent]


class AgentKernel:
    """Coordinate provider planning, tool execution, trace, RAG, and memory."""

    def __init__(
        self,
        db: Database,
        *,
        knowledge_dir: str = "docs/knowledge",
        settings: Settings | None = None,
        provider_name: str | None = None,
        provider_model: str | None = None,
        bitpro_adapter: Any | None = None,
        evaluation_mode: bool = False,
    ) -> None:
        self.db = db
        self._settings = settings
        self.provider_name = provider_name
        self.provider_model = provider_model
        self.bitpro_adapter = bitpro_adapter
        # Evaluation mode is a second trusted boundary for adversarial suites.
        # A planner may still reveal attempted write-tool selection, but dispatch
        # never reaches database, BitPro, paper, Testnet, or live write handlers.
        self.evaluation_mode = evaluation_mode
        self.market = MarketRepository(db)
        self.memory = MemoryService(db)
        self.rag = RagService(db, knowledge_dir=knowledge_dir)
        self.tools = ToolRegistry.default()
        self.governance = RiskGovernancePolicy(self.tools)
        # Shared worker pool enforcing per-tool wall-clock deadlines. A hung
        # provider call must return control to the planner as a timeout payload
        # instead of stalling the whole run (or, at the API layer, the event
        # loop). The underlying thread may linger until its IO unblocks; it is
        # never allowed to block the caller beyond policy timeout.
        self._tool_pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="hypertrade-tool"
        )
        # Standard MCP layer: disabled unless MCP_SERVERS_JSON is configured.
        self._mcp_registry = self._build_mcp_registry()

    def run_chat(self, prompt: str) -> CompletedAgentRun:
        return self.run_chat_with_events(prompt)

    def run_chat_with_events(
        self,
        prompt: str,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> CompletedAgentRun:
        settings = self._settings if self._settings is not None else get_settings()
        started_at = time.monotonic()
        run_id = self._create_run(prompt, execution_mode=self._execution_mode())
        intent = research_intent_for_prompt(prompt, evaluation_mode=self.evaluation_mode)
        _emit(event_sink, {"event": "run_started", "run_id": run_id, "status": "running"})
        try:
            # The first two graph nodes are intentionally lightweight. They make
            # a run observable before any LLM call or tool call can fail.
            self._graph_node(
                run_id,
                "intent_classify",
                {"prompt": prompt},
                {
                    "schema_version": intent.schema_version,
                    "intent_family": intent.intent_family,
                    "cohort": intent.cohort,
                    "execution_mode": intent.execution_mode,
                    "read_write_boundary": intent.read_write_boundary,
                    "intent_source": (
                        "authored_eval_contract"
                        if self.evaluation_mode and intent.intent_family != "general"
                        else "runtime_default"
                    ),
                },
                event_sink=event_sink,
            )
            provider = self._get_chat_provider(settings)
            # Provider routing is isolated here: the planner can be DeepSeek,
            # OpenRouter, Qwen, etc., while all downstream tool execution stays
            # provider-agnostic.
            self._graph_node(
                run_id,
                "plan_tools",
                {
                    "provider": self.provider_name or settings.active_chat_provider,
                    "model": self.provider_model or "",
                },
                {
                    "planner": provider.name if provider else "provider_unavailable",
                    "model": provider.model if provider else "",
                    "candidate_policy": "registry_connector_role_mandate_governance_intersection",
                    "cohort": intent.cohort,
                },
                event_sink=event_sink,
            )
            if provider is not None:
                self._run_with_planner(
                    run_id,
                    prompt,
                    settings,
                    provider=provider,
                    intent=intent,
                    event_sink=event_sink,
                )
            else:
                self._complete_provider_unavailable(run_id, prompt, event_sink=event_sink)
        except Exception as exc:
            self._fail_run(run_id, str(exc))
            self._finalize_run_observability(
                run_id,
                duration_ms=round((time.monotonic() - started_at) * 1000, 3),
            )
            self._export_run_observability(run_id, settings)
            _emit(
                event_sink,
                {"event": "run_failed", "run_id": run_id, "status": "failed", "error": str(exc)},
            )
            raise
        self._finalize_run_observability(
            run_id,
            duration_ms=round((time.monotonic() - started_at) * 1000, 3),
        )
        self._export_run_observability(run_id, settings)
        run = self.get_run(run_id)
        _emit(
            event_sink,
            {"event": "run_completed", "run_id": run.id, "status": run.status},
        )
        return run

    # ------------------------------------------------------------------
    # LLM-planned path
    # ------------------------------------------------------------------

    def _run_with_planner(
        self,
        run_id: str,
        prompt: str,
        settings: Any,
        *,
        provider: Any | None = None,
        intent: Any | None = None,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        llm = provider if provider is not None else self._get_chat_provider(settings)
        if llm is None:
            self._complete_provider_unavailable(run_id, prompt, event_sink=event_sink)
            return
        planner = AgentPlanner(
            llm,
            model_call_sink=lambda record: self._record_model_call(
                run_id,
                record,
                event_sink=event_sink,
            ),
            tool_call_sink=lambda record: self._record_tool_call(run_id, record),
        )
        executor = self._build_executor(run_id, event_sink=event_sink)
        # Final-answer tokens stream out as answer_delta events the moment the
        # provider produces them; SSE/queue consumers forward them verbatim.
        delta_sink: Callable[[str], None] | None = None
        if event_sink is not None:
            def delta_sink(text: str) -> None:
                _emit(
                    event_sink,
                    {"event": "answer_delta", "run_id": run_id, "text": text},
                )

        result: PlannerResult = planner.run(
            prompt,
            executor,
            intent=intent,
            system_suffix=self._memory_prompt_suffix(),
            delta_sink=delta_sink,
        )

        observability = _planner_observability(result, provider=llm.name, model=llm.model)
        self._set_run_observability(run_id, observability)

        self._graph_node(
            run_id,
            "reflect",
            {"tool_count": len(result.tool_calls)},
            {"summary": _reflection_summary(result)},
            event_sink=event_sink,
        )

        report_json: dict[str, Any] = {
            "market_scope": "OKX SWAP",
            "trigger": "user_request",
            "planner": llm.name,
            "model": llm.model,
            "execution_mode": self._execution_mode(),
            "tool_calls": [{"tool": r.tool_name, "input": r.input_json} for r in result.tool_calls],
            "citations": _citations_from_tool_calls(result.tool_calls),
            "graph": self._get_run_state(run_id).get("graph", []),
            "observability": observability,
            "planning_quality": {
                "intent_schema": result.intent.schema_version if result.intent else "unknown",
                "plan_schema": result.tool_plan.schema_version if result.tool_plan else "unknown",
                "cohort": result.intent.cohort if result.intent else "unknown",
                "candidate_count": result.candidate_count,
                "repair_count": result.tool_plan.repair_count if result.tool_plan else 0,
                "policy_projection": (
                    result.tool_plan.policy_projection if result.tool_plan else "unknown"
                ),
                "private_reasoning_stored": False,
            },
            "disclaimer": "Research output only. Not investment advice.",
        }
        for record in result.tool_calls:
            if record.tool_name != "market_summary" or not isinstance(record.output_json, dict):
                continue
            for key in ("top_movers", "heat_summary", "data_source", "as_of_utc"):
                if key in record.output_json:
                    report_json[key] = record.output_json[key]
            break
        report_blocks = build_report_blocks_from_tool_calls(
            result.final_message,
            result.tool_calls,
        )
        if report_blocks:
            report_json["report_blocks"] = [block.to_dict() for block in report_blocks]
        report_markdown = self._render_planner_report(result.final_message, result.tool_calls)
        self._graph_node(
            run_id,
            "final_report",
            {"format": "markdown"},
            {"characters": len(report_markdown)},
            event_sink=event_sink,
        )
        # Capture the graph only after final_report is committed; evaluation and
        # operators must observe the same terminal sequence as the run state.
        report_json["graph"] = self._get_run_state(run_id).get("graph", [])
        self._complete_run(run_id, report_markdown, report_json)

    def _complete_provider_unavailable(
        self,
        run_id: str,
        prompt: str,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._graph_node(
            run_id,
            "reflect",
            {"tool_count": 0},
            {"summary": ("chat provider unavailable; no natural-language tool route was guessed")},
            event_sink=event_sink,
        )
        report_markdown = (
            "# Agent 无法完成意图识别\n\n"
            "未配置可用 Chat Provider，因此无法由 LLM/Planner 判断这个自然语言"
            "请求应该调用哪些工具。\n\n"
            "本次运行没有执行 market、BitPro、RAG 或 Memory 工具，也没有根据关键词"
            "猜测业务路线。\n\n"
            f"- 用户请求: {prompt[:240]}"
        )
        self._graph_node(
            run_id,
            "final_report",
            {"format": "markdown"},
            {"characters": len(report_markdown)},
            event_sink=event_sink,
        )
        report_json = {
            "status": "provider_unavailable",
            "market_scope": "not_selected",
            "trigger": "user_request",
            "planner": "provider_unavailable",
            "model": "",
            "execution_mode": self._execution_mode(),
            "tool_calls": [],
            "citations": [],
            "graph": self._get_run_state(run_id).get("graph", []),
            "disclaimer": "Research output only. Not investment advice.",
        }
        self._complete_run(run_id, report_markdown, report_json)

    def _get_chat_provider(self, settings: Settings) -> Any | None:
        runtime = ProviderRuntime(settings)
        if self.provider_model:
            return runtime.get_chat_provider(
                selected=self.provider_name,
                selected_model=self.provider_model,
            )
        return runtime.get_chat_provider(selected=self.provider_name)

    def _record_model_call(
        self,
        run_id: str,
        record: ModelCallRecord,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        # Store operational metadata only. Prompts, credentials, and private
        # reasoning text never enter the Flight Recorder event stream.
        self._graph_node(
            run_id,
            "model_call",
            {
                "iteration": record.iteration,
                "provider": record.provider,
                "model": record.model,
            },
            {
                "duration_ms": record.duration_ms,
                "tool_call_count": record.tool_call_count,
                "response_type": record.response_type,
                "usage": record.usage.to_dict(),
                "private_reasoning_stored": False,
            },
            event_sink=event_sink,
        )

    def _record_tool_call(self, run_id: str, record: ToolCallRecord) -> None:
        # Persist at execution time so iterative model/tool turns keep their
        # true order instead of being appended after planning completes.
        self._trace(run_id, record.tool_name, record.input_json, record.output_json)

    def _build_executor(
        self,
        run_id: str,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolExecutor:
        # Per-run code workspace: files never leak across agent runs, and the
        # sandbox artifacts ledger keeps the content-addressed audit trail.
        from hypertrade.agent.workspace import AgentWorkspace

        self._workspace = AgentWorkspace(run_id=run_id)

        def executor(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            decision = self.governance.evaluate(tool_name, args)
            if self.evaluation_mode and decision.policy.scope not in {
                "read",
                "live_diagnostic_read",
            }:
                decision = self._evaluation_mode_denial(decision)
            policy = decision.policy
            # Tool policy is enforced at the Agent runtime boundary. Planner
            # schemas help with selection, but only this trusted path decides
            # whether a tool is allowed and how overruns are reported.
            self._graph_node(
                run_id,
                "approval_check",
                {"tool_name": tool_name},
                decision.as_trace_payload(),
                event_sink=event_sink,
            )
            if not decision.allowed:
                result = self._governance_denial_payload(tool_name, decision)
                self._graph_node(
                    run_id,
                    "execute_tool",
                    {"tool_name": tool_name, "args": args},
                    {"status": "denied", "policy_decision": decision.as_trace_payload()},
                    event_sink=event_sink,
                )
                _emit(
                    event_sink,
                    {
                        "event": "tool_completed",
                        "run_id": run_id,
                        "tool_name": tool_name,
                        "status": "denied",
                        "output_json": result,
                    },
                )
                return result
            self._graph_node(
                run_id,
                "execute_tool",
                {"tool_name": tool_name, "args": args},
                {"status": "started", "policy_decision": decision.as_trace_payload()},
                event_sink=event_sink,
            )
            _emit(
                event_sink,
                {
                    "event": "tool_started",
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "input_json": args,
                },
            )
            started_at = time.monotonic()
            if self._is_run_canceled(run_id):
                result = self._tool_error_payload(
                    tool_name,
                    policy,
                    error_type="run_canceled",
                    message="run canceled before tool execution",
                    retryable=False,
                )
                result = self._attach_tool_execution_metadata(
                    result,
                    policy,
                    duration_seconds=time.monotonic() - started_at,
                )
                _emit(
                    event_sink,
                    {
                        "event": "tool_completed",
                        "run_id": run_id,
                        "tool_name": tool_name,
                        "status": "completed",
                        "output_json": result,
                    },
                )
                return result
            # This dispatch table is the Agent "tool call" bridge. The LLM only
            # selects a name and JSON arguments; trusted Python code performs the
            # actual database, OKX, RAG, memory, or strategy operation.
            def dispatch() -> dict[str, Any]:
                return self._dispatch_tool(
                    tool_name,
                    args,
                    run_id=run_id,
                    policy=policy,
                )

            result = self._invoke_tool_with_timeout(tool_name, dispatch, policy)
            duration_seconds = time.monotonic() - started_at
            result = self._attach_tool_execution_metadata(
                result,
                policy,
                duration_seconds=duration_seconds,
            )
            _emit(
                event_sink,
                {
                    "event": "tool_completed",
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "status": "completed",
                    "output_json": result,
                },
            )
            return result

        return executor


    def _dispatch_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        run_id: str,
        policy: ToolPolicy,
    ) -> dict[str, Any]:
        """Trusted tool handler table.

        The planner selects a runtime tool name and JSON arguments; this method
        performs the actual database, OKX, RAG, memory, BitPro, or strategy
        operation and always returns a structured payload. Exceptions propagate
        to the harness retry layer; timeouts are enforced by the caller.
        """
        if tool_name == "market_summary":
            result = self._market_summary_payload()
        elif tool_name == "market_ticker":
            result = self._market_ticker_payload(str(args.get("symbol", "")))
        elif tool_name == "market_candles":
            result = self._market_candles_payload(
                symbol=str(args.get("symbol", "")),
                bar=str(args.get("bar", "1H")),
                limit=int(args.get("limit", 100)),
            )
        elif tool_name == "market_compare":
            raw_symbols = args.get("symbols", [])
            symbols = raw_symbols if isinstance(raw_symbols, list) else [raw_symbols]
            result = self._market_compare_payload(
                symbols=[str(symbol) for symbol in symbols],
                bar=str(args.get("bar", "4H")),
                limit=int(args.get("limit", 100)),
            )
        elif tool_name == "market_intelligence":
            result = self._market_intelligence_payload(
                symbol=str(args.get("symbol", "")),
                include_curated=bool(args.get("include_curated", True)),
            )

        elif tool_name == "world_model_snapshot":
            settings = self._settings if self._settings is not None else get_settings()
            result = WorldModelService(self.db, settings=settings).snapshot()


        elif tool_name == "global_market_snapshot":
            from hypertrade.global_market.service import GlobalMarketService

            snapshot = GlobalMarketService().get_snapshot()
            result = snapshot.model_dump()


        elif tool_name == "rag_search":
            self.rag.scan_once()
            query = str(args.get("query", "market risk"))
            limit = int(args.get("limit", 3))
            hits = self.rag.search(query, limit=limit)
            result = {
                "hits": [
                    {
                        "source_path": h.source_path,
                        "title": h.title,
                        "chunk_index": h.chunk_index,
                        "content": h.content_preview,
                        "score": h.score,
                    }
                    for h in hits
                ]
            }

        elif tool_name == "memory_write":
            content = str(args.get("content", ""))
            kind = str(args.get("kind", "agent_note"))
            item = self.memory.write(
                content=content,
                kind=kind,
                source_run_id=run_id,
                source_tool="memory.write",
                tags=_memory_tags_from_args(args),
                importance=_bounded_unit_interval(args.get("importance"), Decimal("0.50")),
                confidence=_bounded_unit_interval(args.get("confidence"), Decimal("0.70")),
            )
            result = {"memory_id": item.id}

        elif tool_name == "memory_search":
            items = self.memory.search(
                query=str(args.get("query", "")),
                kind=str(args.get("kind", "")),
                tag=str(args.get("tag", "")),
                limit=int(args.get("limit", 10)),
            )
            result = {
                "items": [
                    {
                        "id": m.id,
                        "kind": m.kind,
                        "content": m.content[:200],
                        "tags": m.tags,
                        "importance": str(m.importance),
                        "usage_count": m.usage_count,
                    }
                    for m in items
                ]
            }

        elif tool_name == "strategy_library_search":
            result = StrategyLibraryService(self.db).search(
                query=str(args.get("query", "")),
                strategy_key=str(args.get("strategy_key", "")),
                limit=int(args.get("limit", 10)),
            )

        elif tool_name == "strategy_experiment_plan":
            result = StrategyIterationService(self.db).plan(
                str(args.get("prompt", "")),
                strategy_key=str(args.get("strategy_key", "momentum_breakout_v1")),
                max_variants=int(args.get("max_variants", 3)),
            )
        elif tool_name == "research_mandate_read":
            result = ResearchProgramService(self.db).get_mandate(
                str(args.get("mandate_id", ""))
            )
        elif tool_name == "research_strategy_spec_draft":
            result = ResearchProgramService(self.db).draft_strategy_spec(
                str(args.get("mandate_id", "")), str(args.get("prompt", ""))
            )
        elif tool_name == "research_job_report":
            result = ResearchProgramService(self.db).report(str(args.get("job_id", "")))
        elif tool_name == "research_validation_gate":
            result = self._research_validation_gate_payload(args)
        elif tool_name == "paper_promotion_request":
            result = self._paper_promotion_request_payload(args)
        elif tool_name == "mcp_discover":
            result = self._mcp_discover_payload(args)
        elif tool_name == "mcp_invoke_tool":
            result = self._mcp_invoke_payload(args)
        elif tool_name == "workspace_write_file":
            result = self._workspace.write_file(
                path=str(args.get("path", "")),
                content=str(args.get("content", "")),
            )
        elif tool_name == "workspace_read_file":
            result = self._workspace.read_file(path=str(args.get("path", "")))
        elif tool_name == "workspace_list_files":
            result = self._workspace.list_files()
        elif tool_name == "workspace_run":
            raw_args = args.get("args")
            result = self._workspace.run(
                command=str(args.get("command", "")),
                args=[str(item) for item in raw_args] if isinstance(raw_args, list) else None,
            )
        elif tool_name == "research_validate_strategy_code":
            result = self._validate_strategy_code_payload(args)
        elif tool_name == "strategy_draft":
            research_prompt = str(args.get("prompt", ""))
            result = StrategyResearchService(self.db).create(research_prompt)
        elif tool_name == "backtest_run":
            research_id = str(args.get("research_id", ""))
            strategy_key = str(args.get("strategy_key", "momentum_breakout_v1"))
            result = BacktestService(self.db).run(
                research_id=research_id,
                strategy_key=strategy_key,
            )
        elif tool_name == "bitpro_capabilities":
            result = self._bitpro_adapter().capabilities()
        elif tool_name == "bitpro_health":
            result = self._bitpro_adapter().health()
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_market_klines":
            result = self._bitpro_adapter().market_klines(
                symbol=str(args.get("symbol", "BTC")),
                timeframe=str(args.get("timeframe", args.get("bar", "1h"))),
                limit=int(args.get("limit", 200)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_dashboard":
            strategy_id = args.get("strategy_id")
            result = self._bitpro_adapter().paper_dashboard(
                strategy_id=int(strategy_id) if strategy_id is not None else None,
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_snapshot":
            strategy_id = args.get("strategy_id")
            result = self._bitpro_adapter().paper_snapshot(
                strategy_id=int(strategy_id) if strategy_id is not None else None,
                instance_id=str(args["instance_id"]) if args.get("instance_id") else None,
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_strategy_performance":
            result = self._bitpro_adapter().paper_strategy_performance(
                limit=int(args.get("limit", 20)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_events":
            strategy_id = args.get("strategy_id")
            result = self._bitpro_adapter().paper_events(
                strategy_id=int(strategy_id) if strategy_id is not None else None,
                limit=int(args.get("limit", 50)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_equity_curve":
            strategy_id = args.get("strategy_id")
            result = self._bitpro_adapter().paper_equity_curve(
                strategy_id=int(strategy_id) if strategy_id is not None else None,
                sample_limit=int(args.get("sample_limit", 50)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_monitor_snapshot":
            strategy_id = args.get("strategy_id")
            result = BitProPaperMonitorService(
                self.db,
                bitpro_adapter=self._bitpro_adapter(),
            ).capture(
                strategy_id=int(strategy_id) if strategy_id is not None else None,
                event_limit=int(args.get("event_limit", 50)),
                equity_sample_limit=int(args.get("equity_sample_limit", 50)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_live_positions":
            result = self._bitpro_adapter().live_positions(
                exchange=str(args.get("exchange", "okx")),
                symbol=str(args["symbol"]) if args.get("symbol") else None,
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_live_order_history":
            result = self._bitpro_adapter().live_order_history(
                exchange=str(args.get("exchange", "okx")),
                symbol=str(args["symbol"]) if args.get("symbol") else None,
                limit=int(args.get("limit", 50)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_live_strategy_performance":
            result = self._bitpro_adapter().live_strategy_performance(
                exchange=str(args.get("exchange", "okx")),
                limit=int(args.get("limit", 20)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_strategy_search":
            result = self._bitpro_adapter().strategy_search(
                search=str(args.get("search", "")),
                page=int(args.get("page", 1)),
                per_page=int(args.get("per_page", 18)),
                status=str(args.get("status", "all")),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_strategy_generate":
            result = self._bitpro_adapter().strategy_generate(
                prompt=str(args.get("prompt", "")),
                symbol=str(args.get("symbol", "BTC")),
                timeframe=str(args.get("timeframe", "1h")),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_strategy_create":
            raw_symbols = args.get("symbols", [])
            symbols = raw_symbols if isinstance(raw_symbols, list) else [raw_symbols]
            raw_config = args.get("config", {})
            result = self._bitpro_adapter().strategy_create(
                name=str(args.get("name", "")),
                script_content=str(args.get("script_content", "")),
                description=str(args["description"]) if args.get("description") else None,
                config=raw_config if isinstance(raw_config, dict) else {},
                exchange=str(args.get("exchange", "okx")),
                symbols=[str(symbol) for symbol in symbols],
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_strategy_update":
            raw_symbols = args.get("symbols")
            update_symbols = (
                raw_symbols
                if isinstance(raw_symbols, list)
                else ([raw_symbols] if raw_symbols is not None else None)
            )
            raw_config = args.get("config")
            result = self._bitpro_adapter().strategy_update(
                strategy_id=int(args.get("strategy_id", 0)),
                name=str(args["name"]) if args.get("name") is not None else None,
                script_content=(
                    str(args["script_content"])
                    if args.get("script_content") is not None
                    else None
                ),
                description=(
                    str(args["description"]) if args.get("description") is not None else None
                ),
                config=raw_config if isinstance(raw_config, dict) else None,
                exchange=str(args["exchange"]) if args.get("exchange") is not None else None,
                symbols=(
                    [str(symbol) for symbol in update_symbols]
                    if update_symbols is not None
                    else None
                ),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_backtest_start_job":
            result = self._bitpro_adapter().backtest_start_job(
                strategy_id=int(args.get("strategy_id", 0)),
                start_date=str(args.get("start_date", "")),
                end_date=str(args.get("end_date", "")),
                initial_capital=float(args.get("initial_capital", 10000.0)),
                exchange=str(args.get("exchange", "okx")),
                symbol=str(args["symbol"]) if args.get("symbol") else None,
                timeframe=str(args["timeframe"]) if args.get("timeframe") else None,
                wait_for_result=True,
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_backtest_get_job":
            result = self._bitpro_adapter().backtest_get_job(job_id=str(args.get("job_id", "")))
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_backtest_list_results":
            min_return = args.get("min_total_return_pct")
            result = self._bitpro_adapter().backtest_list_results(
                min_total_return_pct=(float(min_return) if min_return is not None else None),
                status=str(args.get("status", "completed")),
                sort_by=str(args.get("sort_by", "return")),
                sort_order=str(args.get("sort_order", "desc")),
                limit=int(args.get("limit", 100)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_backtest_get_result":
            result = self._bitpro_adapter().backtest_get_result(
                backtest_id=str(args.get("backtest_id", "")),
                sample_limit=int(args.get("sample_limit", 20)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_configure":
            result = self._bitpro_adapter().paper_configure(
                strategy_id=int(args.get("strategy_id", 0)),
                initial_equity=float(args.get("initial_equity", 10000.0)),
                exchange=str(args.get("exchange", "okx")),
                loop_interval_sec=int(args.get("loop_interval_sec", 60)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_start":
            result = self._bitpro_adapter().paper_start(
                strategy_id=int(args.get("strategy_id", 0))
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_pause":
            result = self._bitpro_adapter().paper_pause(
                strategy_id=int(args.get("strategy_id", 0))
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_resume":
            result = self._bitpro_adapter().paper_resume(
                strategy_id=int(args.get("strategy_id", 0))
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "bitpro_paper_stop":
            result = self._bitpro_adapter().paper_stop(
                strategy_id=int(args.get("strategy_id", 0)),
                clear_metrics=bool(args.get("clear_metrics", False)),
            )
            self._trace_bitpro_tool_calls(run_id, result)
        elif tool_name == "live_order_intent":
            settings = self._settings if self._settings is not None else get_settings()
            result = LiveOrderIntentService(self.db, settings=settings).create(
                symbol=str(args.get("symbol", "")),
                side=str(args.get("side", "")),
                size=str(args.get("size", "")),
                order_type=str(args.get("order_type", "market")),
                price=str(args["price"]) if args.get("price") else None,
                reason=str(args.get("reason", "")),
                source="agent",
                source_run_id=run_id,
            )
        else:
            result = self._tool_error_payload(
                tool_name,
                policy,
                error_type="unknown_tool",
                message=f"unknown tool: {tool_name}",
                retryable=False,
            )
        return result

    def _invoke_tool_with_timeout(
        self,
        tool_name: str,
        dispatch: Callable[[], dict[str, Any]],
        policy: ToolPolicy,
    ) -> dict[str, Any]:
        """Enforce the registry timeout_class as a hard wall-clock deadline."""
        future = self._tool_pool.submit(dispatch)
        try:
            return future.result(timeout=self._tool_timeout_seconds(policy))
        except FuturesTimeoutError:
            # The worker thread may still finish in the background; its result
            # is discarded and the planner receives a structured timeout so the
            # run can continue deterministically.
            future.cancel()
            return self._tool_timeout_payload(tool_name, policy)

    def _research_validation_gate_payload(self, args: dict[str, Any]) -> dict[str, Any]:
        """Advisory gate self-check against operator-locked mandate criteria.

        Thresholds are loaded server-side from the mandate so the model can
        never weaken them; the results rows come from the planner context and
        the verdict is advisory — authoritative gating runs when the
        orchestrator records evidence.
        """
        from hypertrade.research.service import ResearchProgramService
        from hypertrade.research.validation import ValidationGate

        mandate_id = str(args.get("mandate_id", ""))
        raw_rows = args.get("results")
        rows: list[dict[str, Any]] = (
            [row for row in raw_rows if isinstance(row, dict)]
            if isinstance(raw_rows, list)
            else []
        )
        if not mandate_id:
            return {
                "status": "error",
                "error": {"type": "missing_mandate", "message": "mandate_id is required"},
            }
        if not rows:
            return {
                "status": "error",
                "error": {
                    "type": "missing_results",
                    "message": "at least one backtest result row is required",
                },
            }
        try:
            mandate = ResearchProgramService(self.db).get_mandate(mandate_id)
        except (KeyError, ValueError) as exc:
            return {
                "status": "unavailable",
                "execution_status": "error",
                "unavailable_reason": "mandate_not_found",
                "error": {"type": "mandate_not_found", "message": str(exc)[:200]},
                "tool_name": "research_validation_gate",
            }
        verdict = ValidationGate().evaluate(
            results=rows[:20],
            validation=dict(mandate.get("validation") or {}),
            data_complete=bool(args.get("data_complete", True)),
            costs_declared=bool(args.get("costs_declared", True)),
        )
        return {
            "status": "ok",
            "mandate_id": mandate_id,
            "evaluated_rows": len(rows[:20]),
            **verdict,
            "note": (
                "Advisory only. Authoritative gates run server-side when research "
                "evidence is recorded."
            ),
        }

    def _paper_promotion_request_payload(self, args: dict[str, Any]) -> dict[str, Any]:
        """Create an operator approval request for fully passing evidence.

        This never touches BitPro: configure/start stay behind the explicit
        human approval record created here. Rejections surface as structured
        errors so the planner can pick different evidence instead of guessing.
        """
        from hypertrade.research.paper_promotion import PaperPromotionService

        evidence_id = str(args.get("evidence_id", ""))
        reason = str(args.get("reason", ""))
        if not evidence_id or not reason.strip():
            return {
                "status": "error",
                "error": {
                    "type": "invalid_arguments",
                    "message": "evidence_id and a non-empty reason are required",
                },
            }
        try:
            promotion = PaperPromotionService(self.db).request(
                evidence_id=evidence_id,
                reason=reason,
            )
        except ValueError as exc:
            return {
                "status": "denied",
                "execution_status": "denied",
                "error": {
                    "type": "promotion_request_rejected",
                    "message": str(exc)[:240],
                },
                "tool_name": "paper_promotion_request",
                "missing_data": [
                    {
                        "field": "passing_evidence",
                        "reason": "promotion_requires_fully_passing_evidence",
                        "source_of_truth": "research_experiment_evidence",
                    }
                ],
            }
        return {"status": "ok", "promotion": promotion}

    def _build_mcp_registry(self) -> Any | None:
        from hypertrade.connectors.mcp_client import (
            McpClientRegistry,
            parse_mcp_server_configs,
        )

        settings = self._settings if self._settings is not None else get_settings()
        servers = parse_mcp_server_configs(str(getattr(settings, "mcp_servers_json", "") or ""))
        return McpClientRegistry(servers) if servers else None

    def _mcp_discover_payload(self, args: dict[str, Any]) -> dict[str, Any]:
        from hypertrade.connectors.mcp_client import run_async

        if self._mcp_registry is None:
            return {
                "status": "unavailable",
                "execution_status": "unavailable",
                "unavailable_reason": "mcp_not_configured",
                "error": {
                    "type": "mcp_not_configured",
                    "message": "No MCP servers configured (MCP_SERVERS_JSON empty).",
                },
            }
        server = str(args.get("server", "")).strip()
        force = bool(args.get("force_refresh", False))
        try:
            if server:
                tools = run_async(
                    self._mcp_registry.list_tools(server, force_refresh=force)
                )
                payload = {
                    "status": "ok",
                    "server": server,
                    "tools": [
                        {
                            "server": tool.server,
                            "name": tool.name,
                            "description": tool.description[:300],
                            "input_schema": tool.input_schema,
                        }
                        for tool in tools[:50]
                    ],
                }
            else:
                servers = self._mcp_registry.server_names()
                all_tools: list[dict[str, str]] = []
                for name in servers:
                    tools = run_async(self._mcp_registry.list_tools(name))
                    all_tools.extend(
                        {
                            "server": tool.server,
                            "name": tool.name,
                            "description": tool.description[:200],
                        }
                        for tool in tools[:25]
                    )
                payload = {"status": "ok", "servers": list(servers), "tools": all_tools}
            return payload
        except Exception as exc:  # noqa: BLE001 - structured tool failure
            return {
                "status": "unavailable",
                "execution_status": "error",
                "unavailable_reason": "mcp_discover_failed",
                "error": {"type": type(exc).__name__, "message": str(exc)[:300]},
            }

    def _mcp_invoke_payload(self, args: dict[str, Any]) -> dict[str, Any]:
        from hypertrade.connectors.mcp_client import McpClientError, run_async

        if self._mcp_registry is None:
            return {
                "status": "unavailable",
                "execution_status": "unavailable",
                "unavailable_reason": "mcp_not_configured",
                "error": {
                    "type": "mcp_not_configured",
                    "message": "No MCP servers configured (MCP_SERVERS_JSON empty).",
                },
            }
        server = str(args.get("server", "")).strip()
        tool = str(args.get("tool", "")).strip()
        raw_arguments = args.get("arguments")
        arguments = dict(raw_arguments) if isinstance(raw_arguments, dict) else {}
        if not server or not tool:
            return {
                "status": "error",
                "error": {
                    "type": "invalid_arguments",
                    "message": "server and tool are required",
                },
            }
        try:
            result = run_async(self._mcp_registry.call_tool(server, tool, arguments))
            return {"status": "ok", "server": server, "tool": tool, "result": result}
        except McpClientError as exc:
            return {
                "status": "unavailable",
                "execution_status": "error",
                "unavailable_reason": "mcp_tool_failed",
                "error": {"type": type(exc).__name__, "message": str(exc)[:300]},
                "tool_name": tool,
            }
        except Exception as exc:  # noqa: BLE001 - structured tool failure
            return {
                "status": "unavailable",
                "execution_status": "error",
                "unavailable_reason": "mcp_invoke_failed",
                "error": {"type": type(exc).__name__, "message": str(exc)[:300]},
                "tool_name": tool,
            }

    def _validate_strategy_code_payload(self, args: dict[str, Any]) -> dict[str, Any]:
        """ARC static gate over workspace code, before any BitPro spend.

        Same single-source validator the codegen pipeline must pass
        (research.codegen.static_code_rejections), so agent-authored code can
        never be held to a different standard than generated candidates.
        """
        import ast
        from hashlib import sha256

        from hypertrade.research.codegen import static_code_rejections

        path = str(args.get("path", ""))
        read_result = self._workspace.read_file(path)
        if read_result.get("status") != "ok":
            return read_result
        code = str(read_result.get("content", ""))
        try:
            ast.parse(code, filename=path)
        except SyntaxError as exc:
            return {
                "status": "ok",
                "path": path,
                "passed": False,
                "rejections": [f"invalid_python_syntax:{exc.lineno}"],
                "content_hash": sha256(code.encode("utf-8")).hexdigest()[:16],
                "next_steps": "fix the syntax error, then re-run this gate",
            }
        rejections = static_code_rejections(code)
        return {
            "status": "ok",
            "path": path,
            "passed": not rejections,
            "rejections": rejections,
            "content_hash": sha256(code.encode("utf-8")).hexdigest()[:16],
            "next_steps": (
                "create the strategy via bitpro_strategy_create with this "
                "script_content, then backtest with bitpro_backtest_start_job"
                if not rejections
                else "fix the rejected constructs, then re-run this gate"
            ),
        }

    def _memory_prompt_suffix(self) -> str:
        """Close the memory write->recall loop.

        Without injection, memories were write-only archives: recall depended
        on the model spontaneously calling memory_search. Top-K governed
        assertions and high-importance items are surfaced deterministically so
        the same DB state yields the same context window. Best-effort: a ledger
        read failure degrades to no context instead of failing the run.
        """
        settings = self._settings if self._settings is not None else get_settings()
        if not getattr(settings, "agent_memory_prompt_injection", False):
            return ""
        lines: list[str] = []
        try:
            from hypertrade.memory.governance import MemoryAssertionService

            for assertion in MemoryAssertionService(self.db).active_for_prompt(limit=5):
                claim = str(assertion.get("claim", "")).strip()[:200]
                confidence = assertion.get("confidence", "")
                lines.append(f"- [assertion|confidence {confidence}] {claim}")
            for item in self.memory.prompt_context(limit=5):
                lines.append(
                    f"- [memory {item.id}|{item.kind}|importance {item.importance}] "
                    f"{item.content[:200]}"
                )
        except Exception:
            logger.warning("memory prompt injection skipped", exc_info=True)
            return ""
        if not lines:
            return ""
        block = "\n".join(lines)[:1200]
        return "## Active governed memory context\nTreat as audited evidence; cite ids.\n" + block

    def _execution_mode(self) -> str:
        return "evaluation" if self.evaluation_mode else "standard"

    @staticmethod
    def _evaluation_mode_denial(decision: GovernanceDecision) -> GovernanceDecision:
        return GovernanceDecision(
            requested_tool_name=decision.requested_tool_name,
            registry_tool_name=decision.registry_tool_name,
            policy=decision.policy,
            allowed=False,
            status="denied",
            missing_fields=list(decision.missing_fields),
            denial_reason=(
                "evaluation mode permits only read and live_diagnostic_read tool scopes"
            ),
        )

    def _tool_policy(self, tool_name: str) -> ToolPolicy:
        try:
            return self.tools.get_for_runtime_name(tool_name).policy
        except KeyError:
            return ToolPolicy(
                scope="read",
                approval="blocked",
                source_of_truth="unknown",
                timeout_class="quick",
                failure_behavior="return_structured_error",
            )

    @staticmethod
    def _policy_outcome(policy: ToolPolicy) -> str:
        if policy.approval == "blocked":
            return "blocked"
        return "approval_required" if policy.approval == "required" else "allowed"

    def _tool_timeout_seconds(self, policy: ToolPolicy) -> float:
        settings = self._settings if self._settings is not None else get_settings()
        if policy.timeout_class == "quick":
            return settings.agent_tool_timeout_quick_seconds
        if policy.timeout_class == "long":
            return settings.agent_tool_timeout_long_seconds
        return settings.agent_tool_timeout_standard_seconds

    @staticmethod
    def _governance_denial_payload(
        tool_name: str,
        decision: GovernanceDecision,
    ) -> dict[str, Any]:
        return {
            "status": "denied",
            "execution_status": "denied",
            "tool_name": tool_name,
            "requested_tool_name": decision.requested_tool_name,
            "registry_tool_name": decision.registry_tool_name,
            "missing_fields": list(decision.missing_fields),
            "denial_reason": decision.denial_reason,
            "policy": decision.policy.to_dict(),
            "policy_outcome": decision.status,
            "policy_decision": decision.as_trace_payload(),
        }

    @staticmethod
    def _attach_tool_execution_metadata(
        payload: dict[str, Any],
        policy: ToolPolicy,
        *,
        duration_seconds: float,
    ) -> dict[str, Any]:
        result = dict(payload)
        result.setdefault("policy", policy.to_dict())
        result.setdefault("policy_outcome", AgentKernel._policy_outcome(policy))
        result.setdefault("execution_status", "completed")
        result["execution_ms"] = round(duration_seconds * 1000, 3)
        return result

    @staticmethod
    def _tool_timeout_payload(tool_name: str, policy: ToolPolicy) -> dict[str, Any]:
        timeout_class = policy.timeout_class
        return {
            "status": "unavailable",
            "execution_status": "timeout",
            "unavailable_reason": "tool_timeout",
            "error": {
                "type": "timeout",
                "message": f"{tool_name} exceeded {timeout_class} timeout",
                "retryable": True,
            },
            "missing_data": [
                {
                    "field": "tool_result",
                    "reason": "tool_timeout",
                    "source_of_truth": policy.source_of_truth,
                }
            ],
        }

    @staticmethod
    def _tool_error_payload(
        tool_name: str,
        policy: ToolPolicy,
        *,
        error_type: str,
        message: str,
        retryable: bool,
    ) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "execution_status": "error",
            "unavailable_reason": error_type,
            "error": {
                "type": error_type,
                "message": message[:240],
                "retryable": retryable,
            },
            "missing_data": [
                {
                    "field": "tool_result",
                    "reason": error_type,
                    "source_of_truth": policy.source_of_truth,
                }
            ],
            "tool_name": tool_name,
        }

    def _bitpro_adapter(self) -> Any:
        if self.bitpro_adapter is None:
            settings = self._settings if self._settings is not None else get_settings()
            self.bitpro_adapter = BitProToolAdapter(BitProMcpClient(settings=settings))
        return self.bitpro_adapter

    def _trace_bitpro_tool_calls(self, run_id: str, payload: dict[str, Any]) -> None:
        calls = payload.get("tool_calls", [])
        if not isinstance(calls, list):
            return
        for call in calls:
            if not isinstance(call, dict):
                continue
            tool_name = _bitpro_trace_tool_name(str(call.get("tool", "")))
            if not tool_name:
                continue
            self._trace(
                run_id,
                tool_name,
                _dict_or_empty(call.get("parameters")),
                {
                    "status": str(call.get("status", "")),
                    "result_summary": _dict_or_empty(call.get("result_summary")),
                    "error": str(call.get("error", "")),
                },
            )

    def _export_run_observability(self, run_id: str, settings: Settings) -> None:
        # Langfuse is an optional secondary projection. The durable local trace
        # remains authoritative, and exporter failure must never change the run.
        result = LangfuseTraceExporter(settings).export(self.get_run(run_id))
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                return
            state = dict(run.run_state_json or {})
            exports = _dict_or_empty(state.get("external_observability"))
            exports["langfuse"] = result.as_dict()
            state["external_observability"] = exports
            run.run_state_json = state

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> CompletedAgentRun:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise KeyError(run_id)
            events = session.scalars(
                select(TraceEvent)
                .where(TraceEvent.run_id == run_id)
                .order_by(TraceEvent.created_at)
            ).all()
            for event in events:
                session.expunge(event)
            return CompletedAgentRun(
                id=run.id,
                status=run.status,
                report_markdown=run.report_markdown,
                report_json=run.report_json,
                run_state_json=run.run_state_json,
                trace_events=list(events),
            )

    def cancel_run(
        self,
        run_id: str,
        *,
        reason: str = "canceled_by_operator",
    ) -> CompletedAgentRun:
        self._cancel_run(run_id, reason)
        return self.get_run(run_id)

    def _create_run(self, prompt: str, *, execution_mode: str) -> str:
        with self.db.session() as session:
            run = AgentRun(
                prompt=prompt,
                status="running",
                run_state_json={"execution_mode": execution_mode},
            )
            session.add(run)
            session.flush()
            return run.id

    def _complete_run(
        self,
        run_id: str,
        report_markdown: str,
        report_json: dict[str, Any],
    ) -> None:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status == "canceled":
                return
            run.status = "completed"
            run.report_markdown = report_markdown
            run.report_json = report_json
            run.run_state_json = {**(run.run_state_json or {}), "final_answer": report_markdown}

    def _cancel_run(self, run_id: str, reason: str) -> None:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise KeyError(run_id)
            run.status = "canceled"
            run.error = reason
            run.report_markdown = f"Agent run canceled: {reason}"
            run.report_json = {
                "status": "canceled",
                "error": {
                    "type": "run_canceled",
                    "message": reason,
                    "retryable": False,
                },
            }
            state = dict(run.run_state_json or {})
            state["canceled"] = True
            state["cancel_reason"] = reason
            run.run_state_json = state

    def _is_run_canceled(self, run_id: str) -> bool:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            return bool(run is not None and run.status == "canceled")

    def _fail_run(self, run_id: str, error: str) -> None:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = error

    def _set_run_observability(
        self,
        run_id: str,
        observability: dict[str, Any],
    ) -> None:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise KeyError(run_id)
            state = dict(run.run_state_json or {})
            state["observability"] = observability
            run.run_state_json = state

    def _finalize_run_observability(self, run_id: str, *, duration_ms: float) -> None:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                return
            state = dict(run.run_state_json or {})
            raw = state.get("observability")
            observability = dict(raw) if isinstance(raw, dict) else _empty_observability()
            observability.update(
                {
                    "schema_version": "agent-observability-v1",
                    "status": run.status,
                    "duration_ms": duration_ms,
                    "started_at": run.created_at.isoformat(),
                    "completed_at": utc_now().isoformat(),
                    "private_reasoning_stored": False,
                }
            )
            state["observability"] = observability
            run.run_state_json = state
            report = dict(run.report_json or {})
            report["observability"] = observability
            run.report_json = report

    def _trace(
        self,
        run_id: str,
        tool_name: str,
        input_json: dict[str, Any],
        output_json: dict[str, Any],
    ) -> None:
        with self.db.session() as session:
            session.add(
                TraceEvent(
                    run_id=run_id,
                    tool_name=tool_name,
                    status="completed",
                    input_json=input_json,
                    output_json=output_json,
                )
            )

    def _graph_node(
        self,
        run_id: str,
        node: str,
        input_json: dict[str, Any],
        output_json: dict[str, Any],
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        # Graph state is duplicated into both trace_events and run_state_json:
        # trace_events are append-only audit records; run_state_json is a compact
        # "current state" view for the harness UI and CLI.
        self._trace(run_id, f"graph.{node}", input_json, output_json)
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise KeyError(run_id)
            state = dict(run.run_state_json or {})
            graph = list(state.get("graph", []))
            graph.append({"node": node, "input": input_json, "output": output_json})
            state["graph"] = graph
            state["current_node"] = node
            run.run_state_json = state
        _emit(
            event_sink,
            {
                "event": "graph_node",
                "run_id": run_id,
                "node": node,
                "status": "completed",
                "output_json": output_json,
            },
        )

    def _get_run_state(self, run_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                return {}
            return dict(run.run_state_json or {})

    def _market_summary_payload(self) -> dict[str, Any]:
        source, error = self._refresh_market_snapshot()
        if source != "okx_rest":
            latest_rows = self.market.latest_tickers(limit=250)
            top_movers = [
                {
                    "inst_id": row.inst_id,
                    "last": str(row.last),
                    "volume_ccy_24h": str(row.volume_ccy_24h),
                    "change_utc0_pct": str(row.change_utc0_pct),
                }
                for row in self.market.top_movers(limit=10)
            ]
            if latest_rows:
                return {
                    "market_scope": "OKX SWAP",
                    "top_movers": top_movers,
                    "heat_summary": _market_heat_summary(latest_rows),
                    "data_source": "db_fallback",
                    "as_of_utc": datetime.now(UTC).isoformat(),
                    "unavailable_reason": error or "okx_rest_unavailable",
                }
            return {
                "market_scope": "OKX SWAP",
                "top_movers": [],
                "heat_summary": _market_heat_summary([]),
                "data_source": source,
                "as_of_utc": datetime.now(UTC).isoformat(),
                "unavailable_reason": error or "okx_rest_unavailable",
            }
        latest_rows = self.market.latest_tickers(limit=250)
        top_movers = [
            {
                "inst_id": row.inst_id,
                "last": str(row.last),
                "volume_ccy_24h": str(row.volume_ccy_24h),
                "change_utc0_pct": str(row.change_utc0_pct),
            }
            for row in self.market.top_movers(limit=10)
        ]
        return {
            "market_scope": "OKX SWAP",
            "top_movers": top_movers,
            "heat_summary": _market_heat_summary(latest_rows),
            "data_source": source,
            "as_of_utc": datetime.now(UTC).isoformat(),
        }

    def _market_ticker_payload(self, symbol: str) -> dict[str, Any]:
        inst_id = _normalize_swap_inst_id(symbol)
        source, error = self._refresh_market_snapshot()
        ticker = self.market.get_ticker(inst_id)
        if ticker is None:
            return {
                "market_scope": "OKX SWAP",
                "symbol": symbol,
                "inst_id": inst_id,
                "found": False,
                "data_source": source,
                "as_of_utc": datetime.now(UTC).isoformat(),
                "unavailable_reason": error if source != "okx_rest" else "",
            }
        return {
            "market_scope": "OKX SWAP",
            "symbol": symbol,
            "inst_id": ticker.inst_id,
            "found": True,
            "last": str(ticker.last),
            "volume_ccy_24h": str(ticker.volume_ccy_24h),
            "change_utc0_pct": str(ticker.change_utc0_pct),
            "ticker_updated_at": ticker.updated_at.isoformat(),
            "data_source": source if source == "okx_rest" else "db_fallback",
            "as_of_utc": datetime.now(UTC).isoformat(),
        }

    def _market_candles_payload(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        inst_id = _normalize_swap_inst_id(symbol)
        safe_limit = max(1, min(limit, 300))
        safe_bar = _normalize_okx_bar(bar)
        try:
            candles = self._fetch_market_candles(inst_id, safe_bar, safe_limit)
            summary = summarize_candles(inst_id, safe_bar, candles)
            summary.update(
                {
                    "market_scope": "OKX SWAP",
                    "symbol": symbol,
                    "data_source": "okx_rest",
                    "as_of_utc": datetime.now(UTC).isoformat(),
                }
            )
            return summary
        except Exception as exc:
            return {
                "market_scope": "OKX SWAP",
                "symbol": symbol,
                "inst_id": inst_id,
                "bar": safe_bar,
                "found": False,
                "candle_count": 0,
                "data_source": "unavailable",
                "as_of_utc": datetime.now(UTC).isoformat(),
                "unavailable_reason": str(exc)[:160],
            }

    def _market_compare_payload(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]:
        safe_bar = _normalize_okx_bar(bar)
        unique_symbols = _unique_symbols(symbols)
        rankings: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for symbol in unique_symbols:
            payload = self._market_candles_payload(symbol=symbol, bar=safe_bar, limit=limit)
            if not payload.get("found"):
                errors.append(
                    {
                        "symbol": symbol,
                        "reason": str(payload.get("unavailable_reason", "not_found")),
                    }
                )
                continue
            score = _strength_score(payload)
            rankings.append(
                {
                    "rank": 0,
                    "symbol": symbol,
                    "inst_id": payload.get("inst_id", _normalize_swap_inst_id(symbol)),
                    "strength_score": _decimal_text(score),
                    "return_pct": str(payload.get("return_pct", "0")),
                    "range_pct": str(payload.get("range_pct", "0")),
                    "close_position_pct": str(payload.get("close_position_pct", "0")),
                    "trend_bias": str(payload.get("trend_bias", "range")),
                    "ma20": str(payload.get("ma20", "0")),
                    "ma60": str(payload.get("ma60", "0")),
                    "data_source": str(payload.get("data_source", "unknown")),
                }
            )
        rankings.sort(key=lambda row: _as_decimal(row["strength_score"]), reverse=True)
        for index, row in enumerate(rankings, start=1):
            row["rank"] = index
        return {
            "market_scope": "OKX SWAP",
            "symbols": unique_symbols,
            "bar": safe_bar,
            "limit": max(1, min(limit, 300)),
            "found": bool(rankings),
            "leader": rankings[0]["inst_id"] if rankings else "",
            "rankings": rankings,
            "errors": errors,
            "data_source": "okx_rest" if rankings else "unavailable",
            "as_of_utc": datetime.now(UTC).isoformat(),
        }

    def _market_intelligence_payload(
        self,
        *,
        symbol: str,
        include_curated: bool = True,
    ) -> dict[str, Any]:
        settings = self._settings if self._settings is not None else get_settings()
        return MarketIntelligenceService(settings=settings).collect(
            symbol=symbol,
            include_curated=include_curated,
        )

    def _fetch_market_candles(
        self,
        inst_id: str,
        bar: str,
        limit: int,
    ) -> list[OkxCandle]:
        settings = self._settings if self._settings is not None else get_settings()
        return asyncio.run(
            OkxRestClient(settings).fetch_candles(
                inst_id=inst_id,
                bar=bar,
                limit=limit,
            )
        )

    def _refresh_market_snapshot(self) -> tuple[str, str]:
        try:
            settings = self._settings if self._settings is not None else get_settings()
            tickers = asyncio.run(OkxRestClient(settings).fetch_swap_tickers())
            for ticker in tickers:
                self.market.upsert_ticker_snapshot(
                    inst_id=ticker.inst_id,
                    inst_type=ticker.inst_type,
                    last=ticker.last,
                    volume_ccy_24h=ticker.volume_ccy_24h,
                    change_utc0_pct=ticker.change_utc0_pct,
                    raw=ticker.raw,
                )
            return ("okx_rest", "")
        except Exception as exc:
            return ("unavailable", str(exc)[:160])

    @staticmethod
    def _render_market_report(report: dict[str, Any]) -> str:
        movers = report.get("top_movers", [])
        heat = report.get("heat_summary")
        heat = heat if isinstance(heat, dict) else _market_heat_summary([])
        lines = [
            "# OKX 永续合约行情归纳",
            "",
            "**范围**: OKX 全市场 SWAP",
            "**触发方式**: 用户按需发起",
            f"**数据时间(UTC)**: {report.get('as_of_utc', 'n/a')}",
            f"**数据来源**: {report.get('data_source', 'unknown')}",
            "",
            "## 市场热度总结",
            "",
            f"- 结论: {heat.get('conclusion', '当前市场热度暂不可用。')}",
            (
                "- 样本: {sample_count} 个合约，上涨 {advancers_count} 个"
                "({advancers_pct}%)，下跌 {decliners_count} 个({decliners_pct}%)，"
                "平均涨跌幅 {average_change_pct}%"
            ).format(
                sample_count=heat.get("sample_count", 0),
                advancers_count=heat.get("advancers_count", 0),
                advancers_pct=heat.get("advancers_pct", "0.000000"),
                decliners_count=heat.get("decliners_count", 0),
                decliners_pct=heat.get("decliners_pct", "0.000000"),
                average_change_pct=heat.get("average_change_pct", "0.000000"),
            ),
            ("- 最强/最弱: {top_gainer} / {top_loser}").format(
                top_gainer=heat.get("top_gainer", "n/a"),
                top_loser=heat.get("top_loser", "n/a"),
            ),
            "",
            "## 异动榜",
        ]
        if not movers:
            lines.append("- 当前无法获取实时 OKX 行情，未输出异动榜。")
            reason = report.get("unavailable_reason")
            if isinstance(reason, str) and reason:
                lines.append(f"- 原因: {reason}")
        for mover in movers:
            line = (
                "- {inst_id}: 最新价 {last}, UTC0 涨跌幅 {change_utc0_pct}%, "
                "24h 成交额 {volume_ccy_24h}"
            )
            lines.append(line.format(**mover))
        return "\n".join(lines)

    @staticmethod
    def _render_planner_report(
        final_message: str,
        tool_calls: list[Any],
    ) -> str:
        market_summary_lines: list[str] = []
        ticker_lines: list[str] = []
        candle_lines: list[str] = []
        compare_lines: list[str] = []
        intelligence_lines: list[str] = []
        world_model_lines: list[str] = []
        bitpro_lines: list[str] = []
        bitpro_backtest_lines: list[str] = []
        bitpro_backtest_detail_lines: list[str] = []
        bitpro_paper_lines: list[str] = []
        paper_performance_lines: list[str] = []
        bitpro_live_order_lines: list[str] = []
        bitpro_live_strategy_lines: list[str] = []
        bitpro_lifecycle_lines: list[str] = []
        strategy_library_lines: list[str] = []
        citation_lines: list[str] = []
        unavailable_lines: list[str] = []
        governance_lines: list[str] = []
        paper_strategy_comparison = _is_paper_strategy_comparison(final_message)
        for record in tool_calls:
            if getattr(record, "tool_name", "") not in {"market_summary", "market.summary"}:
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict):
                continue
            market_summary_lines.extend(_market_summary_report_lines(payload))
            market_summary_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "market_ticker":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or not payload.get("found"):
                continue
            ticker_lines.extend(
                [
                    f"- 标的: {payload.get('inst_id', 'unknown')}",
                    f"- 最新价 {payload.get('last', 'n/a')}",
                    f"- UTC0 涨跌幅 {payload.get('change_utc0_pct', 'n/a')}%",
                    f"- 24h 成交额 {payload.get('volume_ccy_24h', 'n/a')}",
                    f"- 数据来源 {payload.get('data_source', 'unknown')}",
                    f"- 数据时间(UTC) {payload.get('as_of_utc', 'n/a')}",
                    "",
                ]
            )
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "market_candles":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or not payload.get("found"):
                continue
            candle_lines.extend(
                [
                    f"- 标的: {payload.get('inst_id', 'unknown')}",
                    f"- 周期: {payload.get('bar', 'n/a')}",
                    f"- K线数量 {payload.get('candle_count', 'n/a')}",
                    f"- 区间涨跌幅 {payload.get('return_pct', 'n/a')}%",
                    f"- 区间振幅 {payload.get('range_pct', 'n/a')}%",
                    f"- 收盘区间位置 {payload.get('close_position_pct', 'n/a')}%",
                    f"- MA20 {payload.get('ma20', 'n/a')}",
                    f"- MA60 {payload.get('ma60', 'n/a')}",
                    f"- 趋势偏向 {payload.get('trend_bias', 'unknown')}",
                    f"- 数据来源 {payload.get('data_source', 'unknown')}",
                    f"- 数据时间(UTC) {payload.get('as_of_utc', 'n/a')}",
                    "",
                ]
            )
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "market_compare":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or not payload.get("found"):
                continue
            compare_lines.extend(
                [
                    f"- 周期: {payload.get('bar', 'n/a')}",
                    f"- 领先标的: {payload.get('leader', 'unknown')}",
                    "",
                ]
            )
            rankings = payload.get("rankings", [])
            if isinstance(rankings, list):
                for row in rankings:
                    if not isinstance(row, dict):
                        continue
                    compare_lines.append(
                        "{rank}. {inst_id}: 强弱分 {strength_score}, "
                        "涨跌幅 {return_pct}%, 收盘位置 {close_position_pct}%, "
                        "趋势 {trend_bias}".format(
                            rank=row.get("rank", "?"),
                            inst_id=row.get("inst_id", "unknown"),
                            strength_score=row.get("strength_score", "n/a"),
                            return_pct=row.get("return_pct", "n/a"),
                            close_position_pct=row.get("close_position_pct", "n/a"),
                            trend_bias=row.get("trend_bias", "unknown"),
                        )
                    )
            compare_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "market_intelligence":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict):
                continue
            inst_id = str(payload.get("inst_id", payload.get("symbol", "unknown")))
            intelligence_lines.append(f"- 标的: {inst_id}")
            results = payload.get("results")
            results = results if isinstance(results, list) else []
            if not results:
                intelligence_lines.append("- 暂无可用市场情报来源。")
            for item in results[:5]:
                if not isinstance(item, dict):
                    continue
                metrics = item.get("metrics")
                metrics = metrics if isinstance(metrics, dict) else {}
                metric_text = ", ".join(f"{key}={value}" for key, value in metrics.items()) or "n/a"
                missing = item.get("missing_fields")
                missing = missing if isinstance(missing, list) else []
                sample = item.get("sample")
                sample = sample if isinstance(sample, list) else []
                intelligence_lines.extend(
                    [
                        f"- 来源: {item.get('source', 'unknown')}",
                        f"- source_path: {item.get('source_path', 'unknown')}",
                        ("- as_of: {as_of}, freshness_seconds={freshness}").format(
                            as_of=item.get("as_of", "n/a"),
                            freshness=item.get("freshness_seconds", "n/a"),
                        ),
                        f"- 指标: {metric_text}",
                    ]
                )
                if missing:
                    intelligence_lines.append(
                        "- 缺失字段: " + ", ".join(str(field) for field in missing)
                    )
                if sample:
                    intelligence_lines.append(
                        "- 样本: " + " | ".join(str(value) for value in sample[:3])
                    )
            intelligence_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "world_model_snapshot":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict):
                continue
            global_market = _dict_or_empty(payload.get("global_market"))
            crypto_market = _dict_or_empty(payload.get("crypto_market"))
            strategy_state = _dict_or_empty(payload.get("strategy"))
            execution = _dict_or_empty(payload.get("execution"))
            tool_health = _dict_or_empty(payload.get("tool_health"))
            deployment = _dict_or_empty(payload.get("deployment"))
            missing = payload.get("missing_data")
            missing = missing if isinstance(missing, list) else []
            decision = _dict_or_empty(payload.get("decision"))
            world_model_lines.extend(
                [
                    f"- schema_version: {payload.get('schema_version', 'unknown')}",
                    f"- 生成时间: {payload.get('generated_at', 'n/a')}",
                    ("- 全局风险状态: {risk}, cross_asset_signal={cross_asset}").format(
                        risk=global_market.get("risk_regime", "unknown"),
                        cross_asset=global_market.get("cross_asset_signal", "unknown"),
                    ),
                    (
                        "- 加密市场: status={status}, tickers={tickers}, avg_change_utc0={avg}%"
                    ).format(
                        status=crypto_market.get("status", "unknown"),
                        tickers=crypto_market.get("ticker_count", "n/a"),
                        avg=crypto_market.get("average_change_utc0_pct", "n/a"),
                    ),
                    (
                        "- 策略/执行/工具/部署: strategy={strategy}, execution={execution}, "
                        "tool_health={tool_health}, api_health={api_health}"
                    ).format(
                        strategy=strategy_state.get("status", "unknown"),
                        execution=execution.get("status", "unknown"),
                        tool_health=tool_health.get("status", "unknown"),
                        api_health=deployment.get("api_health", "unknown"),
                    ),
                ]
            )
            if missing:
                world_model_lines.append(
                    "- missing_data: " + ", ".join(str(item) for item in missing[:12])
                )
            if decision:
                world_model_lines.append(
                    (
                        "- 场景决策 decision: selected_action_id={selected}, score={score}, "
                        "policy_status={policy_status}, review_after={review_after}"
                    ).format(
                        selected=decision.get("selected_action_id", "unknown"),
                        score=decision.get("selected_score", "n/a"),
                        policy_status=decision.get("policy_status", "unknown"),
                        review_after=decision.get("review_after", "n/a"),
                    )
                )
            # Candidate actions, scenarios, portfolio recommendations, and
            # source references remain in the persisted report blocks/trace for
            # audit. The default Agent answer must foreground the market
            # conclusion rather than dumping operator internals into chat.
            world_model_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "strategy_library_search":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict):
                continue
            strategy_library_lines.extend(
                [
                    f"- 来源: {payload.get('source', 'unknown')}",
                    f"- 记忆证据数: {payload.get('memory_count', 0)}",
                ]
            )
            items = payload.get("items")
            items = items if isinstance(items, list) else []
            if not items:
                strategy_library_lines.append("- 未找到匹配的策略经验。")
            for item in items[:10]:
                if not isinstance(item, dict):
                    continue
                strategy_library_lines.append(
                    ("- {strategy} | 证据: {evidence} 条，pass={passed}，fail={failed}").format(
                        strategy=item.get("strategy_key", "unknown"),
                        evidence=item.get("evidence_count", 0),
                        passed=item.get("passed_count", 0),
                        failed=item.get("failed_count", 0),
                    )
                )
                best = item.get("best")
                best = best if isinstance(best, dict) else {}
                if best:
                    strategy_library_lines.append(
                        (
                            "- 最佳证据: memory={memory}, experiment={experiment}, "
                            "backtest={backtest}, winner={winner}"
                        ).format(
                            memory=best.get("memory_id", "n/a"),
                            experiment=best.get("experiment_id", "n/a"),
                            backtest=best.get("backtest_id", "n/a"),
                            winner=best.get("variant_id", "n/a"),
                        )
                    )
                    strategy_library_lines.append(
                        (
                            "- 指标: 收益={return_pct}%, 回撤={drawdown}%, "
                            "交易={trades}, score={score}"
                        ).format(
                            return_pct=best.get("total_return_pct", "n/a"),
                            drawdown=best.get("max_drawdown_pct", "n/a"),
                            trades=best.get("trade_count", "n/a"),
                            score=best.get("score", "n/a"),
                        )
                    )
                failure_reasons = item.get("failure_reasons")
                if isinstance(failure_reasons, list) and failure_reasons:
                    strategy_library_lines.append(
                        "- 失败原因: " + ", ".join(str(value) for value in failure_reasons)
                    )
                next_experiments = item.get("next_experiments")
                if isinstance(next_experiments, list) and next_experiments:
                    strategy_library_lines.append(f"- 下一轮: {next_experiments[0]}")
                source_memory_ids = item.get("source_memory_ids")
                if isinstance(source_memory_ids, list) and source_memory_ids:
                    strategy_library_lines.append(
                        "- 来源记忆: " + ", ".join(str(value) for value in source_memory_ids)
                    )
            strategy_library_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_market_klines":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            market = payload.get("market", {})
            market = market if isinstance(market, dict) else {}
            nested_calls = payload.get("tool_calls", [])
            nested_tools: list[str] = []
            if isinstance(nested_calls, list):
                nested_tools = [
                    str(call.get("tool", ""))
                    for call in nested_calls
                    if isinstance(call, dict) and call.get("tool")
                ]
            bitpro_lines.extend(
                [
                    f"- 合同版本: {payload.get('contract_version', 'unknown')}",
                    f"- 工具顺序: {', '.join(nested_tools) if nested_tools else 'n/a'}",
                    f"- 交易所: {market.get('exchange', 'n/a')}",
                    f"- 标的: {market.get('symbol', 'unknown')}",
                    f"- 周期: {market.get('timeframe', 'n/a')}",
                    f"- K线数量: {len(payload.get('candles', []))}",
                    "",
                ]
            )
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_backtest_list_results":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            result_filter = payload.get("filter")
            result_filter = result_filter if isinstance(result_filter, dict) else {}
            min_return = result_filter.get("min_total_return_pct")
            bitpro_backtest_lines.extend(
                [
                    (
                        "- 口径: total_return_pct，实际回测总收益；"
                        "不使用 annual_return_pct/年化收益替代"
                    ),
                    (
                        f"- 过滤: total_return_pct > {min_return}%"
                        if min_return is not None
                        else "- 过滤: 未设置收益阈值"
                    ),
                    f"- 命中数量: {payload.get('result_count', 0)}",
                ]
            )
            results = payload.get("results")
            results = results if isinstance(results, list) else []
            if not results:
                bitpro_backtest_lines.append("- 没有匹配的 BitPro 回测结果。")
            for row in results[:20]:
                if not isinstance(row, dict):
                    continue
                bitpro_backtest_lines.append(
                    (
                        "- result #{id}, strategy #{strategy_id}: {name}; "
                        "收益 {total_return_pct}%, 年化 {annual_return_pct}%, "
                        "回撤 {max_drawdown_pct}%, 夏普 {sharpe_ratio}, "
                        "胜率 {win_rate_pct}%, 交易 {trade_count}, 区间 {start_date} 至 {end_date}"
                    ).format(
                        id=row.get("id", "n/a"),
                        strategy_id=row.get("strategy_id", "n/a"),
                        name=row.get("strategy_name", "n/a"),
                        total_return_pct=row.get("total_return_pct", "n/a"),
                        annual_return_pct=row.get("annual_return_pct", "n/a"),
                        max_drawdown_pct=row.get("max_drawdown_pct", "n/a"),
                        sharpe_ratio=row.get("sharpe_ratio", "n/a"),
                        win_rate_pct=row.get("win_rate_pct", "n/a"),
                        trade_count=row.get("trade_count", "n/a"),
                        start_date=row.get("start_date", "n/a"),
                        end_date=row.get("end_date", "n/a"),
                    )
                )
            bitpro_backtest_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_backtest_get_job":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            result = payload.get("backtest_result")
            if not isinstance(result, dict):
                continue
            job = payload.get("job")
            job = job if isinstance(job, dict) else {}
            metrics = result.get("metrics")
            metrics = metrics if isinstance(metrics, dict) else {}
            progress = job.get("percent", job.get("progress", "n/a"))
            bitpro_backtest_lines.extend(
                [
                    ("- 口径: total_return_pct，实际回测总收益；与 BitPro 回测结果页面同源"),
                    ("- 回测任务: job={job_id}, status={status}, progress={progress}%").format(
                        job_id=job.get("job_id", job.get("id", "n/a")),
                        status=job.get("status", "n/a"),
                        progress=progress,
                    ),
                    (
                        "- result #{id}, strategy #{strategy_id}: {name}; "
                        "状态 {status}, 周期 {timeframe}, 区间 {start_date} 至 {end_date}"
                    ).format(
                        id=result.get("id", "n/a"),
                        strategy_id=result.get("strategy_id", "n/a"),
                        name=result.get("strategy_name", "n/a"),
                        status=result.get("status", "n/a"),
                        timeframe=result.get("timeframe", "n/a"),
                        start_date=result.get("start_date", "n/a"),
                        end_date=result.get("end_date", "n/a"),
                    ),
                    "",
                    "### 核心指标",
                    f"- 初始资金: {metrics.get('initial_capital', 'n/a')}",
                    f"- 最终资金: {metrics.get('final_capital', 'n/a')}",
                    f"- 收益: {metrics.get('total_return_pct', 'n/a')}%",
                    f"- 年化收益: {metrics.get('annual_return_pct', 'n/a')}%",
                    f"- 最大回撤: {metrics.get('max_drawdown_pct', 'n/a')}%",
                    f"- 夏普: {metrics.get('sharpe_ratio', 'n/a')}",
                    f"- 胜率: {metrics.get('win_rate_pct', 'n/a')}%",
                    f"- 盈亏比: {metrics.get('profit_factor', 'n/a')}",
                    f"- 交易次数: {metrics.get('trade_count', 'n/a')}",
                    "",
                    "### 数据样本",
                ]
            )
            summary = payload.get("artifact_summary")
            summary = summary if isinstance(summary, dict) else {}
            artifact_labels = {
                "equity_curve": "权益曲线",
                "trades": "交易",
                "orders": "订单",
                "fills": "成交",
                "drawdown_series": "回撤序列",
            }
            for key, label in artifact_labels.items():
                info = summary.get(key)
                info = info if isinstance(info, dict) else {}
                if not info:
                    continue
                state = "可用" if info.get("available") else "不可用"
                bitpro_backtest_lines.append(
                    ("- {label}: {state}，{count} 条，展示 {sample_count} 条样本").format(
                        label=label,
                        state=state,
                        count=info.get("count", 0),
                        sample_count=info.get("sample_count", 0),
                    )
                )
            bitpro_backtest_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_backtest_get_result":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            result = payload.get("result")
            result = result if isinstance(result, dict) else {}
            metrics = result.get("metrics")
            metrics = metrics if isinstance(metrics, dict) else {}
            bitpro_backtest_detail_lines.extend(
                [
                    (
                        "- result #{id}, strategy #{strategy_id}: {name}; "
                        "状态 {status}, 标的 {symbol}, 周期 {timeframe}, "
                        "区间 {start_date} 至 {end_date}"
                    ).format(
                        id=result.get("id", payload.get("backtest_id", "n/a")),
                        strategy_id=result.get("strategy_id", "n/a"),
                        name=result.get("strategy_name", "n/a"),
                        status=result.get("status", "n/a"),
                        symbol=result.get("symbol", "n/a"),
                        timeframe=result.get("timeframe", "n/a"),
                        start_date=result.get("start_date", "n/a"),
                        end_date=result.get("end_date", "n/a"),
                    ),
                    "",
                    "### 核心指标",
                    f"- 收益: {metrics.get('total_return_pct', 'n/a')}%",
                    f"- 最大回撤: {metrics.get('max_drawdown_pct', 'n/a')}%",
                    f"- 夏普: {metrics.get('sharpe_ratio', 'n/a')}",
                    f"- 胜率: {metrics.get('win_rate_pct', 'n/a')}%",
                    f"- 交易次数: {metrics.get('trade_count', 'n/a')}",
                    "",
                    "### 数据样本",
                ]
            )
            summary = payload.get("artifact_summary")
            summary = summary if isinstance(summary, dict) else {}
            artifact_labels = {
                "equity_curve": "权益曲线",
                "trades": "交易",
                "orders": "订单",
                "fills": "成交",
                "drawdown_series": "回撤序列",
            }
            for key, label in artifact_labels.items():
                info = summary.get(key)
                info = info if isinstance(info, dict) else {}
                state = "可用" if info.get("available") else "不可用"
                bitpro_backtest_detail_lines.append(
                    ("- {label}: {state}，{count} 条，展示 {sample_count} 条样本").format(
                        label=label,
                        state=state,
                        count=info.get("count", 0),
                        sample_count=info.get("sample_count", 0),
                    )
                )
            bitpro_backtest_detail_lines.append("")
        paper_tool_names = {
            "bitpro_paper_dashboard",
            "bitpro_paper_strategy_performance",
            "bitpro_paper_events",
            "bitpro_paper_equity_curve",
            "bitpro_paper_monitor_snapshot",
        }
        has_paper_performance_matrix = any(
            str(getattr(record, "tool_name", "")) == "bitpro_paper_strategy_performance"
            for record in tool_calls
        )
        if not has_paper_performance_matrix and any(
            str(getattr(record, "tool_name", "")) in paper_tool_names for record in tool_calls
        ):
            summary = _paper_monitor_conclusion(final_message, tool_calls)
            if summary:
                bitpro_paper_lines.extend([f"- 结论: {summary}", ""])
        rendered_paper_dashboard = False
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_paper_strategy_performance":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            strategies = payload.get("strategies")
            strategies = strategies if isinstance(strategies, list) else []
            unavailable = payload.get("unavailable_strategies")
            unavailable = unavailable if isinstance(unavailable, list) else []
            summary = payload.get("performance_summary")
            summary = summary if isinstance(summary, dict) else {}
            comparable_count = summary.get("comparable_count", len(strategies))
            reported_total = summary.get("reported_total", len(strategies) + len(unavailable))
            ranking_status = summary.get("ranking_status", "partial")
            top = strategies[0] if strategies and isinstance(strategies[0], dict) else {}
            if ranking_status == "complete" and top:
                conclusion = (
                    "已完成全部 {total} 个运行策略的同口径比较，#{strategy_id} "
                    "{name} 以 {return_pct}% 暂列第一。"
                ).format(
                    total=reported_total,
                    strategy_id=top.get("strategy_id", "n/a"),
                    name=top.get("strategy_name", "n/a"),
                    return_pct=top.get("return_pct", "n/a"),
                )
            elif top:
                conclusion = (
                    "目前仅 {comparable}/{total} 个运行策略具备身份匹配的模拟盘收益证据；"
                    "#{strategy_id} 在可比样本中暂列第一，但不能断言它是全量最优。"
                ).format(
                    comparable=comparable_count,
                    total=reported_total,
                    strategy_id=top.get("strategy_id", "n/a"),
                )
            else:
                conclusion = "当前没有策略具备身份匹配且含收益指标的模拟盘证据，无法生成排名。"
            paper_performance_lines.extend(
                [
                    "## 结论",
                    "",
                    conclusion,
                    "",
                    "## 策略比较",
                    "",
                    "| 排名 | 策略 | 收益率 | 最大回撤 | Sharpe |",
                    "|---:|---|---:|---:|---:|",
                ]
            )
            for strategy in strategies[:10]:
                if not isinstance(strategy, dict):
                    continue
                paper_performance_lines.append(
                    "| {rank} | #{strategy_id} {name} | {return_pct}% | "
                    "{drawdown}% | {sharpe} |".format(
                        rank=strategy.get("rank", "-"),
                        strategy_id=strategy.get("strategy_id", "n/a"),
                        name=strategy.get("strategy_name", "n/a"),
                        return_pct=strategy.get("return_pct", "n/a"),
                        drawdown=strategy.get("max_drawdown_pct", "n/a"),
                        sharpe=strategy.get("sharpe_ratio", "n/a"),
                    )
                )
            if not strategies:
                paper_performance_lines.append("| - | 暂无可比策略 | - | - | - |")
            paper_performance_lines.extend(
                [
                    "",
                    "## 风险与数据缺口",
                    "",
                    f"- 证据覆盖：{comparable_count}/{reported_total}，"
                    f"排名状态：{'完整' if ranking_status == 'complete' else '部分覆盖'}。",
                ]
            )
            if unavailable:
                missing_ids = [
                    str(item.get("strategy_id", "n/a"))
                    for item in unavailable
                    if isinstance(item, dict)
                ]
                paper_performance_lines.append(
                    "- 暂不可比策略：" + "、".join(missing_ids[:12]) + "。"
                )
            paper_performance_lines.extend(
                [
                    "- 仅采用 requested/returned strategy_id 一致的当前模拟盘证据；"
                    "回测结果不参与本排名。",
                    "",
                    "## 下一步",
                    "",
                    (
                        "- 补齐不可比策略的独立 dashboard/绩效接口后重新运行全量排名。"
                        if ranking_status != "complete"
                        else "- 继续按相同口径定期复查收益、回撤和 Sharpe 的变化。"
                    ),
                    "",
                ]
            )
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_paper_dashboard":
                continue
            if has_paper_performance_matrix:
                continue
            if paper_strategy_comparison and rendered_paper_dashboard:
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            rendered_paper_dashboard = True
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
            running_items = running.get("items")
            running_items = running_items if isinstance(running_items, list) else []
            running_total = running.get("total", len(running_items))
            monitor = payload.get("monitor_summary")
            monitor = monitor if isinstance(monitor, dict) else {}
            bitpro_paper_lines.extend(
                [
                    f"- Dashboard 范围: {scope.get('dashboard_scope', 'unknown')}",
                    (
                        "- 当前 dashboard: strategy_id={strategy_id}, {name}, "
                        "state={state}, mode={mode}, uptime={uptime}"
                    ).format(
                        strategy_id=system.get("strategy_id", "n/a"),
                        name=system.get("strategy", "n/a"),
                        state=system.get("state", "n/a"),
                        mode=system.get("mode", "n/a"),
                        uptime=system.get("uptime", "n/a"),
                    ),
                    (
                        "- 当前 dashboard 绩效: equity={equity}, total_pnl_pct={pnl}%, "
                        "sharpe={sharpe}, max_drawdown={drawdown}%"
                    ).format(
                        equity=equity.get("current", "n/a"),
                        pnl=performance.get("total_pnl_pct", "n/a"),
                        sharpe=performance.get("sharpe_ratio", "n/a"),
                        drawdown=performance.get("max_drawdown", "n/a"),
                    ),
                ]
            )
            if running_items or running_total:
                state = "complete"
                if isinstance(running_total, int) and running_total > len(running_items):
                    state = "truncated"
                bitpro_paper_lines.append(
                    f"- 运行策略覆盖: listed={len(running_items)}, total={running_total}, {state}"
                )
            if monitor:
                inventory = monitor.get("running_inventory")
                inventory = inventory if isinstance(inventory, dict) else {}
                bitpro_paper_lines.append(f"- 监控结论: {monitor.get('mode', 'unknown')}")
                alerts = monitor.get("alerts")
                alerts = alerts if isinstance(alerts, list) else []
                for alert in alerts[:3]:
                    if not isinstance(alert, dict):
                        continue
                    bitpro_paper_lines.append(
                        "- 告警 {level}/{code}: {message}".format(
                            level=alert.get("level", "info"),
                            code=alert.get("code", "unknown"),
                            message=alert.get("message", "n/a"),
                        )
                    )
                data_gaps = monitor.get("data_gaps")
                data_gaps = data_gaps if isinstance(data_gaps, list) else []
                for gap in data_gaps[:3]:
                    bitpro_paper_lines.append(f"- 数据缺口: {gap}")
            bitpro_paper_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_paper_events":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            summary = payload.get("event_summary")
            summary = summary if isinstance(summary, dict) else {}
            events = payload.get("events")
            events = events if isinstance(events, list) else []
            bitpro_paper_lines.extend(
                [
                    (
                        "- 事件: strategy_id={strategy_id}, count={count}, "
                        "errors={errors}, latest={latest}"
                    ).format(
                        strategy_id=_paper_strategy_id(payload),
                        count=summary.get("count", len(events)),
                        errors=summary.get("error_count", 0),
                        latest=summary.get("latest_event_at", "n/a"),
                    ),
                ]
            )
            for event in events:
                if not isinstance(event, dict):
                    continue
                if str(event.get("level", "")).lower() != "error":
                    continue
                bitpro_paper_lines.append(
                    "- 最近错误: {id} {level}/{type}: {message} ({timestamp})".format(
                        id=event.get("id", "n/a"),
                        level=event.get("level", "info"),
                        type=event.get("type", "event"),
                        message=event.get("message", "n/a"),
                        timestamp=event.get("timestamp", "n/a"),
                    )
                )
                break
            bitpro_paper_lines.append("")
        paper_equity_payloads = [
            getattr(record, "output_json", {})
            for record in tool_calls
            if getattr(record, "tool_name", "") == "bitpro_paper_equity_curve"
            and isinstance(getattr(record, "output_json", {}), dict)
            and getattr(record, "output_json", {}).get("status") == "ok"
        ]
        if paper_strategy_comparison and paper_equity_payloads:
            strategy_ids = sorted(
                str(_paper_strategy_id(payload)) for payload in paper_equity_payloads
            )
            bitpro_paper_lines.extend(
                [
                    "- 比较数据: 已读取 {count} 条逐策略权益曲线（策略 {strategy_ids}）。".format(
                        count=len(paper_equity_payloads),
                        strategy_ids=", ".join(strategy_ids),
                    ),
                    (
                        "- 排名状态: 不展示逐工具原始曲线；在 BitPro 提供可比的逐策略收益/回撤前，"
                        "不生成全量收益排行。"
                    ),
                    "",
                ]
            )
        else:
            for payload in paper_equity_payloads:
                summary = payload.get("equity_summary")
                summary = summary if isinstance(summary, dict) else {}
                points = payload.get("equity_curve")
                points = points if isinstance(points, list) else []
                bitpro_paper_lines.extend(
                    [
                        (
                            "- 权益曲线: strategy_id={strategy_id}, points={count}, "
                            "latest_at={latest_at}, latest_equity={latest}, "
                            "latest_drawdown={latest_dd}%, max_drawdown={max_dd}%"
                        ).format(
                            strategy_id=_paper_strategy_id(payload),
                            count=summary.get("count", len(points)),
                            latest_at=summary.get("latest_at", "n/a"),
                            latest=summary.get("latest_equity", "n/a"),
                            latest_dd=summary.get("latest_drawdown_pct", "n/a"),
                            max_dd=summary.get("max_drawdown_pct", "n/a"),
                        ),
                    ]
                )
                bitpro_paper_lines.append("")
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_paper_monitor_snapshot":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            metrics = payload.get("metrics")
            metrics = metrics if isinstance(metrics, dict) else {}
            drift = payload.get("drift")
            drift = drift if isinstance(drift, dict) else {}
            bitpro_paper_lines.extend(
                [
                    (
                        "- 监控快照: {snapshot_id}, strategy_id={strategy_id}, previous={previous}"
                    ).format(
                        snapshot_id=payload.get("snapshot_id", "n/a"),
                        strategy_id=_paper_strategy_id(payload),
                        previous=payload.get("previous_snapshot_id", "none"),
                    ),
                    (
                        "- 当前指标: equity={equity}, total_pnl={pnl}%, "
                        "max_drawdown={drawdown}%, errors={errors}"
                    ).format(
                        equity=metrics.get("latest_equity", "n/a"),
                        pnl=metrics.get("total_pnl_pct", "n/a"),
                        drawdown=metrics.get("max_drawdown_pct", "n/a"),
                        errors=metrics.get("error_count", "n/a"),
                    ),
                    (
                        "- 快照漂移: mode={mode}, equity_delta={equity_delta}, "
                        "pnl_delta={pnl_delta}%, drawdown_delta={drawdown_delta}%, "
                        "error_delta={error_delta}"
                    ).format(
                        mode=drift.get("mode", "unknown"),
                        equity_delta=drift.get("equity_delta", "n/a"),
                        pnl_delta=drift.get("total_pnl_delta_pct", "n/a"),
                        drawdown_delta=drift.get("max_drawdown_delta_pct", "n/a"),
                        error_delta=drift.get("error_count_delta", "n/a"),
                    ),
                ]
            )
            alerts = drift.get("alerts")
            alerts = alerts if isinstance(alerts, list) else []
            for alert in alerts[:3]:
                if not isinstance(alert, dict):
                    continue
                bitpro_paper_lines.append(
                    "- 告警 {level}/{code}: {message}".format(
                        level=alert.get("level", "info"),
                        code=alert.get("code", "unknown"),
                        message=alert.get("message", "n/a"),
                    )
                )
            data_gaps = drift.get("data_gaps")
            data_gaps = data_gaps if isinstance(data_gaps, list) else []
            for gap in data_gaps[:3]:
                bitpro_paper_lines.append(f"- 数据缺口: {gap}")
            bitpro_paper_lines.append("")
        if any(
            str(getattr(record, "tool_name", "")) == "bitpro_live_order_history"
            for record in tool_calls
        ):
            summary = _compact_final_message(final_message)
            if summary:
                bitpro_live_order_lines.extend([f"- 结论: {summary}", ""])
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_live_order_history":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            orders = payload.get("orders")
            orders = orders if isinstance(orders, list) else []
            summary = payload.get("order_summary")
            summary = summary if isinstance(summary, dict) else {}
            bitpro_live_order_lines.extend(
                [
                    (
                        "- 来源: exchange={exchange}, symbol={symbol}, limit={limit}, "
                        "订单数量: {count}"
                    ).format(
                        exchange=payload.get("exchange", "okx"),
                        symbol=payload.get("symbol") or "all",
                        limit=payload.get("limit", "n/a"),
                        count=summary.get("count", len(orders)),
                    ),
                ]
            )
            if not orders:
                bitpro_live_order_lines.append("- 最近订单: 暂无 BitPro 返回的实盘历史订单。")
                bitpro_live_order_lines.append("")
                continue
            latest = orders[0] if isinstance(orders[0], dict) else {}
            bitpro_live_order_lines.append("- 最近订单: " + _format_live_order_line(latest))
            bitpro_live_order_lines.append("")
        if any(
            str(getattr(record, "tool_name", "")) == "bitpro_live_strategy_performance"
            for record in tool_calls
        ):
            summary = _compact_final_message(final_message)
            if summary:
                bitpro_live_strategy_lines.extend([f"- 结论: {summary}", ""])
        for record in tool_calls:
            if getattr(record, "tool_name", "") != "bitpro_live_strategy_performance":
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                continue
            strategies = payload.get("strategies")
            strategies = strategies if isinstance(strategies, list) else []
            performance_summary = payload.get("performance_summary")
            performance_summary = (
                performance_summary if isinstance(performance_summary, dict) else {}
            )
            bitpro_live_strategy_lines.extend(
                [
                    (
                        "- 来源: exchange={exchange}, limit={limit}, 排名口径={rank_basis}, "
                        "策略数量: {count}"
                    ).format(
                        exchange=payload.get("exchange", "okx"),
                        limit=payload.get("limit", "n/a"),
                        rank_basis=payload.get("rank_basis", "return_pct"),
                        count=performance_summary.get("count", len(strategies)),
                    ),
                ]
            )
            if not strategies:
                bitpro_live_strategy_lines.append(
                    "- 最高策略: 暂无 BitPro 返回的实盘策略收益数据。"
                )
                bitpro_live_strategy_lines.append("")
                continue
            top = strategies[0] if isinstance(strategies[0], dict) else {}
            bitpro_live_strategy_lines.append("- 最高策略: " + _format_live_strategy_top_line(top))
            for index, strategy in enumerate(strategies[:5], start=1):
                if not isinstance(strategy, dict):
                    continue
                bitpro_live_strategy_lines.append(
                    f"- {index}. {_format_live_strategy_rank_line(strategy)}"
                )
            bitpro_live_strategy_lines.append("")
        lifecycle_tool_names = {
            "bitpro_strategy_search",
            "bitpro_strategy_generate",
            "bitpro_strategy_create",
            "bitpro_strategy_update",
            "bitpro_backtest_start_job",
            "bitpro_backtest_get_job",
            "bitpro_paper_configure",
            "bitpro_paper_start",
            "bitpro_paper_pause",
            "bitpro_paper_resume",
            "bitpro_paper_stop",
        }
        for record in tool_calls:
            tool_name = str(getattr(record, "tool_name", ""))
            if bitpro_backtest_lines or bitpro_backtest_detail_lines:
                continue
            if tool_name not in lifecycle_tool_names:
                continue
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict):
                continue
            if payload.get("status") == "denied":
                missing_fields = payload.get("missing_fields")
                missing_fields = missing_fields if isinstance(missing_fields, list) else []
                line = ("- {tool}: denied, reason={reason}").format(
                    tool=tool_name,
                    reason=payload.get("denial_reason", "unknown"),
                )
                if missing_fields:
                    line += ", missing_fields=" + ", ".join(str(field) for field in missing_fields)
                governance_lines.append(line)
                continue
            nested_tools = _nested_bitpro_tools(payload)
            line = f"- {tool_name}: {payload.get('status', 'unknown')}"
            strategy = payload.get("strategy")
            if isinstance(strategy, dict):
                line += f", strategy={strategy.get('id', strategy.get('name', 'n/a'))}"
            job = payload.get("job")
            if isinstance(job, dict):
                line += f", job={job.get('job_id', job.get('id', 'n/a'))}"
                if job.get("status"):
                    line += f", job_status={job.get('status')}"
            paper = payload.get("paper")
            if isinstance(paper, dict):
                line += f", paper={paper.get('instance_id', paper.get('id', 'n/a'))}"
                if paper.get("status"):
                    line += f", paper_status={paper.get('status')}"
            if nested_tools:
                line += f", tools={', '.join(nested_tools)}"
            bitpro_lifecycle_lines.append(line)
        if bitpro_lifecycle_lines:
            bitpro_lifecycle_lines.append("")
        for record in tool_calls:
            payload = getattr(record, "output_json", {})
            if not isinstance(payload, dict):
                continue
            is_unavailable = payload.get("status") == "unavailable"
            is_error = payload.get("execution_status") in {"timeout", "error"}
            if not is_unavailable and not is_error:
                continue
            error = payload.get("error")
            error = error if isinstance(error, dict) else {}
            policy = payload.get("policy")
            policy = policy if isinstance(policy, dict) else {}
            unavailable_lines.append(
                "- {tool}: 数据暂不可用，原因 {reason}，来源 {source}".format(
                    tool=getattr(record, "tool_name", "unknown"),
                    reason=error.get("message") or payload.get("unavailable_reason", "unknown"),
                    source=policy.get("source_of_truth", "unknown"),
                )
            )
        if unavailable_lines:
            unavailable_lines.append("")
        if paper_strategy_comparison:
            # Paper performance must not be drowned out by unrelated historical
            # backtest rows. The tool evidence remains persisted for audit.
            bitpro_backtest_lines.clear()
            bitpro_backtest_detail_lines.clear()
        if has_paper_performance_matrix:
            # Inventory/tool-preflight calls remain in Trace, but they are not
            # a user-facing lifecycle result for a read-only comparison.
            bitpro_lifecycle_lines.clear()
        sections: list[str] = []
        if unavailable_lines:
            sections.extend(["## 数据暂不可用", "", *unavailable_lines])
        if governance_lines:
            sections.extend(["## 风控治理", "", *governance_lines, ""])
        market_tool_sections = bool(
            market_summary_lines or ticker_lines or candle_lines or compare_lines
        )
        final_summary = _compact_final_message(final_message)
        if world_model_lines and not final_summary:
            final_summary = _summary_from_markdown_table(
                [line.strip() for line in str(final_message or "").splitlines() if line.strip()],
                max_chars=240,
            )
        if (market_tool_sections or world_model_lines) and final_summary:
            sections.extend(["## 总结", "", f"- {final_summary}", ""])
        if market_summary_lines:
            sections.extend(["## 市场热度总结", "", *market_summary_lines])
        if ticker_lines:
            sections.extend(["## 单标的行情", "", *ticker_lines])
        if candle_lines:
            sections.extend(["## K线趋势特征", "", *candle_lines])
        if compare_lines:
            sections.extend(["## 多标的强弱比较", "", *compare_lines])
        if intelligence_lines:
            sections.extend(["## 市场情报", "", *intelligence_lines])
        if world_model_lines:
            sections.extend(["## 全局世界模型", "", *world_model_lines])
        if strategy_library_lines:
            sections.extend(["## 策略库记忆", "", *strategy_library_lines])
        if bitpro_lines:
            sections.extend(["## BitPro MCP K线直连", "", *bitpro_lines])
        if bitpro_backtest_lines:
            sections.extend(["## BitPro 回测结果", "", *bitpro_backtest_lines])
        if bitpro_backtest_detail_lines:
            sections.extend(["## BitPro 回测详情", "", *bitpro_backtest_detail_lines])
        if bitpro_paper_lines:
            sections.extend(["## BitPro 模拟盘状态", "", *bitpro_paper_lines])
        if paper_performance_lines:
            sections.extend(paper_performance_lines)
        if bitpro_live_order_lines:
            sections.extend(["## BitPro 实盘订单", "", *bitpro_live_order_lines])
        if bitpro_live_strategy_lines:
            sections.extend(["## BitPro 实盘策略收益", "", *bitpro_live_strategy_lines])
        if bitpro_lifecycle_lines:
            sections.extend(["## BitPro 策略生命周期", "", *bitpro_lifecycle_lines])
        has_bitpro_evidence_report = bool(
            bitpro_backtest_lines
            or bitpro_backtest_detail_lines
            or bitpro_paper_lines
            or paper_performance_lines
            or bitpro_live_order_lines
            or bitpro_live_strategy_lines
        )
        citations = [] if has_bitpro_evidence_report else _citations_from_tool_calls(tool_calls)
        if citations:
            for index, citation in enumerate(citations, start=1):
                citation_lines.append(
                    "{index}. {title} - {source_path}#{chunk_index} (score {score})".format(
                        index=index,
                        title=citation.get("title") or "Knowledge",
                        source_path=citation.get("source_path", "unknown"),
                        chunk_index=citation.get("chunk_index", 0),
                        score=citation.get("score", "n/a"),
                    )
                )
            citation_lines.append("")
            sections.extend(["## 引用来源", "", *citation_lines])
        if not sections:
            return final_message
        if (
            bitpro_backtest_lines
            or bitpro_backtest_detail_lines
            or bitpro_paper_lines
            or paper_performance_lines
            or bitpro_live_order_lines
            or world_model_lines
        ):
            return "\n".join(sections)
        return "\n".join([*sections, final_message])


def _memory_tags_from_args(args: dict[str, Any]) -> list[str] | None:
    """Normalize planner-supplied tags; untrusted input, so bound and clean it."""
    raw = args.get("tags")
    if not isinstance(raw, list):
        return None
    tags = [str(tag).strip().casefold()[:32] for tag in raw if str(tag).strip()]
    return tags[:8] or None


def _bounded_unit_interval(value: Any, default: Decimal) -> Decimal:
    """Clamp untrusted numeric memory weights into [0, 1] with a fixed default."""
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default
    if parsed != parsed or parsed in (Decimal("Infinity"), Decimal("-Infinity")):
        return default
    return max(Decimal("0.0000"), min(Decimal("1.0000"), parsed)).quantize(Decimal("0.0001"))


def _compact_final_message(value: object, *, max_chars: int = 240) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(raw_lines) > 4 or any("|" in line for line in raw_lines):
        return _compact_long_final_message(raw_lines, max_chars=max_chars)
    parts: list[str] = []
    for line in raw_lines:
        lowered = line.lower()
        if (
            "not investment advice" in lowered
            or "research output only" in lowered
            or "不构成投资建议" in line
        ):
            continue
        if "|" in line:
            continue
        if line.startswith("#"):
            continue
        while line.startswith(("-", "*")):
            line = line[1:].strip()
        if line:
            parts.append(line)
        if len(" ".join(parts)) >= max_chars:
            break
    summary = " ".join(parts).strip()
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "..."


def _paper_monitor_conclusion(final_message: object, tool_calls: list[Any]) -> str:
    """Keep a paper-ranking answer evidence-bound when BitPro omits its metrics."""
    if not _is_paper_strategy_comparison(final_message):
        return _compact_final_message(final_message)
    for record in tool_calls:
        if getattr(record, "tool_name", "") != "bitpro_paper_dashboard":
            continue
        payload = getattr(record, "output_json", {})
        if not isinstance(payload, dict):
            continue
        monitor = payload.get("monitor_summary")
        monitor = monitor if isinstance(monitor, dict) else {}
        data_gaps = monitor.get("data_gaps")
        data_gaps = data_gaps if isinstance(data_gaps, list) else []
        if any(
            "per-strategy" in str(gap).lower()
            and ("pnl" in str(gap).lower() or "drawdown" in str(gap).lower())
            for gap in data_gaps
        ):
            return (
                "暂无法比较全部运行策略的收益：BitPro 当前只提供当前 dashboard "
                "策略的绩效，运行策略清单不含逐策略收益或回撤。"
            )
    return _compact_final_message(final_message)


def _is_paper_strategy_comparison(final_message: object) -> bool:
    final_text = str(final_message or "")
    ranking_markers = ("排名", "排行", "哪个", "最好", "最优", "收益比较", "收益对比")
    return any(marker in final_text for marker in ranking_markers)


def _compact_long_final_message(lines: list[str], *, max_chars: int) -> str:
    for raw_line in lines:
        line = raw_line.strip()
        if not line or "|" in line:
            continue
        if set(line) <= {"-", ":", " "}:
            continue
        if line.startswith("#"):
            continue
        while line.startswith(("-", "*")):
            line = line[1:].strip()
        lower = line.lower()
        noisy_prefixes = ("**策略", "**模式", "**交易标的", "**时间框架", "策略**", "模式**")
        if lower.startswith(noisy_prefixes):
            continue
        if not any(marker in line for marker in ("结论", "核心", "建议", "风险", "异常")):
            continue
        if len(line) <= max_chars:
            return line
        return line[: max_chars - 1].rstrip() + "..."
    return ""


def _summary_from_markdown_table(lines: list[str], *, max_chars: int) -> str:
    """Turn a small Markdown metric table into one operator-facing sentence."""
    pairs: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if "|" not in line:
            continue
        cells = [_clean_markdown_cell(cell) for cell in line.strip("|").split("|")]
        if len(cells) < 2 or all(not cell for cell in cells):
            continue
        if all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        key, value = cells[0], cells[1]
        if key.lower() in {"指标", "item", "metric", "名称", "币种"}:
            continue
        if not key or not value:
            continue
        pairs.append(f"{key}：{value}")
        if len(pairs) >= 4:
            break
    summary = "；".join(pairs)
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "…"


def _clean_markdown_cell(value: str) -> str:
    return value.replace("**", "").replace("`", "").strip()


def _paper_strategy_id(payload: dict[str, Any]) -> object:
    strategy_id = payload.get("strategy_id")
    return "all" if strategy_id is None else strategy_id


def _format_live_order_line(order: dict[str, Any]) -> str:
    order_id = _order_value(order, "order_id", "id")
    symbol = _order_value(order, "symbol", "inst_id", "instId")
    side = _order_value(order, "side")
    status = _order_value(order, "status", "state")
    order_type = _order_value(order, "type", "order_type", "ordType")
    average = _order_value(order, "average", "avgPx", "avg_price")
    amount = _order_value(order, "amount", "qty", "sz")
    filled = _order_value(order, "filled", "filled_qty", "accFillSz")
    timestamp = _order_value(order, "timestamp", "created_at", "cTime", "uTime")
    source = _order_value(order, "bitpro_source_label", "source_strategy_name")
    return (
        f"{order_id} {symbol} {side} {status} | type={order_type}, "
        f"均价={average}, 委托量={amount}, 成交量={filled}, 时间={timestamp}, "
        f"策略来源={source}"
    )


def _format_live_strategy_top_line(strategy: dict[str, Any]) -> str:
    return (
        f"#{_strategy_value(strategy, 'strategy_id', 'id')} "
        f"{_strategy_value(strategy, 'strategy_name', 'name')} "
        f"收益率={_strategy_value(strategy, 'return_pct')}% "
        f"收益金额={_strategy_value(strategy, 'total_pnl', 'pnl')}"
    )


def _format_live_strategy_rank_line(strategy: dict[str, Any]) -> str:
    symbols = strategy.get("symbols")
    if isinstance(symbols, list):
        symbol_text = ",".join(str(symbol) for symbol in symbols if symbol is not None) or "n/a"
    else:
        symbol_text = str(symbols) if symbols is not None and str(symbols) else "n/a"
    status = _strategy_value(strategy, "status")
    workspace_status = _strategy_value(strategy, "workspace_status", "deployment_status")
    return (
        f"#{_strategy_value(strategy, 'strategy_id', 'id')} "
        f"{_strategy_value(strategy, 'strategy_name', 'name')} "
        f"status={status}/{workspace_status} symbols={symbol_text} "
        f"收益率={_strategy_value(strategy, 'return_pct')}% "
        f"收益金额={_strategy_value(strategy, 'total_pnl', 'pnl')} "
        f"account={_strategy_value(strategy, 'account_id')}"
    )


def _strategy_value(strategy: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = strategy.get(key)
        if value is not None and str(value) != "":
            return str(value)
    return "n/a"


def _order_value(order: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = order.get(key)
        if value is not None and str(value) != "":
            return str(value)
    return "n/a"


def _planner_observability(
    result: PlannerResult,
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    usage = _empty_usage()
    for call in result.model_calls:
        call_usage = call.usage.to_dict()
        for key in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            usage[key] = int(usage[key]) + int(call_usage[key])
        if call.usage.reported:
            usage["reported_requests"] = int(usage["reported_requests"]) + 1
    usage["request_count"] = len(result.model_calls)
    usage["unreported_requests"] = len(result.model_calls) - int(usage["reported_requests"])
    usage["reported"] = bool(usage["reported_requests"])

    tool_calls: list[dict[str, Any]] = []
    error_count = 0
    total_execution_ms = 0.0
    slowest: dict[str, Any] | None = None
    memory_reads: list[str] = []
    memory_writes: list[str] = []
    for record in result.tool_calls:
        output = record.output_json if isinstance(record.output_json, dict) else {}
        execution_ms = _safe_float(output.get("execution_ms"))
        execution_status = str(output.get("execution_status", "completed"))
        total_execution_ms += execution_ms
        if execution_status in {"error", "timeout", "denied", "unavailable"}:
            error_count += 1
        entry = {
            "tool_name": record.tool_name,
            "execution_status": execution_status,
            "execution_ms": execution_ms,
        }
        tool_calls.append(entry)
        if slowest is None or execution_ms > float(slowest["execution_ms"]):
            slowest = entry
        if record.tool_name == "memory_write":
            memory_id = output.get("memory_id")
            if isinstance(memory_id, str) and memory_id:
                memory_writes.append(memory_id)
        elif record.tool_name == "memory_search":
            raw_items = output.get("items")
            if isinstance(raw_items, list):
                memory_reads.extend(
                    str(item.get("id"))
                    for item in raw_items
                    if isinstance(item, dict) and item.get("id")
                )

    return {
        "schema_version": "agent-observability-v1",
        "provider": provider,
        "model": model,
        "model_calls": [call.to_dict() for call in result.model_calls],
        "usage": usage,
        "tools": {
            "call_count": len(tool_calls),
            "error_count": error_count,
            "total_execution_ms": round(total_execution_ms, 3),
            "slowest": slowest,
            "calls": tool_calls,
            # Harness-level per-tool latency/error/retry aggregates collected
            # across every planning iteration of this run.
            "telemetry": dict(result.tool_telemetry or {}),
        },
        "memory": {
            "read_ids": list(dict.fromkeys(memory_reads)),
            "write_ids": list(dict.fromkeys(memory_writes)),
            "read_count": len(memory_reads),
            "write_count": len(memory_writes),
        },
        "context": {
            "compactions": int(result.context_compactions),
            "history_tokens_last": int(result.history_tokens_last),
        },
        "private_reasoning_stored": False,
    }


def _empty_observability() -> dict[str, Any]:
    return {
        "schema_version": "agent-observability-v1",
        "provider": "provider_unavailable",
        "model": "",
        "model_calls": [],
        "usage": _empty_usage(),
        "tools": {
            "call_count": 0,
            "error_count": 0,
            "total_execution_ms": 0.0,
            "slowest": None,
            "calls": [],
            "telemetry": {},
        },
        "memory": {
            "read_ids": [],
            "write_ids": [],
            "read_count": 0,
            "write_count": 0,
        },
        "context": {
            "compactions": 0,
            "history_tokens_last": 0,
        },
        "private_reasoning_stored": False,
    }


def _empty_usage() -> dict[str, int | bool]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "request_count": 0,
        "reported_requests": 0,
        "unreported_requests": 0,
        "reported": False,
    }


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _reflection_summary(result: PlannerResult) -> str:
    names = [record.tool_name for record in result.tool_calls]
    if not names:
        return "planner completed without tool calls"
    return "planner completed with tools: " + ", ".join(names)


def _citations_from_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for record in tool_calls:
        tool_name = getattr(record, "tool_name", "")
        payload = getattr(record, "output_json", {})
        if tool_name in {"market_candles", "market.candles"} and isinstance(payload, dict):
            source = str(payload.get("data_source", ""))
            if source and source not in {"unavailable", "unknown"}:
                key = (f"{source}/market_candles", 0)
                if key not in seen:
                    seen.add(key)
                    citations.append(
                        {
                            "source_path": key[0],
                            "title": "OKX public market candles",
                            "chunk_index": 0,
                            "score": 1,
                            "content_preview": "",
                        }
                    )
            continue
        if tool_name not in {"rag_search", "rag.search"}:
            continue
        if not isinstance(payload, dict):
            continue
        hits = payload.get("hits", [])
        if not isinstance(hits, list):
            continue
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            source_path = str(hit.get("source_path", ""))
            chunk_index = int(hit.get("chunk_index", 0) or 0)
            key = (source_path, chunk_index)
            if not source_path or key in seen:
                continue
            seen.add(key)
            citations.append(
                {
                    "source_path": source_path,
                    "title": str(hit.get("title", "")),
                    "chunk_index": chunk_index,
                    "score": hit.get("score", 0),
                    "content_preview": str(hit.get("content", hit.get("content_preview", "")))[
                        :240
                    ],
                }
            )
    return citations[:5]


def _bitpro_trace_tool_name(tool_name: str) -> str:
    return {
        "bitpro_capabilities": "bitpro.capabilities",
        "bitpro_health": "bitpro.health",
        "market_klines": "bitpro.market_klines",
        "strategy_search": "bitpro.strategy_search",
        "strategy_get": "bitpro.strategy_get",
        "strategy_generate": "bitpro.strategy_generate",
        "strategy_create": "bitpro.strategy_create",
        "strategy_update": "bitpro.strategy_update",
        "backtest_start_job": "bitpro.backtest_start_job",
        "backtest_get_job": "bitpro.backtest_get_job",
        "backtest_list_results": "bitpro.backtest_list_results",
        "backtest_get_result": "bitpro.backtest_get_result",
        "paper_configure": "bitpro.paper_configure",
        "paper_start": "bitpro.paper_start",
        "paper_pause": "bitpro.paper_pause",
        "paper_resume": "bitpro.paper_resume",
        "paper_stop": "bitpro.paper_stop",
        "paper_dashboard": "bitpro.paper_dashboard",
        "paper_events": "bitpro.paper_events",
        "paper_equity_curve": "bitpro.paper_equity_curve",
        "trading_positions": "bitpro.live_positions",
        "trading_order_history": "bitpro.live_order_history",
        "live_strategies": "bitpro.live_strategy_performance",
    }.get(tool_name, "")


def _nested_bitpro_tools(payload: dict[str, Any]) -> list[str]:
    calls = payload.get("tool_calls", [])
    if not isinstance(calls, list):
        return []
    return [
        str(call.get("tool", "")) for call in calls if isinstance(call, dict) and call.get("tool")
    ]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_swap_inst_id(symbol: str) -> str:
    value = symbol.strip().upper().replace("_", "-").replace("/", "-")
    if not value:
        return "BTC-USDT-SWAP"
    if value.endswith("-SWAP"):
        return value
    if value.endswith("-USDT"):
        return f"{value}-SWAP"
    if "-" not in value:
        return f"{value}-USDT-SWAP"
    return f"{value}-SWAP"


def _normalize_okx_bar(bar: str) -> str:
    value = bar.strip()
    if not value:
        return "1H"
    if value.lower().endswith("h"):
        return f"{value[:-1]}H"
    if value.lower().endswith("d"):
        return f"{value[:-1]}D"
    return value


def _unique_symbols(symbols: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for symbol in symbols:
        value = symbol.strip()
        key = value.upper()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result[:6]


def _market_heat_summary(rows: list[Any]) -> dict[str, Any]:
    changes: list[tuple[str, Decimal]] = []
    for row in rows:
        inst_id = str(getattr(row, "inst_id", "unknown"))
        change = _as_decimal(getattr(row, "change_utc0_pct", "0"))
        changes.append((inst_id, change))
    if not changes:
        return {
            "sample_count": 0,
            "advancers_count": 0,
            "decliners_count": 0,
            "flat_count": 0,
            "advancers_pct": "0.000000",
            "decliners_pct": "0.000000",
            "average_change_pct": "0.000000",
            "median_change_pct": "0.000000",
            "heat_level": "unavailable",
            "top_gainer": "n/a",
            "top_loser": "n/a",
            "conclusion": "当前市场热度暂不可用，缺少可统计的 OKX SWAP ticker 样本。",
        }

    sample_count = len(changes)
    advancers = [(inst_id, change) for inst_id, change in changes if change > 0]
    decliners = [(inst_id, change) for inst_id, change in changes if change < 0]
    flat_count = sample_count - len(advancers) - len(decliners)
    total_change = sum((change for _, change in changes), Decimal("0"))
    average = total_change / Decimal(sample_count)
    median = _median_decimal([change for _, change in changes])
    advancers_pct = Decimal(len(advancers)) * Decimal("100") / Decimal(sample_count)
    decliners_pct = Decimal(len(decliners)) * Decimal("100") / Decimal(sample_count)
    top_gainer = max(changes, key=lambda item: item[1])
    top_loser = min(changes, key=lambda item: item[1])
    heat_level = _market_heat_level(
        average_change=average,
        advancers_pct=advancers_pct,
        decliners_pct=decliners_pct,
    )
    return {
        "sample_count": sample_count,
        "advancers_count": len(advancers),
        "decliners_count": len(decliners),
        "flat_count": flat_count,
        "advancers_pct": _decimal_text(advancers_pct),
        "decliners_pct": _decimal_text(decliners_pct),
        "average_change_pct": _decimal_text(average),
        "median_change_pct": _decimal_text(median),
        "heat_level": heat_level,
        "top_gainer": _format_heat_leader(top_gainer),
        "top_loser": _format_heat_leader(top_loser),
        "conclusion": _market_heat_conclusion(
            heat_level=heat_level,
            average_change=average,
            advancers_pct=advancers_pct,
            decliners_pct=decliners_pct,
        ),
    }


def _market_summary_report_lines(payload: dict[str, Any]) -> list[str]:
    heat = payload.get("heat_summary")
    heat = heat if isinstance(heat, dict) else _market_heat_summary([])
    lines = [
        f"- 结论: {heat.get('conclusion', '当前市场热度暂不可用。')}",
        (
            "- 样本: {sample_count} 个合约，上涨 {advancers_count} 个"
            "({advancers_pct}%)，下跌 {decliners_count} 个({decliners_pct}%)，"
            "平均涨跌幅 {average_change_pct}%"
        ).format(
            sample_count=heat.get("sample_count", 0),
            advancers_count=heat.get("advancers_count", 0),
            advancers_pct=heat.get("advancers_pct", "0.000000"),
            decliners_count=heat.get("decliners_count", 0),
            decliners_pct=heat.get("decliners_pct", "0.000000"),
            average_change_pct=heat.get("average_change_pct", "0.000000"),
        ),
        ("- 最强/最弱: {top_gainer} / {top_loser}").format(
            top_gainer=heat.get("top_gainer", "n/a"),
            top_loser=heat.get("top_loser", "n/a"),
        ),
        "",
        "### 异动榜",
    ]
    movers = payload.get("top_movers")
    movers = movers if isinstance(movers, list) else []
    if not movers:
        lines.append("- 当前无法获取实时 OKX 行情，未输出异动榜。")
        reason = payload.get("unavailable_reason")
        if isinstance(reason, str) and reason:
            lines.append(f"- 原因: {reason}")
        return lines
    for mover in movers[:10]:
        if not isinstance(mover, dict):
            continue
        lines.append(
            (
                "- {inst_id}: 最新价 {last}, UTC0 涨跌幅 {change_utc0_pct}%, "
                "24h 成交额 {volume_ccy_24h}"
            ).format(
                inst_id=mover.get("inst_id", "unknown"),
                last=mover.get("last", "n/a"),
                change_utc0_pct=mover.get("change_utc0_pct", "n/a"),
                volume_ccy_24h=mover.get("volume_ccy_24h", "n/a"),
            )
        )
    return lines


def _median_decimal(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _market_heat_level(
    *,
    average_change: Decimal,
    advancers_pct: Decimal,
    decliners_pct: Decimal,
) -> str:
    if average_change >= Decimal("1") and advancers_pct >= Decimal("55"):
        return "hot"
    if average_change >= Decimal("0.2") and advancers_pct >= Decimal("45"):
        return "warm"
    if average_change <= Decimal("-1") and decliners_pct >= Decimal("55"):
        return "risk_off"
    if average_change <= Decimal("-0.2") and decliners_pct >= Decimal("45"):
        return "cold"
    return "neutral"


def _market_heat_conclusion(
    *,
    heat_level: str,
    average_change: Decimal,
    advancers_pct: Decimal,
    decliners_pct: Decimal,
) -> str:
    label = {
        "hot": "偏热",
        "warm": "温和偏热",
        "neutral": "中性",
        "cold": "偏冷",
        "risk_off": "风险偏弱",
    }.get(heat_level, "不可用")
    average = _decimal_text(average_change)
    advancers = _decimal_text(advancers_pct)
    decliners = _decimal_text(decliners_pct)
    return f"{label}：样本平均涨跌幅 {average}% ，上涨占比 {advancers}% ，下跌占比 {decliners}% 。"


def _format_heat_leader(item: tuple[str, Decimal]) -> str:
    inst_id, change = item
    return f"{inst_id} ({_decimal_text(change)}%)"


def _strength_score(payload: dict[str, Any]) -> Decimal:
    return_pct = _as_decimal(payload.get("return_pct", "0"))
    close_position = _as_decimal(payload.get("close_position_pct", "0"))
    trend_bonus = {
        "up": Decimal("15"),
        "range": Decimal("0"),
        "down": Decimal("-15"),
    }.get(str(payload.get("trend_bias", "range")), Decimal("0"))
    return return_pct * Decimal("3") + close_position + trend_bonus


def _as_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _decimal_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.000001")))


def _emit(
    event_sink: Callable[[dict[str, Any]], None] | None,
    event: dict[str, Any],
) -> None:
    if event_sink is not None:
        event_sink(event)
