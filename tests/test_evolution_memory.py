from copy import deepcopy
from datetime import date

import pytest
from hypertrade.arc.contracts import ResearchWindowsV1
from hypertrade.arc.evolution_memory import curate_memory, experiment_key

WINDOWS = ResearchWindowsV1(as_of=date(2026, 9, 12))


def record(**changes):
    start, end = WINDOWS.window("development")
    result = {
        "mission_id": "source",
        "candidate_id": "candidate",
        "code_sha256": "a" * 64,
        "hypothesis": "reduce churn",
        "spec": {"symbol": "SOL-USDT-SWAP", "timeframe": "1H", "family": "ma_crossover"},
        "capital": "100",
        "development": {
            "purpose": "development",
            "code_sha256": "a" * 64,
            "backtest_id": "receipt",
            "passed": False,
            "reasons": ["net_return_too_low"],
            "metrics": {
                "config_sha256": "d" * 64,
                "cost_policy_hash": "c" * 64,
                "net_return": -0.1,
                "max_drawdown": 0.2,
                "evaluation_window": {
                    "purpose": "development",
                    "start_date": str(start),
                    "end_date": str(end),
                },
            },
        },
    }
    result.update(changes)
    return result


def curate(records):
    return curate_memory(records, symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS)


def test_memory_is_a_bounded_source_bound_projection_not_raw_metrics():
    item = record()
    item["development"]["metrics"]["nested"] = {"final_score": 999, "token": "secret"}
    item["spec"]["source_code"] = "private code"
    before = deepcopy(item)
    entries, manifest = curate([item])
    assert len(entries) == 1
    assert "999" not in str(entries) and "private code" not in str(entries)
    assert entries[0]["evidence_status"] == "development_only"
    assert manifest["selected"] == 1
    assert len(manifest["digest"]) == 64
    assert item == before


@pytest.mark.parametrize(
    "fault", ["symbol", "timeframe", "final", "future", "nan", "identity", "unknown"]
)
def test_incompatible_or_unsettled_experience_is_excluded(fault):
    item = record()
    if fault in {"symbol", "timeframe"}:
        item["spec"][fault] = "OTHER"
    elif fault == "final":
        item["development"]["purpose"] = "final"
    elif fault == "future":
        item["development"]["metrics"]["evaluation_window"]["end_date"] = "2026-09-12"
    elif fault == "nan":
        item["development"]["metrics"]["net_return"] = float("nan")
    elif fault == "identity":
        item["development"]["code_sha256"] = "b" * 64
    else:
        item["development"]["backtest_id"] = None
    entries, manifest = curate([item])
    assert entries == []
    assert sum(manifest["excluded"].values()) == 1


def test_memory_deduplicates_receipts_and_retains_failed_experiments():
    passed = record(candidate_id="positive")
    passed["development"]["passed"] = True
    passed["development"]["backtest_id"] = "positive"
    entries, manifest = curate([record(), record(), passed])
    assert len(entries) == 2
    assert {e["development"]["passed"] for e in entries} == {False, True}
    assert manifest["excluded"]["duplicate_receipt"] == 1


def test_experiment_identity_binds_capital_window_instrument_and_code():
    a = record()
    base = experiment_key(a["code_sha256"], a["spec"], a["capital"], WINDOWS)
    assert base != experiment_key(a["code_sha256"], a["spec"], "200", WINDOWS)
    assert base != experiment_key(a["code_sha256"], {**a["spec"], "symbol": "X"}, "100", WINDOWS)
    assert base == experiment_key(a["code_sha256"], a["spec"], "100.0", WINDOWS)


