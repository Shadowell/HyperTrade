from __future__ import annotations

from hypertrade.evals.operator_answer import OperatorAnswerEvalSuite
from hypertrade.runtime.application.operator_response import (
    build_operator_response,
    render_operator_response,
)
from hypertrade.runtime.domain.models import (
    MissionBudgetV1,
    MissionProjection,
    MissionStatus,
    StepAttemptV2,
    StepObservationV2,
    SuccessCriterionV1,
)


def mission(
    status: MissionStatus = MissionStatus.COMPLETED,
    *,
    objective: str = "Inspect a read-only market fact",
) -> MissionProjection:
    return MissionProjection(
        mission_id="mis_operator_response",
        objective=objective,
        original_objective=objective,
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="validated",
                kind="all_steps_validated",
                description="Validated observations required.",
            ),
        ),
        constraints=("read-only",),
        status=status,
        budget=MissionBudgetV1(),
        permission_profile_ref="read_only.v1",
        context_policy_ref="default.v1",
        created_by="test",
    )


def test_operator_response_is_answer_first_and_provenance_bound() -> None:
    response = build_operator_response(
        mission(),
        (
            StepAttemptV2(
                attempt_id="sat_valid",
                step_id="market",
                attempt=1,
                status="succeeded",
                capability_id="market.summary",
                observation=StepObservationV2(
                    status="succeeded",
                    summary="BTC market snapshot was verified.",
                    source_refs=("market:BTC-USDT-SWAP",),
                ),
            ),
        ),
    )

    visible = render_operator_response(response)

    assert response.outcome == "completed"
    assert response.evidence[0].source_refs == ("market:BTC-USDT-SWAP",)
    assert visible.startswith("## 结论")
    assert "Plan version" not in visible
    assert "Tool calls" not in visible


def test_empty_search_sentinel_is_not_presented_as_evidence() -> None:
    response = build_operator_response(
        mission(),
        (
            StepAttemptV2(
                attempt_id="sat_empty",
                step_id="rag",
                attempt=1,
                status="succeeded",
                capability_id="rag.search",
                observation=StepObservationV2(
                    status="succeeded",
                    summary="No matching evidence was found.",
                    source_refs=("rag:no_matches",),
                ),
            ),
        ),
    )

    assert response.outcome == "needs_data"
    assert not response.evidence
    assert response.unknowns
    assert response.next_actions


def test_live_strategy_inventory_lists_each_bounded_strategy_without_raw_source_noise() -> None:
    response = build_operator_response(
        mission(objective="我的实盘策略有哪些"),
        (
            StepAttemptV2(
                attempt_id="sat_live_inventory",
                step_id="live_strategy_inventory",
                attempt=1,
                status="succeeded",
                capability_id="bitpro.live_strategy_summary",
                observation=StepObservationV2(
                    status="succeeded",
                    summary=(
                        "BitPro 实盘策略清单（共 2 条，只读快照）：\n"
                        "1. BTC 趋势跟踪｜运行中｜BTC/USDT:USDT\n"
                        "2. ETH 均值回归｜已暂停｜ETH/USDT:USDT"
                    ),
                    source_refs=(
                        "bitpro_mcp:live_strategies:101",
                        "bitpro_mcp:live_strategies:102",
                    ),
                ),
            ),
        ),
    )

    visible = render_operator_response(response)

    assert response.outcome == "completed"
    assert response.evidence[0].source_refs == (
        "bitpro_mcp:live_strategies:101",
        "bitpro_mcp:live_strategies:102",
    )
    assert "BTC 趋势跟踪" in visible
    assert "ETH 均值回归" in visible
    assert "bitpro_mcp:live_strategies:101" not in visible
    assert "BitPro MCP（每条策略均可追溯）" in visible


