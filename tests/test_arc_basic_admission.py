from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest
from hypertrade.arc.admission import (
    BASIC_ADMISSION_VERSION,
    basic_admission,
    basic_admitted,
    basic_validation_id,
)
from hypertrade.arc.auto_review import evaluate_auto_review
from hypertrade.arc.avo import _perform, _recover_receipt
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCSuccessCriteriaV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import EvolutionConfig
from hypertrade.arc.paper_review import build_paper_review, request_paper_review
from hypertrade.arc.self_test import ARCSelfTestService
from hypertrade.arc.store import reset_store, save_mission
from test_source_variant_avo import HYPOTHESIS, MockSelfTestClient

WINDOW = {
    "purpose": "final",
    "start_date": "2026-01-01",
    "end_date": "2026-03-01",
    "research_id": "baseline-research",
}


def _metrics(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "evaluation_window": dict(WINDOW),
        "net_return": 0.10,
        "max_drawdown": 0.05,
        "trades": 40,
    }
    values.update(overrides)
    return values


def _baseline(**overrides: Any) -> dict[str, Any]:
    return {"backtest_id": "bt-base", "metrics": _metrics(**overrides)}


def _build_mission() -> ARCController:
    variant_policy = {
        "contract_version": "strategy_research_variant_policy.v1",
        "parent_strategy_id": 107,
        "parent_manifest_sha256": "a" * 64,
        "parent_execution_identity_sha256": "e" * 64,
        "variant_creation_supported": True,
        "authorized_parameters": [
            {
                "name": "fast_window",
                "type": "int",
                "minimum": 5,
                "maximum": 50,
                "current_value": 10,
            },
        ],
    }
    baseline_attempt = ARCCandidateAttemptV1(
        attempt_id="baseline_107",
        candidate_id="baseline_107",
        hypothesis="原策略基线",
        strategy_code="class NativeStrategy107: pass\n",
        strategy_spec={
            "symbol": "BTC-USDT",
            "timeframe": "1H",
            "is_source_variant": True,
            "parent_strategy_id": 107,
            "parent_manifest_sha256": "a" * 64,
            "parent_execution_identity_sha256": "e" * 64,
            "tunable_parameters": {"fast_window": 10},
            "baseline_config": {"fast_window": 10},
        },
    )
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="对107号策略进行参数调优",
            symbols=["BTC-USDT"],
            timeframes=["1H"],
            paper_review_required=True,
            research_mode="avo",
            budget=ARCBudgetV1(max_candidates=5, max_backtests=10),
            success_criteria=ARCSuccessCriteriaV1(required_validation_policy="arc_windowed_v1"),
            evolution_context={
                "source_strategy_id": 107,
                "paper_feedback": {"status": "observed"},
                "variant_policy": variant_policy,
                "baseline": baseline_attempt.model_dump(mode="json"),
            },
        )
    )
    save_mission(ctrl)
    return ctrl


@pytest.fixture
def mission():
    reset_store()
    ctrl = _build_mission()
    yield ctrl
    reset_store()


def _window(ctrl: ARCController) -> dict[str, Any]:
    goal = ctrl.projection.goal
    assert goal is not None and goal.research_windows is not None
    start, end = goal.research_windows.window("final")
    return {
        "purpose": "final",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "research_id": goal.research_id,
    }


class CandidateClient(MockSelfTestClient):
    """Baseline and candidate differ only in their final metrics."""

    def __init__(self, candidate: dict[str, Any], baseline: dict[str, Any]) -> None:
        super().__init__()
        self._candidate = candidate
        self._baseline = baseline
        self._baseline_ids: set[int] = set()

    def strategy_research_variant_create(self, *, purpose: str = "candidate", **kwargs: Any):
        created = super().strategy_research_variant_create(purpose=purpose, **kwargs)
        if purpose == "baseline":
            self._baseline_ids.add(int(created["candidate_strategy_id"]))
        return created

    def backtest_start_job(self, **kwargs: Any) -> dict[str, Any]:
        result = super().backtest_start_job(**kwargs)
        strategy_id = int(kwargs["strategy_id"])
        result["metrics"] = dict(
            self._baseline if strategy_id in self._baseline_ids else self._candidate
        )
        result["job"] = {
            "status": "completed",
            "strategy_input_snapshot": {
                "runtime_sha256": "a" * 64,
                "cost_policy_hash": "b" * 64,
                "initial_capital": kwargs["initial_capital"],
                "symbols": ["BTC-USDT"],
                "timeframes": [kwargs["timeframe"]],
                "start_date": kwargs["start_date"],
                "end_date": kwargs["end_date"],
            },
            "verified_data_binding": {
                "version": "verified_backtest_data.v3",
                "entries": [{"verified_snapshot_id": "vbs", "manifest_sha256": "d" * 64}],
            },
        }
        return result


