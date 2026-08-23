"""Slice 3 of the ARC real-closure contract: the true BitPro pipeline.

The live probe (2026-08-23, run 03baf9b7) proved validate -> create -> backtest ->
result against production BitPro and revealed the exact result payload shape:
metrics arrive under ``sharpe_ratio`` / ``trade_count`` with percentages spelled
``*_pct`` as *strings*. These tests pin that shape so the referee can never again
report real numbers as missing, and pin the fault paths (timeout, duplicate,
unknown outcome) as fail-closed with zero fabricated references.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypertrade.arc.adversarial import BlueTeamQuant
from hypertrade.arc.contracts import ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.arc.self_test import ARCSelfTestService, apply_success_criteria


class _RealShapeBitPro:
    """A double that speaks the REAL BitPro adapter payload shapes.

    Shapes are copied from the live probe: ``strategy.create`` nests the id under
    ``strategy.id``, backtest results nest under ``backtest_result.metrics`` with
    string-encoded percentage fields. No business logic is stubbed out: whatever the
    service reads must exist here exactly as production returns it.
    """

    def __init__(self) -> None:
        self.validate_calls = 0
        self.create_calls: list[dict[str, Any]] = []
        self.backtest_calls: list[dict[str, Any]] = []
        self.fail_backtest_with: Exception | None = None

    def strategy_validate_code(self, **kwargs: Any) -> dict[str, Any]:
        self.validate_calls += 1
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "validation": {"valid": True, "smoke": True},
        }

    def strategy_create(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append(kwargs)
        if kwargs.get("idempotency_key") == self.create_calls[0]["idempotency_key"] or len(
            self.create_calls
        ) == 1:
            # Server-side dedupe: the same content-bound key replays the first fact.
            return {"status": "ok", "strategy": {"id": 445}}
        return {"status": "ok", "strategy": {"id": 446}}

    def backtest_start_job(self, **kwargs: Any) -> dict[str, Any]:
        self.backtest_calls.append(kwargs)
        if self.fail_backtest_with is not None:
            raise self.fail_backtest_with
        # String-encoded numbers, exactly as the live probe observed.
        return {
            "status": "ok",
            "backtest_result": {
                "id": 450,
                "metrics": {
                    "total_return_pct": "0.835692901303264",
                    "annual_return_pct": "3.4327",
                    "max_drawdown_pct": "1.5167",
                    "sharpe_ratio": "0.2034",
                    "win_rate_pct": "34.09",
                    "trade_count": 44,
                },
            },
        }

    def paper_configure(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ok", "instance_id": 9001}

    def paper_start(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "ok", "instance_id": 9001}


def _candidate():
    return BlueTeamQuant().propose_initial_strategy("均线金叉趋势跟踪", "BTC-USDT-SWAP")


def _goal() -> ARCGoalV1:
    return ARCGoalV1(
        objective="真身正路验收",
        success_criteria=ARCSuccessCriteriaV1(),
    )


def _criteria_loose() -> ARCSuccessCriteriaV1:
    criteria = ARCSuccessCriteriaV1()
    criteria.min_oos_sharpe = Decimal("0.1")
    criteria.max_drawdown = Decimal("0.5")
    criteria.min_trades = 10
    criteria.min_oos_net_return = Decimal("0.001")
    return criteria


def test_success_criteria_reads_the_real_bitpro_metric_shape() -> None:
    """String-encoded ``*_pct`` values must translate to fractions, not face value."""
    service = ARCSelfTestService(client=_RealShapeBitPro())
    result = service.run(_candidate(), _goal())

    assert result.bitpro_strategy_id == "445"
    assert result.backtest_id == "450"
    # Raw metrics stay exactly as BitPro reported them: string-encoded percentages.
    assert result.metrics["max_drawdown_pct"] == "1.5167"
    passed, reasons = apply_success_criteria(result.metrics, _criteria_loose())
    assert passed, reasons


def test_backtest_timeout_fails_closed_and_keeps_only_real_refs() -> None:
    import httpx

    double = _RealShapeBitPro()
    double.fail_backtest_with = httpx.ReadTimeout("job poll exceeded deadline")
    service = ARCSelfTestService(client=double)
    result = service.run(_candidate(), _goal())

    assert result.passed is False
    assert result.validation_id is None
    # The strategy was really created; that ref survives. No invented backtest id.
    assert result.bitpro_strategy_id == "445"
    assert result.backtest_id is None
    assert any(r.startswith("bitpro_backtest_failed") for r in result.reasons)


def test_duplicate_candidate_replays_one_content_bound_key_set() -> None:
    """Same candidate twice -> identical idempotency keys, one physical create."""
    double = _RealShapeBitPro()
    service = ARCSelfTestService(client=double)
    attempt = _candidate()
    service.run(attempt, _goal())
    service.run(attempt, _goal())

    create_keys = [call["idempotency_key"] for call in double.create_calls]
    backtest_keys = [call["idempotency_key"] for call in double.backtest_calls]
    assert len(set(create_keys)) == 1, "create key must be content-bound to the candidate"
    assert len(set(backtest_keys)) == 1


def test_incubation_reuses_probe_strategy_without_a_second_create() -> None:
    from hypertrade.arc.contracts import PaperPreauthorizationV1

    double = _RealShapeBitPro()
    attempt = _candidate()
    attempt.bitpro_strategy_id = "445"
    attempt.state = "validated"
    resolver = ARCPaperIncubationResolver(client=double)
    ok, instance_id, _name, reason = resolver.resolve_and_provision_paper_trading(
        attempt=attempt,
        preauth=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok, reason
    assert str(instance_id) != ""
    assert double.create_calls == [], "an existing strategy ref must not create again"


def test_no_path_invents_a_paper_instance_without_bitpro_saying_so() -> None:
    """The hollow-claim regression: an unconfirmed instance id blocks promotion."""
    from hypertrade.arc.contracts import PaperPreauthorizationV1

    class _NoInstanceIdBitPro(_RealShapeBitPro):
        def paper_configure(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": "ok"}  # real BitPro omits instance_id on failure paths

    double = _NoInstanceIdBitPro()
    attempt = _candidate()
    attempt.bitpro_strategy_id = "445"
    attempt.state = "validated"
    resolver = ARCPaperIncubationResolver(client=double)
    ok, instance_id, _name, reason = resolver.resolve_and_provision_paper_trading(
        attempt=attempt,
        preauth=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert not ok
    assert instance_id is None
