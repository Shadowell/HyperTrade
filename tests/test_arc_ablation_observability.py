"""Ablation budget and effectiveness visibility: read-only counters over persisted rows."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hypertrade.arc import ablation
from hypertrade.arc.effectiveness import build_effectiveness_report
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.evolution_models import (
    ArcAblationRun,
    ArcAblationStep,
    ArcForwardOutcome,
    ArcRuntimeError,
)
from hypertrade.arc.research_budget import budget_status
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.db import Database
from sqlalchemy import select

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


@pytest.fixture
def db():
    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    try:
        yield database
    finally:
        reset_store()


def _run(
    db: Database,
    *,
    run_id: str,
    challenger: str,
    status: str,
    reason: str = "",
    next_check_at: datetime | None = None,
) -> None:
    with db.session() as session:
        session.add(
            ArcAblationRun(
                id=run_id,
                outcome_id="out_" + run_id,
                target_id="bitpro",
                parent_strategy_id="443",
                challenger_strategy_id=challenger,
                status=status,
                reason=reason,
                next_check_at=next_check_at,
            )
        )


def _step(
    db: Database, *, run_id: str, step_key: str, charged_at: datetime | None = None
) -> None:
    with db.session() as session:
        session.add(
            ArcAblationStep(
                id=f"{run_id}:{step_key}",
                run_id=run_id,
                step_key=step_key,
                ordinal=0 if step_key == "baseline" else 1,
                kind="baseline" if step_key == "baseline" else "single",
                status="pending",
                charged_at=charged_at,
            )
        )


def _loser(
    db: Database,
    *,
    outcome_id: str,
    challenger: str,
    lineage: str = "linked",
    changes: dict[str, Any] | None = None,
) -> None:
    with db.session() as session:
        session.add(
            ArcForwardOutcome(
                id=outcome_id,
                target_id="bitpro",
                parent_strategy_id="443",
                challenger_strategy_id=challenger,
                verdict="lost_futility",
                lineage_status=lineage,
                changes_json=(
                    dict(changes)
                    if changes is not None
                    else {"parameter_changes": {"fast": 12, "slow": 40}}
                ),
            )
        )


def _seed_ledger(db: Database) -> None:
    _run(db, run_id="run_pending", challenger="9101", status="pending")
    _run(
        db,
        run_id="run_running",
        challenger="9102",
        status="running",
        reason="backtest_pending",
        next_check_at=NOW + timedelta(minutes=5),
    )
    _run(db, run_id="run_completed", challenger="9103", status="completed")
    _run(
        db,
        run_id="run_skipped",
        challenger="9104",
        status="skipped",
        reason="too_many_changes",
    )
    _run(
        db,
        run_id="run_failed",
        challenger="9105",
        status="failed",
        reason="parent_relay_hold_timeout",
    )
    _step(db, run_id="run_completed", step_key="baseline", charged_at=NOW)
    _step(db, run_id="run_completed", step_key="param:fast", charged_at=NOW)
    _step(
        db,
        run_id="run_completed",
        step_key="param:slow",
        charged_at=NOW - timedelta(days=1),
    )
    _loser(db, outcome_id="out_a", challenger="9101")
    _loser(db, outcome_id="out_b", challenger="9202")
    _loser(
        db,
        outcome_id="out_c",
        challenger="9203",
        changes={"parameter_changes": {"fast": 12}},
    )
    _loser(db, outcome_id="out_d", challenger="9204", lineage="no_lineage")


def _errors(db: Database) -> list[ArcRuntimeError]:
    with db.session() as session:
        return list(session.scalars(select(ArcRuntimeError)))


def test_budget_status_includes_ablation_view_without_touching_research_counters(
    db: Database,
) -> None:
    _seed_ledger(db)

    state = budget_status(db, EvolutionConfig(), NOW)
    view = state["ablation"]

    assert view["schema_version"] == "ablation_budget.v1"
    assert view["enabled"] is True
    assert view["unit"] == "backtests"
    assert view["period"] == "2026-10-21"
    assert view["period_used"] == 2
    assert view["period_limit"] == 6
    assert view["per_loser_limit"] == 6
    assert view["runs"] == {
        "pending": 1,
        "running": 1,
        "completed": 1,
        "skipped": 1,
        "failed": 1,
    }
    assert view["reasons"] == {
        "backtest_pending": 1,
        "too_many_changes": 1,
        "parent_relay_hold_timeout": 1,
    }
    assert view["losers"] == {
        "eligible": 2,
        "single_change": 1,
        "unlinked": 1,
        "scheduled": 1,
    }
    assert view["next_run_at"] == (NOW + timedelta(minutes=5)).isoformat()
    assert view["reason"] is None

    # The daily research quota is untouched by ablation backtests.
    assert state["period_used"] == 0
    assert state["period_limit"] == 4
    assert "sources" in state and "receipts" in state


def test_ablation_view_reports_disabled_and_exhausted(db: Database) -> None:
    disabled = budget_status(db, EvolutionConfig(ablation_enabled=False), NOW)["ablation"]
    assert disabled["enabled"] is False
    assert disabled["reason"] == "disabled"

    _run(db, run_id="run_completed", challenger="9103", status="completed")
    _step(db, run_id="run_completed", step_key="baseline", charged_at=NOW)
    _step(db, run_id="run_completed", step_key="param:fast", charged_at=NOW)
    exhausted = budget_status(
        db, EvolutionConfig(ablation_max_backtests_per_day=2), NOW
    )["ablation"]
    assert exhausted["period_used"] == 2
    assert exhausted["reason"] == "period_budget_exhausted"


def test_budget_status_survives_ablation_view_failure(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(ablation, "ablation_budget_view", boom)

    state = budget_status(db, EvolutionConfig(), NOW)
    assert state["ablation"]["status"] == "unavailable"
    assert "boom" in state["ablation"]["error"]
    assert state["period_used"] == 0
    assert "receipts" in state


def test_evolution_status_exposes_ablation_budget(db: Database) -> None:
    budget = EvolutionService(db).status()["budget"]
    assert budget["ablation"]["schema_version"] == "ablation_budget.v1"


def test_effectiveness_counts_ablation_runs_and_charges(db: Database) -> None:
    _seed_ledger(db)

    report = build_effectiveness_report(db, now=NOW)

    assert report.ablation_runs_by_status == {
        "pending": 1,
        "running": 1,
        "completed": 1,
        "skipped": 1,
        "failed": 1,
    }
    assert report.ablation_reasons == {
        "backtest_pending": 1,
        "too_many_changes": 1,
        "parent_relay_hold_timeout": 1,
    }
    assert report.ablation_backtests_charged == 3
    assert report.ablation_error is None


def test_effectiveness_survives_ablation_ledger_failure(db: Database) -> None:
    ArcAblationStep.__table__.drop(db.engine)

    report = build_effectiveness_report(db, now=NOW)

    assert report.schema_version == "evolution_effectiveness.v1"
    assert report.ablation_error
    assert report.ablation_runs_by_status == {}


def _cancel_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cancel(_delay: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", cancel)


def test_evolution_loop_runs_ablation_after_scan_and_alerts(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypertrade import worker
    from hypertrade.arc import evolution_alerts

    calls: list[str] = []

    def tick(_self: Any, now: datetime | None = None) -> dict[str, Any]:
        calls.append("tick")
        return {"status": "no_action"}

    monkeypatch.setattr(EvolutionService, "tick", tick)
    monkeypatch.setattr(
        evolution_alerts, "evolution_alerts_once", lambda _db: calls.append("alerts")
    )
    monkeypatch.setattr(ablation, "ablation_once", lambda _db: calls.append("ablation"))
    _cancel_sleep(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.arc_evolution_loop(db))

    assert calls == ["tick", "alerts", "ablation"]


def test_evolution_loop_journals_ablation_failure(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hypertrade import worker
    from hypertrade.arc import evolution_alerts

    calls: list[str] = []

    def tick(_self: Any, now: datetime | None = None) -> dict[str, Any]:
        calls.append("tick")
        return {"status": "no_action"}

    def boom(_db: Database) -> dict[str, Any]:
        calls.append("ablation")
        raise RuntimeError("ablation exploded")

    monkeypatch.setattr(EvolutionService, "tick", tick)
    monkeypatch.setattr(
        evolution_alerts, "evolution_alerts_once", lambda _db: calls.append("alerts")
    )
    monkeypatch.setattr(ablation, "ablation_once", boom)
    _cancel_sleep(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.arc_evolution_loop(db))

    assert calls == ["tick", "alerts", "ablation"]
    rows = _errors(db)
    assert [row.component for row in rows] == ["worker.arc_ablation"]
