from __future__ import annotations

import json
from pathlib import Path

from hypertrade.evals.baseline import build_baseline_report
from hypertrade.evals.quality_gate import validate_reports
from hypertrade.evals.service import AgentEvalSuite


def _reference(case_id: str, cohort: str, *, tool: str = "") -> dict:
    return {
        "case_id": case_id,
        "category": cohort,
        "risk_tier": "critical" if cohort == "safety" else "standard",
        "cohort": cohort,
        "prompt": f"private prompt {case_id}",
        "reference_tool_calls": [{"name": tool, "args": {}}] if tool else [],
        "min_citations": 1 if case_id == "source" else 0,
        "source_bound_answer": case_id == "source",
        "graph_applicable": cohort == "research_graph",
        "required_denied_tools": [tool] if cohort == "safety" else [],
    }


def test_quality_v2_uses_only_applicable_cohort_denominators_and_passes_thresholds() -> None:
    references = [
        _reference("chat", "chat_answer"),
        _reference("tool", "tool_required", tool="market_ticker"),
        _reference("source", "tool_required", tool="rag_search"),
        _reference("graph", "research_graph", tool="market_candles"),
        _reference("safety", "safety", tool="memory_write"),
    ]
    trajectories = [
        {
            "case_id": reference["case_id"],
            "status": "completed",
            "citation_count": 1 if reference["case_id"] == "source" else 0,
            "metrics": {"duration_ms": 1, "total_tokens": 2},
            "tool_calls": (
                [
                    {
                        "name": reference["reference_tool_calls"][0]["name"],
                        "execution_status": (
                            "denied" if reference["cohort"] == "safety" else "completed"
                        ),
                        "policy_scope": (
                            "research_write" if reference["cohort"] == "safety" else "read"
                        ),
                    }
                ]
                if reference["reference_tool_calls"]
                else []
            ),
        }
        for reference in references
    ]
    scores = [
        {
            "case_id": reference["case_id"],
            "status": "scored",
            "tool_call_accuracy": 1.0,
            "tool_call_f1": 1.0,
            "node_sequence_accuracy": 1.0 if reference["cohort"] == "research_graph" else None,
            "task_status_match": True,
        }
        for reference in references
    ]

    report = build_baseline_report(references, trajectories, scores)
    quality = report["metrics"]["quality_v2"]

    assert quality["status"] == "passed"
    assert quality["cohort_denominators"] == {
        "chat_answer": 1,
        "tool_required": 2,
        "research_graph": 1,
        "safety": 1,
    }
    assert quality["tool_route_accuracy"] == 1.0
    assert quality["graph_critical_sequence_rate"] == 1.0
    assert quality["unsafe_dispatch_count"] == 0
    serialized = json.dumps(report)
    assert "private prompt" not in serialized
    assert "args" not in serialized
    assert "private_reasoning_included" in serialized


def test_quality_v2_does_not_count_chat_or_graph_in_tool_route_denominator() -> None:
    references = [
        _reference("chat", "chat_answer"),
        _reference("tool", "tool_required", tool="market_ticker"),
        _reference("graph", "research_graph", tool="market_candles"),
    ]
    trajectories = [
        {"case_id": item["case_id"], "citation_count": 0, "metrics": {}, "tool_calls": []}
        for item in references
    ]
    scores = [
        {
            "case_id": "chat",
            "status": "scored",
            "tool_call_accuracy": 0.0,
            "tool_call_f1": 0.0,
            "task_status_match": True,
        },
        {
            "case_id": "tool",
            "status": "scored",
            "tool_call_accuracy": 1.0,
            "tool_call_f1": 1.0,
            "task_status_match": True,
        },
        {
            "case_id": "graph",
            "status": "scored",
            "tool_call_accuracy": 0.0,
            "tool_call_f1": 0.0,
            "node_sequence_accuracy": 1.0,
            "task_status_match": True,
        },
    ]

    quality = build_baseline_report(references, trajectories, scores)["metrics"]["quality_v2"]

    assert quality["tool_route_accuracy"] == 1.0


def test_two_run_gate_requires_fixed_denominator_and_passing_quality(tmp_path: Path) -> None:
    paths = [tmp_path / "one.json", tmp_path / "two.json"]
    for path in paths:
        path.write_text(
            json.dumps(
                {
                    "case_count": 26,
                    "metrics": {"quality_v2": {"status": "passed", "failures": []}},
                }
            ),
            encoding="utf-8",
        )

    result = validate_reports(paths)

    assert result["status"] == "passed"
    assert result["run_count"] == 2
    assert result["fixed_case_count"] == 26


def test_api_quality_projection_loads_only_aggregate_baseline(
    tmp_path: Path, monkeypatch
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "prompt": "must not project",
                "metrics": {
                    "quality_v2": {
                        "status": "failed",
                        "cohort_denominators": {"tool_required": 2},
                        "tool_route_accuracy": 0.5,
                        "failures": ["tool_route_accuracy_below_threshold"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HYPERTRADE_QUALITY_BASELINE_PATH", str(baseline))

    quality = AgentEvalSuite().status()["quality"]

    assert quality["provider_baseline"] == "loaded"
    assert quality["status"] == "failed"
    assert quality["failure_categories"] == {"tool_route_accuracy_below_threshold": 1}
    assert "must not project" not in json.dumps(quality)
