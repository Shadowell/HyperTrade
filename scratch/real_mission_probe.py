"""Run a full ARC mission against the configured real history window.

Shows what the autonomous loop actually does end to end: what it proposed, what the
evidence said, what it concluded, and whether anything reached paper.

    BITPRO_SQLITE_PATH=... uv run python scratch/real_mission_probe.py [OBJECTIVE]
"""

from __future__ import annotations

import sys

from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence import preflight_window
from hypertrade.arc.router import _ARC_MISSIONS, run_autonomous_arc_loop

SYMBOL = "BTC-USDT-SWAP"


def main(argv: list[str]) -> int:
    objective = argv[1] if len(argv) > 1 else "在 BTC 上找到一个稳健的、样本外站得住的交易优势"

    print(f"preflight: {preflight_window(symbol=SYMBOL, timeframe='1H')}\n")

    goal = ARCGoalV1(
        objective=objective,
        symbols=[SYMBOL],
        budget=ARCBudgetV1(max_candidates=8),
        paper_authorization=PaperPreauthorizationV1(symbols=[SYMBOL]),
    )
    controller = ARCController(goal=goal)
    _ARC_MISSIONS[controller.mission_id] = controller

    run_autonomous_arc_loop(controller.mission_id, parallel_workers=4)

    projection = controller.projection
    print(f"objective: {objective}")
    print(f"mission state: {projection.state}")
    print(f"candidates used: {projection.goal.budget.candidates_used}")
    print(f"attempts: {len(projection.attempts)}\n")

    for attempt in projection.attempts:
        spec = attempt.strategy_spec
        metrics = attempt.observed_metrics
        oos = metrics.get("out_of_sample_sharpe")
        print(
            f"  {spec.get('family', '?'):22s} {spec.get('direction', '?'):11s} "
            f"state={attempt.state:14s} "
            f"oos_sharpe={'n/a' if oos is None else round(oos, 2):>7} "
            f"trades={metrics.get('out_of_sample_trades', 'n/a'):>5} "
            f"basis={metrics.get('ranking_basis', 'n/a')}"
        )

    print("\nrejection reasons recorded by reflexion:")
    for event in projection.reflexion_history:
        codes = ", ".join(event.reason_codes) or "(none)"
        print(f"  {event.candidate_id}: {codes}")

    paper = [a.paper_instance_id for a in projection.attempts if a.paper_instance_id]
    print(f"\npaper instances provisioned: {paper or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
