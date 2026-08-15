"""
ARC Autonomous Research Mission Runner: Crude Oil (CLUSDT / CL-USDT-SWAP) 1H Strategy
"""

import sys
import json
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

from hypertrade.arc.contracts import ARCGoalV1, ARCBudgetV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.router import _ARC_MISSIONS, run_autonomous_arc_loop

def main():
    symbol = "CL-USDT-SWAP"
    objective = "研究 CLUSDT (WTI原油永续合约) 1小时 (1H) 周期策略，实现回测一年收益率达到100%，红蓝对抗过检后自动配置上线模拟盘"

    preauth = PaperPreauthorizationV1(symbols=[symbol])
    goal = ARCGoalV1(
        objective=objective,
        symbols=[symbol],
        timeframes=["1H"],
        budget=ARCBudgetV1(max_candidates=10),
        paper_authorization=preauth,
    )

    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl

    run_autonomous_arc_loop(ctrl.mission_id)

    proj = ctrl.projection
    print("Mission ID:", ctrl.mission_id)
    for att in proj.attempts:
        print("Candidate ID:", att.candidate_id, "State:", att.state, "Paper ID:", att.paper_instance_id)
        print(att.strategy_code)

if __name__ == "__main__":
    main()
