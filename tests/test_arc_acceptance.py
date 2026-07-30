"""
Sprint 135 — End-to-End Acceptance Test for ARC (Autonomous Research Core)
Verifies Single Entrance -> Autonomous Search -> Red-Blue Attack -> Validation -> Auto Paper Launch
"""

from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.router import _ARC_MISSIONS, run_autonomous_arc_loop


def test_arc_end_to_end_autonomous_loop_acceptance():
    preauth = PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"])
    goal = ARCGoalV1(
        objective="自主搜索高胜率趋势突破策略，红蓝攻防过检后自动配置模拟盘上线运行",
        symbols=["BTC-USDT-SWAP"],
        budget=ARCBudgetV1(max_candidates=5),
        paper_authorization=preauth,
    )

    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl

    # Run background execution loop synchronously
    run_autonomous_arc_loop(ctrl.mission_id)

    proj = ctrl.projection
    assert proj.state == "completed"
    assert len(proj.attempts) >= 2

    # Verify attempt states and paper trading auto incubation
    validated_attempt = next(
        (
            att
            for att in proj.attempts
            if att.state in ["validated", "paper_observing"]
        ),
        None,
    )
    assert validated_attempt is not None
    assert validated_attempt.paper_instance_id is not None
    assert validated_attempt.paper_instance_id.startswith("bitpro_paper_")

    active_paper_instances = [
        att.paper_instance_id for att in proj.attempts if att.paper_instance_id
    ]
    assert len(active_paper_instances) == 1