def _candidate_metrics(**overrides: Any) -> dict[str, Any]:
    values = {"net_return": 0.185, "sharpe": 1.8, "max_drawdown": 0.05, "trades": 40}
    values.update(overrides)
    return values


def _baseline_metrics(**overrides: Any) -> dict[str, Any]:
    values = {"net_return": 0.20, "sharpe": 1.8, "max_drawdown": 0.05, "trades": 40}
    values.update(overrides)
    return values


def _propose(ctrl: ARCController, service: ARCSelfTestService) -> str:
    return str(
        _perform(
            ctrl,
            "propose",
            {
                "hypothesis": "提高快线周期至15以过滤假突破",
                "evolution_hypothesis": HYPOTHESIS,
                "parameter_changes": {"fast_window": 15},
            },
            service,
        )["attempt_id"]
    )


def _run_to_finish(
    ctrl: ARCController,
    *,
    candidate: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
) -> tuple[str, ARCSelfTestService]:
    client = CandidateClient(candidate or _candidate_metrics(), baseline or _baseline_metrics())
    service = ARCSelfTestService(client=client)
    if "started_at" not in ctrl.projection.avo:
        ctrl.apply_event("avo_initialized", {"messages": []})
    attempt_id = _propose(ctrl, service)
    _perform(ctrl, "develop", {"attempt_id": attempt_id}, service)
    _perform(ctrl, "finish", {"attempt_id": attempt_id}, service)
    return attempt_id, service


def _attempt(ctrl: ARCController, attempt_id: str) -> ARCCandidateAttemptV1:
    return next(a for a in ctrl.projection.attempts if a.attempt_id == attempt_id)


# ---------------------------------------------------------------------------
# basic_admission unit tests
# ---------------------------------------------------------------------------


def test_basic_admission_admits_a_candidate_within_two_points():
    result = basic_admission(_metrics(net_return=0.09), _baseline())
    assert result["version"] == BASIC_ADMISSION_VERSION
    assert result["passed"] is True
    assert result["reasons"] == []
    assert result["checks"]["return_tolerance"] == "0.025"


def test_basic_admission_rejects_a_shortfall_beyond_tolerance():
    result = basic_admission(_metrics(net_return=0.05), _baseline())
    assert result["passed"] is False
    assert result["reasons"] == ["return_shortfall"]


def test_basic_admission_tolerance_grows_with_half_the_parent_drawdown():
    baseline = _baseline(max_drawdown=0.10)
    within = basic_admission(_metrics(net_return=0.06, max_drawdown=0.10), baseline)
    beyond = basic_admission(_metrics(net_return=0.04, max_drawdown=0.10), baseline)
    assert within["passed"] is True
    assert within["checks"]["return_tolerance"] == "0.05"
    assert beyond["passed"] is False
    assert beyond["reasons"] == ["return_shortfall"]


def test_basic_admission_rejects_drawdown_more_than_five_points_worse():
    result = basic_admission(_metrics(max_drawdown=0.16), _baseline(max_drawdown=0.10))
    assert result["passed"] is False
    assert result["reasons"] == ["drawdown_too_large"]
    assert result["checks"]["drawdown_limit"] == "0.15"


def test_basic_admission_caps_drawdown_at_thirty_percent_even_for_a_worse_parent():
    result = basic_admission(_metrics(max_drawdown=0.31), _baseline(max_drawdown=0.35))
    assert result["passed"] is False
    assert result["reasons"] == ["drawdown_too_large"]
    assert result["checks"]["drawdown_limit"] == "0.30"


