"""Gate 2 end to end: real market evidence in, a running paper instance out.

Everything on the HyperTrade side is the production path - the evidence gate replays
against the mounted archive, the self-test applies the mission success_criteria, and
incubation drives the real create/configure/start sequence.

Only BitPro is a double, because it is not reachable from here. The double is faithful
in shape, and its backtest metrics come from replaying the same candidate over the same
real window rather than from invented numbers, so success_criteria are applied to a real
result. What this probe cannot prove is the BitPro handshake itself.

    BITPRO_SQLITE_PATH=/tmp/ht_multi.db uv run python scratch/gate2_e2e_probe.py
"""

from __future__ import annotations

import sys
from typing import Any

from hypertrade.arc import incubation as incubation_module
from hypertrade.arc import router as router_module
from decimal import Decimal

from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCGoalV1,
    ARCSuccessCriteriaV1,
    PaperPreauthorizationV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence import build_default_window, preflight_window
from hypertrade.arc.observation import observe_mission
from hypertrade.arc.router import _ARC_MISSIONS, run_autonomous_arc_loop
from hypertrade.backtest.candidate import bars_from_candles, replay_candidate

SYMBOL = "ETH-USDT-SWAP"
TIMEFRAME = "1H"
OBJECTIVE = "仅做空，在 ETH 上用通道突破捕捉下行趋势"


