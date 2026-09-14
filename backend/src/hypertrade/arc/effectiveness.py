"""Autonomous-evolution effectiveness ledger (evolution_effectiveness.v1).

Answers the question the cycle ledger alone cannot: of everything the
evolution loop proposed and executed, how much actually beat the baseline,
how far did it get through the governed pipeline, and what did it cost?
Every number is a deterministic count over persisted receipts (mission
projections, final self-test records with their baseline comparison, paper
review decisions, settled StrategyOutcome rows, mission budget usage) — the
report is descriptive accounting, never a causal claim.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from hypertrade.arc.controller import ARCMissionProjection
from hypertrade.arc.evolution_models import EvolutionCycle
from hypertrade.db import ArcMission, Database, StrategyOutcome

CYCLE_STATUSES = (
    "queued",
    "scanning",
    "preview_complete",
    "cancelled_by_config",
    "no_action",
    "source_changed",
    "deferred",
    "research_created",
    "error",
)


class PerSourceEffectivenessV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: int
    admitted_missions: int = 0
    degradation_triggers: int = 0
    proactive_triggers: int = 0
    beat_baseline: int = 0
    paper_observing: int = 0
    outcomes_settled: int = 0


class EvolutionEffectivenessV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "evolution_effectiveness.v1"
    generated_at: str
    target_id: str
    window_since: str | None = None
    cycles_total: int = 0
    cycles_by_status: dict[str, int] = Field(default_factory=dict)
    missions_total: int = 0
    missions_active: int = 0
    missions_completed: int = 0
    missions_failed: int = 0
    missions_needs_operator: int = 0
    candidates_proposed: int = 0
    development_runs: int = 0
    development_passed: int = 0
    final_runs: int = 0
    final_passed: int = 0
    baseline_comparisons: int = 0
    baseline_comparisons_invalid: int = 0
    beat_baseline: int = 0
    baseline_win_rate: str | None = None
    paper_approved: int = 0
    paper_rejected: int = 0
    paper_observing: int = 0
    paper_effect_unknown: int = 0
    outcomes_settled: int = 0
    outcomes_by_type: dict[str, int] = Field(default_factory=dict)
    cost_model_calls: int = 0
    cost_backtests: int = 0
    cost_candidates: int = 0
    missions_admitted: int = 0
    per_source: list[PerSourceEffectivenessV1] = Field(default_factory=list)
    causal_conclusion: str = "not_established"
    note: str = (
        "只统计进化循环发起的任务（evolution_context/feedback_parent）；胜率是"
        "同窗基线对比通过的比例，样本量小时不足以支撑结论"
    )


def _receipt_purpose(record: dict[str, Any]) -> str:
    return str(record.get("purpose") or "final")


def build_effectiveness_report(
    db: Database, *, target_id: str = "bitpro", now: datetime | None = None
) -> EvolutionEffectivenessV1:
    now = now or datetime.now(UTC)
    report = EvolutionEffectivenessV1(generated_at=now.isoformat(), target_id=target_id)

    with db.session() as session:
        statuses = Counter(
            str(row.status)
            for row in session.scalars(select(EvolutionCycle)).yield_per(100)
        )
        report.cycles_by_status = {code: statuses.get(code, 0) for code in CYCLE_STATUSES}
        report.cycles_total = sum(statuses.get(code, 0) for code in CYCLE_STATUSES)
        report.missions_admitted = statuses.get("budget_admitted", 0)
        outcome_types: Counter[str] = Counter()
        outcome_mission_ids: Counter[str] = Counter()
        for outcome_row in session.scalars(select(StrategyOutcome)).yield_per(100):
            outcome_types[str(outcome_row.outcome_type)] += 1
            outcome_mission_ids[str(outcome_row.mission_id)] += 1
        report.outcomes_by_type = dict(sorted(outcome_types.items()))
        report.outcomes_settled = sum(outcome_types.values())

        per_source: dict[int, PerSourceEffectivenessV1] = {}
        for mission_row in session.scalars(select(ArcMission)).yield_per(50):
            projection = ARCMissionProjection.model_validate(mission_row.projection_json)
            goal = projection.goal
            if goal is None:
                continue
            context = goal.evolution_context or {}
            parent = goal.feedback_parent or {}
            if not context and not parent:
                continue
            source_id = context.get("source_strategy_id") or parent.get("strategy_id")
            if source_id is None:
                continue
            try:
                strategy_id = int(source_id)
            except (TypeError, ValueError):
                continue
            entry = per_source.setdefault(
                strategy_id, PerSourceEffectivenessV1(strategy_id=strategy_id)
            )
            entry.admitted_missions += 1
            trigger = str(context.get("trigger_source") or "")
            if trigger == "degradation":
                entry.degradation_triggers += 1
            elif trigger == "proactive":
                entry.proactive_triggers += 1

            report.missions_total += 1
            if projection.state in {"completed"}:
                report.missions_completed += 1
            elif projection.state in {"failed", "rejected"}:
                report.missions_failed += 1
            elif projection.state == "needs_operator":
                report.missions_needs_operator += 1
            else:
                report.missions_active += 1

            budget = goal.budget
            report.cost_model_calls += int(getattr(budget, "model_calls_used", 0) or 0)
            report.cost_backtests += int(getattr(budget, "backtests_used", 0) or 0)
            report.cost_candidates += int(getattr(budget, "candidates_used", 0) or 0)
            report.candidates_proposed += int(getattr(budget, "candidates_used", 0) or 0)

            for record in projection.self_test_records:
                if not isinstance(record, dict):
                    continue
                if _receipt_purpose(record) == "development":
                    report.development_runs += 1
                    if record.get("passed"):
                        report.development_passed += 1
                else:
                    report.final_runs += 1
                    if record.get("passed"):
                        report.final_passed += 1
                    comparison = (record.get("metrics") or {}).get("baseline_comparison")
                    if isinstance(comparison, dict) and "passed" in comparison:
                        if "reason" in comparison:
                            # comparison_evidence_invalid: no usable comparison exists,
                            # so it must not silently count as a loss either.
                            report.baseline_comparisons_invalid += 1
                        else:
                            report.baseline_comparisons += 1
                            if comparison.get("passed"):
                                report.beat_baseline += 1
                                entry.beat_baseline += 1

            review = projection.paper_review or {}
            status = str(review.get("status") or "")
            if status == "rejected":
                report.paper_rejected += 1
            elif status == "paper_observing":
                report.paper_observing += 1
                entry.paper_observing += 1
            elif status == "effect_unknown":
                report.paper_effect_unknown += 1
            elif status == "approved_pending_effect":
                report.paper_approved += 1

            entry.outcomes_settled += outcome_mission_ids.get(mission_row.mission_id, 0)

        report.per_source = [per_source[k] for k in sorted(per_source)]

    if report.baseline_comparisons:
        win_rate = report.beat_baseline / report.baseline_comparisons
        report.baseline_win_rate = f"{win_rate:.4f}"
    return report