def test_basic_admission_rejects_zero_or_too_few_trades():
    zero = basic_admission(_metrics(trades=0), _baseline(trades=40))
    few = basic_admission(_metrics(trades=11), _baseline(trades=40))
    assert zero["reasons"] == ["too_few_trades"]
    assert few["reasons"] == ["too_few_trades"]
    assert few["checks"]["required_trades"] == "12"


def test_basic_admission_reads_percentage_spellings():
    candidate = {
        "evaluation_window": dict(WINDOW),
        "total_return_pct": 9.0,
        "max_drawdown_pct": 5.0,
        "trade_count": 40,
    }
    baseline = {
        "backtest_id": "bt-base",
        "metrics": {
            "evaluation_window": dict(WINDOW),
            "total_return_pct": 10.0,
            "max_drawdown_pct": 5.0,
            "trade_count": 40,
        },
    }
    result = basic_admission(candidate, baseline)
    assert result["passed"] is True
    assert result["checks"]["candidate_return"] == "0.09"


def test_basic_admission_reports_a_missing_metric():
    candidate = _metrics()
    del candidate["trades"]
    result = basic_admission(candidate, _baseline())
    assert result["passed"] is False
    assert result["reasons"] == ["metric_missing:candidate_trades"]

    parent = _baseline()
    del parent["metrics"]["trades"]
    result = basic_admission(_metrics(), parent)
    assert result["reasons"] == ["metric_missing:parent_trades"]


def test_basic_admission_rejects_incomparable_windows():
    candidate = _metrics(evaluation_window={**WINDOW, "end_date": "2026-04-01"})
    result = basic_admission(candidate, _baseline())
    assert result["passed"] is False
    assert result["reasons"] == ["baseline_evidence_invalid"]


def test_basic_admission_is_deterministic():
    candidate, baseline = _metrics(net_return=0.06, max_drawdown=0.10), _baseline(
        max_drawdown=0.10
    )
    assert basic_admission(candidate, baseline) == basic_admission(candidate, baseline)


def test_basic_validation_id_is_content_bound():
    receipt = {
        "attempt_id": "att_1",
        "backtest_id": "bt_1",
        "code_sha256": "a" * 64,
        "bitpro_strategy_id": "9003",
        "admission": {"version": BASIC_ADMISSION_VERSION, "passed": True},
    }
    assert basic_validation_id(receipt).startswith("val_basic_")
    assert basic_validation_id(receipt) != basic_validation_id({**receipt, "backtest_id": "bt_2"})


# ---------------------------------------------------------------------------
# AVO flow
# ---------------------------------------------------------------------------


def test_basic_admission_lets_a_slightly_worse_candidate_reach_paper_review(mission):
    mission.projection.goal.paper_admission = "basic"
    attempt_id, _ = _run_to_finish(mission)

    record = mission.projection.self_test_records[-1]
    assert record["attempt_id"] == attempt_id
    assert record["passed"] is False
    assert "baseline_not_improved" in record["reasons"]
    assert record["admitted"] is True
    assert record["admission"]["passed"] is True
    assert record["validation_id"].startswith("val_basic_")
    assert basic_admitted(mission.projection.goal, record) is True
    assert _attempt(mission, attempt_id).state == "validated"
    assert mission.projection.state == "paper_review_ready"
    package = build_paper_review(mission.projection)
    assert package["unknowns"] == []
    assert package["admission"]["policy"] == "basic"


def test_strict_admission_keeps_the_failed_candidate_with_the_operator(mission):
    assert mission.projection.goal.paper_admission == "strict"
    attempt_id, _ = _run_to_finish(mission)

    record = mission.projection.self_test_records[-1]
    assert record["passed"] is False
    assert "admitted" not in record
    assert "admission" not in record
    assert _attempt(mission, attempt_id).state != "validated"
    assert mission.projection.state == "needs_operator"
    assert mission.projection.events[-1].payload["reason"] == "avo_final_validation_failed"
    assert "admission" not in build_paper_review(mission.projection)


