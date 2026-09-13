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
