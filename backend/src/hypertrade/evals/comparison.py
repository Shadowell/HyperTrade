"""Prompt-free comparison for two isolated Research OS baselines."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def compare_baselines(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_cases = _case_map(left)
    right_cases = _case_map(right)
    case_ids = sorted(set(left_cases) | set(right_cases))
    cases: list[dict[str, Any]] = []
    regression_count = 0
    improvement_count = 0
    for case_id in case_ids:
        before = left_cases.get(case_id)
        after = right_cases.get(case_id)
        regressions: list[str] = []
        improvements: list[str] = []
        if before is None:
            improvements.append("case_added")
        elif after is None:
            regressions.append("case_missing")
        else:
            _compare_score(
                regressions,
                improvements,
                "tool_call_accuracy",
                _nested(before, "tool_selection", "accuracy"),
                _nested(after, "tool_selection", "accuracy"),
            )
            _compare_score(
                regressions,
                improvements,
                "node_sequence_accuracy",
                _nested(before, "research_os", "node_sequence_accuracy"),
                _nested(after, "research_os", "node_sequence_accuracy"),
            )
            if _nested(before, "safety", "unsafe_dispatches") == [] and _nested(
                after, "safety", "unsafe_dispatches"
            ):
                regressions.append("unsafe_dispatch_introduced")
            if (
                _nested(before, "safety", "expected_denials_satisfied") is True
                and _nested(after, "safety", "expected_denials_satisfied") is False
            ):
                regressions.append("expected_denial_regressed")
        regression_count += len(regressions)
        improvement_count += len(improvements)
        cases.append(
            {
                "case_id": case_id,
                "regressions": regressions,
                "improvements": improvements,
            }
        )
    return {
        "schema_version": "research_os_baseline_comparison.v1",
        "status": "regressed" if regression_count else "stable_or_improved",
        "left_case_count": len(left_cases),
        "right_case_count": len(right_cases),
        "regression_count": regression_count,
        "improvement_count": improvement_count,
        "cases": cases,
        "data_boundary": {
            "prompts_included": False,
            "reports_included": False,
            "tool_arguments_included": False,
            "raw_tool_outputs_included": False,
            "credentials_included": False,
        },
    }


def _case_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = report.get("case_reports")
    rows = value if isinstance(value, list) else []
    return {
        str(row.get("case_id", "")): dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("case_id")
    }


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _compare_score(
    regressions: list[str],
    improvements: list[str],
    label: str,
    before: Any,
    after: Any,
) -> None:
    if not isinstance(before, int | float) or not isinstance(after, int | float):
        return
    if float(after) < float(before):
        regressions.append(f"{label}_decreased")
    elif float(after) > float(before):
        improvements.append(f"{label}_increased")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two safe Research OS baselines.")
    parser.add_argument("--left", required=True, type=Path)
    parser.add_argument("--right", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = compare_baselines(
        json.loads(args.left.read_text(encoding="utf-8")),
        json.loads(args.right.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: report[key] for key in ("status", "regression_count")}, indent=2))
    return 1 if report["status"] == "regressed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
