from __future__ import annotations

from hypertrade.evals.operator_answer import OperatorAnswerEvalSuite, OperatorAnswerObservation
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


def test_operator_answer_catalog_covers_operator_journeys() -> None:
    suite = OperatorAnswerEvalSuite()

    status = suite.catalog_status()

    assert status["status"] == "ready"
    assert status["case_count"] >= 24
    assert set(status["cohorts"]) == {
        "context",
        "delivery",
        "execution",
        "market",
        "portfolio",
        "strategy",
    }


def test_operator_answer_evaluator_accepts_compliant_contract_fixtures() -> None:
    suite = OperatorAnswerEvalSuite()

    results = [suite.evaluate(case, suite.compliant_fixture(case)) for case in suite.cases()]

    assert all(result["status"] == "passed" for result in results)


def test_operator_answer_evaluator_rejects_internal_noise_and_missing_context() -> None:
    suite = OperatorAnswerEvalSuite()
    case = next(item for item in suite.cases() if item.case_id == "strategy_followup_trading_data")
    observation = suite.compliant_fixture(case)
    noisy = OperatorAnswerObservation(
        response=(
            observation.response.model_copy(update={"context_refs": ()})
            if observation.response
            else None
        ),
        visible_text="## 结论\nMission: mis_1\nPlan version: 1",
        event_types=observation.event_types,
        first_public_event_ms=observation.first_public_event_ms,
    )

    result = suite.evaluate(case, noisy)

    assert result["status"] == "failed"
    assert "context_resolution" in result["failed_checks"]


def test_mission_operator_response_is_compact_and_source_bound() -> None:
    mission = _mission()
    attempts = (
        StepAttemptV2(
            attempt_id="mat_1",
            step_id="market_summary",
            attempt=1,
            status="succeeded",
            capability_id="market_summary",
            observation=StepObservationV2(
                status="succeeded",
                summary="ETH 1H 市场数据已验证，价格与成交量来自受控行情源。",
                source_refs=("okx:ETH-USDT-SWAP",),
            ),
        ),
    )

    response = build_operator_response(mission, attempts)
    markdown = render_operator_response(response)

    assert response.outcome == "completed"
    assert response.evidence[0].source_refs == ("okx:ETH-USDT-SWAP",)
    assert markdown.startswith("## 结论")
    assert "Plan version" not in markdown
    assert "Tool calls" not in markdown
    assert "Mission:" not in markdown


def test_mission_operator_response_refuses_to_fill_missing_evidence() -> None:
    mission = _mission(status=MissionStatus.COMPLETED, unknowns=("MUUSDT 不存在可验证行情。",))

    response = build_operator_response(mission, ())
    markdown = render_operator_response(response)

    assert response.outcome == "needs_data"
    assert response.confidence == "not_assessed"
    assert response.next_actions
    assert "MUUSDT 不存在可验证行情。" in markdown
    assert "不能给出交易判断" not in markdown


def _mission(
    *,
    status: MissionStatus = MissionStatus.COMPLETED,
    unknowns: tuple[str, ...] = (),
) -> MissionProjection:
    return MissionProjection(
        mission_id="mis_operator_response",
        objective="读取受控市场证据",
        original_objective="读取受控市场证据",
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="sources",
                kind="minimum_sources",
                description="至少保留一个来源。",
                expected=1,
            ),
        ),
        constraints=("只读。",),
        status=status,
        budget=MissionBudgetV1(),
        permission_profile_ref="read_only.v1",
        context_policy_ref="mission_context.v1",
        created_by="test",
        unknowns=unknowns,
    )
