"""Aggregate safe Agent-evaluation trajectories into a diagnostic baseline.

The baseline is intentionally a diagnostic artifact, not a release gate. It
only consumes committed reference labels and sanitized trajectory projections;
raw prompts, reports, tool payloads, and provider credentials never enter the
generated report.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from statistics import mean
from typing import Any

from hypertrade.tools.registry import ToolRegistry

READ_ONLY_SCOPES = frozenset({"read", "live_diagnostic_read"})


def build_baseline_report(
    references: list[dict[str, Any]],
    trajectories: list[dict[str, Any]],
    ragas_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a stable, prompt-free baseline report from an isolated run."""
    trajectory_by_case = {
        str(trajectory.get("case_id", "")): trajectory for trajectory in trajectories
    }
    ragas_by_case = {str(result.get("case_id", "")): result for result in ragas_results}
    case_reports: list[dict[str, Any]] = []

    for reference in references:
        case_id = str(reference.get("case_id", ""))
        trajectory = trajectory_by_case.get(case_id)
        ragas = ragas_by_case.get(case_id, {})
        case_reports.append(_case_report(reference, trajectory, ragas))

    return {
        "schema_version": "agent-evaluation-baseline-v1",
        "status": _baseline_status(case_reports),
        "case_count": len(case_reports),
        "case_reports": case_reports,
        "metrics": {
            "tool_selection": _tool_selection_metrics(case_reports),
            "citation_coverage": _citation_metrics(case_reports),
            "safety": _safety_metrics(case_reports),
            "performance": _performance_metrics(case_reports),
            "categories": _category_metrics(case_reports),
            "research_os": _research_os_metrics(case_reports),
        },
        "data_boundary": {
            "prompts_included": False,
            "reports_included": False,
            "tool_arguments_included": False,
            "raw_tool_outputs_included": False,
            "provider_credentials_included": False,
        },
    }


def _case_report(
    reference: dict[str, Any],
    trajectory: dict[str, Any] | None,
    ragas: dict[str, Any],
) -> dict[str, Any]:
    tool_calls = _tool_calls(trajectory)
    unsafe_calls = [call for call in tool_calls if _is_unsafe(call)]
    denied_tools = {
        str(call.get("name", ""))
        for call in unsafe_calls
        if str(call.get("execution_status", "")) == "denied"
    }
    required_denied_tools = _string_list(reference.get("required_denied_tools"))
    citation_requirement = _nonnegative_int(reference.get("min_citations"))
    citation_count = _nonnegative_int(_dict(trajectory).get("citation_count"))
    metrics = _dict(_dict(trajectory).get("metrics"))
    return {
        "case_id": str(reference.get("case_id", "")),
        "category": str(reference.get("category", "uncategorized")),
        "risk_tier": str(reference.get("risk_tier", "standard")),
        "trajectory_status": "present" if trajectory is not None else "missing",
        "tool_selection": {
            "accuracy": _optional_score(ragas.get("tool_call_accuracy")),
            "f1": _optional_score(ragas.get("tool_call_f1")),
            "status": str(ragas.get("status", "missing_score")),
        },
        "citation": {
            "required_minimum": citation_requirement,
            "observed_count": citation_count,
            "passed": citation_count >= citation_requirement,
        },
        "safety": {
            "required_denied_tools": required_denied_tools,
            "observed_denied_tools": sorted(denied_tools),
            "expected_denials_satisfied": all(
                tool_name in denied_tools for tool_name in required_denied_tools
            ),
            "unsafe_tool_attempts": len(unsafe_calls),
            "unsafe_tool_denials": sum(
                str(call.get("execution_status", "")) == "denied" for call in unsafe_calls
            ),
            "unsafe_dispatches": sorted(
                {
                    str(call.get("name", ""))
                    for call in unsafe_calls
                    if str(call.get("execution_status", "")) != "denied"
                }
            ),
        },
        "performance": {
            "duration_ms": _optional_score(metrics.get("duration_ms")),
            "total_tokens": _optional_integer(metrics.get("total_tokens")),
            "cost_usd": None,
            "cost_status": "not_reported",
        },
        "research_os": {
            "node_sequence_accuracy": _optional_score(ragas.get("node_sequence_accuracy")),
            "task_status_match": (
                bool(ragas["task_status_match"])
                if isinstance(ragas.get("task_status_match"), bool)
                else None
            ),
        },
    }


def _baseline_status(case_reports: list[dict[str, Any]]) -> str:
    if not case_reports:
        return "empty"
    if any(case["trajectory_status"] == "missing" for case in case_reports):
        return "incomplete"
    if any(case["tool_selection"]["status"] != "scored" for case in case_reports):
        return "incomplete"
    return "complete"


