"""Reusable report blocks with source provenance.

Report blocks are the stable boundary between Agent tool evidence and operator
surfaces. They keep default reports compact while preserving source ids, tool
paths, and missing fields for audit mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    source_id: str
    tool_name: str
    path: str
    as_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "tool_name": self.tool_name,
            "path": self.path,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class ReportBlock:
    block_type: str
    title: str
    source_refs: list[SourceRef] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_type": self.block_type,
            "title": self.title,
            "source_refs": [source.to_dict() for source in self.source_refs],
            "metrics": dict(self.metrics),
            "rows": [dict(row) for row in self.rows],
            "missing": list(self.missing),
            "notes": list(self.notes),
            "severity": self.severity,
        }


def build_report_blocks_from_tool_calls(
    final_message: object,
    tool_calls: list[Any],
) -> list[ReportBlock]:
    blocks: list[ReportBlock] = []
    compact_summary = _compact_text(final_message)
    for record in tool_calls:
        tool_name = str(getattr(record, "tool_name", ""))
        payload = getattr(record, "output_json", {})
        if not isinstance(payload, dict):
            continue
        if tool_name == "strategy_library_search":
            blocks.extend(_strategy_library_blocks(payload))
        elif tool_name == "world_model_snapshot":
            blocks.extend(_world_model_blocks(payload, compact_summary))
        elif tool_name == "bitpro_paper_dashboard" and payload.get("status", "ok") == "ok":
            blocks.extend(_bitpro_paper_dashboard_blocks(payload, compact_summary))
    return blocks


def render_report_blocks(blocks: list[ReportBlock | dict[str, Any]], *, audit: bool) -> str:
    normalized = [_coerce_block(block) for block in blocks]
    lines: list[str] = []
    for block in normalized:
        if block.block_type == "audit_references" and not audit:
            continue
        if not _block_has_visible_content(block, audit=audit):
            continue
        if lines:
            lines.append("")
        lines.append(f"{block.title}:")
        if block.notes:
            for note in block.notes:
                lines.append(f"- {note}")
        if block.metrics:
            metric_text = ", ".join(
                f"{key}={_display(value)}" for key, value in block.metrics.items()
            )
            lines.append(f"- Metrics: {metric_text}")
        if block.rows:
            for row in block.rows[:20]:
                lines.append("- " + _row_text(row))
        if block.missing:
            for item in block.missing:
                lines.append(f"- Missing: {item}")
        if audit and block.source_refs:
            lines.append("- Sources:")
            for source in block.source_refs:
                as_of = f", as_of={source.as_of}" if source.as_of else ""
                lines.append(
                    f"  - {source.source_type}:{source.source_id} "
                    f"tool={source.tool_name} path={source.path}{as_of}"
                )
    return "\n".join(lines)


def _strategy_library_blocks(payload: dict[str, Any]) -> list[ReportBlock]:
    items = payload.get("items")
    items = items if isinstance(items, list) else []
    source_refs = [
        SourceRef(
            source_type="memory",
            source_id=str(memory_id),
            tool_name="strategy_library_search",
            path="memory.strategy_knowledge",
        )
        for item in items
        if isinstance(item, dict)
        for memory_id in _list_values(item.get("source_memory_ids"))
    ]
    if not source_refs:
        source_refs.append(
            SourceRef(
                source_type="memory",
                source_id=str(payload.get("source", "memory.strategy_knowledge")),
                tool_name="strategy_library_search",
                path="strategy.library_search",
            )
        )

    blocks = [
        ReportBlock(
            block_type="summary",
            title="Strategy Library Memory",
            source_refs=source_refs,
            metrics={"memory_count": payload.get("memory_count", 0)},
            notes=[f"source={payload.get('source', 'unknown')}"],
        )
    ]
    rows: list[dict[str, Any]] = []
    next_rows: list[dict[str, Any]] = []
    missing: list[str] = []
    if not items:
        missing.append("no matching strategy knowledge")
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        best = item.get("best")
        best = best if isinstance(best, dict) else {}
        rows.append(
            {
                "strategy": item.get("strategy_key", "unknown"),
                "evidence": item.get("evidence_count", 0),
                "pass": item.get("passed_count", 0),
                "fail": item.get("failed_count", 0),
                "best_memory": best.get("memory_id", "n/a"),
                "best_backtest": best.get("backtest_id", "n/a"),
                "winner": best.get("variant_id", "n/a"),
                "return_pct": best.get("total_return_pct", "n/a"),
                "drawdown_pct": best.get("max_drawdown_pct", "n/a"),
                "trades": best.get("trade_count", "n/a"),
            }
        )
        for next_experiment in _list_values(item.get("next_experiments"))[:1]:
            next_rows.append(
                {
                    "strategy": item.get("strategy_key", "unknown"),
                    "next": next_experiment,
                }
            )
    blocks.append(
        ReportBlock(
            block_type="evidence_list",
            title="Strategy Library Evidence",
            source_refs=source_refs,
            rows=rows,
            missing=missing,
        )
    )
    if next_rows:
        blocks.append(
            ReportBlock(
                block_type="next_actions",
                title="Strategy Library Next Actions",
                source_refs=source_refs,
                rows=next_rows,
            )
        )
    blocks.append(
        ReportBlock(
            block_type="audit_references",
            title="Strategy Library Audit References",
            source_refs=source_refs,
        )
    )
    return blocks


def _bitpro_paper_dashboard_blocks(
    payload: dict[str, Any],
    compact_summary: str,
) -> list[ReportBlock]:
    dashboard = _dict_value(payload.get("dashboard"))
    system = _dict_value(dashboard.get("system"))
    equity = _dict_value(dashboard.get("equity"))
    performance = _dict_value(dashboard.get("performance"))
    monitor = _dict_value(payload.get("monitor_summary"))
    scope = _dict_value(payload.get("paper_scope"))
    inventory = _dict_value(monitor.get("running_inventory"))
    strategy_id = system.get("strategy_id", payload.get("strategy_id"))
    source_id = "strategy:all" if strategy_id is None else f"strategy:{strategy_id}"
    sources = _bitpro_source_refs(payload, source_id=source_id)
    data_gaps = [str(value) for value in _list_values(monitor.get("data_gaps"))]
    actions = [
        {
            "action": _dict_value(action).get("action", "observe"),
            "message": _dict_value(action).get("message", "n/a"),
        }
        for action in _list_values(monitor.get("recommended_actions"))
        if isinstance(action, dict)
    ]
    alerts = [
        {
            "level": _dict_value(alert).get("level", "info"),
            "code": _dict_value(alert).get("code", "unknown"),
            "message": _dict_value(alert).get("message", "n/a"),
        }
        for alert in _list_values(monitor.get("alerts"))
        if isinstance(alert, dict)
    ]
    blocks = [
        ReportBlock(
            block_type="summary",
            title="BitPro Paper Monitor",
            source_refs=sources,
            notes=[
                note
                for note in [
                    compact_summary,
                    f"mode={monitor.get('mode', 'unknown')}",
                    f"dashboard_scope={scope.get('dashboard_scope', 'unknown')}",
                ]
                if note
            ],
            severity="warning" if alerts or data_gaps else "info",
        ),
        ReportBlock(
            block_type="metric_table",
            title="BitPro Paper Monitor",
            source_refs=sources,
            metrics={
                "strategy_id": "all" if strategy_id is None else strategy_id,
                "state": system.get("state", "n/a"),
                "mode": system.get("mode", "n/a"),
                "equity": equity.get("current", "n/a"),
                "total_pnl_pct": performance.get("total_pnl_pct", "n/a"),
                "max_drawdown_pct": performance.get("max_drawdown", "n/a"),
                "running_listed": inventory.get("listed_count", "n/a"),
                "running_total": inventory.get("reported_total", "n/a"),
            },
        ),
    ]
    if alerts:
        blocks.append(
            ReportBlock(
                block_type="evidence_list",
                title="BitPro Paper Alerts",
                source_refs=sources,
                rows=alerts,
                severity="warning",
            )
        )
    if data_gaps:
        blocks.append(
            ReportBlock(
                block_type="missing_data",
                title="BitPro Paper Missing Data",
                source_refs=sources,
                missing=data_gaps,
                severity="warning",
            )
        )
    if actions:
        blocks.append(
            ReportBlock(
                block_type="next_actions",
                title="BitPro Paper Next Actions",
                source_refs=sources,
                rows=actions,
            )
        )
    blocks.append(
        ReportBlock(
            block_type="risk_boundary",
            title="BitPro Paper Risk Boundary",
            source_refs=sources,
            notes=["read-only paper monitoring; no live trading write tool was called"],
        )
    )
    blocks.append(
        ReportBlock(
            block_type="audit_references",
            title="BitPro Paper Audit References",
            source_refs=sources,
        )
    )
    return blocks


def _world_model_blocks(
    payload: dict[str, Any],
    compact_summary: str,
) -> list[ReportBlock]:
    sources = _world_model_source_refs(payload)
    global_market = _dict_value(payload.get("global_market"))
    crypto_market = _dict_value(payload.get("crypto_market"))
    strategy = _dict_value(payload.get("strategy"))
    execution = _dict_value(payload.get("execution"))
    tool_health = _dict_value(payload.get("tool_health"))
    deployment = _dict_value(payload.get("deployment"))
    missing = [str(item) for item in _list_values(payload.get("missing_data"))]
    decision = _dict_value(payload.get("decision"))
    defensive = _dict_value(payload.get("defensive_automation"))
    scenarios = [
        scenario
        for scenario in _list_values(payload.get("action_scenarios"))
        if isinstance(scenario, dict)
    ]
    candidate_rows = [
        {
            "action_id": _dict_value(action).get("action_id", "unknown"),
            "level": _dict_value(action).get("level", "L0"),
            "requires_confirmation": _dict_value(action).get(
                "requires_human_confirmation",
                False,
            ),
            "reason": _dict_value(action).get("reason", "n/a"),
        }
        for action in _list_values(payload.get("candidate_actions"))
        if isinstance(action, dict)
    ]
    blocks = [
        ReportBlock(
            block_type="summary",
            title="Global WorldState",
            source_refs=sources,
            notes=[
                note
                for note in [
                    compact_summary,
                    f"schema={payload.get('schema_version', 'unknown')}",
                    f"risk_regime={global_market.get('risk_regime', 'unknown')}",
                    f"cross_asset_signal={global_market.get('cross_asset_signal', 'unknown')}",
                    (
                        f"decision={decision.get('selected_action_id')} "
                        f"policy_status={decision.get('policy_status')}"
                        if decision
                        else ""
                    ),
                ]
                if note
            ],
            severity="warning" if missing else "info",
        ),
        ReportBlock(
            block_type="metric_table",
            title="Global WorldState Components",
            source_refs=sources,
            metrics={
                "crypto_tickers": crypto_market.get("ticker_count", "n/a"),
                "crypto_status": crypto_market.get("status", "unknown"),
                "strategy_status": strategy.get("status", "unknown"),
                "strategy_memory_count": strategy.get("memory_count", "n/a"),
                "execution_status": execution.get("status", "unknown"),
                "tool_health": tool_health.get("status", "unknown"),
                "api_health": deployment.get("api_health", "unknown"),
            },
        ),
        ReportBlock(
            block_type="missing_data",
            title="Global WorldState Missing Data",
            source_refs=sources,
            missing=missing,
            severity="warning" if missing else "info",
        ),
        ReportBlock(
            block_type="next_actions",
            title="Global WorldState Candidate Actions",
            source_refs=sources,
            rows=candidate_rows,
        ),
        ReportBlock(
            block_type="scenario_comparison",
            title="Global WorldState Scenario Comparison",
            source_refs=sources,
            rows=[
                {
                    "rank": scenario.get("rank", "n/a"),
                    "action_id": scenario.get("action_id", "unknown"),
                    "score": scenario.get("score", "n/a"),
                    "policy_status": scenario.get("policy_status", "unknown"),
                    "expected_benefit": _nested_score(
                        scenario.get("expected_benefit")
                    ),
                    "downside": _nested_score(scenario.get("downside")),
                    "confidence": scenario.get("confidence", "n/a"),
                    "review_after": scenario.get("review_after", "n/a"),
                }
                for scenario in scenarios[:10]
            ],
        ),
        ReportBlock(
            block_type="decision",
            title="Global WorldState Decision",
            source_refs=sources,
            metrics={
                "decision_id": decision.get("decision_id", "n/a"),
                "selected_action_id": decision.get("selected_action_id", "n/a"),
                "selected_score": decision.get("selected_score", "n/a"),
                "policy_status": decision.get("policy_status", "unknown"),
                "review_after": decision.get("review_after", "n/a"),
                "human_confirmation_required": decision.get(
                    "human_confirmation_required",
                    "n/a",
                ),
            },
            notes=[str(decision.get("rationale", ""))] if decision else [],
        ),
        ReportBlock(
            block_type="automation_status",
            title="Global WorldState Defensive Automation",
            source_refs=sources,
            metrics={
                "enabled": defensive.get("enabled", False),
                "allowlist": ",".join(
                    str(item) for item in _list_values(defensive.get("allowlist"))
                ),
                "recent_attempt_count": defensive.get("recent_attempt_count", 0),
            },
            rows=[
                {
                    "status": attempt.get("status", "unknown"),
                    "action_id": attempt.get("action_id", "unknown"),
                    "reason": attempt.get("reason", "n/a"),
                    "idempotency_key": attempt.get("idempotency_key", "n/a"),
                }
                for attempt in _list_values(defensive.get("recent_attempts"))[:10]
                if isinstance(attempt, dict)
            ],
        ),
        ReportBlock(
            block_type="risk_boundary",
            title="Global WorldState Risk Boundary",
            source_refs=sources,
            notes=["read-only WorldState snapshot; no execution or live-write tool was called"],
        ),
        ReportBlock(
            block_type="audit_references",
            title="Global WorldState Audit References",
            source_refs=sources,
        ),
    ]
    return blocks


def _bitpro_source_refs(payload: dict[str, Any], *, source_id: str) -> list[SourceRef]:
    refs = [
        SourceRef(
            source_type="bitpro_mcp",
            source_id=source_id,
            tool_name="bitpro_paper_dashboard",
            path="bitpro.paper_dashboard",
            as_of=_as_of(payload),
        )
    ]
    nested = payload.get("tool_calls")
    if isinstance(nested, list):
        for call in nested:
            if not isinstance(call, dict):
                continue
            tool = str(call.get("tool", "")).strip()
            if not tool:
                continue
            refs.append(
                SourceRef(
                    source_type="bitpro_mcp",
                    source_id=source_id,
                    tool_name=tool,
                    path=_bitpro_path(tool),
                    as_of=_as_of(payload),
                )
            )
    return _dedupe_sources(refs)


def _world_model_source_refs(payload: dict[str, Any]) -> list[SourceRef]:
    refs = [
        SourceRef(
            source_type=str(source.get("source_type", "unknown")),
            source_id=str(source.get("source_id", "unknown")),
            tool_name=str(source.get("tool_name", "world_model_snapshot")),
            path=str(source.get("path", "unknown")),
            as_of=source.get("as_of") if isinstance(source.get("as_of"), str) else None,
        )
        for source in _list_values(payload.get("source_refs"))
        if isinstance(source, dict)
    ]
    if not refs:
        refs.append(
            SourceRef(
                source_type="world_model",
                source_id=str(payload.get("source_id", "world_model:latest")),
                tool_name="world_model_snapshot",
                path="hypertrade.world_model.service",
                as_of=_as_of(payload),
            )
        )
    return _dedupe_sources(refs)


def _coerce_block(value: ReportBlock | dict[str, Any]) -> ReportBlock:
    if isinstance(value, ReportBlock):
        return value
    source_refs = [
        SourceRef(
            source_type=str(source.get("source_type", "unknown")),
            source_id=str(source.get("source_id", "unknown")),
            tool_name=str(source.get("tool_name", "unknown")),
            path=str(source.get("path", "unknown")),
            as_of=source.get("as_of") if isinstance(source.get("as_of"), str) else None,
        )
        for source in value.get("source_refs", [])
        if isinstance(source, dict)
    ]
    return ReportBlock(
        block_type=str(value.get("block_type", "summary")),
        title=str(value.get("title", "Report Block")),
        source_refs=source_refs,
        metrics=_dict_value(value.get("metrics")),
        rows=[
            dict(row)
            for row in value.get("rows", [])
            if isinstance(row, dict)
        ],
        missing=[str(item) for item in _list_values(value.get("missing"))],
        notes=[str(item) for item in _list_values(value.get("notes"))],
        severity=str(value.get("severity", "info")),
    )


def _block_has_visible_content(block: ReportBlock, *, audit: bool) -> bool:
    return bool(
        block.notes
        or block.metrics
        or block.rows
        or block.missing
        or (audit and block.source_refs)
    )


def _row_text(row: dict[str, Any]) -> str:
    return ", ".join(f"{key}={_display(value)}" for key, value in row.items())


def _display(value: object) -> str:
    if value is None:
        return "n/a"
    text = str(value).strip()
    return text or "n/a"


def _nested_score(value: object) -> object:
    if not isinstance(value, dict):
        return value
    return value.get("score", "n/a")


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_values(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact_text(value: object, *, max_chars: int = 220) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lines = [line.strip().lstrip("-* ").strip() for line in text.splitlines() if line.strip()]
    summary = " ".join(line for line in lines if not line.startswith("#")).strip()
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 1].rstrip() + "..."


def _bitpro_path(tool: str) -> str:
    mapping = {
        "bitpro_capabilities": "bitpro.capabilities",
        "bitpro_health": "bitpro.health",
        "paper_dashboard": "bitpro.paper_dashboard",
    }
    return mapping.get(tool, f"bitpro.{tool}")


def _as_of(payload: dict[str, Any]) -> str | None:
    for key in ("as_of_utc", "generated_at", "updated_at", "created_at"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _dedupe_sources(refs: list[SourceRef]) -> list[SourceRef]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[SourceRef] = []
    for ref in refs:
        key = (ref.source_type, ref.source_id, ref.tool_name, ref.path)
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result
