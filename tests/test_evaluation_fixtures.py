from __future__ import annotations

from hypertrade.runtime.application.evaluation_fixtures import (
    IsolatedLiveStrategyFixtureAdapter,
    operator_eval_fixture_enabled,
)


def test_operator_task_fixtures_are_unreachable_outside_evaluation() -> None:
    assert operator_eval_fixture_enabled(app_env="evaluation", enabled=True)
    assert not operator_eval_fixture_enabled(app_env="production", enabled=True)
    assert not operator_eval_fixture_enabled(app_env="staging", enabled=True)
    assert not operator_eval_fixture_enabled(app_env="evaluation", enabled=False)


def test_isolated_live_strategy_fixture_is_bounded_and_synthetic() -> None:
    payload = IsolatedLiveStrategyFixtureAdapter().live_strategy_performance(
        exchange="okx", limit=2
    )

    assert [item["strategy_name"] for item in payload["strategies"]] == [
        "BTC 趋势跟踪",
        "ETH 均值回归",
    ]
    assert all(item["strategy_id"].startswith("eval_live_") for item in payload["strategies"])
