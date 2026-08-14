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


def test_loop_searches_across_structurally_different_hypotheses():
    """The search used to explore one family and tune its parameters."""
    goal = ARCGoalV1(
        objective="自主搜索高胜率趋势突破策略",
        symbols=["BTC-USDT-SWAP"],
        budget=ARCBudgetV1(max_candidates=5),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl

    run_autonomous_arc_loop(ctrl.mission_id)

    proj = ctrl.projection
    families = {att.strategy_spec.get("family") for att in proj.attempts}
    assert len(families) >= 2, "the frontier must span more than one strategy family"
    assert len({att.strategy_code for att in proj.attempts}) == len(proj.attempts)
    # Seeding must leave room for at least one generation of repair.
    assert proj.goal is not None
    assert proj.goal.budget.candidates_used < proj.goal.budget.max_candidates


def test_candidate_without_out_of_sample_evidence_never_reaches_paper():
    """The gate that stops an unproven candidate has to hold end to end.

    Before the evidence gate existed, review read only what a candidate declared about
    itself, so a strategy with defensible parameters and no edge was provisioned onto
    paper. A flat window makes every family inert, which is precisely the case a gate
    reading only Sharpe would have scored as flawless.
    """
    from decimal import Decimal

    import hypertrade.arc.router as router_module
    from hypertrade.arc.evidence import HistoricalEvidenceGate
    from hypertrade.strategy.sdk import Candle

    flat = Decimal("100")
    candles = [
        Candle(
            timestamp=f"2026-01-01T{index:05d}",
            open=flat,
            high=flat,
            low=flat,
            close=flat,
            volume=Decimal("10"),
        )
        for index in range(800)
    ]

    class _Window:
        def read(self, *, symbol, timeframe, limit):
            return candles

    goal = ARCGoalV1(
        objective="自主搜索趋势突破策略",
        symbols=["BTC-USDT-SWAP"],
        budget=ARCBudgetV1(max_candidates=5),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl

    original = router_module.build_default_window
    router_module.build_default_window = lambda *args, **kwargs: _Window()
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.build_default_window = original

    proj = ctrl.projection
    assert proj.state == "needs_operator"
    assert not any(att.paper_instance_id for att in proj.attempts)
    # The rejection has to be attributed to held-back evidence, not to a parameter guess.
    evidence_codes = {
        code
        for event in proj.reflexion_history
        for code in event.reason_codes
        if code.startswith(("OOS_", "INERT_", "IS_OOS_", "PERMANENT_"))
    }
    assert evidence_codes, "rejection must cite out-of-sample evidence"
    assert HistoricalEvidenceGate(_Window()).evaluate(proj.attempts[0]).passed is False


def test_loop_stops_at_the_candidate_budget_when_nothing_survives():
    """Budget is the stopping condition; the loop must not spin on hopeless candidates."""
    goal = ARCGoalV1(
        objective="自主搜索趋势策略",
        symbols=["BTC-USDT-SWAP"],
        budget=ARCBudgetV1(max_candidates=4),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl

    # Every candidate is rejected, so the loop can only terminate on its own budget.
    import hypertrade.arc.router as router_module

    original = router_module.ARCAdversarialEngine.run_adversarial_session

    def always_reject(self, attempt):  # type: ignore[no-untyped-def]
        from hypertrade.arc.findings import ARCReasonCode, AttackFinding

        return (
            False,
            {"sharpe_after_attack": 0.1, "max_drawdown_after_attack": 0.4},
            [
                AttackFinding(
                    code=ARCReasonCode.WIDE_STOP_LOSS,
                    gate="parameter_perturbation",
                    detail="synthetic rejection",
                )
            ],
        )

    router_module.ARCAdversarialEngine.run_adversarial_session = always_reject  # type: ignore[method-assign]
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.ARCAdversarialEngine.run_adversarial_session = original  # type: ignore[method-assign]

    proj = ctrl.projection
    assert proj.state == "needs_operator"
    assert proj.goal is not None
    assert proj.goal.budget.candidates_used <= proj.goal.budget.max_candidates
    assert len(proj.reflexion_history) >= 1
    assert not any(att.paper_instance_id for att in proj.attempts)