def test_cross_task_repeat_requires_reason_and_preserves_budget_and_source():
    from hypertrade.arc.avo import _perform
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.store import reset_store

    reset_store()
    goal = ARCGoalV1(
        objective="trend",
        research_mode="avo",
        paper_review_required=True,
        symbols=["SOL-USDT-SWAP"],
        research_windows=WINDOWS,
    )
    old = ARCController(goal=goal.model_copy(deep=True))
    request = {"provider": "test", "model": "test", "request_hash": "hash"}
    old.apply_event("avo_model_requested", request)
    args = {
        "hypothesis": "trend",
        "family_key": "ma_crossover",
        "direction": "long_only",
        "parameter_bounds": {},
    }
    original = _perform(old, "propose", args, None)
    candidate = old.projection.attempts[0]
    key = experiment_key(original["code_sha256"], candidate.strategy_spec, "100", WINDOWS)
    goal.evolution_context = {"memory": [{"experiment_key": key, "memory_id": "prior"}]}
    args["evolution_hypothesis"] = {
        "evidence_refs": ["prior"],
        "expected_metric": "net_return",
        "expected_direction": "increase",
        "falsification": "No gain on the same development window",
    }
    new = ARCController(goal=goal)
    new.apply_event("avo_model_requested", request)
    with pytest.raises(ValueError, match="repeat_reason"):
        _perform(new, "propose", args, None)
    assert new.projection.goal.budget.candidates_used == 0
    accepted = _perform(
        new, "propose", {**args, "repeat_reason": "Verify corrected data revision"}, None
    )
    assert accepted["repeated_memory_ids"] == ["prior"]
    assert new.projection.goal.budget.candidates_used == 1
    assert (
        new.projection.attempts[0].strategy_spec["repeat_reason"]
        == "Verify corrected data revision"
    )
    assert len(old.projection.attempts) == 1
    reset_store()


def test_evolution_proposal_rejects_missing_or_invented_evidence():
    from hypertrade.arc.evolution_memory import bind_hypothesis

    with pytest.raises(ValueError, match="requires"):
        bind_hypothesis({}, {}, {})
    proposal = {"evolution_hypothesis": {"evidence_refs": ["invented"]}}
    with pytest.raises(ValueError, match="unavailable"):
        bind_hypothesis(proposal, {}, {})


def test_context_budget_keeps_counterexamples_and_does_not_grow_forever():
    rows = []
    for i in range(80):
        item = record(candidate_id=str(i))
        item["development"]["backtest_id"] = str(i)
        item["development"]["passed"] = i < 60
        rows.append(item)
    entries, manifest = curate(rows)
    assert len(entries) == 20
    assert manifest["supporting"] == manifest["opposing"] == 10
    assert manifest["excluded"]["context_budget"] == 60
    assert sum(len(__import__("json").dumps(e)) for e in entries) < 50000


@pytest.mark.parametrize("field", ["spec", "development"])
def test_malformed_history_does_not_break_the_next_research_cycle(field):
    entries, manifest = curate([record(**{field: None}), record()])
    assert len(entries) == 1
    assert manifest["excluded"]["malformed_receipt"] == 1


@pytest.mark.parametrize(
    "metric,old,new,direction,expected",
    [
        ("net_return", -0.1, 0.1, "increase", "observed"),
        ("net_return", 0.1, -0.1, "increase", "not_observed"),
        ("max_drawdown", 0.2, 0.1, "decrease", "observed"),
        ("trade_count", 40, 40, "decrease", "not_observed"),
    ],
)
def test_development_assessment_checks_the_predicted_metric_direction(
    metric, old, new, direction, expected
):
    from hypertrade.arc.evolution_memory import assess_hypothesis

    entry = curate([record()])[0][0]
    entry["development"]["metrics"] = {metric: old}
    spec = {
        **entry["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entry["memory_id"]],
            "expected_metric": metric,
            "expected_direction": direction,
        },
    }
    result = assess_hypothesis(
        spec, {**record()["development"]["metrics"], metric: new}, [entry], WINDOWS, "100"
    )
    assert result["status"] == expected
    assert result["scope"] == "development_metric_direction_only"
    assert result["causal_claim_verified"] is False


