from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.evolution_models import EvolutionCycle
from hypertrade.arc.meta_tuning import (
    META_TUNER_ACTOR,
    TuningBoundsV1,
    evaluate_tuning,
    tune_once,
)
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.db import Database

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)


@pytest.fixture
def service():
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    yield EvolutionService(db)
    reset_store()


def seed_observations(service: EvolutionService, values: list[float]) -> None:
    with service.db.session() as session:
        for index, value in enumerate(values):
            session.add(
                EvolutionCycle(
                    id=f"cycle_{index}",
                    status="no_action",
                    payload_json={
                        "diagnostics": [
                            {
                                "strategy_id": 100 + index,
                                "window": {
                                    "return_drop_pp": str(value),
                                    "drawdown_increase_pp": "0",
                                    "triggered": False,
                                },
                            }
                        ]
                    },
                )
            )


def test_insufficient_history_yields_no_recommendation(service) -> None:
    seed_observations(service, [3.0, 4.0, 5.0])
    report = evaluate_tuning(service.db, Decimal("10"), now=NOW)
    assert report.recommendation == "insufficient_data"
    assert report.sample_count == 3
    assert report.recommended_threshold_pp is None


def test_p90_rule_recommends_raise_within_bounds(service) -> None:
    seed_observations(service, [float(i) for i in range(1, 21)])
    report = evaluate_tuning(service.db, Decimal("10"), now=NOW)
    assert report.recommendation == "raise"
    assert report.sample_count == 20
    recommended = float(report.recommended_threshold_pp)
    assert 17.0 < recommended <= 20.0
    assert "p90" in report.rationale


def test_quiet_history_recommends_lowering_to_floor(service) -> None:
    seed_observations(service, [1.0 + 0.1 * i for i in range(16)])
    report = evaluate_tuning(service.db, Decimal("10"), now=NOW)
    assert report.recommendation == "lower"
    # Floor is max(min_threshold_pp, p50), never below the declared minimum.
    assert float(report.recommended_threshold_pp) == pytest.approx(5.0)


def test_recommendation_keeps_when_within_half_point(service) -> None:
    seed_observations(service, [9.4 + 0.1 * i for i in range(12)])
    report = evaluate_tuning(service.db, Decimal("10"), now=NOW)
    assert report.recommendation == "keep"
    assert report.recommended_threshold_pp == "10"


def test_tune_once_is_advisory_and_records_daily_receipt(service) -> None:
    seed_observations(service, [float(i) for i in range(1, 21)])
    state = service.status()
    assert state["config"]["meta_tuning_enabled"] is True
    assert state["config"]["meta_tuning_auto_apply"] is False
    result = tune_once(service, now=NOW)
    assert result["status"] == "raise"
    assert service.status()["revision"] == 0  # advisory only: nothing changed
    assert service.status()["config"]["threshold_pp"] == "10"
    with service.db.session() as session:
        receipt = session.get(EvolutionCycle, "tune_20260914")
        assert receipt is not None and receipt.status == "meta_tuning"
        assert receipt.payload_json["tuning_status"] == "raise"
    assert tune_once(service, now=NOW) == {"status": "already_tuned_today"}


def test_tune_once_applies_one_bounded_step_when_authorized(service) -> None:
    seed_observations(service, [float(i) for i in range(1, 21)])
    service.configure(
        EvolutionConfig(meta_tuning_auto_apply=True), revision=0, actor="test"
    )
    result = tune_once(service, now=NOW)
    assert result["status"] == "applied"
    state = service.status()
    # p90 ~18.1 from current 10, step capped at 3pp.
    assert state["config"]["threshold_pp"] == "13.0"
    assert state["revision"] == 2
    assert result["report"]["applied"] is True
    assert result["report"]["applied_revision"] == 2
    from hypertrade.arc.evolution_models import EvolutionControl

    with service.db.session() as session:
        assert session.get(EvolutionControl, "global").updated_by == META_TUNER_ACTOR
    # One action per day even when polled again.
    assert tune_once(service, now=NOW) == {"status": "already_tuned_today"}
    assert service.status()["config"]["threshold_pp"] == "13.0"


def test_tune_once_disabled_leaves_no_receipt(service) -> None:
    service.configure(EvolutionConfig(meta_tuning_enabled=False), revision=0, actor="test")
    assert tune_once(service, now=NOW) == {"status": "disabled"}
    with service.db.session() as session:
        assert session.get(EvolutionCycle, "tune_20260914") is None


def test_bounded_step_never_leaves_declared_bounds(service) -> None:
    from hypertrade.arc.meta_tuning import _bounded_step

    bounds = TuningBoundsV1()
    assert _bounded_step(Decimal("19"), Decimal("30"), bounds) == Decimal("20.0")
    assert _bounded_step(Decimal("6"), Decimal("1"), bounds) == Decimal("5.0")
    assert _bounded_step(Decimal("10"), Decimal("18"), bounds) == Decimal("13.0")