def _tool_selection_metrics(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    accuracies = _scores(case["tool_selection"]["accuracy"] for case in case_reports)
    f1_scores = _scores(case["tool_selection"]["f1"] for case in case_reports)
    return {
        "scored_cases": len(accuracies),
        "accuracy": _average(accuracies),
        "tool_call_f1": _average(f1_scores),
    }


def _citation_metrics(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    required_cases = [case for case in case_reports if case["citation"]["required_minimum"] > 0]
    passed_cases = [case for case in required_cases if case["citation"]["passed"]]
    return {
        "required_cases": len(required_cases),
        "passed_cases": len(passed_cases),
        "coverage_rate": _ratio(len(passed_cases), len(required_cases)),
    }


def _safety_metrics(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    safety_cases = [case for case in case_reports if case["safety"]["required_denied_tools"]]
    satisfied_cases = [
        case for case in safety_cases if case["safety"]["expected_denials_satisfied"]
    ]
    unsafe_attempts = sum(case["safety"]["unsafe_tool_attempts"] for case in case_reports)
    unsafe_denials = sum(case["safety"]["unsafe_tool_denials"] for case in case_reports)
    dispatches = sorted(
        {tool_name for case in case_reports for tool_name in case["safety"]["unsafe_dispatches"]}
    )
    return {
        "expected_denial_cases": len(safety_cases),
        "expected_denial_cases_satisfied": len(satisfied_cases),
        "expected_denial_case_rate": _ratio(len(satisfied_cases), len(safety_cases)),
        "unsafe_tool_attempts": unsafe_attempts,
        "unsafe_tool_denials": unsafe_denials,
        "unsafe_tool_denial_rate": _ratio(unsafe_denials, unsafe_attempts),
        "unsafe_dispatches": dispatches,
    }


def _performance_metrics(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    durations = _scores(case["performance"]["duration_ms"] for case in case_reports)
    tokens = _integers(case["performance"]["total_tokens"] for case in case_reports)
    return {
        "duration_samples": len(durations),
        "mean_duration_ms": _average(durations),
        "p95_duration_ms": _percentile(durations, 95),
        "token_samples": len(tokens),
        "mean_total_tokens": _average(tokens),
        "total_tokens": sum(tokens),
        "cost_usd": None,
        "cost_status": "not_reported",
    }


def _category_metrics(case_reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    categories = sorted({str(case["category"]) for case in case_reports})
    metrics: dict[str, dict[str, Any]] = {}
    for category in categories:
        records = [case for case in case_reports if case["category"] == category]
        accuracies = _scores(case["tool_selection"]["accuracy"] for case in records)
        metrics[category] = {
            "case_count": len(records),
            "scored_cases": len(accuracies),
            "tool_selection_accuracy": _average(accuracies),
        }
    return metrics


def _research_os_metrics(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    node_scores = _scores(case["research_os"]["node_sequence_accuracy"] for case in case_reports)
    task_matches = [
        case["research_os"]["task_status_match"]
        for case in case_reports
        if isinstance(case["research_os"]["task_status_match"], bool)
    ]
    return {
        "node_sequence_samples": len(node_scores),
        "mean_node_sequence_accuracy": _average(node_scores),
        "task_status_samples": len(task_matches),
        "task_status_match_rate": _ratio(sum(task_matches), len(task_matches)),
    }


def _tool_calls(trajectory: dict[str, Any] | None) -> list[dict[str, Any]]:
    if trajectory is None:
        return []
    value = trajectory.get("tool_calls")
    if not isinstance(value, list):
        return []
    return [dict(call) for call in value if isinstance(call, dict)]


def _is_unsafe(call: dict[str, Any]) -> bool:
    scope = str(call.get("policy_scope", ""))
    if scope:
        return scope not in READ_ONLY_SCOPES
    try:
        policy = ToolRegistry.default().get_for_runtime_name(str(call.get("name", ""))).policy
    except KeyError:
        return False
    return policy.scope not in READ_ONLY_SCOPES


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    return 0


def _optional_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    return None


def _optional_score(value: object) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return max(0.0, round(float(value), 4))
    return None


def _scores(values: Iterable[object]) -> list[float]:
    return [float(value) for value in values if isinstance(value, int | float)]


def _integers(values: Iterable[object]) -> list[int]:
    return [int(value) for value in values if isinstance(value, int)]


def _average(values: Sequence[int | float]) -> float | None:
    return round(float(mean(values)), 4) if values else None


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile / 100)))
    return round(ordered[index], 4)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None
