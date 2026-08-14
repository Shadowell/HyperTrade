"""
End-to-end acceptance for the ARC loop.

A completed mission is only legal when a candidate survived held-out evidence and
BitPro actually created the paper instance. Missing data, projected Sharpe, and a
swallowed BitPro error are all `needs_operator`.
"""

from decimal import Decimal
from typing import Any

from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.router import _ARC_MISSIONS, run_autonomous_arc_loop
from hypertrade.strategy.sdk import Candle


def _goal(*, max_candidates: int = 5) -> ARCGoalV1:
    return ARCGoalV1(
        objective="自主搜索高胜率趋势突破策略，红蓝攻防过检后自动配置模拟盘上线运行",
        symbols=["BTC-USDT-SWAP"],
        budget=ARCBudgetV1(max_candidates=max_candidates),
        paper_authorization=PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )


def _start(goal: ARCGoalV1) -> ARCController:
    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl
    return ctrl


def _flat_window(rows: int = 800) -> object:
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
        for index in range(rows)
    ]

    class _Window:
        def read(self, *, symbol: str, timeframe: str, limit: int) -> list[Candle]:
            return candles[:limit] if limit else candles

    return _Window()


def test_missing_window_never_completes_or_reaches_paper() -> None:
    """The previous golden test certified the lie: no archive, fake paper id, completed."""
    ctrl = _start(_goal())
    run_autonomous_arc_loop(ctrl.mission_id)

    proj = ctrl.projection
    assert proj.state == "needs_operator"
    assert proj.attempts == []
    assert not any(att.paper_instance_id for att in proj.attempts)
    reasons = [
        event.payload.get("reason")
        for event in proj.events
        if event.event_type == "operator_needed"
    ]
    assert "evidence_window_unavailable" in reasons


def test_loop_searches_across_structurally_different_hypotheses() -> None:
    """The search used to explore one family and tune its parameters."""
    import hypertrade.arc.router as router_module

    ctrl = _start(_goal())
    original = router_module.build_default_window
    router_module.build_default_window = lambda *args, **kwargs: _flat_window()
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.build_default_window = original

    proj = ctrl.projection
    families = {att.strategy_spec.get("family") for att in proj.attempts}
    assert len(families) >= 2, "the frontier must span more than one strategy family"
    assert len({att.strategy_code for att in proj.attempts}) == len(proj.attempts)
    assert proj.goal is not None
    assert proj.goal.budget.candidates_used <= proj.goal.budget.max_candidates
    assert proj.state == "needs_operator"
    assert not any(att.paper_instance_id for att in proj.attempts)


def test_candidate_without_out_of_sample_evidence_never_reaches_paper() -> None:
    """The gate that stops an unproven candidate has to hold end to end.

    Before the evidence gate existed, review read only what a candidate declared about
    itself, so a strategy with defensible parameters and no edge was provisioned onto
    paper. A flat window makes every family inert, which is precisely the case a gate
    reading only Sharpe would have scored as flawless.
    """
    import hypertrade.arc.router as router_module
    from hypertrade.arc.evidence import HistoricalEvidenceGate

    window = _flat_window()
    ctrl = _start(_goal())
    original = router_module.build_default_window
    router_module.build_default_window = lambda *args, **kwargs: window
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.build_default_window = original

    proj = ctrl.projection
    assert proj.state == "needs_operator"
    assert not any(att.paper_instance_id for att in proj.attempts)
    evidence_codes = {
        code
        for event in proj.reflexion_history
        for code in event.reason_codes
        if code.startswith(("OOS_", "INERT_", "IS_OOS_", "PERMANENT_"))
    }
    assert evidence_codes, "rejection must cite out-of-sample evidence"
    assert HistoricalEvidenceGate(window).evaluate(proj.attempts[0]).passed is False  # type: ignore[arg-type]


def test_loop_stops_at_the_candidate_budget_when_nothing_survives() -> None:
    """Budget is the stopping condition; the loop must not spin on hopeless candidates."""
    import hypertrade.arc.router as router_module
    from hypertrade.arc.findings import ARCReasonCode, AttackFinding

    ctrl = _start(_goal(max_candidates=4))
    original_window = router_module.build_default_window
    original_review = router_module.ARCAdversarialEngine.run_adversarial_session

    def always_reject(self, attempt):  # type: ignore[no-untyped-def]
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

    router_module.build_default_window = lambda *args, **kwargs: _flat_window()
    router_module.ARCAdversarialEngine.run_adversarial_session = always_reject  # type: ignore[method-assign]
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.build_default_window = original_window
        router_module.ARCAdversarialEngine.run_adversarial_session = original_review  # type: ignore[method-assign]

    proj = ctrl.projection
    assert proj.state == "needs_operator"
    assert proj.goal is not None
    assert proj.goal.budget.candidates_used <= proj.goal.budget.max_candidates
    assert len(proj.reflexion_history) >= 1
    assert not any(att.paper_instance_id for att in proj.attempts)


