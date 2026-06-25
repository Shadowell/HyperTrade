from __future__ import annotations

from hypertrade.evals.service import AgentEvalSuite, EvalObservation


def test_eval_suite_exposes_sprint_53_cases_with_contract_fields() -> None:
    status = AgentEvalSuite().status()

    expected_cases = {
        "tool_selection",
        "rag_citation",
        "memory_behavior",
        "risk_refusal",
        "testnet_order_safety",
        "strategy_library_history_source",
        "bitpro_backtest_page_parity",
        "missing_artifact_disclosure",
        "paper_monitor_read_only",
        "compact_report_rendering",
        "live_order_history_source",
        "live_strategy_performance_source",
        "world_model_global_operator_state",
        "world_model_portfolio_review",
    }
    assert status["status"] == "passed"
    assert status["case_count"] == len(expected_cases)
    assert {case["name"] for case in status["cases"]} == expected_cases

    sprint_53_cases = {
        case["name"]: case
        for case in status["cases"]
        if case["name"]
        in {
            "strategy_library_history_source",
            "bitpro_backtest_page_parity",
            "missing_artifact_disclosure",
            "paper_monitor_read_only",
            "compact_report_rendering",
            "live_order_history_source",
            "live_strategy_performance_source",
        }
    }
    for case in sprint_53_cases.values():
        assert case["prompt"]
        assert case["required_tools"]
        assert "required_report_fragments" in case
        assert "forbidden_report_fragments" in case
        assert "expected_source_ids" in case
        assert "missing_data_expectations" in case


def test_strategy_library_eval_fails_without_strategy_library_tool() -> None:
    suite = AgentEvalSuite()
    case = suite.get_case("strategy_library_history_source")

    result = suite.evaluate_case(
        case,
        EvalObservation(
            prompt=case.prompt,
            tool_calls=["memory_search"],
            report_markdown=(
                "strategy_knowledge evidence from memory:mem_strategy_001; "
                "下一轮继续验证低频参数。"
            ),
            source_ids=["memory:mem_strategy_001"],
        ),
    )

    assert result["status"] == "failed"
    assert _finding_codes(result) == {"required_tool_missing", "forbidden_tool_used"}
    assert "strategy_library_search" in result["findings"][0]["message"]


def test_bitpro_page_parity_eval_rejects_memory_or_annualized_substitution() -> None:
    suite = AgentEvalSuite()
    case = suite.get_case("bitpro_backtest_page_parity")

    result = suite.evaluate_case(
        case,
        EvalObservation(
            prompt=case.prompt,
            tool_calls=["memory_search"],
            report_markdown=(
                "根据记忆，策略收益大于100%，annual_return_pct 是 142.4%，可以视为页面收益。"
            ),
            source_ids=["mem_strategy_001"],
        ),
    )

    assert result["status"] == "failed"
    assert {
        "required_tool_missing",
        "forbidden_tool_used",
        "forbidden_report_fragment",
        "source_id_missing",
    }.issubset(_finding_codes(result))


def test_missing_artifact_eval_fails_when_unavailable_artifact_disappears() -> None:
    suite = AgentEvalSuite()
    case = suite.get_case("missing_artifact_disclosure")

    result = suite.evaluate_case(
        case,
        EvalObservation(
            prompt=case.prompt,
            tool_calls=["bitpro_backtest_get_result"],
            report_markdown="result #196 已读取，订单和成交记录都完整。",
            source_ids=["bitpro_result:196"],
            missing_data=[],
        ),
    )

    assert result["status"] == "failed"
    assert "missing_data_not_reported" in _finding_codes(result)


def test_live_order_history_eval_rejects_market_summary_fallback() -> None:
    suite = AgentEvalSuite()
    case = suite.get_case("live_order_history_source")

    result = suite.evaluate_case(
        case,
        EvalObservation(
            prompt=case.prompt,
            tool_calls=["market_summary"],
            report_markdown="## 市场热度总结\nTop movers cannot answer live account orders.",
            source_ids=["okx_rest:market_summary"],
        ),
    )

    assert result["status"] == "failed"
    assert {
        "required_tool_missing",
        "forbidden_tool_used",
        "forbidden_report_fragment",
        "source_id_missing",
    }.issubset(_finding_codes(result))


def test_live_strategy_performance_eval_rejects_market_summary_fallback() -> None:
    suite = AgentEvalSuite()
    case = suite.get_case("live_strategy_performance_source")

    result = suite.evaluate_case(
        case,
        EvalObservation(
            prompt=case.prompt,
            tool_calls=["market_summary"],
            report_markdown="## Market Report\nTop Movers are not live strategy returns.",
            source_ids=["okx_rest:market_summary"],
        ),
    )

    assert result["status"] == "failed"
    assert {
        "required_tool_missing",
        "forbidden_tool_used",
        "forbidden_report_fragment",
        "source_id_missing",
    }.issubset(_finding_codes(result))


def test_world_model_eval_rejects_market_summary_fallback() -> None:
    suite = AgentEvalSuite()
    case = suite.get_case("world_model_global_operator_state")

    result = suite.evaluate_case(
        case,
        EvalObservation(
            prompt=case.prompt,
            tool_calls=["market_summary"],
            report_markdown="## 市场热度总结\n只看 OKX top movers，未形成全局 WorldState。",
            source_ids=["okx_rest:market_summary"],
        ),
    )

    assert result["status"] == "failed"
    assert {
        "required_tool_missing",
        "forbidden_tool_used",
        "forbidden_report_fragment",
        "source_id_missing",
        "missing_data_not_reported",
    }.issubset(_finding_codes(result))


def test_world_model_eval_rejects_missing_scenario_decision_evidence() -> None:
    suite = AgentEvalSuite()
    case = suite.get_case("world_model_global_operator_state")

    result = suite.evaluate_case(
        case,
        EvalObservation(
            prompt=case.prompt,
            tool_calls=["world_model_snapshot"],
            report_markdown=(
                "## 全局世界模型\nWorldState missing_data "
                "global_market.us_equities_unavailable"
            ),
            source_ids=["world_model:latest"],
            missing_data=["global_market.us_equities_unavailable"],
        ),
    )

    assert result["status"] == "failed"
    assert "required_report_fragment_missing" in _finding_codes(result)


def test_fixture_helpers_build_source_bound_tool_outputs_and_memory_evidence() -> None:
    tool_output = AgentEvalSuite.tool_output_fixture(
        "bitpro_backtest_list_results",
        source_id="bitpro_result:161",
        payload={"total_return_pct": "305.53"},
    )
    memory_evidence = AgentEvalSuite.strategy_memory_fixture(
        memory_id="mem_strategy_001",
        strategy_key="momentum_breakout_v1",
        backtest_id="bt_001",
    )

    assert tool_output == {
        "tool_name": "bitpro_backtest_list_results",
        "source_id": "bitpro_result:161",
        "payload": {"total_return_pct": "305.53"},
        "missing_data": [],
    }
    assert memory_evidence["kind"] == "strategy_knowledge"
    assert memory_evidence["source_id"] == "memory:mem_strategy_001"
    assert memory_evidence["strategy_key"] == "momentum_breakout_v1"
    assert memory_evidence["backtest_id"] == "bt_001"


def _finding_codes(result: dict[str, object]) -> set[str]:
    findings = result["findings"]
    assert isinstance(findings, list)
    return {str(finding["code"]) for finding in findings if isinstance(finding, dict)}
