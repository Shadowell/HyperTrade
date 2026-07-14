"""Bounded read-tool adapter for Research Graph roles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from hypertrade.db import Database
from hypertrade.market.repository import MarketRepository
from hypertrade.rag.service import RagService
from hypertrade.research.evidence import EvidenceService
from hypertrade.research.roles.schemas import RoleToolCall, ToolObservation
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.source_refs import source_ref_from_snapshot
from hypertrade.strategy.library import StrategyLibraryService


class ResearchBitProReadAdapter(Protocol):
    def capabilities(self) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...

    def market_klines(
        self, *, symbol: str, timeframe: str, limit: int, exchange: str = "okx"
    ) -> dict[str, Any]: ...

    def backtest_get_job(self, *, job_id: str) -> dict[str, Any]: ...

    def backtest_get_result(
        self, *, backtest_id: str | int, sample_limit: int = 20
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GraphToolContext:
    task_id: str
    mandate_id: str
    job_id: str
    objective: str
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    strategy_key: str = ""


class ResearchToolRunner(Protocol):
    def run(self, call: RoleToolCall, context: GraphToolContext) -> ToolObservation: ...


class BuiltinResearchToolRunner:
    """Only implements bounded reads; unsupported capabilities become visible gaps."""

    def __init__(
        self,
        db: Database,
        *,
        bitpro_adapter: ResearchBitProReadAdapter | None = None,
        knowledge_dir: Path | str | None = None,
    ) -> None:
        self.db = db
        self.bitpro_adapter = bitpro_adapter
        self.knowledge_dir = Path(knowledge_dir) if knowledge_dir else None

    def run(self, call: RoleToolCall, context: GraphToolContext) -> ToolObservation:
        now = datetime.now(UTC)
        try:
            if call.name == "research.mandate_read":
                payload = ResearchProgramService(self.db).get_mandate(context.mandate_id)
                return self._available(call.name, payload, now=now)
            if call.name == "research.evidence_read":
                rows = EvidenceService(self.db).query(task_id=context.task_id, limit=100)
                payload = {
                    "items": [
                        {
                            "id": row["id"],
                            "type": row["evidence_type"],
                            "status": row["status"],
                            "claim": str(row["claim"])[:500],
                            "confidence": row["confidence"],
                        }
                        for row in rows
                    ]
                }
                return self._available(call.name, payload, now=now)
            if call.name == "market.tickers":
                ticker_rows = MarketRepository(self.db).latest_tickers(limit=50)
                payload = {
                    "tickers": [
                        {
                            "inst_id": row.inst_id,
                            "last": str(row.last),
                            "change_utc0_pct": str(row.change_utc0_pct),
                            "volume_ccy_24h": str(row.volume_ccy_24h),
                        }
                        for row in ticker_rows
                    ]
                }
                if not ticker_rows:
                    return self._unavailable(call.name, "market_tickers_empty")
                return self._available(call.name, payload, now=now)
            if call.name == "strategy.library_search":
                result = StrategyLibraryService(self.db).search(
                    query=str(call.arguments.get("query", "")),
                    strategy_key=context.strategy_key,
                    limit=10,
                )
                payload = {
                    "source": result.get("source"),
                    "memory_count": result.get("memory_count", 0),
                    "strategy_keys": [
                        str(item.get("strategy_key", ""))
                        for item in result.get("items", [])
                        if isinstance(item, dict)
                    ],
                }
                return self._available(call.name, payload, now=now)
            if call.name == "research.strategy_spec_draft":
                payload = ResearchProgramService(self.db).draft_strategy_spec(
                    context.mandate_id, context.objective
                )
                return self._available(call.name, payload, now=now)
            if call.name == "research.job_report":
                if not context.job_id:
                    return self._unavailable(call.name, "research_job_not_linked")
                payload = ResearchProgramService(self.db).report(context.job_id)
                return self._available(call.name, payload, now=now)
            if call.name == "rag.search":
                if self.knowledge_dir is None:
                    return self._unavailable(call.name, "rag_not_configured")
                hits = RagService(self.db, knowledge_dir=self.knowledge_dir).search(
                    str(call.arguments.get("query", context.objective)), limit=5
                )
                payload = {
                    "hits": [
                        {
                            "source_path": hit.source_path,
                            "chunk_index": hit.chunk_index,
                            "preview": hit.content_preview,
                        }
                        for hit in hits
                    ]
                }
                if not hits:
                    return self._unavailable(call.name, "rag_hits_empty")
                return self._available(call.name, payload, now=now)
            if call.name.startswith("bitpro."):
                return self._bitpro_read(call, context, now=now)
        except (KeyError, ValueError) as exc:
            return self._unavailable(call.name, f"read_validation_error:{type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001 - upstream reads become structured gaps
            return self._unavailable(call.name, f"read_unavailable:{type(exc).__name__}")
        return self._unavailable(call.name, "tool_runner_not_implemented")

    def _bitpro_read(
        self, call: RoleToolCall, context: GraphToolContext, *, now: datetime
    ) -> ToolObservation:
        if self.bitpro_adapter is None:
            return self._unavailable(call.name, "bitpro_adapter_unavailable")
        if call.name == "bitpro.capabilities":
            return self._available(call.name, self.bitpro_adapter.capabilities(), now=now)
        if call.name == "bitpro.health":
            return self._available(call.name, self.bitpro_adapter.health(), now=now)
        if call.name in {"bitpro.market_klines", "market.candles"}:
            symbol = str(
                call.arguments.get("symbol")
                or (context.symbols[0] if context.symbols else "")
            )
            timeframe = str(
                call.arguments.get("timeframe")
                or (context.timeframes[0] if context.timeframes else "1H")
            )
            if not symbol:
                return self._unavailable(call.name, "mandate_symbol_missing")
            payload = self.bitpro_adapter.market_klines(
                symbol=symbol,
                timeframe=timeframe,
                limit=min(500, max(100, int(call.arguments.get("limit", 300)))),
            )
            return self._available(call.name, payload, now=now)
        if call.name == "bitpro.backtest_get_job":
            job_id = str(call.arguments.get("job_id", context.job_id))
            if not job_id:
                return self._unavailable(call.name, "backtest_job_id_missing")
            return self._available(
                call.name, self.bitpro_adapter.backtest_get_job(job_id=job_id), now=now
            )
        if call.name == "bitpro.backtest_get_result":
            result_id = str(call.arguments.get("backtest_id", ""))
            if not result_id:
                return self._unavailable(call.name, "backtest_result_id_missing")
            return self._available(
                call.name,
                self.bitpro_adapter.backtest_get_result(
                    backtest_id=result_id,
                    sample_limit=20,
                ),
                now=now,
            )
        return self._unavailable(call.name, "bitpro_read_not_implemented")

    @staticmethod
    def _available(tool_name: str, payload: dict[str, Any], *, now: datetime) -> ToolObservation:
        bounded = _bounded_projection(payload)
        source = source_ref_from_snapshot(
            snapshot_id=f"{tool_name}:{now.isoformat()}",
            snapshot_projection=bounded,
            observed_at=now,
        )
        return ToolObservation(
            tool_name=tool_name,
            available=True,
            summary=json.dumps(bounded, ensure_ascii=False, sort_keys=True)[:4_000],
            sources=[source.model_dump(mode="json")],
            artifact_ref={"source_id": source.source_id, "content_hash": source.content_hash},
        )

    @staticmethod
    def _unavailable(tool_name: str, error_code: str) -> ToolObservation:
        return ToolObservation(
            tool_name=tool_name,
            available=False,
            summary=f"{tool_name} unavailable",
            error_code=error_code,
        )


def _bounded_projection(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        return {
            str(key): _bounded_projection(item, depth=depth + 1)
            for key, item in list(value.items())[:50]
            if str(key).lower()
            not in {"access_token", "api_key", "authorization", "cookie", "password", "secret"}
        }
    if isinstance(value, list):
        return [_bounded_projection(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:1_000]
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:1_000]
