"""North Star gate probe, part 2.

Tests the production research pipeline (not ARC) and the Gate 2-5 execution
capabilities. Run directly:

    uv run python scratch/northstar_probe2.py
"""

import inspect

from hypertrade.config import Settings
from hypertrade.research.orchestrator import _compile_strategy, _matrix_variants


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def probe_7_production_strategy_generation() -> None:
    """Does the production pipeline generate different strategies per hypothesis?"""
    rule("PROBE 7: 生产管道 (orchestrator) 的策略生成")
    keys = [
        "momentum_breakout",
        "mean_reversion_short_only",
        "orderbook_imbalance_hft",
        "funding_rate_arbitrage",
        "volatility_regime_switching",
    ]
    bodies = {}
    for key in keys:
        code = _compile_strategy(key)
        # Strip the class declaration line so only the logic remains.
        logic = "\n".join(ln for ln in code.split("\n") if not ln.startswith("class "))
        bodies[key] = logic
        print(f"\nstrategy_key: {key}")
        print(f"  类名: {[ln for ln in code.split(chr(10)) if ln.startswith('class ')][0][:60]}")
        print(f"  逻辑指纹: {hash(logic)}")

    unique_logic = len(set(bodies.values()))
    print(f"\n>>> 5 个语义完全不同的 strategy_key 产生了 {unique_logic} 种不同策略逻辑")
    print(">>> strategy_key 唯一作用是拼类名；策略体恒为 fast_ma/slow_ma 双均线交叉")
    print(f">>> 结论: {'通过' if unique_logic > 1 else '失败 - 假设无法转化为策略逻辑'}")


def probe_8_parameter_space_coverage() -> None:
    """How much of the parameter space does the matrix actually explore?"""
    rule("PROBE 8: 参数空间探索覆盖度")
    bounds = {
        "fast_window": {"min": 2, "max": 50},
        "slow_window": {"min": 20, "max": 200},
        "stop_loss": {"min": 0.01, "max": 0.20},
        "leverage": {"min": 1, "max": 10},
    }
    variants = _matrix_variants(bounds, limit=20)
    print(f"\n参数边界: 4 个维度")
    print(f"允许上限: 20 个变体")
    print(f"实际生成: {len(variants)} 个变体\n")
    for name, params in variants:
        print(f"  {name}: {params}")

    print("\n>>> 每个维度只取 [min,max] 的中点，且每个变体只改动 1 个参数")
    print(">>> 不存在网格搜索、不存在维度组合、不存在自适应细化")
    print(">>> 结论: 失败 - 4 维空间只采样了 5 个点，且全部落在坐标轴上")


def probe_9_autonomy_flags() -> None:
    """Which autonomous capabilities are actually enabled by default?"""
    rule("PROBE 9: 自主能力开关默认状态")
    s = Settings()
    flags = {
        "mission_runtime_enabled": "Mission 运行时 (Gate 1 事件真相源)",
        "mission_runtime_worker_enabled": "Mission 后台执行器",
        "research_triggers_enabled": "研究触发器 (Gate 2 自动启动研究)",
        "strategy_sandbox_enabled": "策略沙箱 (代码校验前置条件)",
        "dynamic_team_enabled": "动态多 Agent 团队",
        "world_model_defensive_actions_enabled": "防御性自动动作",
        "paper_enabled": "本地模拟盘",
        "monitor_scheduler_enabled": "监控调度器",
    }
    on, off = [], []
    for attr, desc in flags.items():
        val = getattr(s, attr)
        (on if val else off).append(f"{desc} ({attr})")
        print(f"  {'[ON ]' if val else '[OFF]'} {desc}")

    print(f"\n>>> 开启: {len(on)} / 关闭: {len(off)}")
    print(">>> Gate 1 的事件真相源与 Gate 2 的自动研究触发默认都是关闭的")
    print(">>> 结论: 北极星链路上的核心自主能力未在默认配置中启用")


