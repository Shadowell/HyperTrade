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


def mission(status: MissionStatus = MissionStatus.COMPLETED) -> MissionProjection:
    return MissionProjection(
        mission_id="mis_operator_response",
        objective="Inspect a read-only market fact",
        original_objective="Inspect a read-only market fact",
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


def test_blocked_and_failed_responses_require_a_safe_next_action() -> None:
    canceled = build_operator_response(mission(MissionStatus.CANCELED), ())
    failed = build_operator_response(mission(MissionStatus.FAILED), ())

    assert canceled.outcome == "blocked"
    assert canceled.next_actions
    assert failed.outcome == "failed"
    assert failed.next_actions


def test_operator_answer_golden_catalog_and_fixtures_are_contract_compliant() -> None:
    suite = OperatorAnswerEvalSuite()

    assert suite.catalog_status()["status"] == "ready"
    for case in suite.cases():
        result = suite.evaluate(case, suite.compliant_fixture(case))
        assert result["status"] == "passed", result
