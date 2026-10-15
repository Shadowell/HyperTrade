from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.self_test import ARCSelfTestService
from test_source_variant_avo import MockSelfTestClient, source_variant_mission  # noqa: F401


def test_failed_candidate_job_cannot_pass_from_attached_partial_metrics(source_variant_mission):  # noqa: F811
    class FailedJob(MockSelfTestClient):
        def backtest_start_job(self, **kwargs):
            result = super().backtest_start_job(**kwargs)
            if len(self.backtests_started) == 2:
                result["job"].update(
                    job_id="failed-candidate",
                    status="failed",
                    error_message="input verification failed",
                )
            return result

    goal = source_variant_mission.projection.goal
    baseline = goal.evolution_context["baseline"]
    candidate = ARCCandidateAttemptV1(
        attempt_id="a",
        candidate_id="c",
        hypothesis="change",
        strategy_code=baseline["strategy_code"],
        strategy_spec={**baseline["strategy_spec"], "parameter_changes": {"fast_window": 15}},
    )
    result = ARCSelfTestService(client=FailedJob()).run(candidate, goal, purpose="development")
    assert result.passed is False
    assert result.metrics == {}
    assert result.terminal_failure["status"] == "failed"
