from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.effectiveness import build_effectiveness_report
from hypertrade.arc.evolution_models import EvolutionCycle
from hypertrade.arc.store import configure_store, reset_store, save_mission
from hypertrade.db import Database, StrategyOutcome

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def db():
    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


def final_record(*, passed: bool, comparison: dict | None) -> dict:
    metrics = {"net_return": "0.12", "evaluation_window": {"purpose": "final"}}
    if comparison is not None:
        metrics["baseline_comparison"] = comparison
    return {
        "attempt_id": "att1",
        "purpose": "final",
        "passed": passed,
        "backtest_id": "bt1",
        "metrics": metrics,
    }


def evolution_mission(
    db: Database,
    mission_id: str,
    *,
    strategy_id: int = 333,
    trigger: str = "degradation",
    state: str = "completed",
    records: tuple[dict, ...] = (),
    review_status: str | None = None,
    budget_used: tuple[int, int, int] = (3, 5, 2),
) -> ARCController:
    goal = ARCGoalV1(
        objective="evolve the source strategy",
        symbols=["SOL-USDT-SWAP"],
        evolution_context={
            "source_strategy_id": strategy_id,
            "source_instance_id": "paper-x",
            "trigger_source": trigger,
            "cycle_id": "evo_1_1",
        },
    )
    ctrl = ARCController(mission_id=mission_id, goal=goal)
    ctrl.projection.state = state
    ctrl.projection.self_test_records = list(records)
    if review_status is not None:
        ctrl.projection.paper_review = {"status": review_status, "attempt_id": "att1"}
    ctrl.projection.goal.budget.candidates_used = budget_used[0]
    ctrl.projection.goal.budget.model_calls_used = budget_used[1]
    ctrl.projection.goal.budget.backtests_used = budget_used[2]
    save_mission(ctrl)
    return ctrl


def seed_outcome(db: Database, mission_id: str, *, outcome_type: str = "paper_review") -> None:
    with db.session() as session:
        session.add(
            StrategyOutcome(
                id=f"sout_{mission_id[:18]}",
                schema_version="strategy_outcome.v1",
                outcome_type=outcome_type,
                strategy_lineage_id="lin-1",
                strategy_version_id="ver-1",
                strategy_card_id="card-1",
                manifest_id="man-1",
                mission_id=mission_id,
                as_of=NOW,
                settled_at=NOW,
                content_hash="a" * 64,
                idempotency_key=f"idem-{mission_id}"[:32],
                outcome_json={},
                created_by="test",
            )
        )


def test_empty_history_reports_zeros_without_a_win_rate(db) -> None:
    report = build_effectiveness_report(db, now=NOW)
    assert report.schema_version == "evolution_effectiveness.v1"
    assert report.target_id == "bitpro"
    assert report.cycles_total == 0
    assert report.missions_total == 0
    assert report.baseline_win_rate is None
    assert report.baseline_comparisons == 0
    assert report.causal_conclusion == "not_established"
    assert set(report.cycles_by_status) >= {"no_action", "research_created", "error"}


def test_winning_mission_counts_through_the_whole_pipeline(db) -> None:
    evolution_mission(
        db,
        "arc_evo_win",
        records=(
            {"attempt_id": "att1", "purpose": "development", "passed": True, "metrics": {}},
            final_record(
                passed=True,
                comparison={"passed": True, "backtest_id": "bt-base", "net_return": "0.08"},
            ),
        ),
        review_status="paper_observing",
    )
    seed_outcome(db, "arc_evo_win")
    with db.session() as session:
        session.add(EvolutionCycle(id="evo_1_1", status="research_created", payload_json={}))
        session.add(
            EvolutionCycle(id="budget_arc_evo_win", status="budget_admitted", payload_json={})
        )

    report = build_effectiveness_report(db, now=NOW)
    assert report.missions_total == 1
    assert report.missions_completed == 1
    assert report.development_runs == 1 and report.development_passed == 1
    assert report.final_runs == 1 and report.final_passed == 1
    assert report.baseline_comparisons == 1
    assert report.beat_baseline == 1
    assert report.baseline_win_rate == "1.0000"
    assert report.paper_observing == 1
    assert report.outcomes_settled == 1
    assert (report.cost_candidates, report.cost_model_calls, report.cost_backtests) == (3, 5, 2)
    assert report.missions_admitted == 1
    assert report.cycles_by_status["research_created"] == 1
    # budget rows are receipts, not cycles
    assert report.cycles_by_status.get("budget_admitted", 0) == 0
    source = report.per_source[0]
    assert source.strategy_id == 333
    assert source.admitted_missions == 1
    assert source.degradation_triggers == 1
    assert source.beat_baseline == 1
    assert source.paper_observing == 1
    assert source.outcomes_settled == 1


def test_invalid_comparison_is_not_silently_a_loss(db) -> None:
    evolution_mission(
        db,
        "arc_evo_invalid",
        records=(
            final_record(
                passed=False,
                comparison={"passed": False, "reason": "comparison_evidence_invalid"},
            ),
        ),
    )
    report = build_effectiveness_report(db, now=NOW)
    assert report.baseline_comparisons == 0
    assert report.baseline_comparisons_invalid == 1
    assert report.beat_baseline == 0
    assert report.baseline_win_rate is None


def test_losing_mission_and_rejection_are_counted_honestly(db) -> None:
    evolution_mission(
        db,
        "arc_evo_loss",
        trigger="proactive",
        state="needs_operator",
        records=(
            final_record(
                passed=False,
                comparison={"passed": False, "backtest_id": "bt-base", "net_return": "0.2"},
            ),
        ),
        review_status="rejected",
    )
    report = build_effectiveness_report(db, now=NOW)
    assert report.missions_needs_operator == 1
    assert report.baseline_comparisons == 1
    assert report.beat_baseline == 0
    assert report.baseline_win_rate == "0.0000"
    assert report.paper_rejected == 1
    assert report.per_source[0].proactive_triggers == 1


def test_plain_missions_without_evolution_context_are_excluded(db) -> None:
    plain = ARCController(goal=ARCGoalV1(objective="unrelated", symbols=["SOL-USDT-SWAP"]))
    plain.projection.state = "completed"
    save_mission(plain)
    report = build_effectiveness_report(db, now=NOW)
    assert report.missions_total == 0
    assert report.per_source == []
