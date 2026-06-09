"""Observable Agent runtime used by API, CLI, and streaming endpoints.

This module is the runtime boundary for the HyperTrade Agent flow.
`AgentKernel` keeps one public interface (`run_chat`) while the internals look
like a small graph: classify intent, plan tools, check approval, execute tools,
reflect, and write the final report. Every graph node is persisted as trace so
the frontend harness and CLI can show what the Agent is doing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from hypertrade.agent.planner import AgentPlanner, PlannerResult, ToolExecutor
from hypertrade.backtest.service import BacktestService
from hypertrade.config import Settings, get_settings
from hypertrade.db import AgentRun, Database, TraceEvent
from hypertrade.live.service import LiveOrderIntentService
from hypertrade.market.analysis import summarize_candles
from hypertrade.market.client import OkxRestClient
from hypertrade.market.okx import OkxCandle
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.rag.service import RagService
from hypertrade.strategy.service import StrategyResearchService
from hypertrade.tools.registry import ToolRegistry


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
    ) -> None:
        self.db = db
        self._settings = settings
        self.provider_name = provider_name
        self.market = MarketRepository(db)
        self.memory = MemoryService(db)
        self.rag = RagService(db, knowledge_dir=knowledge_dir)
        self.tools = ToolRegistry.default()

    def run_chat(self, prompt: str) -> CompletedAgentRun:
        return self.run_chat_with_events(prompt)

    def run_chat_with_events(
        self,
        prompt: str,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> CompletedAgentRun:
        settings = self._settings if self._settings is not None else get_settings()
        run_id = self._create_run(prompt)
        _emit(event_sink, {"event": "run_started", "run_id": run_id, "status": "running"})
        try:
            # The first two graph nodes are intentionally lightweight. They make
            # a run observable before any LLM call or tool call can fail.
            self._graph_node(
                run_id,
                "intent_classify",
                {"prompt": prompt},
                {"intent": _classify_intent(prompt)},
                event_sink=event_sink,
            )
            provider = ProviderRuntime(settings).get_chat_provider(selected=self.provider_name)
            # Provider routing is isolated here: the planner can be DeepSeek,
            # OpenRouter, Qwen, etc., while all downstream tool execution stays
            # provider-agnostic.
            self._graph_node(
                run_id,
                "plan_tools",
                {"provider": self.provider_name or settings.active_chat_provider},
                {
                    "planner": provider.name if provider else "deterministic_fallback",
                    "model": provider.model if provider else "",
                },
                event_sink=event_sink,
            )
            if provider is not None:
                self._run_with_planner(run_id, prompt, settings, event_sink=event_sink)
            else:
                self._run_hardcoded(run_id, prompt, event_sink=event_sink)
        except Exception as exc:
            self._fail_run(run_id, str(exc))
            _emit(
                event_sink,
                {"event": "run_failed", "run_id": run_id, "status": "failed", "error": str(exc)},
            )
            raise
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
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        llm = ProviderRuntime(settings).get_chat_provider(selected=self.provider_name)
        if llm is None:
            self._run_hardcoded(run_id, prompt, event_sink=event_sink)
            return
        planner = AgentPlanner(llm)
        executor = self._build_executor(run_id, event_sink=event_sink)
        result: PlannerResult = planner.run(prompt, executor)

        # Planner tool records are written as business traces after the graph
        # node traces. Keeping both lets operators inspect graph state and actual
        # tool payloads separately.
        for record in result.tool_calls:
            self._trace(run_id, record.tool_name, record.input_json, record.output_json)

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
            "tool_calls": [
                {"tool": r.tool_name, "input": r.input_json}
                for r in result.tool_calls
            ],
            "citations": _citations_from_tool_calls(result.tool_calls),
            "graph": self._get_run_state(run_id).get("graph", []),
            "disclaimer": "Research output only. Not investment advice.",
        }
        report_markdown = self._render_planner_report(result.final_message, result.tool_calls)
        self._graph_node(
            run_id,
            "final_report",
            {"format": "markdown"},
            {"characters": len(report_markdown)},
            event_sink=event_sink,
        )
        self._complete_run(run_id, report_markdown, report_json)

    def _build_executor(
        self,
        run_id: str,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolExecutor:
        def executor(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            # Only live order intent creation enters the approval family. Market,
            # RAG, memory, and research tools remain auto-executable in V1.
            self._graph_node(
                run_id,
                "approval_check",
                {"tool_name": tool_name},
                {"requires_approval": tool_name == "live_order_intent"},
                event_sink=event_sink,
            )
            self._graph_node(
                run_id,
                "execute_tool",
                {"tool_name": tool_name, "args": args},
                {"status": "started"},
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
            # This dispatch table is the Agent "tool call" bridge. The LLM only
            # selects a name and JSON arguments; trusted Python code performs the
            # actual database, OKX, RAG, memory, or strategy operation.
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
                )
                result = {"memory_id": item.id}
            elif tool_name == "memory_search":
                items = self.memory.search(query=str(args.get("query", "")), limit=10)
                result = {
                    "items": [
                        {
                            "id": m.id,
                            "kind": m.kind,
                            "content": m.content[:200],
                            "tags": m.tags,
                            "usage_count": m.usage_count,
                        }
                        for m in items[-10:]
                    ]
                }
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
            elif tool_name == "live_order_intent":
                result = LiveOrderIntentService(self.db, settings=self._settings).create(
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
                result = {"error": f"unknown tool: {tool_name}"}
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

    # ------------------------------------------------------------------
    # Hardcoded fallback path (no API key configured)
    # ------------------------------------------------------------------

    def _run_hardcoded(
        self,
        run_id: str,
        prompt: str,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        # The fallback path is deliberately deterministic. It keeps local tests,
        # demos, and first-time setup useful even when no provider API key exists.
        self._graph_node(
            run_id,
            "approval_check",
            {"tool_name": "market.summary"},
            {"requires_approval": False},
            event_sink=event_sink,
        )
        self._graph_node(
            run_id,
            "execute_tool",
            {"tool_name": "market.summary"},
            {"status": "started"},
            event_sink=event_sink,
        )
        _emit(
            event_sink,
            {"event": "tool_started", "run_id": run_id, "tool_name": "market.summary"},
        )
        market_payload = self._market_summary_payload()
        self._trace(run_id, "market.summary", {"prompt": prompt}, market_payload)
        _emit(
            event_sink,
            {
                "event": "tool_completed",
                "run_id": run_id,
                "tool_name": "market.summary",
                "status": "completed",
                "output_json": market_payload,
            },
        )

        _emit(event_sink, {"event": "tool_started", "run_id": run_id, "tool_name": "rag.search"})
        self._graph_node(
            run_id,
            "approval_check",
            {"tool_name": "rag.search"},
            {"requires_approval": False},
            event_sink=event_sink,
        )
        self._graph_node(
            run_id,
            "execute_tool",
            {"tool_name": "rag.search"},
            {"status": "started"},
            event_sink=event_sink,
        )
        self.rag.scan_once()
        rag_hits = [
            {
                "source_path": hit.source_path,
                "title": hit.title,
                "chunk_index": hit.chunk_index,
                "content": hit.content[:240],
                "score": hit.score,
            }
            for hit in self.rag.search("volume risk market funding open interest", limit=3)
        ]
        self._trace(run_id, "rag.search", {"query": "market risk"}, {"hits": rag_hits})
        _emit(
            event_sink,
            {
                "event": "tool_completed",
                "run_id": run_id,
                "tool_name": "rag.search",
                "status": "completed",
                "output_json": {"hits": rag_hits},
            },
        )

        _emit(event_sink, {"event": "tool_started", "run_id": run_id, "tool_name": "memory.write"})
        self._graph_node(
            run_id,
            "approval_check",
            {"tool_name": "memory.write"},
            {"requires_approval": False},
            event_sink=event_sink,
        )
        self._graph_node(
            run_id,
            "execute_tool",
            {"tool_name": "memory.write"},
            {"status": "started"},
            event_sink=event_sink,
        )
        memory_item = self.memory.write(
            content=f"Latest market summary requested by user prompt: {prompt[:120]}",
            kind="market_summary",
            source_run_id=run_id,
            source_tool="memory.write",
        )
        self._trace(
            run_id,
            "memory.write",
            {"kind": "market_summary"},
            {"memory_id": memory_item.id},
        )
        _emit(
            event_sink,
            {
                "event": "tool_completed",
                "run_id": run_id,
                "tool_name": "memory.write",
                "status": "completed",
                "output_json": {"memory_id": memory_item.id},
            },
        )

        report_json = {
            "market_scope": "OKX SWAP",
            "trigger": "user_request",
            "top_movers": market_payload["top_movers"],
            "data_source": market_payload.get("data_source", "db_fallback"),
            "as_of_utc": market_payload.get("as_of_utc", datetime.now(UTC).isoformat()),
            "rag_hits": rag_hits,
            "citations": rag_hits,
            "graph": self._get_run_state(run_id).get("graph", []),
            "disclaimer": "Research output only. Not investment advice.",
        }
        self._graph_node(
            run_id,
            "reflect",
            {"tool_count": 3},
            {"summary": "deterministic market summary fallback completed"},
            event_sink=event_sink,
        )
        self._graph_node(
            run_id,
            "final_report",
            {"format": "markdown"},
            {"characters": len(self._render_market_report(report_json))},
            event_sink=event_sink,
        )
        self._complete_run(run_id, self._render_market_report(report_json), report_json)

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

    def _create_run(self, prompt: str) -> str:
        with self.db.session() as session:
            run = AgentRun(prompt=prompt, status="running")
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
            run.status = "completed"
            run.report_markdown = report_markdown
            run.report_json = report_json
            run.run_state_json = {**(run.run_state_json or {}), "final_answer": report_markdown}

    def _fail_run(self, run_id: str, error: str) -> None:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = error

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
            return {
                "market_scope": "OKX SWAP",
                "top_movers": [],
                "data_source": source,
                "as_of_utc": datetime.now(UTC).isoformat(),
                "unavailable_reason": error or "okx_rest_unavailable",
            }
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
        lines = [
            "# OKX 永续合约行情归纳",
            "",
            "**范围**: OKX 全市场 SWAP",
            "**触发方式**: 用户按需发起",
            f"**数据时间(UTC)**: {report.get('as_of_utc', 'n/a')}",
            f"**数据来源**: {report.get('data_source', 'unknown')}",
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
        ticker_lines: list[str] = []
        candle_lines: list[str] = []
        compare_lines: list[str] = []
        citation_lines: list[str] = []
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
        sections: list[str] = []
        if ticker_lines:
            sections.extend(["## 单标的行情", "", *ticker_lines])
        if candle_lines:
            sections.extend(["## K线趋势特征", "", *candle_lines])
        if compare_lines:
            sections.extend(["## 多标的强弱比较", "", *compare_lines])
        citations = _citations_from_tool_calls(tool_calls)
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
        return "\n".join([*sections, final_message])


def _classify_intent(prompt: str) -> str:
    text = prompt.casefold()
    if any(word in text for word in ("下单", "order", "buy", "sell", "做多", "做空")):
        return "order"
    if any(word in text for word in ("回测", "backtest", "策略", "strategy", "experiment")):
        return "strategy"
    if any(word in text for word in ("行情", "价格", "走势", "compare", "比较", "ticker")):
        return "market"
    return "general"


def _reflection_summary(result: PlannerResult) -> str:
    names = [record.tool_name for record in result.tool_calls]
    if not names:
        return "planner completed without tool calls"
    return "planner completed with tools: " + ", ".join(names)


def _citations_from_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for record in tool_calls:
        if getattr(record, "tool_name", "") not in {"rag_search", "rag.search"}:
            continue
        payload = getattr(record, "output_json", {})
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
                    "content_preview": str(
                        hit.get("content", hit.get("content_preview", ""))
                    )[:240],
                }
            )
    return citations[:5]


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
