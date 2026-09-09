from datetime import date

from hypertrade.arc.contracts import ARCGoalV1, ResearchWindowsV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.self_test import ARCSelfTestService
from test_arc_real_bitpro_path import _candidate, _RealShapeBitPro


def test_development_and_final_windows_are_frozen_and_disjoint():
    goal = ARCGoalV1(
        objective="research",
        paper_review_required=True,
        research_mode="avo",
        research_windows=ResearchWindowsV1(as_of=date(2026, 8, 31)),
    )
    ARCController(mission_id="arc_windows", goal=goal)
    client = _RealShapeBitPro()
    runner = ARCSelfTestService(client=client)
    runner.run(_candidate(), goal, purpose="development")
    runner.run(_candidate(), goal, purpose="final")
    runner.run(_candidate(), goal, purpose="development")
    dev, final, retry = client.backtest_calls
    assert dev["end_date"] < final["start_date"]
    assert final["end_date"] == "2026-08-31"
    assert dev["initial_capital"] == final["initial_capital"] == 100.0
    assert dev == retry
    assert dev["idempotency_key"] != final["idempotency_key"]
    assert client.create_calls[0]["idempotency_key"] == client.create_calls[1]["idempotency_key"]
