from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from fastapi.testclient import TestClient
from hypertrade.cli import handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import ExperimentRegister
from hypertrade.research.robustness import (
    RobustnessValidationService,
    evaluate_robustness,
    plan_robustness_validation,
)
from hypertrade.research.robustness_schemas import (
    RobustnessPlanV2,
    RobustnessPolicyV2,
    ScenarioObservation,
)
from test_experiment_manifest import manifest


def _plan(
    *, budget: int = 4, fingerprint: str = "a" * 64, snapshot: str = "b" * 64
) -> RobustnessPlanV2:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return plan_robustness_validation(
        fingerprint=fingerprint,
        data_snapshot_hash=snapshot,
        candle_times=[start + timedelta(hours=index) for index in range(500)],
        parameter_bounds={
            "lookback": {"min": 2, "max": 120},
            "threshold": {"min": 0, "max": 0.1},
        },
        maker_fee_bps=Decimal("10"),
        taker_fee_bps=Decimal("10"),
        slippage_bps=Decimal("5"),
        policy=RobustnessPolicyV2(),
        max_new_backtests=budget,
    )


def _passing_observations(plan: RobustnessPlanV2) -> list[ScenarioObservation]:
    return [
        ScenarioObservation(
            scenario_id=scenario.scenario_id,
            status="completed",
            result_ref={"job_id": scenario.scenario_id, "result_id": "1"},
            metrics={
                "total_return_pct": Decimal("5"),
                "max_drawdown_pct": Decimal("8"),
                "trade_count": Decimal("30"),
            },
        )
        for scenario in plan.scenarios
    ]


def test_locked_oos_requires_freeze_and_never_overlaps_walk_forward() -> None:
    with pytest.raises(ValueError, match="fingerprint is required"):
        plan_robustness_validation(
            fingerprint="",
            data_snapshot_hash="b" * 64,
            candle_times=[],
            parameter_bounds={},
            maker_fee_bps=Decimal("1"),
            taker_fee_bps=Decimal("1"),
            slippage_bps=Decimal("1"),
            policy=RobustnessPolicyV2(),
            max_new_backtests=4,
        )

    plan = _plan()
    locked = next(item for item in plan.scenarios if item.kind == "locked_oos")
    walk = [item for item in plan.scenarios if item.kind == "walk_forward"]

    assert plan.projected_new_backtests == 4
    assert len(plan.scenarios) == 7
    assert len(walk) == 2
    assert all(item.window.end < locked.window.start for item in walk)
    assert all(item.source == "reuse" for item in plan.scenarios if "sensitivity" in item.kind)


def test_plan_pre_reserves_backtest_budget() -> None:
    with pytest.raises(ValueError, match="exceeds remaining backtest budget"):
        _plan(budget=3)


def test_planner_rejects_gaps_and_supports_optional_regime_windows() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    times = [start + timedelta(hours=index) for index in range(501)]
    times.pop(250)
    with pytest.raises(ValueError, match="contain gaps"):
        plan_robustness_validation(
            fingerprint="a" * 64,
            data_snapshot_hash="b" * 64,
            candle_times=times,
            parameter_bounds={},
            maker_fee_bps=Decimal("10"),
            taker_fee_bps=Decimal("10"),
            slippage_bps=Decimal("5"),
            policy=RobustnessPolicyV2(),
            max_new_backtests=4,
        )

    plan = plan_robustness_validation(
        fingerprint="a" * 64,
        data_snapshot_hash="b" * 64,
        candle_times=[start + timedelta(hours=index) for index in range(500)],
        parameter_bounds={},
        maker_fee_bps=Decimal("10"),
        taker_fee_bps=Decimal("10"),
        slippage_bps=Decimal("5"),
        policy=RobustnessPolicyV2(),
        max_new_backtests=5,
        regime_windows={
            "high_vol": [start + timedelta(hours=index) for index in range(40, 80)]
        },
    )
    regime = next(item for item in plan.scenarios if item.kind == "regime_stress")
    assert regime.required is False
    assert regime.regime == "high_vol"