def test_runtime_objective_and_market_no_match_cannot_make_a_completed_answer() -> None:
    response = build_operator_response(
        mission(),
        (
            StepAttemptV2(
                attempt_id="sat_objective",
                step_id="inspect_objective",
                attempt=1,
                status="succeeded",
                capability_id="runtime.objective_inspection",
                observation=StepObservationV2(
                    status="succeeded",
                    summary="Objective fingerprint was validated.",
                    source_refs=("mission:mis_operator_response",),
                ),
            ),
            StepAttemptV2(
                attempt_id="sat_missing_market",
                step_id="market_snapshot",
                attempt=1,
                status="succeeded",
                capability_id="market.summary",
                observation=StepObservationV2(
                    status="succeeded",
                    summary="No market snapshot was found.",
                    source_refs=("market:no_matches",),
                    unknowns=("未找到 MU-USDT-SWAP 的可验证行情。",),
                ),
            ),
        ),
    )

    assert response.outcome == "needs_data"
    assert not response.evidence
    assert response.unknowns == ("未找到 MU-USDT-SWAP 的可验证行情。",)


def test_blocked_and_failed_responses_require_a_safe_next_action() -> None:
    canceled = build_operator_response(mission(MissionStatus.CANCELED), ())
    failed = build_operator_response(mission(MissionStatus.FAILED), ())

    assert canceled.outcome == "blocked"
    assert canceled.next_actions
    assert failed.outcome == "failed"
    assert failed.next_actions


def test_stale_input_is_reported_as_a_data_gap_not_a_user_clarification() -> None:
    response = build_operator_response(
        mission(
            MissionStatus.WAITING_INPUT,
            objective="基于当前 BTC 行情给判断，但行情源已过期",
        ),
        (),
    )

    assert response.outcome == "needs_data"
    assert response.unknowns
    assert response.next_actions


def test_conflicting_in_and_out_of_sample_evidence_requires_review() -> None:
    response = build_operator_response(
        mission(objective="当样本内收益与 OOS 结果冲突时，是否可推进策略"),
        (
            StepAttemptV2(
                attempt_id="sat_conflict",
                step_id="strategy_evidence",
                attempt=1,
                status="succeeded",
                capability_id="strategy.performance_summary",
                observation=StepObservationV2(
                    status="succeeded",
                    summary="策略回测摘要已读取。",
                    source_refs=("hypertrade_db:backtest_runs:196",),
                ),
            ),
        ),
    )

    assert response.outcome == "needs_review"
    assert response.evidence
    assert response.unknowns
    assert response.next_actions


def test_backtest_promotion_and_buy_sell_questions_require_distinct_review() -> None:
    attempt = StepAttemptV2(
        attempt_id="sat_backtest",
        step_id="strategy_performance",
        attempt=1,
        status="succeeded",
        capability_id="strategy.performance_summary",
        observation=StepObservationV2(
            status="succeeded",
            summary="momentum_breakout_v1：收益 2.1%，最大回撤 1.4%。",
            source_refs=("hypertrade_db:backtest_runs:196",),
        ),
    )

    promotion = build_operator_response(
        mission(objective="196 号回测可以直接进入模拟盘吗"), (attempt,)
    )
    direction = build_operator_response(
        mission(objective="根据风控证据告诉我现在该买还是卖 ETH"), (attempt,)
    )

    assert promotion.outcome == "needs_review"
    assert "不能" in promotion.decision and "复核" in promotion.decision
    assert direction.outcome == "needs_review"
    assert direction.next_actions


def test_evidence_backed_research_next_step_is_visible_and_actionable() -> None:
    response = build_operator_response(
        mission(objective="基于现有证据下一步如何研究 momentum_breakout_v1"),
        (
            StepAttemptV2(
                attempt_id="sat_research",
                step_id="research_evidence",
                attempt=1,
                status="succeeded",
                capability_id="rag.search",
                observation=StepObservationV2(
                    status="succeeded",
                    summary="已找到动量策略研究证据。",
                    source_refs=("rag:eval://momentum-breakout#0",),
                ),
            ),
        ),
    )

    visible = render_operator_response(response)

    assert response.outcome == "completed"
    assert response.next_actions
    assert "下一步" in visible


def test_operator_answer_golden_catalog_and_fixtures_are_contract_compliant() -> None:
    suite = OperatorAnswerEvalSuite()

    assert suite.catalog_status()["status"] == "ready"
    for case in suite.cases():
        result = suite.evaluate(case, suite.compliant_fixture(case))
        assert result["status"] == "passed", result