def test_basic_admission_still_rejects_a_clearly_worse_candidate(mission):
    mission.projection.goal.paper_admission = "basic"
    attempt_id, _ = _run_to_finish(
        mission,
        candidate=_candidate_metrics(net_return=0.10),
        baseline=_baseline_metrics(net_return=0.20),
    )

    record = mission.projection.self_test_records[-1]
    assert record["passed"] is False
    assert record["admission"]["passed"] is False
    assert "return_shortfall" in record["admission"]["reasons"]
    assert "admitted" not in record
    assert _attempt(mission, attempt_id).state != "validated"
    assert mission.projection.state == "needs_operator"


def test_strict_review_package_keys_are_unchanged(mission):
    attempt_id = _propose(mission, ARCSelfTestService(client=CandidateClient({}, {})))
    attempt = _attempt(mission, attempt_id)
    window = _window(mission)
    metrics = {
        "evaluation_window": window,
        "net_return": 0.20,
        "max_drawdown": 0.05,
        "trades": 40,
        "selection_bias": {"status": "observed"},
        "baseline_comparison": {"passed": True, "backtest_id": "bt-base"},
    }
    mission.apply_event(
        "bitpro_self_tested",
        {
            "attempt_id": attempt_id,
            "purpose": "final",
            "passed": True,
            "reasons": [],
            "bitpro_strategy_id": "9003",
            "backtest_id": "bt-candidate",
            "validation_id": "val_arc_strict",
            "code_sha256": hashlib.sha256(attempt.strategy_code.encode()).hexdigest(),
            "metrics": metrics,
        },
    )
    request_paper_review(mission)
    package = build_paper_review(mission.projection)
    assert package["status"] == "ready"
    assert "admission" not in package
    assert set(package) == {
        "schema_version",
        "mission_id",
        "attempt_id",
        "strategy",
        "backtest",
        "criteria",
        "feedback_policy",
        "paper_configuration",
        "research_windows",
        "evolution_source",
        "package_hash",
        "status",
        "unknowns",
        "kind",
        "recommendation",
    }
    binding = {
        key: value
        for key, value in package.items()
        if key not in {"package_hash", "status", "unknowns", "kind", "recommendation"}
    }
    assert package["package_hash"] == hashlib.sha256(
        json.dumps(binding, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def test_auto_review_approves_a_basic_admitted_mission_and_rechecks_the_numbers(mission):
    mission.projection.goal.paper_admission = "basic"
    _run_to_finish(mission)

    evaluation = evaluate_auto_review(
        mission, EvolutionConfig(enabled=True, paper_review_mode="agent")
    )
    assert evaluation["decision"] == "approve"
    assert evaluation["admission"] == "basic"
    assert evaluation["reasons"] == []

    # The stored strict result is still False; tampering its numbers must fail the recheck.
    mission.projection.self_test_records[-1]["metrics"]["net_return"] = -0.5
    tampered = evaluate_auto_review(
        mission, EvolutionConfig(enabled=True, paper_review_mode="agent")
    )
    assert tampered["decision"] == "reject"
    assert tampered["admission"] == "basic"
    assert any(
        reason.startswith("basic:") or reason == "basic_admission_receipt_mismatch"
        for reason in tampered["reasons"]
    )


def test_recovery_finishes_an_admitted_receipt_without_repeating_the_backtest(mission):
    mission.projection.goal.paper_admission = "basic"
    service = ARCSelfTestService(client=CandidateClient(_candidate_metrics(), _baseline_metrics()))
    attempt_id = _propose(mission, service)
    attempt = _attempt(mission, attempt_id)
    mission.apply_event(
        "avo_final_requested", {"attempt_id": attempt_id, "tool_call_id": "call-recover"}
    )

    window = _window(mission)
    candidate_metrics = {
        "evaluation_window": window,
        "net_return": 0.185,
        "max_drawdown": 0.05,
        "trades": 40,
        "baseline_comparison": {"passed": False, "backtest_id": "bt-base"},
    }
    baseline_receipt = {
        "backtest_id": "bt-base",
        "metrics": {
            "evaluation_window": window,
            "net_return": 0.20,
            "max_drawdown": 0.05,
            "trades": 40,
        },
    }
    admission = basic_admission(candidate_metrics, baseline_receipt)
    assert admission["passed"] is True
    receipt = {
        "attempt_id": attempt_id,
        "tool_call_id": "call-recover",
        "purpose": "final",
        "passed": False,
        "reasons": ["baseline_not_improved"],
        "bitpro_strategy_id": "9003",
        "backtest_id": "bt-candidate",
        "code_sha256": hashlib.sha256(attempt.strategy_code.encode()).hexdigest(),
        "metrics": candidate_metrics,
        "admission": admission,
        "admitted": True,
    }
    receipt["validation_id"] = basic_validation_id(receipt)
    mission.apply_event("bitpro_self_tested", receipt)
    mission.projection.avo["baseline_final"] = baseline_receipt
    mission.projection.avo["pending"] = {
        "kind": "tool",
        "id": "call-recover",
        "name": "finish",
        "arguments": {"attempt_id": attempt_id},
    }

    _recover_receipt(mission)

    assert _attempt(mission, attempt_id).state == "validated"
    assert mission.projection.avo["pending"] is None
    assert mission.projection.state == "paper_review_ready"
    assert build_paper_review(mission.projection)["admission"]["policy"] == "basic"


def test_basic_admitted_rejects_a_tampered_final_receipt(mission):
    mission.projection.goal.paper_admission = "basic"
    _run_to_finish(mission)
    goal = mission.projection.goal
    record = copy.deepcopy(mission.projection.self_test_records[-1])
    assert record["admitted"] is True
    assert basic_admitted(goal, record) is True

    # (a) One number inside the admission evidence moves.
    tampered_checks = copy.deepcopy(record)
    tampered_checks["admission"]["checks"]["candidate_return"] = "0.0001"
    assert tampered_checks["admission"]["checks"] != record["admission"]["checks"]
    assert basic_admitted(goal, tampered_checks) is False

    # (b) A well-formed but different val_basic_... id.
    tampered_id = copy.deepcopy(record)
    tampered_id["validation_id"] = basic_validation_id(
        {**record, "backtest_id": "bt-somewhere-else"}
    )
    assert tampered_id["validation_id"].startswith("val_basic_")
    assert tampered_id["validation_id"] != record["validation_id"]
    assert basic_admitted(goal, tampered_id) is False

    # The review package must notice either tamper on the stored record.
    for tampered in (tampered_checks, tampered_id):
        mission.projection.self_test_records[-1] = copy.deepcopy(tampered)
        package = build_paper_review(mission.projection)
        assert "missing_matching_final_validation_receipt" in package["unknowns"]
        assert package["status"] != "ready"


def test_basic_admitted_requires_the_basic_goal_policy(mission):
    mission.projection.goal.paper_admission = "basic"
    _run_to_finish(mission)
    admitted = copy.deepcopy(mission.projection.self_test_records[-1])
    assert basic_admitted(mission.projection.goal, admitted) is True

    strict_goal = mission.projection.goal.model_copy(update={"paper_admission": "strict"})
    assert strict_goal.paper_admission == "strict"
    assert basic_admitted(strict_goal, admitted) is False

    # Replaying that receipt into a strict mission must not produce a ready package.
    assert _attempt(mission, admitted["attempt_id"]).state == "validated"
    mission.projection.self_test_records[-1] = copy.deepcopy(admitted)
    mission.projection.goal = strict_goal
    package = build_paper_review(mission.projection)
    assert package["status"] != "ready"
    assert "admission" not in package
    assert {
        "missing_matching_final_validation_receipt",
        "missing_or_failed_baseline_comparison",
    } & set(package["unknowns"])


def test_basic_review_package_omits_admission_when_basic_admission_fails(mission):
    mission.projection.goal.paper_admission = "basic"
    _run_to_finish(
        mission,
        candidate=_candidate_metrics(net_return=0.10),
        baseline=_baseline_metrics(net_return=0.20),
    )

    record = mission.projection.self_test_records[-1]
    assert record["admission"]["passed"] is False
    assert "admitted" not in record

    package = build_paper_review(mission.projection)
    assert "admission" not in package