def test_assessment_does_not_compare_different_capitals_or_windows():
    from hypertrade.arc.evolution_memory import assess_hypothesis

    entry = curate([record()])[0][0]
    spec = {
        **entry["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entry["memory_id"]],
            "expected_metric": "net_return",
            "expected_direction": "increase",
        },
    }
    assert (
        assess_hypothesis(spec, {"net_return": 9}, [entry], WINDOWS, "200")["status"] == "unknown"
    )
    entry["development"]["window"][1] = "2026-07-01"
    assert (
        assess_hypothesis(spec, {"net_return": 9}, [entry], WINDOWS, "100")["status"] == "unknown"
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_window",
        "wrong_window",
        "final_window",
        "bad_reference",
        "bad_spec",
        "bad_capital",
        "missing_receipt",
        "wrong_symbol",
        "wrong_timeframe",
        "nan",
        "invalid_direction",
        "invalid_metric",
    ],
)
def test_assessment_returns_unknown_for_unverifiable_comparisons(fault):
    from hypertrade.arc.evolution_memory import assess_hypothesis

    entry = curate([record()])[0][0]
    spec = {
        **entry["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entry["memory_id"]],
            "expected_metric": "net_return",
            "expected_direction": "increase",
        },
    }
    metrics = {**record()["development"]["metrics"], "net_return": 0.3}
    if fault == "missing_window":
        metrics.pop("evaluation_window")
    elif fault == "wrong_window":
        metrics["evaluation_window"]["end_date"] = "2026-01-01"
    elif fault == "final_window":
        metrics["evaluation_window"]["purpose"] = "final"
    elif fault == "bad_reference":
        entry["development"] = None
    elif fault == "bad_spec":
        entry["spec"] = None
    elif fault == "bad_capital":
        entry["capital"] = "NaN"
    elif fault == "missing_receipt":
        entry["development"].pop("backtest_id")
    elif fault in {"wrong_symbol", "wrong_timeframe"}:
        entry["spec"] = {**entry["spec"], fault.removeprefix("wrong_"): "OTHER"}
    elif fault == "nan":
        metrics["net_return"] = float("nan")
    elif fault == "invalid_direction":
        spec["evolution_hypothesis"]["expected_direction"] = "sideways"
    else:
        spec["evolution_hypothesis"]["expected_metric"] = "invented"
    assert assess_hypothesis(spec, metrics, [entry], WINDOWS, "100")["status"] == "unknown"


def test_development_assessment_survives_event_storage_and_next_memory_recall():
    import hashlib

    from hypertrade.arc.avo import _perform
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController, ARCMissionProjection
    from hypertrade.arc.self_test import SelfTestResult
    from hypertrade.arc.store import reset_store

    class Experiments:
        def run(self, candidate, goal, *, purpose):
            assert purpose == "development"
            return SelfTestResult(
                True,
                "validation",
                "123",
                "new-receipt",
                metrics={**record()["development"]["metrics"], "net_return": 0.2},
            )

    reset_store()
    try:
        memory = curate([record()])[0]
        ctrl = ARCController(
            goal=ARCGoalV1(
                objective="improve",
                research_mode="avo",
                paper_review_required=True,
                symbols=["SOL-USDT-SWAP"],
                research_windows=WINDOWS,
                evolution_context={"memory": memory},
            )
        )
        ctrl.apply_event(
            "avo_model_requested", {"provider": "test", "model": "test", "request_hash": "hash"}
        )
        proposal = _perform(
            ctrl,
            "propose",
            {
                "hypothesis": "reduce churn",
                "family_key": "ma_crossover",
                "direction": "long_only",
                "parameter_bounds": {},
                "evolution_hypothesis": {
                    "evidence_refs": [memory[0]["memory_id"]],
                    "expected_metric": "net_return",
                    "expected_direction": "increase",
                    "falsification": "No same-window gain",
                },
            },
            None,
        )
        result = _perform(ctrl, "develop", {"attempt_id": proposal["attempt_id"]}, Experiments())
        assert result["hypothesis_assessment"]["status"] == "observed"
        restored = ARCMissionProjection.model_validate_json(ctrl.projection.model_dump_json())
        candidate = restored.attempts[0]
        receipt = restored.avo["development"][candidate.attempt_id]
        assert receipt["hypothesis_assessment"] == result["hypothesis_assessment"]
        recalled, _ = curate(
            [
                record(
                    spec=candidate.strategy_spec,
                    candidate_id=candidate.candidate_id,
                    code_sha256=hashlib.sha256(candidate.strategy_code.encode()).hexdigest(),
                    development=receipt,
                )
            ]
        )
        assert recalled[0]["hypothesis_assessment"]["status"] == "observed"
        assert recalled[0]["hypothesis_assessment"]["causal_claim_verified"] is False
        assert candidate.paper_instance_id is None
        assert restored.goal.budget.backtests_used == 1
        assert memory[0]["development"]["metrics"]["net_return"] == -0.1
    finally:
        reset_store()


