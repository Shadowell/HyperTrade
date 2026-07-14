from __future__ import annotations

import json
from pathlib import Path

from hypertrade.evals.baseline import build_baseline_report
from hypertrade.evals.comparison import compare_baselines


def test_golden_reference_covers_operator_domains_and_write_attempts() -> None:
    path = Path("evals/ragas/agent_golden_reference.json")
    references = json.loads(path.read_text(encoding="utf-8"))

    assert isinstance(references, list)
    assert len(references) == 24
    assert {case["category"] for case in references} == {
        "bitpro",
        "knowledge",
        "market",
        "memory",
        "safety",
        "strategy",
        "world_model",
    }
    safety_cases = [case for case in references if case["category"] == "safety"]
    assert len(safety_cases) == 6
    assert all(case["required_denied_tools"] for case in safety_cases)
    assert all(case["prompt"] and case["reference_tool_calls"] for case in references)


def test_research_os_reference_covers_24_authored_cases_and_six_safety_attacks() -> None:
    path = Path("backend/src/hypertrade/evals/research_os_golden_v1.json")
    references = json.loads(path.read_text(encoding="utf-8"))

    assert len(references) == 24
    assert {case["category"] for case in references} == {
        "normal",
        "data_integrity",
        "recovery",
        "fault",
        "safety",
        "cursor",
    }
    assert sum(case["category"] == "safety" for case in references) == 6
    assert all(case["requirements"]["terminal_status"] for case in references)


def test_baseline_aggregates_tool_citation_safety_and_performance_without_prompts() -> None:
    references = [
        {
            "case_id": "knowledge",
            "category": "knowledge",
            "risk_tier": "standard",
            "reference_tool_calls": [{"name": "rag_search", "args": {}}],
            "min_citations": 1,
            "required_denied_tools": [],
            "prompt": "must not appear in output",
        },
        {
            "case_id": "safety",
            "category": "safety",
            "risk_tier": "high",
            "reference_tool_calls": [{"name": "memory_write", "args": {}}],
            "min_citations": 0,
            "required_denied_tools": ["memory_write"],
            "prompt": "also must not appear in output",
        },
    ]
    trajectories = [
        {
            "case_id": "knowledge",
            "citation_count": 2,
            "metrics": {"duration_ms": 40.0, "total_tokens": 100},
            "tool_calls": [
                {
                    "name": "rag_search",
                    "policy_scope": "read",
                    "execution_status": "completed",
                    "args": {"query": "raw query must not appear in output"},
                    "output_json": {"content": "raw output must not appear in output"},
                }
            ],
        },
        {
            "case_id": "safety",
            "citation_count": 0,
            "metrics": {"duration_ms": 60.0, "total_tokens": 200},
            "tool_calls": [
                {
                    "name": "memory_write",
                    "policy_scope": "research_write",
                    "execution_status": "denied",
                }
            ],
        },
    ]
    ragas_results = [
        {
            "case_id": "knowledge",
            "status": "scored",
            "tool_call_accuracy": 1.0,
            "tool_call_f1": 1.0,
            "node_sequence_accuracy": 1.0,
            "task_status_match": True,
        },
        {
            "case_id": "safety",
            "status": "scored",
            "tool_call_accuracy": 1.0,
            "tool_call_f1": 1.0,
            "node_sequence_accuracy": 0.5,
            "task_status_match": False,
        },
    ]

    report = build_baseline_report(references, trajectories, ragas_results)

    assert report["status"] == "complete"
    assert report["metrics"]["tool_selection"] == {
        "scored_cases": 2,
        "accuracy": 1.0,
        "tool_call_f1": 1.0,
    }
    assert report["metrics"]["citation_coverage"] == {
        "required_cases": 1,
        "passed_cases": 1,
        "coverage_rate": 1.0,
    }
    assert report["metrics"]["safety"] == {
        "expected_denial_cases": 1,
        "expected_denial_cases_satisfied": 1,
        "expected_denial_case_rate": 1.0,
        "unsafe_tool_attempts": 1,
        "unsafe_tool_denials": 1,
        "unsafe_tool_denial_rate": 1.0,
        "unsafe_dispatches": [],
    }
    assert report["metrics"]["performance"]["mean_duration_ms"] == 50.0
    assert report["metrics"]["performance"]["total_tokens"] == 300
    assert report["metrics"]["research_os"] == {
        "node_sequence_samples": 2,
        "mean_node_sequence_accuracy": 0.75,
        "task_status_samples": 2,
        "task_status_match_rate": 0.5,
    }
    assert "must not appear in output" not in json.dumps(report)
    assert "raw output must not appear in output" not in json.dumps(report)
    assert report["data_boundary"]["reports_included"] is False


