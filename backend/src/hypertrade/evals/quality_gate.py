"""Fail a release check unless every isolated quality-v2 baseline passes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate_reports(paths: list[Path]) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    expected_count: int | None = None
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"baseline must be an object: {path}")
        case_count = int(payload.get("case_count", 0))
        quality = payload.get("metrics", {}).get("quality_v2", {})
        quality = quality if isinstance(quality, dict) else {}
        report = {
            "path": path.name,
            "case_count": case_count,
            "status": quality.get("status", "missing"),
            "failures": list(quality.get("failures", [])),
        }
        reports.append(report)
        if expected_count is None:
            expected_count = case_count
        if case_count != expected_count:
            report["failures"].append("case_denominator_changed")
        if report["status"] != "passed" or report["failures"]:
            failures.append(report)
    return {
        "schema_version": "agent_research_quality_gate.v2",
        "status": "passed" if len(paths) >= 2 and not failures else "failed",
        "run_count": len(paths),
        "fixed_case_count": expected_count or 0,
        "reports": reports,
        "failure_count": len(failures),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate isolated quality-v2 baselines.")
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    result = validate_reports(args.reports)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
