from __future__ import annotations

from hypertrade.evals.research_os import ResearchOSEvalSuite


def test_professional_readiness_suite_covers_long_horizon_failure_modes() -> None:
    report = ResearchOSEvalSuite().status()

    assert report["status"] == "passed"
    assert report["case_count"] >= 20
    assert report["categories"]["recovery"] >= 1
    assert report["categories"]["fault"] >= 1
    assert report["categories"]["safety"] >= 1
    assert report["categories"]["cursor"] >= 1
    assert all(case["status"] == "passed" for case in report["cases"])


def test_readiness_has_no_unsafe_dispatch_or_false_completion() -> None:
    report = ResearchOSEvalSuite().status()

    findings = [finding for case in report["cases"] for finding in case["findings"]]
    assert not any(
        item["code"] in {"dangerous_tool_dispatched", "write_scope_not_fail_closed"}
        for item in findings
    )
