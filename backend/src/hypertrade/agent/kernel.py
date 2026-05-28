import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from hypertrade.config import get_settings
from hypertrade.db import AgentRun, Database, TraceEvent
from hypertrade.market.client import OkxRestClient
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.rag.service import RagService
from hypertrade.tools.registry import ToolRegistry


@dataclass(frozen=True)
class CompletedAgentRun:
    id: str
    status: str
    report_markdown: str
    report_json: dict[str, Any]
    trace_events: list[TraceEvent]


class AgentKernel:
    def __init__(self, db: Database, *, knowledge_dir: str = "docs/knowledge") -> None:
        self.db = db
        self.market = MarketRepository(db)
        self.memory = MemoryService(db)
        self.rag = RagService(db, knowledge_dir=knowledge_dir)
        self.tools = ToolRegistry.default()

    def run_chat(self, prompt: str) -> CompletedAgentRun:
        run_id = self._create_run(prompt)
        try:
            market_payload = self._market_summary_payload()
            self._trace(run_id, "market.summary", {"prompt": prompt}, market_payload)

            self.rag.scan_once()
            rag_hits = [
                {"source_path": hit.source_path, "content": hit.content[:240], "score": hit.score}
                for hit in self.rag.search("volume risk market funding open interest", limit=3)
            ]
            self._trace(run_id, "rag.search", {"query": "market risk"}, {"hits": rag_hits})

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

            report_json = {
                "market_scope": "OKX SWAP",
                "trigger": "user_request",
                "top_movers": market_payload["top_movers"],
                "data_source": market_payload.get("data_source", "db_fallback"),
                "as_of_utc": market_payload.get("as_of_utc", datetime.now(UTC).isoformat()),
                "rag_hits": rag_hits,
                "disclaimer": "Research output only. Not investment advice.",
            }
            report_markdown = self._render_market_report(report_json)
            self._complete_run(run_id, report_markdown, report_json)
        except Exception as exc:
            self._fail_run(run_id, str(exc))
            raise
        return self.get_run(run_id)

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

    def _market_summary_payload(self) -> dict[str, Any]:
        # Prefer a fresh REST snapshot on each summary request.
        source = self._refresh_market_snapshot()
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

    def _refresh_market_snapshot(self) -> str:
        try:
            settings = get_settings()
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
            return "okx_rest"
        except Exception:
            # Keep CLI/API responsive if upstream REST is temporarily unavailable.
            return "db_fallback"

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
            lines.append("- 暂无行情快照。")
        for mover in movers:
            line = (
                "- {inst_id}: 最新价 {last}, UTC0 涨跌幅 {change_utc0_pct}%, "
                "24h 成交额 {volume_ccy_24h}"
            )
            lines.append(line.format(**mover))
        return "\n".join(lines)
