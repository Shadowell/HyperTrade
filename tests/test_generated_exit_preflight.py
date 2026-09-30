import pytest
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.self_test import ARCSelfTestService
from hypertrade.research.codegen import (
    StrategyCodegenError,
    generate_strategy,
    generated_candidate_config,
)


def candidate():
    g = generate_strategy({"strategy_key": "preflight", "family_key": "ma_crossover"})
    spec = {
        "symbol": "BTC-USDT-SWAP",
        "timeframe": "1H",
        "risk_overlays": list(g.risk_overlays),
        "tunable_parameters": g.tunable_parameters,
    }
    return g, spec


def test_generated_config_exposes_the_same_effective_exits_to_platform_and_runtime():
    g, spec = candidate()
    cfg = generated_candidate_config(spec, g.code)
    assert cfg["stop_loss"] == cfg["research_parameters"]["stop_loss"] == 0.05
    assert cfg["take_profit"] == cfg["research_parameters"]["take_profit"] == 0.1


@pytest.mark.parametrize("value", [0, -1, True, float("inf"), None])
def test_preflight_blocks_invalid_exit_before_remote_calls(value):
    g, spec = candidate()
    spec["tunable_parameters"]["take_profit"] = value

    class NoCalls:
        def strategy_validate_code(self, **kwargs):
            raise AssertionError("remote call must not happen")

    attempt = ARCCandidateAttemptV1(
        attempt_id="preflight",
        candidate_id="preflight",
        hypothesis="x",
        strategy_code=g.code,
        strategy_spec=spec,
    )
    result = ARCSelfTestService(NoCalls()).run(attempt, ARCGoalV1(objective="x"))
    assert not result.passed
    assert result.reasons == ["local_strategy_preflight_failed"]


def test_old_generated_source_without_recovery_contract_cannot_be_created():
    g, spec = candidate()
    code = g.code.replace(
        'runtime_state_contract = "arc_generated.v1"', 'runtime_state_contract = "old"'
    )
    with pytest.raises(StrategyCodegenError):
        generated_candidate_config(spec, code)


def test_selftest_create_binds_protection_capital_and_timeframe():
    from decimal import Decimal

    g, spec = candidate()
    writes = []

    class Client:
        def strategy_validate_code(self, **kwargs):
            assert kwargs["market_type"] == "swap"
            return {"status": "ok"}

        def strategy_create(self, **kwargs):
            writes.append(kwargs)
            return {"status": "error"}

    attempt = ARCCandidateAttemptV1(
        attempt_id="configured",
        candidate_id="configured",
        hypothesis="x",
        strategy_code=g.code,
        strategy_spec=spec,
    )
    ARCSelfTestService(Client()).run(
        attempt,
        ARCGoalV1(
            objective="x",
            paper_review_required=True,
            research_id="config-proof",
            paper_initial_equity=Decimal("100.5"),
        ),
    )
    assert len(writes) == 1
    cfg = writes[0]["config"]
    assert cfg["initial_capital"] == cfg["paper_initial_equity"] == 100.5
    assert cfg["timeframe"].lower() == "1h"
    assert cfg["stop_loss"] == cfg["research_parameters"]["stop_loss"]