def test_projected_sharpe_survivor_does_not_reach_paper() -> None:
    """A pass whose ranking basis is the candidate's own projection is not evidence."""
    import hypertrade.arc.router as router_module

    ctrl = _start(_goal())
    original_window = router_module.build_default_window
    original_review = router_module.ARCAdversarialEngine.run_adversarial_session

    def projected_pass(self, attempt):  # type: ignore[no-untyped-def]
        return (
            True,
            {
                "ranking_sharpe": 1.85,
                "ranking_basis": "declared_projection",
                "sharpe_after_attack": 1.85,
            },
            [],
        )

    router_module.build_default_window = lambda *args, **kwargs: _flat_window()
    router_module.ARCAdversarialEngine.run_adversarial_session = projected_pass  # type: ignore[method-assign]
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.build_default_window = original_window
        router_module.ARCAdversarialEngine.run_adversarial_session = original_review  # type: ignore[method-assign]

    proj = ctrl.projection
    assert proj.state == "needs_operator"
    assert not any(att.paper_instance_id for att in proj.attempts)
    reasons = [
        event.payload.get("reason")
        for event in proj.events
        if event.event_type == "operator_needed"
    ]
    assert "no_out_of_sample_evidence" in reasons


def test_held_out_survivor_reaches_paper_only_when_bitpro_creates_it() -> None:
    import hypertrade.arc.incubation as incubation_module
    import hypertrade.arc.router as router_module

    class _OkBitPro:
        def strategy_create(self, **kwargs: Any) -> Any:
            return {"status": "ok", "strategy": {"id": 77}}

        def paper_configure(self, **kwargs: Any) -> Any:
            return {"status": "ok", "paper": {"instance_id": 77}}

        def paper_start(self, **kwargs: Any) -> Any:
            return {"status": "ok", "paper": {"instance_id": 77, "status": "running"}}

    ctrl = _start(_goal())
    original_window = router_module.build_default_window
    original_review = router_module.ARCAdversarialEngine.run_adversarial_session
    original_client = incubation_module.BitProToolAdapter

    def held_out_pass(self, attempt):  # type: ignore[no-untyped-def]
        return (
            True,
            {
                "ranking_sharpe": 1.4,
                "ranking_basis": "out_of_sample",
                "out_of_sample_sharpe": 1.4,
            },
            [],
        )

    router_module.build_default_window = lambda *args, **kwargs: _flat_window()
    router_module.ARCAdversarialEngine.run_adversarial_session = held_out_pass  # type: ignore[method-assign]
    incubation_module.BitProToolAdapter = lambda *args, **kwargs: _OkBitPro()  # type: ignore[misc,assignment]
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.build_default_window = original_window
        router_module.ARCAdversarialEngine.run_adversarial_session = original_review  # type: ignore[method-assign]
        incubation_module.BitProToolAdapter = original_client

    proj = ctrl.projection
    assert proj.state == "completed"
    papered = [att for att in proj.attempts if att.paper_instance_id]
    assert len(papered) == 1
    assert papered[0].paper_instance_id == "77"
    assert papered[0].state == "paper_observing"


def test_held_out_survivor_stays_needs_operator_when_bitpro_fails() -> None:
    import hypertrade.arc.incubation as incubation_module
    import hypertrade.arc.router as router_module

    class _DownBitPro:
        def strategy_create(self, **kwargs: Any) -> Any:
            raise RuntimeError("timeout")

        def paper_configure(self, **kwargs: Any) -> Any:
            raise AssertionError("configure must not run after create failure")

        def paper_start(self, **kwargs: Any) -> Any:
            raise AssertionError("start must not run after create failure")

    ctrl = _start(_goal())
    original_window = router_module.build_default_window
    original_review = router_module.ARCAdversarialEngine.run_adversarial_session
    original_client = incubation_module.BitProToolAdapter

    def held_out_pass(self, attempt):  # type: ignore[no-untyped-def]
        return True, {"ranking_sharpe": 1.4, "ranking_basis": "out_of_sample"}, []

    router_module.build_default_window = lambda *args, **kwargs: _flat_window()
    router_module.ARCAdversarialEngine.run_adversarial_session = held_out_pass  # type: ignore[method-assign]
    incubation_module.BitProToolAdapter = lambda *args, **kwargs: _DownBitPro()  # type: ignore[misc,assignment]
    try:
        run_autonomous_arc_loop(ctrl.mission_id)
    finally:
        router_module.build_default_window = original_window
        router_module.ARCAdversarialEngine.run_adversarial_session = original_review  # type: ignore[method-assign]
        incubation_module.BitProToolAdapter = original_client

    proj = ctrl.projection
    assert proj.state == "needs_operator"
    assert not any(att.paper_instance_id for att in proj.attempts)
