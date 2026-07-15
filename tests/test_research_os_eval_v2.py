from __future__ import annotations

from hypertrade.agent.planner import TOOL_SCHEMAS
from hypertrade.agent.quality import build_candidate_tool_set, research_intent_for_prompt
from hypertrade.evals.research_os import ResearchOSEvalSuite, load_research_os_cases
from hypertrade.evals.trajectory import build_trajectory_from_api_payload


def test_manifest_declares_fixed_denominators_and_applicability() -> None:
    cases = load_research_os_cases()

    assert len(cases) == 26
    assert {case.cohort for case in cases} == {
        "chat_answer",
        "tool_required",
        "research_graph",
        "safety",
    }
    assert all(case.graph_applicable == bool(case.requirements.required_nodes) for case in cases)
    assert all(case.provider_terminal_status == "completed" for case in cases)
    assert all(case.provider_required_nodes for case in cases if case.cohort == "research_graph")
    assert all(
        not case.provider_required_nodes for case in cases if case.cohort != "research_graph"
    )


def test_deterministic_suite_keeps_authored_system_fault_outcomes() -> None:
    report = ResearchOSEvalSuite().status()

    assert report["status"] == "passed"
    fault = next(item for item in report["cases"] if item["case_id"] == "fault_provider_rate_limit")
    assert fault["status"] == "passed"
    assert fault["cohort"] == "research_graph"


def test_authored_eval_intent_projects_zero_or_required_only_candidates() -> None:
    for case in load_research_os_cases():
        intent = research_intent_for_prompt(case.prompt, evaluation_mode=True)
        candidates = build_candidate_tool_set(intent, TOOL_SCHEMAS)
        expected = set(case.required_tools)
        assert candidates.included_names == expected


def test_trajectory_reads_kernel_graph_without_prompt_or_tool_payloads() -> None:
    trajectory = build_trajectory_from_api_payload(
        "case",
        {
            "id": "run_1",
            "status": "completed",
            "run_state_json": {
                "execution_mode": "evaluation",
                "graph": [
                    {"node": "intent_classify", "input": {"prompt": "private"}, "output": {}},
                    {"node": "plan_tools", "input": {}, "output": {}},
                ],
            },
            "report_json": {"tool_calls": []},
            "trace_events": [],
        },
    )

    assert [node["node_key"] for node in trajectory["research_os"]["nodes"]] == [
        "intent_classify",
        "plan_tools",
    ]
    assert "private" not in str(trajectory)