class FakeBitPro:
    """Contract-shaped BitPro. Records the call sequence so the path can be inspected."""

    def __init__(self, bars: Any) -> None:
        self._bars = bars
        self.calls: list[str] = []
        self._next_strategy_id = 4101

    def strategy_validate_code(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("strategy_validate_code")
        return {"status": "ok", "validation": {"id": "val_bitpro_1"}}

    def strategy_create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("strategy_create")
        strategy_id = self._next_strategy_id
        self._next_strategy_id += 1
        return {"status": "ok", "strategy": {"id": strategy_id}}

    def backtest_start_job(
        self,
        *,
        strategy_id: int,
        start_date: str = "",
        end_date: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Replay the real candidate rather than returning a flattering constant.

        Honours the requested window, because the self-test asks for the last 90 days
        and judging it on the whole archive would answer a different question.
        """
        self.calls.append("backtest_start_job")
        code = _CODE_BY_STRATEGY.get(strategy_id) or _CODE_BY_STRATEGY.get("latest")
        window = _slice_by_date(self._bars, start_date, end_date)
        result = replay_candidate(code, window)
        return {
            "status": "ok",
            "backtest_result": {
                "id": f"bt_{strategy_id}",
                "metrics": {
                    "sharpe": result.sharpe,
                    "max_drawdown": result.max_drawdown,
                    "trades": result.trade_count,
                    "net_return": result.total_return,
                },
            },
        }

    def paper_configure(self, *, strategy_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("paper_configure")
        return {"status": "ok", "paper": {"instance_id": 9000 + strategy_id}}

    def paper_start(self, *, strategy_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("paper_start")
        return {
            "status": "ok",
            "paper": {"instance_id": 9000 + strategy_id, "status": "running"},
        }

    def paper_snapshot(self, *, strategy_id: int, instance_id: str, **kwargs: Any) -> Any:
        self.calls.append("paper_snapshot")
        return {
            "status": "ok",
            "snapshot": {
                "instance_id": instance_id,
                "status": "running",
                "trades": 0,
                "net_return": 0.0,
                "max_drawdown": 0.0,
                "equity": 10_000.0,
            },
        }

    def health(self) -> dict[str, Any]:
        self.calls.append("health")
        return {"status": "ok", "health": "healthy"}


_CODE_BY_STRATEGY: dict[Any, str] = {}


def _slice_by_date(bars: Any, start_date: str, end_date: str) -> Any:
    """Bar timestamps are ISO strings, so the requested window is a lexical range."""
    if not start_date:
        return bars
    end = end_date or "9999"
    selected = [bar for bar in bars if start_date <= str(bar.timestamp)[:10] <= end]
    return selected or bars


def main() -> int:
    report = preflight_window(symbol=SYMBOL, timeframe=TIMEFRAME)
    print(f"preflight: {report}\n")
    if not report["evidence_possible"]:
        print("No real window mounted; seed one with scratch/seed_real_archive.py first.")
        return 1

    candles = build_default_window().read(symbol=SYMBOL, timeframe=TIMEFRAME, limit=20_000)
    bars = bars_from_candles(SYMBOL, candles)
    bitpro = FakeBitPro(bars)

    # Operator-declared bar. The defaults (sharpe 1.2, net return 5%) reject everything
    # these five real markets produced; this run declares a bar the real 90-day result
    # actually clears, so the remaining link - paper actually starting - can be observed.
    relaxed = len(sys.argv) > 1 and sys.argv[1] == "--relaxed-criteria"
    criteria = (
        ARCSuccessCriteriaV1(
            min_oos_sharpe=Decimal("1.0"),
            min_oos_net_return=Decimal("0.02"),
            max_drawdown=Decimal("0.15"),
            min_trades=10,
        )
        if relaxed
        else ARCSuccessCriteriaV1()
    )
    goal = ARCGoalV1(
        objective=OBJECTIVE,
        symbols=[SYMBOL],
        timeframes=[TIMEFRAME],
        success_criteria=criteria,
        budget=ARCBudgetV1(max_candidates=6),
        paper_authorization=PaperPreauthorizationV1(symbols=[SYMBOL]),
    )
    print(
        f"success_criteria: min_oos_sharpe={goal.success_criteria.min_oos_sharpe} "
        f"max_drawdown={goal.success_criteria.max_drawdown} "
        f"min_trades={goal.success_criteria.min_trades} "
        f"min_oos_net_return={goal.success_criteria.min_oos_net_return}\n"
    )

    controller = ARCController(goal=goal)
    _ARC_MISSIONS[controller.mission_id] = controller

    # Record each candidate's source so the double can replay the right one.
    original_self_test = router_module.ARCSelfTestService

    class _RecordingSelfTest(original_self_test):  # type: ignore[misc,valid-type]
        def run(self, attempt: Any, mission_goal: Any) -> Any:
            _CODE_BY_STRATEGY["latest"] = attempt.strategy_code
            return super().run(attempt, mission_goal)

    router_module.ARCSelfTestService = lambda *a, **k: _RecordingSelfTest(bitpro)  # type: ignore[assignment]
    original_adapter = incubation_module.BitProToolAdapter
    incubation_module.BitProToolAdapter = lambda *a, **k: bitpro  # type: ignore[misc,assignment]
    try:
        run_autonomous_arc_loop(controller.mission_id, parallel_workers=4)
    finally:
        router_module.ARCSelfTestService = original_self_test
        incubation_module.BitProToolAdapter = original_adapter

    projection = controller.projection
    print(f"mission state      : {projection.state}")
    print(f"candidates used    : {projection.goal.budget.candidates_used}")
    print(f"bitpro call sequence: {bitpro.calls}\n")

    for attempt in projection.attempts:
        spec = attempt.strategy_spec
        metrics = attempt.observed_metrics
        oos = metrics.get("out_of_sample_sharpe")
        print(
            f"  {spec.get('family', '?'):20s} {spec.get('direction', '?'):11s} "
            f"state={attempt.state:16s} "
            f"oos={'n/a' if oos is None else round(oos, 2):>6} "
            f"strategy_id={attempt.bitpro_strategy_id or '-':>6} "
            f"backtest={attempt.bitpro_backtest_id or '-':>10} "
            f"paper={attempt.paper_instance_id or '-'}"
        )

    print("\n=== events ===")
    for event in projection.events:
        body = str(event.payload)
        if event.event_type in {"candidate_proposed", "candidate_mutated"}:
            body = body[:80]
        print(f"  {event.event_type:22s} {body[:400]}")

    papered = [a for a in projection.attempts if a.paper_instance_id]
    if not papered:
        print("\nNo candidate reached paper.")
        for event in projection.reflexion_history:
            print(f"  {event.candidate_id}: {', '.join(event.reason_codes) or '(none)'}")
            for key in ("detail", "details", "observations", "constraints", "notes"):
                value = getattr(event, key, None)
                if value:
                    print(f"      {key}: {str(value)[:400]}")
        return 1

    print(f"\npaper instance running: {papered[-1].paper_instance_id}")

    observe_mission(controller, client=bitpro)
    print(f"after observation  : state={controller.projection.state}")
    print(f"paper observation  : {controller.projection.paper_observation}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
