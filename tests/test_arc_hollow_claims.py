"""Regression net for claims that used to look finished while doing nothing.

Each assertion is a previously observed hollow. If one fails, a claimed capability
has either been filled in (update this file) or has regressed into a new lie.
"""

from inspect import getsource

from hypertrade.arc import incubation, router
from hypertrade.arc.adversarial import RedTeamQuant
from hypertrade.arc.canary_vault import CanaryVaultPipeline
from hypertrade.arc.contracts import ARCGoalV1


def test_paper_provision_calls_configure_and_start() -> None:
    src = getsource(incubation.ARCPaperIncubationResolver.resolve_and_provision_paper_trading)
    assert "paper_configure" in src
    assert "paper_start" in src
    assert "BitProToolAdapter" in src
    assert "bitpro_paper_strat_" not in src
    assert "except Exception:\n            pass" not in src


def test_win_rate_is_not_a_restated_verdict() -> None:
    src = getsource(RedTeamQuant.evaluate_adversarial_attack)
    assert "win_rate = 0.65" not in src
    assert "win_rate = 0.42" not in src
    assert 'observed_metrics["win_rate"] = 0.65' not in src
    assert "out_of_sample_win_rate" in src


def test_loop_stops_without_a_window_instead_of_completing() -> None:
    src = getsource(router.run_autonomous_arc_loop)
    assert "evidence_window_unavailable" in src
    assert "no_out_of_sample_evidence" in src
    assert "budget.is_exhausted" in src


def test_loop_self_tests_against_success_criteria_before_paper() -> None:
    src = getsource(router.run_autonomous_arc_loop)
    assert "success_criteria" in src
    assert "ARCSelfTestService" in src
    assert "mission_completed" not in src


def test_missions_are_loaded_from_the_store() -> None:
    src = getsource(router)
    assert "get_controller" in src
    assert "save_mission" in src


def test_live_write_is_still_unexpressible() -> None:
    src = getsource(CanaryVaultPipeline)
    assert "place_order" not in src
    assert "live_order" not in src
    try:
        ARCGoalV1(objective="x", symbols=["BTC-USDT-SWAP"], live_allowed=True)
    except Exception:
        return
    raise AssertionError("live_allowed=True must stay unconstructable")


def test_remaining_hollows_are_still_visible() -> None:
    """These are not done. The test exists so they cannot silently look done."""
    loop = getsource(router.run_autonomous_arc_loop)
    assert "UnifiedStrategyValidation" not in loop
