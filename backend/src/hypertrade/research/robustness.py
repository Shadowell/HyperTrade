"""Deterministic window planning, gate evaluation, and persistence for Sprint 100."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import (
    Database,
    ExperimentExecution,
    ExperimentManifest,
    RobustnessScenarioResult,
    RobustnessValidationRun,
)
from hypertrade.research.robustness_schemas import (
    RobustnessGateResult,
    RobustnessPlanV2,
    RobustnessPolicyV2,
    RobustnessScenario,
    RobustnessValidationResultV2,
    RobustnessWindow,
    ScenarioObservation,
    robustness_policy_hash,
    robustness_policy_payload,
)

_REQUIRED_METRICS = ("total_return_pct", "max_drawdown_pct", "trade_count")


def plan_robustness_validation(
    *,
    fingerprint: str,
    data_snapshot_hash: str,
    candle_times: list[datetime],
    parameter_bounds: dict[str, dict[str, float]],
    maker_fee_bps: Decimal,
    taker_fee_bps: Decimal,
    slippage_bps: Decimal,
    policy: RobustnessPolicyV2,
    max_new_backtests: int,
    regime_windows: dict[str, list[datetime]] | None = None,
) -> RobustnessPlanV2:
    """Freeze a candidate before exposing locked OOS and scenario windows."""
    if len(fingerprint) != 64:
        raise ValueError("candidate fingerprint is required before locked OOS planning")
    ordered = sorted(_utc(value) for value in candle_times)
    if len(ordered) != len(set(ordered)):
        raise ValueError("candle timestamps contain duplicates")
    if ordered and ordered[-1] > datetime.now(UTC):
        raise ValueError("candle timestamps contain future data")
    deltas = [right - left for left, right in zip(ordered, ordered[1:], strict=False)]
    if deltas and any(delta != min(deltas) for delta in deltas):
        raise ValueError("candle timestamps contain gaps")
    development = ordered[: -policy.locked_oos_bars]
    locked = ordered[-policy.locked_oos_bars :]
    fold_size = policy.train_bars + policy.validation_bars + policy.test_bars
    if len(locked) != policy.locked_oos_bars or len(development) < fold_size:
        raise ValueError("insufficient chronological data for robustness windows")
    max_start = len(development) - fold_size
    starts = _even_starts(max_start=max_start, count=policy.walk_forward_folds)
    scenarios: list[RobustnessScenario] = [
        _scenario(
            scenario_id="locked_oos_baseline",
            kind="locked_oos",
            source="reuse",
            segment=locked,
            parameters={},
            maker=maker_fee_bps,
            taker=taker_fee_bps,
            slippage=slippage_bps,
        )
    ]
    for index, start in enumerate(starts, start=1):
        test_start = start + policy.train_bars + policy.validation_bars
        segment = development[test_start : test_start + policy.test_bars]
        scenarios.append(
            _scenario(
                scenario_id=f"walk_forward_{index}",
                kind="walk_forward",
                source="execute",
                segment=segment,
                parameters={},
                maker=maker_fee_bps,
                taker=taker_fee_bps,
                slippage=slippage_bps,
            )
        )
    for key in sorted(parameter_bounds)[: policy.max_parameter_neighbors]:
        bound = parameter_bounds[key]
        low, high = _decimal(bound.get("min")), _decimal(bound.get("max"))
        if low is None or high is None or high < low:
            continue
        scenarios.append(
            _scenario(
                scenario_id=f"sensitivity_{_safe_key(key)}"[:96],
                kind="parameter_sensitivity",
                source="reuse",
                segment=locked,
                parameters={key: (low + high) / Decimal("2")},
                maker=maker_fee_bps,
                taker=taker_fee_bps,
                slippage=slippage_bps,
            )
        )
    for multiplier in policy.cost_multipliers:
        suffix = str(multiplier).replace(".", "_")
        scenarios.append(
            _scenario(
                scenario_id=f"cost_stress_{suffix}x",
                kind="cost_stress",
                source="execute",
                segment=locked,
                parameters={},
                maker=maker_fee_bps * multiplier,
                taker=taker_fee_bps * multiplier,
                slippage=slippage_bps * multiplier,
            )
        )
    for label, segment in sorted((regime_windows or {}).items()):
        safe_label = "".join(character if character.isalnum() else "_" for character in label)
        scenarios.append(
            _scenario(
                scenario_id=f"regime_{safe_label.lower()}"[:96],
                kind="regime_stress",
                source="execute",
                segment=sorted(_utc(value) for value in segment),
                parameters={},
                maker=maker_fee_bps,
                taker=taker_fee_bps,
                slippage=slippage_bps,
                required=policy.require_regime_stress,
                regime=label,
            )
        )
    projected = sum(item.source == "execute" for item in scenarios)
    if projected > max_new_backtests:
        raise ValueError("robustness plan exceeds remaining backtest budget")
    return RobustnessPlanV2(
        fingerprint=fingerprint,
        data_snapshot_hash=data_snapshot_hash,
        candidate_frozen_at=datetime.now(UTC),
        scenarios=scenarios,
        projected_new_backtests=projected,
    )


def evaluate_robustness(
    plan: RobustnessPlanV2,
    observations: list[ScenarioObservation],
    policy: RobustnessPolicyV2,
) -> RobustnessValidationResultV2:
    observation_ids = [item.scenario_id for item in observations]
    planned_ids = {item.scenario_id for item in plan.scenarios}
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("duplicate robustness scenario observations")
    if set(observation_ids) - planned_ids:
        raise ValueError("observation references an unplanned robustness scenario")
    by_id = {item.scenario_id: item for item in observations}
    scenario_gates: dict[str, dict[str, str]] = {}
    unknowns: list[str] = []
    groups: dict[str, list[tuple[RobustnessScenario, str, list[str]]]] = {}
    for scenario in plan.scenarios:
        observation = by_id.get(scenario.scenario_id)
        outcome, reasons, details = _scenario_outcome(observation, policy)
        scenario_gates[scenario.scenario_id] = details
        groups.setdefault(scenario.kind, []).append((scenario, outcome, reasons))
        if outcome == "unknown":
            unknowns.extend(reasons or [f"missing:{scenario.scenario_id}"])

    gates: dict[str, RobustnessGateResult] = {
        "data_integrity": RobustnessGateResult(outcome="passed", required=True),
        "locked_oos": _group_gate(groups.get("locked_oos", []), required=True),
        "walk_forward": _group_gate(groups.get("walk_forward", []), required=True),
        "parameter_sensitivity": _degradation_gate(
            groups.get("parameter_sensitivity", []),
            by_id=by_id,
            baseline=by_id.get("locked_oos_baseline"),
            maximum=policy.sensitivity_max_degradation_pct,
            required=bool(groups.get("parameter_sensitivity")),
        ),
        "cost_stress": _degradation_gate(
            groups.get("cost_stress", []),
            by_id=by_id,
            baseline=by_id.get("locked_oos_baseline"),
            maximum=policy.cost_max_degradation_pct,
            required=True,
        ),
        "regime_stress": _group_gate(
            groups.get("regime_stress", []), required=policy.require_regime_stress
        ),
    }
    failed = [name for name, gate in gates.items() if gate.required and gate.outcome == "failed"]
    missing = [name for name, gate in gates.items() if gate.required and gate.outcome == "unknown"]
    optional_concern = [
        name
        for name, gate in gates.items()
        if not gate.required and gate.outcome in {"failed", "unknown"}
    ]
    final_status = (
        "rejected"
        if failed
        else "needs_data"
        if missing
        else "needs_review"
        if optional_concern
        else "validated"
    )
    unknowns.extend(f"gate:{name}" for name in missing + optional_concern)
    return RobustnessValidationResultV2(
        final_status=final_status,
        gates=gates,
        scenario_gates=scenario_gates,
        unknowns=sorted(set(unknowns)),
        summary={
            "scenario_count": len(plan.scenarios),
            "completed_count": sum(item.status == "completed" for item in observations),
            "failed_gate_count": len(failed),
            "unknown_gate_count": len(missing) + len(optional_concern),
        },
    )


class RobustnessValidationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        *,
        execution_id: str,
        plan: RobustnessPlanV2,
        policy: RobustnessPolicyV2,
        observations: list[ScenarioObservation],
        actor: str,
    ) -> dict[str, Any]:
        result = evaluate_robustness(plan, observations, policy)
        with self.db.session() as session:
            execution = session.get(ExperimentExecution, execution_id)
            if execution is None:
                raise KeyError(execution_id)
            if execution.status != "running":
                raise ValueError("robustness validation requires a running execution")
            manifest = session.get(ExperimentManifest, execution.manifest_id)
            if manifest is None or manifest.fingerprint != plan.fingerprint:
                raise ValueError("robustness plan fingerprint does not match execution")
            expected_snapshot = str(dict(manifest.canonical_json)["data_snapshot_hash"])
            if expected_snapshot != plan.data_snapshot_hash:
                raise ValueError("robustness data snapshot does not match experiment manifest")
            existing = session.scalar(
                select(RobustnessValidationRun).where(
                    RobustnessValidationRun.experiment_execution_id == execution_id
                )
            )
            if existing is not None:
                return self.get(existing.id)
            run = RobustnessValidationRun(
                experiment_execution_id=execution_id,
                fingerprint=plan.fingerprint,
                policy_version=policy.schema_version,
                policy_hash=robustness_policy_hash(policy),
                policy_json=robustness_policy_payload(policy),
                plan_json=plan.model_dump(mode="json"),
                final_status=result.final_status,
                gate_results_json={
                    key: value.model_dump(mode="json") for key, value in result.gates.items()
                },
                summary_json=result.summary,
                unknowns_json=result.unknowns,
                created_by=actor,
            )
            session.add(run)
            session.flush()
            for scenario in plan.scenarios:
                observation = next(
                    (item for item in observations if item.scenario_id == scenario.scenario_id),
                    ScenarioObservation(scenario_id=scenario.scenario_id, status="unknown"),
                )
                session.add(
                    RobustnessScenarioResult(
                        validation_run_id=run.id,
                        scenario_id=scenario.scenario_id,
                        kind=scenario.kind,
                        required=scenario.required,
                        status=observation.status,
                        window_json=scenario.window.model_dump(mode="json"),
                        parameters_json={
                            key: format(value.normalize(), "f")
                            for key, value in scenario.parameters.items()
                        },
                        costs_json={
                            "maker_fee_bps": str(scenario.maker_fee_bps),
                            "taker_fee_bps": str(scenario.taker_fee_bps),
                            "slippage_bps": str(scenario.slippage_bps),
                        },
                        regime=scenario.regime,
                        result_ref_json=dict(observation.result_ref),
                        metrics_json={
                            key: format(value.normalize(), "f")
                            for key, value in observation.metrics.items()
                        },
                        gate_results_json=result.scenario_gates.get(scenario.scenario_id, {}),
                        error_json=(
                            {"code": observation.error_code}
                            if observation.error_code
                            else {}
                        ),
                    )
                )
            session.flush()
            run_id = run.id
        return self.get(run_id)

    def get(self, run_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            run = session.get(RobustnessValidationRun, run_id)
            if run is None:
                raise KeyError(run_id)
            scenarios = session.scalars(
                select(RobustnessScenarioResult)
                .where(RobustnessScenarioResult.validation_run_id == run_id)
                .order_by(RobustnessScenarioResult.scenario_id)
            ).all()
            return _run_projection(run, scenarios)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(RobustnessValidationRun)
                .order_by(desc(RobustnessValidationRun.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [_run_projection(row, []) for row in rows]


def _scenario(
    *,
    scenario_id: str,
    kind: str,
    source: str,
    segment: list[datetime],
    parameters: dict[str, Decimal],
    maker: Decimal,
    taker: Decimal,
    slippage: Decimal,
    required: bool = True,
    regime: str = "",
) -> RobustnessScenario:
    if not segment:
        raise ValueError(f"empty robustness scenario window: {scenario_id}")
    return RobustnessScenario(
        scenario_id=scenario_id,
        kind=kind,
        source=source,
        required=required,
        window=RobustnessWindow(start=segment[0], end=segment[-1]),
        parameters=parameters,
        maker_fee_bps=maker,
        taker_fee_bps=taker,
        slippage_bps=slippage,
        regime=regime,
    )


def _scenario_outcome(
    observation: ScenarioObservation | None, policy: RobustnessPolicyV2
) -> tuple[str, list[str], dict[str, str]]:
    if observation is None or observation.status == "unknown":
        return "unknown", ["result_missing"], {"result": "unknown"}
    if observation.status == "failed":
        return "failed", [observation.error_code or "backtest_failed"], {"result": "failed"}
    if not observation.result_ref:
        return "unknown", ["result_reference_missing"], {"result": "unknown"}
    missing = [key for key in _REQUIRED_METRICS if key not in observation.metrics]
    details = {
        "result": "passed",
        "metrics": "passed",
        "trades": "passed",
        "drawdown": "passed",
        "concentration": "not_applicable",
    }
    reasons: list[str] = []
    if missing:
        details["metrics"] = "unknown"
        reasons.append("missing_metrics:" + ",".join(missing))
        return "unknown", reasons, details
    if observation.metrics["trade_count"] < policy.min_trade_count:
        details["trades"] = "failed"
        reasons.append("trade_count_below_minimum")
    if observation.metrics["max_drawdown_pct"] > policy.max_drawdown_pct:
        details["drawdown"] = "failed"
        reasons.append("drawdown_exceeds_policy")
    concentration = observation.metrics.get("largest_trade_contribution_pct")
    if concentration is not None:
        details["concentration"] = "passed"
        if concentration > policy.max_largest_trade_contribution_pct:
            details["concentration"] = "failed"
            reasons.append("largest_trade_contribution_exceeds_policy")
    return ("failed" if reasons else "passed"), reasons, details


def _group_gate(
    rows: list[tuple[RobustnessScenario, str, list[str]]], *, required: bool
) -> RobustnessGateResult:
    if not rows:
        return RobustnessGateResult(
            outcome="unknown" if required else "not_applicable",
            required=required,
            reasons=["scenario_unavailable"] if required else [],
        )
    outcomes = {row[1] for row in rows}
    outcome = "failed" if "failed" in outcomes else "unknown" if "unknown" in outcomes else "passed"
    return RobustnessGateResult(
        outcome=outcome,
        required=required,
        reasons=sorted({reason for _, _, reasons in rows for reason in reasons}),
        scenario_ids=[row[0].scenario_id for row in rows],
    )


def _degradation_gate(
    rows: list[tuple[RobustnessScenario, str, list[str]]],
    *,
    by_id: dict[str, ScenarioObservation],
    baseline: ScenarioObservation | None,
    maximum: Decimal,
    required: bool,
) -> RobustnessGateResult:
    base_gate = _group_gate(rows, required=required)
    if base_gate.outcome != "passed" or not rows:
        return base_gate
    baseline_return = _metric(baseline, "total_return_pct")
    if baseline_return is None:
        return RobustnessGateResult(
            outcome="unknown", required=required, reasons=["baseline_return_missing"]
        )
    floor = baseline_return - (abs(baseline_return) * maximum / Decimal("100"))
    degraded: list[str] = []
    for scenario, _, _ in rows:
        observed_return = _metric(by_id.get(scenario.scenario_id), "total_return_pct")
        if observed_return is None or observed_return < floor:
            degraded.append(scenario.scenario_id)
    if degraded:
        return RobustnessGateResult(
            outcome="failed",
            required=required,
            reasons=["return_degradation_exceeds_policy"],
            scenario_ids=degraded,
        )
    return base_gate


def _run_projection(
    run: RobustnessValidationRun, scenarios: Sequence[RobustnessScenarioResult]
) -> dict[str, Any]:
    return {
        "id": run.id,
        "schema_version": "robustness_validation_run.v2",
        "experiment_execution_id": run.experiment_execution_id,
        "fingerprint": run.fingerprint,
        "policy_version": run.policy_version,
        "policy_hash": run.policy_hash,
        "status": run.status,
        "final_status": run.final_status,
        "gates": dict(run.gate_results_json),
        "summary": dict(run.summary_json),
        "unknowns": list(run.unknowns_json),
        "plan": dict(run.plan_json),
        "scenarios": [
            {
                "id": row.id,
                "scenario_id": row.scenario_id,
                "kind": row.kind,
                "required": row.required,
                "status": row.status,
                "window": dict(row.window_json),
                "parameters": dict(row.parameters_json),
                "costs": dict(row.costs_json),
                "regime": row.regime,
                "result_ref": dict(row.result_ref_json),
                "metrics": dict(row.metrics_json),
                "gates": dict(row.gate_results_json),
                "error": dict(row.error_json),
            }
            for row in scenarios
        ],
        "created_by": run.created_by,
        "created_at": run.created_at.isoformat(),
    }


def _even_starts(*, max_start: int, count: int) -> list[int]:
    if count == 1:
        return [max_start]
    return [round(index * max_start / (count - 1)) for index in range(count)]


def _metric(observation: ScenarioObservation | None, key: str) -> Decimal | None:
    return observation.metrics.get(key) if observation is not None else None


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("candle timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _safe_key(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in value)
    return cleaned.strip("_").lower() or "parameter"
