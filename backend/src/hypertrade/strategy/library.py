from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from hypertrade.db import Database, MemoryItem, utc_now
from hypertrade.strategy.evidence import StrategyEvidence, parse_strategy_evidence


class StrategyLibraryService:
    """Aggregate source-bound strategy knowledge from audited Memory cards."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def search(
        self,
        *,
        query: str = "",
        strategy_key: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        evidence = [_parse_strategy_memory(item) for item in self._memory_items(limit=100)]
        evidence = [item for item in evidence if item.get("strategy_key")]
        normalized_strategy = strategy_key.strip().casefold()
        if normalized_strategy:
            evidence = [
                item
                for item in evidence
                if str(item.get("strategy_key", "")).casefold() == normalized_strategy
            ]

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in evidence:
            grouped[str(item["strategy_key"])].append(item)

        normalized_query = query.strip().casefold()
        summaries = [
            _strategy_summary(strategy_key=key, evidence=rows)
            for key, rows in sorted(grouped.items())
        ]
        if normalized_query:
            summaries = [
                item
                for item in summaries
                if normalized_query in _summary_haystack(item).casefold()
            ]

        capped_limit = max(1, min(limit, 100))
        return {
            "source": "memory.strategy_knowledge",
            "memory_count": sum(item["evidence_count"] for item in summaries),
            "items": summaries[:capped_limit],
        }

    def _memory_items(self, *, limit: int) -> list[MemoryItem]:
        with self.db.session() as session:
            items = session.scalars(
                select(MemoryItem)
                .where(MemoryItem.disabled.is_(False))
                .where(MemoryItem.kind == "strategy_knowledge")
                .order_by(MemoryItem.created_at)
                .limit(limit)
            ).all()
            for item in items:
                # Strategy library reads count as audited reuse of strategy memory.
                item.usage_count += 1
                item.last_used_at = utc_now()
            session.flush()
            for item in items:
                session.expunge(item)
            return list(items)


def _parse_strategy_memory(item: MemoryItem) -> dict[str, Any]:
    structured = parse_strategy_evidence(item.content)
    if structured is not None:
        return _parse_structured_strategy_memory(item, structured)

    lines = [line.strip() for line in item.content.splitlines() if line.strip()]
    identity = _parse_pairs(_line_after_prefix(lines, "experiment="), separator=";")
    metrics = _parse_pairs(_line_after_prefix(lines, "metrics="), separator=";")
    data = _parse_pairs(_line_after_prefix(lines, "data="), separator=";")
    gate_results = _parse_pairs(_line_after_prefix(lines, "gate_results="), separator=",")
    params = _parse_pairs(_line_after_prefix(lines, "params="), separator=",")
    failure_reasons = _split_reasons(_line_after_prefix(lines, "failure_reasons="))
    next_experiment = _line_after_prefix(lines, "next_experiment=")
    variant_count = _safe_int(_line_after_prefix(lines, "variant_count="))
    boundaries = _split_reasons(_line_after_prefix(lines, "boundary="))
    return {
        "schema_version": "",
        "memory_id": item.id,
        "created_at": item.created_at.isoformat(),
        "source_run_id": item.source_run_id,
        "source_tool": item.source_tool,
        "strategy_key": identity.get("strategy", ""),
        "experiment_id": identity.get("experiment", item.source_run_id),
        "research_id": identity.get("research", ""),
        "backtest_id": identity.get("backtest", ""),
        "bitpro_result_id": identity.get("bitpro_result_id", ""),
        "variant_id": identity.get("winner", ""),
        "passed": _bool_text(identity.get("passed")),
        "variant_count": variant_count,
        "params": params,
        "total_return_pct": metrics.get("total_return_pct", "n/a"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct", "n/a"),
        "trade_count": _safe_int(metrics.get("trade_count")),
        "score": metrics.get("score", "n/a"),
        "data": data,
        "gate_results": gate_results,
        "failure_reasons": failure_reasons,
        "next_experiment": next_experiment,
        "boundaries": boundaries,
        "tags": item.tags,
        "importance": str(item.importance),
        "confidence": str(item.confidence),
        "_raw_content": item.content,
    }


def _parse_structured_strategy_memory(
    item: MemoryItem,
    evidence: StrategyEvidence,
) -> dict[str, Any]:
    return {
        "schema_version": evidence.schema_version,
        "memory_id": item.id,
        "created_at": item.created_at.isoformat(),
        "source_run_id": item.source_run_id,
        "source_tool": item.source_tool,
        "strategy_key": evidence.strategy_key,
        "experiment_id": evidence.experiment_id or item.source_run_id,
        "research_id": evidence.research_id,
        "backtest_id": evidence.backtest_id,
        "bitpro_result_id": evidence.bitpro_result_id,
        "variant_id": evidence.variant_id,
        "passed": evidence.passed,
        "variant_count": evidence.variant_count,
        "params": evidence.parameters,
        "total_return_pct": evidence.metrics.get("total_return_pct", "n/a"),
        "max_drawdown_pct": evidence.metrics.get("max_drawdown_pct", "n/a"),
        "trade_count": _safe_int(evidence.metrics.get("trade_count")),
        "score": evidence.metrics.get("score", "n/a"),
        "data": evidence.source_data,
        "gate_results": evidence.gate_results,
        "failure_reasons": evidence.failure_reasons,
        "next_experiment": evidence.next_experiment,
        "boundaries": evidence.boundaries,
        "tags": item.tags,
        "importance": str(item.importance),
        "confidence": str(item.confidence),
        "_raw_content": item.content,
    }


def _strategy_summary(*, strategy_key: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(evidence, key=lambda row: str(row.get("created_at", "")))
    latest_first = list(reversed(ordered))
    best = max(ordered, key=_evidence_rank) if ordered else {}
    variants: dict[str, dict[str, Any]] = {}
    for row in ordered:
        variant_id = str(row.get("variant_id", "") or "unknown")
        bucket = variants.setdefault(
            variant_id,
            {"variant_id": variant_id, "evidence_count": 0, "passed_count": 0},
        )
        bucket["evidence_count"] += 1
        if row.get("passed"):
            bucket["passed_count"] += 1
    failure_reasons = sorted(
        {
            reason
            for row in ordered
            for reason in row.get("failure_reasons", [])
            if reason and reason != "none"
        }
    )
    next_experiments: list[str] = []
    for row in latest_first:
        next_step = str(row.get("next_experiment", "")).strip()
        if next_step and next_step not in next_experiments:
            next_experiments.append(next_step)
    return {
        "strategy_key": strategy_key,
        "evidence_count": len(ordered),
        "passed_count": sum(1 for row in ordered if row.get("passed")),
        "failed_count": sum(1 for row in ordered if not row.get("passed")),
        "best": _public_evidence(best),
        "latest": _public_evidence(latest_first[0]) if latest_first else {},
        "variants": [variants[key] for key in sorted(variants)],
        "failure_reasons": failure_reasons,
        "next_experiments": next_experiments[:5],
        "source_memory_ids": [str(row.get("memory_id", "")) for row in ordered],
    }


def _public_evidence(row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "schema_version": row.get("schema_version", ""),
        "memory_id": row.get("memory_id", ""),
        "experiment_id": row.get("experiment_id", ""),
        "research_id": row.get("research_id", ""),
        "backtest_id": row.get("backtest_id", ""),
        "bitpro_result_id": row.get("bitpro_result_id", ""),
        "variant_id": row.get("variant_id", ""),
        "passed": bool(row.get("passed")),
        "variant_count": row.get("variant_count", 0),
        "params": row.get("params", {}),
        "total_return_pct": row.get("total_return_pct", "n/a"),
        "max_drawdown_pct": row.get("max_drawdown_pct", "n/a"),
        "trade_count": row.get("trade_count", 0),
        "score": row.get("score", "n/a"),
        "data": row.get("data", {}),
        "gate_results": row.get("gate_results", {}),
        "failure_reasons": row.get("failure_reasons", []),
        "next_experiment": row.get("next_experiment", ""),
        "boundaries": row.get("boundaries", []),
        "created_at": row.get("created_at", ""),
    }


def _evidence_rank(row: dict[str, Any]) -> tuple[bool, Decimal, Decimal, Decimal]:
    return (
        bool(row.get("passed")),
        _decimal(row.get("score")),
        _decimal(row.get("total_return_pct")),
        -_decimal(row.get("max_drawdown_pct")),
    )


def _summary_haystack(summary: dict[str, Any]) -> str:
    parts = [
        str(summary.get("strategy_key", "")),
        " ".join(summary.get("failure_reasons", [])),
        " ".join(summary.get("next_experiments", [])),
        " ".join(summary.get("source_memory_ids", [])),
    ]
    for key in ("best", "latest"):
        evidence = summary.get(key)
        if isinstance(evidence, dict):
            parts.extend(str(evidence.get(field, "")) for field in ("variant_id", "backtest_id"))
    variants = summary.get("variants", [])
    if isinstance(variants, list):
        parts.extend(str(row.get("variant_id", "")) for row in variants if isinstance(row, dict))
    return " ".join(parts)


def _line_after_prefix(lines: list[str], prefix: str) -> str:
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _parse_pairs(text: str, *, separator: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in text.split(separator):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        clean_key = key.strip()
        if clean_key:
            result[clean_key] = value.strip()
    return result


def _split_reasons(text: str) -> list[str]:
    if not text or text.strip().casefold() == "none":
        return []
    return [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]


def _bool_text(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"true", "1", "yes", "pass", "passed"}


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value).replace("%", ""))
    except Exception:
        return Decimal("-999999")


def _safe_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