def test_all_required_scenarios_validate_deterministically() -> None:
    plan = _plan()
    policy = RobustnessPolicyV2()

    first = evaluate_robustness(plan, _passing_observations(plan), policy)
    second = evaluate_robustness(plan, _passing_observations(plan), policy)

    assert first == second
    assert first.final_status == "validated"
    assert first.gates["regime_stress"].outcome == "not_applicable"


def test_missing_metric_is_needs_data_and_high_return_cannot_hide_spike() -> None:
    plan = _plan()
    observations = _passing_observations(plan)
    observations[0].metrics.pop("trade_count")

    missing = evaluate_robustness(plan, observations, RobustnessPolicyV2())

    assert missing.final_status == "needs_data"
    assert missing.gates["locked_oos"].outcome == "unknown"

    observations = _passing_observations(plan)
    observations[0].metrics["total_return_pct"] = Decimal("100")
    spiky = evaluate_robustness(plan, observations, RobustnessPolicyV2())

    assert spiky.final_status == "rejected"
    assert spiky.gates["parameter_sensitivity"].outcome == "failed"


def test_result_refs_and_observation_identity_fail_closed() -> None:
    plan = _plan()
    observations = _passing_observations(plan)
    observations[0].result_ref = {}

    missing_ref = evaluate_robustness(plan, observations, RobustnessPolicyV2())

    assert missing_ref.final_status == "needs_data"
    with pytest.raises(ValueError, match="duplicate robustness"):
        evaluate_robustness(
            plan,
            _passing_observations(plan) + [_passing_observations(plan)[0]],
            RobustnessPolicyV2(),
        )


def test_cost_stress_trade_failure_rejects_candidate() -> None:
    plan = _plan()
    observations = _passing_observations(plan)
    stressed = next(item for item in observations if item.scenario_id.startswith("cost_stress"))
    stressed.metrics["trade_count"] = Decimal("1")

    result = evaluate_robustness(plan, observations, RobustnessPolicyV2())

    assert result.final_status == "rejected"
    assert result.gates["cost_stress"].outcome == "failed"


def test_largest_trade_concentration_fails_closed_when_metric_is_available() -> None:
    plan = _plan()
    observations = _passing_observations(plan)
    observations[0].metrics["largest_trade_contribution_pct"] = Decimal("90")

    result = evaluate_robustness(plan, observations, RobustnessPolicyV2())

    assert result.final_status == "rejected"
    assert result.scenario_gates["locked_oos_baseline"]["concentration"] == "failed"


def test_validation_persistence_public_api_and_cli_projection() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    registration = ExperimentLedgerService(db).register(
        ExperimentRegister(
            manifest=manifest(), idempotency_key="robustness-ledger-key-001"
        ),
        actor="test",
    )
    execution_id = str(dict(registration["execution"])["id"])  # type: ignore[arg-type]
    fingerprint = str(dict(registration["manifest"])["fingerprint"])  # type: ignore[arg-type]
    canonical = dict(dict(registration["manifest"])["manifest"])  # type: ignore[arg-type]
    ExperimentLedgerService(db).start(execution_id)
    plan = _plan(fingerprint=fingerprint, snapshot=str(canonical["data_snapshot_hash"]))
    recorded = RobustnessValidationService(db).record(
        execution_id=execution_id,
        plan=plan,
        policy=RobustnessPolicyV2(),
        observations=_passing_observations(plan),
        actor="test",
    )

    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="robustness-api-test",
            ),
            db=db,
        )
    )
    assert client.get("/api/research/validations").json()["items"][0][
        "final_status"
    ] == "validated"
    assert client.get(f"/api/research/validations/{recorded['id']}").status_code == 200

    class ValidationClient:
        def list_robustness_validations(self):
            return [recorded]

        def get_robustness_validation(self, validation_id: str):
            assert validation_id == recorded["id"]
            return recorded

    output = StringIO()
    cli = ValidationClient()
    handle_slash_command("/validations list", client=cli, output=output)  # type: ignore[arg-type]
    handle_slash_command(
        f"/validations show {recorded['id']}", client=cli, output=output  # type: ignore[arg-type]
    )
    rendered = output.getvalue()
    assert "[validated]" in rendered
    assert "locked_oos: passed required=True" in rendered
