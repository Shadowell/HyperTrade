from decimal import Decimal

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.arc.self_test import ARCSelfTestService, apply_success_criteria


def test_success_criteria_reject_weak_metrics() -> None:
    passed, reasons = apply_success_criteria(
        {"sharpe": 0.4, "max_drawdown": 0.4, "trades": 2, "net_return": 0.01},
        ARCSuccessCriteriaV1(),
    )
    assert passed is False
    assert any("sharpe" in item for item in reasons)
    assert any("drawdown" in item for item in reasons)
    assert any("trades" in item for item in reasons)


def test_success_criteria_pass_when_all_floors_hold() -> None:
    passed, reasons = apply_success_criteria(
        {
            "out_of_sample_sharpe": 1.3,
            "out_of_sample_max_drawdown": 0.09,
            "out_of_sample_trades": 14,
            "out_of_sample_return": 0.08,
        },
        ARCSuccessCriteriaV1(min_oos_sharpe=Decimal("1.2"), min_trades=10),
    )
    assert passed is True
    assert reasons == []


def test_self_test_fail_closed_without_backtest_ref() -> None:
    class _Client:
        def strategy_validate_code(self, **kwargs):  # type: ignore[no-untyped-def]
            return {"status": "ok"}

        def strategy_create(self, **kwargs):  # type: ignore[no-untyped-def]
            return {"status": "ok", "strategy": {"id": 9}}

        def backtest_start_job(self, **kwargs):  # type: ignore[no-untyped-def]
            return {"status": "ok", "metrics": {"sharpe": 2.0}}

    attempt = ARCCandidateAttemptV1(
        attempt_id="att_1",
        candidate_id="cand_1",
        hypothesis="x",
        strategy_code="class X: pass",
        strategy_spec={"symbol": "BTC-USDT-SWAP", "timeframe": "1H"},
    )
    result = ARCSelfTestService(_Client()).run(attempt, ARCGoalV1(objective="x"))
    assert result.passed is False
    assert result.backtest_id is None
    assert "bitpro_backtest_missing_result_ref" in result.reasons


def test_self_test_passes_only_with_ref_and_criteria() -> None:
    class _Client:
        def strategy_validate_code(self, **kwargs):  # type: ignore[no-untyped-def]
            return {"status": "ok"}

        def strategy_create(self, **kwargs):  # type: ignore[no-untyped-def]
            return {"status": "ok", "strategy": {"id": 9}}

        def backtest_start_job(self, **kwargs):  # type: ignore[no-untyped-def]
            return {
                "status": "ok",
                "backtest_result": {
                    "id": "bt_9",
                    "metrics": {
                        "sharpe": 1.5,
                        "max_drawdown": 0.07,
                        "trades": 20,
                        "net_return": 0.12,
                    },
                },
            }

    attempt = ARCCandidateAttemptV1(
        attempt_id="att_1",
        candidate_id="cand_1",
        hypothesis="x",
        strategy_code="class X: pass",
        strategy_spec={"symbol": "BTC-USDT-SWAP", "timeframe": "1m"},
    )
    result = ARCSelfTestService(_Client()).run(attempt, ARCGoalV1(objective="x"))
    assert result.passed is True
    assert result.backtest_id == "bt_9"
    assert result.bitpro_strategy_id == "9"
    assert result.validation_id
