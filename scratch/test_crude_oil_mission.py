"""
ARC Autonomous Research Mission Runner: Crude Oil (WTI/OIL-USDT) 1H Strategy
Target: 100% Annual Return Target via Autonomous MCTS & Red-Blue Adversarial Evolution
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
    print("=" * 80)
    print("🚀 启动 ARC (Autonomous Research Core) 自主策略研究与进化测试任务")
    print("🎯 研究目标: 原油标的 (OIL-USDT/WTI) 1小时 (1H) 周期策略，回测目标年化收益率 >= 100%")
    print("=" * 80)

    symbol = "OIL-USDT-SWAP"
    objective = "自主研究原油 (OIL-USDT) 1小时 (1H) 周期策略，寻找极强Alpha以实现回测一年收益率达到100%，红蓝对抗通过后自动配置上线模拟盘"

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

    print(f"\n[任务初始化] Mission ID: {ctrl.mission_id}")
    print(f"[初始状态] {ctrl.projection.state}")

    print("\n----------------------------------------------------------------")
    print("🔄 开始运行 ARC 自主循环：Goal -> MCTS Node -> Blue Proposal -> Red Attack -> Reflexion -> Mutation -> Validation -> Incubation")
    print("----------------------------------------------------------------\n")

    run_autonomous_arc_loop(ctrl.mission_id)

    proj = ctrl.projection
    print(f"\n================================================================")
    print(f"📊 任务执行完毕 - 终态: {proj.state.upper()}")
    print(f"================================================================")
    print(f"总产生的策略候选 (Attempts): {len(proj.attempts)} 个")
    print(f"反思账本记录 (Reflexions): {len(proj.reflexion_history)} 条")
    print(f"已上线的模拟盘实例 ID: {proj.attempts[-1].paper_instance_id if proj.attempts else 'None'}")

    print("\n📜 策略进化树与红蓝攻防轨迹:")
    for idx, att in enumerate(proj.attempts, 1):
        print(f"\n--- [候选策略 #{idx}] Attempt ID: {att.attempt_id} | 状态: {att.state} ---")
        print(f"假设 (Hypothesis): {att.hypothesis}")
        print("策略代码片段:")
        print("-" * 40)
        print(att.strategy_code.strip())
        print("-" * 40)
        if att.observed_metrics:
            print(f"回测与压测指标: {json.dumps(att.observed_metrics, indent=2, ensure_ascii=False)}")
        if att.paper_instance_id:
            print(f"🎉 模拟盘自动孵化实例 ID: {att.paper_instance_id}")

    if proj.reflexion_history:
        print("\n🧠 归因反思账本 (Reflexion Memory Ledger 提取的负向约束):")
        for r_evt in proj.reflexion_history:
            print(f"- 失败归因 [{r_evt.failure_class}]: {r_evt.reason_codes}")
            for c in r_evt.negative_constraints:
                print(f"  ❌ 提取强约束 Prompt: {c}")

    print("\n" + "=" * 80)
    if any(att.state in ["validated", "paper_observing"] for att in proj.attempts):
        print("✅ 任务成功完成！ARC 自主搜索并进化出了符合要求、通过红蓝压测的原油 1H 高收益策略，并已自动上线模拟盘！")
    else:
        print("⚠️ 任务失败：ARC 未能找到符合要求的策略。")
    print("=" * 80)

if __name__ == "__main__":
    main()