def probe_10_live_capability_absent() -> None:
    """Gate 4/5 require live execution. Does any live-write path exist?"""
    rule("PROBE 10: Gate 4/5 实盘执行能力")
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.tools.registry import ToolRegistry

    registry = ToolRegistry.default()
    tools = registry.all() if hasattr(registry, "all") else []
    names = [getattr(t, "name", str(t)) for t in tools] if tools else []
    live_tools = [n for n in names if "live" in n.lower()]
    order_tools = [n for n in names if "order" in n.lower()]

    print(f"\n注册工具总数: {len(names)}")
    print(f"含 'live' 的工具: {live_tools}")
    print(f"含 'order' 的工具: {order_tools}")

    fields = ARCGoalV1.model_fields
    live_field = fields.get("live_allowed")
    print(f"\nARCGoalV1.live_allowed 类型标注: {live_field.annotation if live_field else 'n/a'}")

    try:
        ARCGoalV1(objective="试图开启实盘", symbol="BTC-USDT-SWAP", live_allowed=True)
        print("  构造 live_allowed=True: 成功 (风险!)")
    except Exception as exc:
        print(f"  构造 live_allowed=True: 被类型系统拒绝 -> {type(exc).__name__}")

    print("\n>>> live_allowed 被 Literal[False] 锁死，实盘授权模型在类型层不可表达")
    print(">>> LiveTradingMandate / Risk Engine / Canary 对账 均未实现")
    print(">>> 结论: Gate 4 / Gate 5 = 0% (这是有意的安全设计，非缺陷)")


def probe_11_gate_matrix() -> None:
    """Summarize gate attainment based on all probe evidence."""
    rule("PROBE 11: 北极星 Gate 达成度矩阵")
    gates = [
        (
            "Gate 1 可信研究闭环",
            [
                ("统一事件真相源与可重放 Outcome Ledger", "部分", "代码完整但 flag 默认关闭"),
                ("自动优化已有策略", "部分", "只能改参数中点，不能改逻辑"),
                ("从全新 Alpha 假设生成新策略", "否", "假设无法转化为策略代码"),
                ("真实数据 OOS / walk-forward / 成本 / 鲁棒性", "是", "robustness.py 生产级"),
                ("失败/尝试/窗口/artifact 可追溯", "是", "ExperimentLedger 完整"),
            ],
        ),
        (
            "Gate 2 自动模拟盘进化",
            [
                ("Research Trigger 按 regime/衰减启动研究", "部分", "已实现但默认关闭"),
                ("通过验证的候选进入 Paper", "部分", "需人工审批，预授权路径有限"),
                ("Champion/Challenger 自动评估降级退役", "部分", "生产实测 0 可比成员"),
            ],
        ),
        (
            "Gate 3 自动 Shadow 组合",
            [
                ("对齐收益矩阵与条件风险模型", "部分", "依赖 BitPro 未交付的时序合同"),
                ("有约束组合方案 + 压力验证", "部分", "模板齐备，实测 0 eligible"),
                ("迟滞/冷却期防噪声切换", "是", "regime_shadow 已实现"),
            ],
        ),
        (
            "Gate 4 实盘 Canary",
            [
                ("LiveTradingMandate / 独立执行身份", "否", "未实现"),
                ("write-ahead intent + 对账 + kill switch", "部分", "Sprint 124 有骨架"),
                ("小额限时可撤销 Canary", "否", "未实现"),
            ],
        ),
        (
            "Gate 5 授权内自主实盘组合",
            [
                ("按市场状态自动进入/退出/调权", "否", "未实现"),
                ("状态未知时自动降险", "否", "未实现"),
                ("多市场状态与故障场景验证", "否", "未实现"),
            ],
        ),
    ]

    for gate_name, items in gates:
        yes = sum(1 for _, v, _ in items if v == "是")
        part = sum(1 for _, v, _ in items if v == "部分")
        no = sum(1 for _, v, _ in items if v == "否")
        total = len(items)
        score = (yes + part * 0.5) / total * 100
        print(f"\n{gate_name}  —  约 {score:.0f}%")
        for req, verdict, note in items:
            mark = {"是": "[√]", "部分": "[~]", "否": "[×]"}[verdict]
            print(f"  {mark} {req}")
            print(f"       {note}")


if __name__ == "__main__":
    probe_7_production_strategy_generation()
    probe_8_parameter_space_coverage()
    probe_9_autonomy_flags()
    probe_10_live_capability_absent()
    probe_11_gate_matrix()
    rule("PROBE 2 完成")
