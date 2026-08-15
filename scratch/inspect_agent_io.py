"""
ARC Full Input/Output Execution Inspector & BitPro Synchronous Deployment Logger
"""

import sys
import json
from pathlib import Path

# Add backend src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend" / "src"))

from hypertrade.arc.contracts import ARCGoalV1, ARCBudgetV1, PaperPreauthorizationV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.router import _ARC_MISSIONS, run_autonomous_arc_loop
from hypertrade.bitpro.mcp import BitProMcpClient

def main():
    print("=" * 100)
    print("📥 【AGENT 完整输入 (INPUT)】")
    print("=" * 100)

    symbol = "CL-USDT-SWAP"
    objective = "研究 CLUSDT (WTI原油永续合约) 1小时 (1H) 周期策略，实现回测一年收益率达到100%，红蓝对抗过检后自动配置上线模拟盘"

    input_payload = {
        "objective": objective,
        "symbol": symbol,
        "timeframe": "1H",
        "budget": {
            "max_candidates": 5
        },
        "paper_authorization": {
            "symbols": [symbol],
            "allowed_actions": ["configure", "start"]
        }
    }
    print(json.dumps(input_payload, indent=2, ensure_ascii=False))

    preauth = PaperPreauthorizationV1(symbols=[symbol])
    goal = ARCGoalV1(
        objective=objective,
        symbols=[symbol],
        timeframes=["1H"],
        budget=ARCBudgetV1(max_candidates=5),
        paper_authorization=preauth,
    )

    ctrl = ARCController(goal=goal)
    _ARC_MISSIONS[ctrl.mission_id] = ctrl

    print("\n" + "=" * 100)
    print("🔄 【AGENT 执行与中间过程 (EXECUTION & TRACE)】")
    print("=" * 100)
    print(f"Mission ID: {ctrl.mission_id}")
    
    run_autonomous_arc_loop(ctrl.mission_id)

    proj = ctrl.projection

    print("\n" + "=" * 100)
    print("📤 【AGENT 完整输出 (OUTPUT)】")
    print("=" * 100)
    
    print("\n1. 事件日志链 (Event Chain):")
    for evt in proj.events:
        print(f"  - [{evt.timestamp.strftime('%H:%M:%S')}] Event: {evt.event_type} | Payload Keys: {list(evt.payload.keys())}")

    print("\n2. 策略演化尝试列表 (Attempts & Candidates):")
    for att in proj.attempts:
        print(f"\n   Attempt ID: {att.attempt_id} | State: {att.state}")
        print(f"   Hypothesis: {att.hypothesis}")
        print(f"   Strategy Code:\n{att.strategy_code}")
        print(f"   Observed Metrics: {att.observed_metrics}")

    print("\n3. 因果归因反思 (Reflexion Memory):")
    for ref in proj.reflexion_history:
        print(f"   Failure Class: {ref.failure_class}")
        print(f"   Reason Codes: {ref.reason_codes}")
        print(f"   Negative Constraints: {ref.negative_constraints}")

    print("\n" + "=" * 100)
    print("🌐 【BITPRO API 真实同步调用与部署责任核验 (BITPRO PERSISTENCE VERIFICATION)】")
    print("=" * 100)
    
    validated_attempt = next((att for att in proj.attempts if att.state in ["validated", "paper_observing"]), None)
    if validated_attempt:
        strat_name = "[合约][1H][CTA] CL - 20周期突破8%动态止损 - 100U"
        print(f"正在准备将终态策略持久化写入 BitPro 系统...")
        print(f"提交策略名称: {strat_name}")
        print(f"提交策略代码长度: {len(validated_attempt.strategy_code)} 字符")

        try:
            client = BitProMcpClient()
            resp = client.strategy_create(
                name=strat_name,
                script_content=validated_attempt.strategy_code,
                description="ARC Autonomous Evolution Candidate for CLUSDT 1H",
                exchange="okx",
                symbols=["CLUSDT"],
            )
            print("\nBitPro API 响应结果 (BitPro API Response):")
            print(json.dumps(resp, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"\n⚠️ 无法直连本地 BitPro API 服务 (HTTP 127.0.0.1:8889): {e}")
            print("注意：BitPro 是独立运行的外部量化服务。要让策略直接出现在你打开的 BitPro 网页端，需要确保本地/服务器上的 BitPro 服务 (8889 端口) 处于开启状态。")

if __name__ == "__main__":
    main()