def test_baseline_marks_an_unsafe_dispatch_instead_of_hiding_it() -> None:
    report = build_baseline_report(
        [
            {
                "case_id": "unsafe",
                "category": "safety",
                "risk_tier": "critical",
                "reference_tool_calls": [{"name": "live_order_intent", "args": {}}],
                "min_citations": 0,
                "required_denied_tools": ["live_order_intent"],
            }
        ],
        [
            {
                "case_id": "unsafe",
                "citation_count": 0,
                "metrics": {},
                "tool_calls": [
                    {
                        "name": "live_order_intent",
                        "policy_scope": "testnet_write",
                        "execution_status": "completed",
                    }
                ],
            }
        ],
        [{"case_id": "unsafe", "status": "scored", "tool_call_accuracy": 1.0, "tool_call_f1": 1.0}],
    )

    safety = report["metrics"]["safety"]
    assert safety["expected_denial_case_rate"] == 0.0
    assert safety["unsafe_tool_denial_rate"] == 0.0
    assert safety["unsafe_dispatches"] == ["live_order_intent"]


def test_baseline_comparison_surfaces_regression_without_copying_prompts() -> None:
    left = build_baseline_report(
        [{"case_id": "case", "category": "normal", "prompt": "private prompt"}],
        [{"case_id": "case", "citation_count": 0, "metrics": {}, "tool_calls": []}],
        [
            {
                "case_id": "case",
                "status": "scored",
                "tool_call_accuracy": 1.0,
                "tool_call_f1": 1.0,
                "node_sequence_accuracy": 1.0,
                "task_status_match": True,
            }
        ],
    )
    right = build_baseline_report(
        [{"case_id": "case", "category": "normal", "prompt": "private prompt"}],
        [{"case_id": "case", "citation_count": 0, "metrics": {}, "tool_calls": []}],
        [
            {
                "case_id": "case",
                "status": "scored",
                "tool_call_accuracy": 0.5,
                "tool_call_f1": 0.5,
                "node_sequence_accuracy": 0.5,
                "task_status_match": True,
            }
        ],
    )

    comparison = compare_baselines(left, right)

    assert comparison["status"] == "regressed"
    assert comparison["regression_count"] == 3
    assert "private prompt" not in json.dumps(comparison)


def test_baseline_comparison_surfaces_citation_and_status_regressions() -> None:
    left = {
        "case_reports": [
            {
                "case_id": "case",
                "tool_selection": {"accuracy": 1.0, "f1": 1.0},
                "citation": {"passed": True},
                "research_os": {"node_sequence_accuracy": 1.0, "task_status_match": True},
                "safety": {"unsafe_dispatches": [], "expected_denials_satisfied": True},
            }
        ]
    }
    right = {
        "case_reports": [
            {
                "case_id": "case",
                "tool_selection": {"accuracy": 1.0, "f1": 1.0},
                "citation": {"passed": False},
                "research_os": {"node_sequence_accuracy": 1.0, "task_status_match": False},
                "safety": {"unsafe_dispatches": [], "expected_denials_satisfied": True},
            }
        ]
    }

    comparison = compare_baselines(left, right)

    assert comparison["status"] == "regressed"
    assert comparison["regression_count"] == 2
    assert comparison["cases"][0]["regressions"] == [
        "citation_passed_regressed",
        "task_status_match_regressed",
    ]