def test_assessment_normalizes_percentages_and_reports_conflicting_references():
    from hypertrade.arc.evolution_memory import assess_hypothesis

    entries = curate([record(), record(candidate_id="other")])[0]
    other = deepcopy(entries[0])
    other["memory_id"] = "other"
    other["development"]["backtest_id"] = "other"
    other["development"]["metrics"] = {"total_return_pct": 30}
    spec = {
        **entries[0]["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entries[0]["memory_id"], "other"],
            "expected_metric": "net_return",
            "expected_direction": "increase",
        },
    }
    metrics = {
        "config_sha256": "d" * 64,
        "cost_policy_hash": "c" * 64,
        "total_return_pct": 20,
        "evaluation_window": record()["development"]["metrics"]["evaluation_window"],
    }
    result = assess_hypothesis(spec, metrics, [*entries, other, other], WINDOWS, "100.0")
    assert result["status"] == "mixed"
    assert len(result["comparisons"]) == 2
    assert [c["after"] for c in result["comparisons"]] == [0.2, 0.2]


def test_assessment_rejects_overflowed_delta_and_malformed_hypothesis():
    from hypertrade.arc.evolution_memory import assess_hypothesis

    entry = curate([record()])[0][0]
    entry["development"]["metrics"] = {"net_return": -1e308}
    spec = {
        **entry["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entry["memory_id"]],
            "expected_metric": "net_return",
            "expected_direction": "increase",
        },
    }
    metrics = {**record()["development"]["metrics"], "net_return": 1e308}
    assert assess_hypothesis(spec, metrics, [entry], WINDOWS, "100")["status"] == "unknown"
    spec["evolution_hypothesis"]["expected_metric"] = []
    assert assess_hypothesis(spec, metrics, [entry], WINDOWS, "100")["status"] == "unknown"


@pytest.mark.parametrize(
    "old_hash,new_hash", [(None, "c" * 64), ("c" * 64, None), ("a" * 64, "c" * 64)]
)
def test_metric_improvement_is_unknown_without_matching_cost_evidence(old_hash, new_hash):
    from hypertrade.arc.evolution_memory import assess_hypothesis

    item = record()
    item["development"]["metrics"]["cost_policy_hash"] = old_hash
    entry = curate([item])[0][0]
    spec = {
        **entry["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entry["memory_id"]],
            "expected_metric": "net_return",
            "expected_direction": "increase",
        },
    }
    metrics = {
        **record()["development"]["metrics"],
        "net_return": 0.4,
        "cost_policy_hash": new_hash,
    }
    result = assess_hypothesis(spec, metrics, [entry], WINDOWS, "100")
    assert result["status"] == "unknown"
    assert result["causal_claim_verified"] is False


def test_legacy_assessment_without_cost_identity_is_not_recalled_as_verified_direction():
    item = record()
    item["development"]["metrics"].pop("cost_policy_hash", None)
    item["development"]["hypothesis_assessment"] = {
        "status": "observed",
        "metric": "net_return",
        "direction": "increase",
        "scope": "development_metric_direction_only",
    }
    entries, _ = curate([item])
    assert len(entries) == 1
    assert entries[0]["cost_policy_hash"] is None
    assert entries[0]["hypothesis_assessment"]["status"] == "unknown"


def test_one_matching_reference_cannot_hide_a_cited_cost_mismatch():
    from hypertrade.arc.evolution_memory import assess_hypothesis

    entries = curate([record()])[0]
    other = deepcopy(entries[0])
    other["memory_id"] = "different-cost"
    other["cost_policy_hash"] = "d" * 64
    spec = {
        **entries[0]["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entries[0]["memory_id"], other["memory_id"]],
            "expected_metric": "net_return",
            "expected_direction": "increase",
        },
    }
    result = assess_hypothesis(
        spec,
        {**record()["development"]["metrics"], "net_return": 0.3},
        [*entries, other],
        WINDOWS,
        "100",
    )
    assert len(result["comparisons"]) == 1
    assert result["status"] == "unknown"
    assert result["incomparable_cost_references"] == 1
