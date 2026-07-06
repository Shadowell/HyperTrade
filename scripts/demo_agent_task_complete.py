#!/usr/bin/env python3
"""完整的 Agent 工具任务演示 - 集成所有 UI 优化"""

import sys
import time
from datetime import datetime

sys.path.insert(0, "backend/src")

from hypertrade.ui.colors import Color
from hypertrade.ui.formatter import EnhancedFormatter
from hypertrade.ui.progress import Spinner


def simulate_agent_task():
    """模拟完整的 Agent 工具执行任务"""

    formatter = EnhancedFormatter(width=80)
    color = Color()

    # ============================================================================
    # 任务开始
    # ============================================================================

    formatter.banner(
        "HyperTrade Agent 工具任务",
        subtitle="智能交易决策执行",
    )

    print(color.paint("任务 ID:", "label"), color.paint("task_20260706_001", "value"))
    print(color.paint("触发方式:", "label"), color.paint("用户请求", "value"))
    print(color.paint("开始时间:", "label"), color.paint(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "value"))
    print()

    # ============================================================================
    # 工具 1: 全球市场快照
    # ============================================================================

    formatter.section("工具 1: world_model_snapshot")

    with Spinner("正在收集全球市场数据", frames=Spinner.CIRCLE) as spinner:
        time.sleep(1.5)

    formatter.success("✓ 数据收集完成")

    # 显示全球市场数据
    formatter.subsection("全球市场状态")
    print()
    print(color.paint("══════════════════════════════════════════════", "border"))
    print(color.paint("🌍 全球市场状态", "title"))
    print(color.paint("══════════════════════════════════════════════", "border"))
    print()

    print(color.paint("状态:", "label"), color.success("✅ Healthy"))
    print()

    print(color.paint("【市场制度分类】", "section"))
    print(f"  风险制度: {color.neutral('⚖️  Mixed')}")
    print(f"  波动率:   {color.warning('⬆️  Elevated (VIX 16.5)')}")
    print(f"  美元压力: {color.info('Neutral')}")
    print(f"  利率压力: {color.warning('Elevated')}")
    print(f"  跨资产:   {color.warning('⚡ Conflicting')}")
    print()

    print(color.paint("【关键市场数据】", "section"))
    print(f"  美国:")
    print(f"    {color.bearish('📉')} 标普500  5,900.5 {color.change_percent(-0.35)}")
    print(f"    {color.bearish('📉')} 纳指    19,200.2 {color.change_percent(-0.52)}")
    print(f"  亚洲:")
    print(f"    {color.bullish('📈')} 恒指    20,100.8 {color.change_percent(2.15)}")
    print(f"    {color.bullish('📈')} 日经    38,500.3 {color.change_percent(1.88)}")
    print(f"  恐慌指数: VIX 16.5 {color.warning('(😐偏高)')}")
    print()

    formatter.kv("数据时间", "2026-07-06T10:30:00Z", indent=0)
    formatter.kv("数据来源", "yfinance + Alpha Vantage", indent=0)
    formatter.kv("获取耗时", "1.2 秒", indent=0)
    print()

    # ============================================================================
    # 工具 2: 加密货币市场数据
    # ============================================================================

    formatter.section("工具 2: market_summary")

    with Spinner("正在获取加密货币行情", frames=Spinner.GROWING) as spinner:
        time.sleep(1.2)

    formatter.success("✓ 行情获取完成")

    # 显示加密货币市场
    formatter.subsection("加密货币市场")
    print()

    formatter.table(
        headers=["币种", "价格", "24h 变化", "成交量", "趋势"],
        rows=[
            ["BTC", "$67,850.25", color.change_percent(2.35), "$28.5B", color.bullish("↑ 上涨")],
            ["ETH", "$3,456.78", color.change_percent(-1.23), "$12.3B", color.bearish("↓ 下跌")],
            ["SOL", "$156.32", color.change_percent(4.56), "$2.1B", color.bullish("↑ 上涨")],
        ],
        alignments=["left", "right", "right", "right", "center"],
    )
    print()

    formatter.kv("市场状态", color.success("活跃"), indent=0)
    formatter.kv("总市值", "$2.4T", indent=0)
    formatter.kv("BTC 占比", "54.2%", indent=0)
    print()

    # ============================================================================
    # 工具 3: RAG 知识库搜索
    # ============================================================================

    formatter.section("工具 3: rag_search")

    with Spinner("搜索知识库", frames=Spinner.DOTS) as spinner:
        time.sleep(1.0)

    formatter.success("✓ 找到 3 条相关内容")

    formatter.subsection("知识库检索结果")
    print()

    print(color.paint("1. 📄 市场风险管理策略", "value"))
    print(f"   来源: docs/risk/market_risk.md")
    print(f"   相关度: {color.success('⭐⭐⭐⭐')}")
    print(f"   内容: 在高波动市场环境下，应该采取分散投资策略...")
    print()

    print(color.paint("2. 📄 波动率交易指南", "value"))
    print(f"   来源: docs/strategies/volatility_trading.md")
    print(f"   相关度: {color.success('⭐⭐⭐⭐')}")
    print(f"   内容: VIX 指数高于 20 时表明市场恐慌情绪升温...")
    print()

    print(color.paint("3. 📄 趋势跟踪策略", "value"))
    print(f"   来源: docs/strategies/trend_following.md")
    print(f"   相关度: {color.info('⭐⭐⭐')}")
    print(f"   内容: 在明确的趋势中，使用动量指标可以提高胜率...")
    print()

    # ============================================================================
    # 工具 4: 策略库搜索
    # ============================================================================

    formatter.section("工具 4: strategy_library_search")

    with Spinner("查询策略库", frames=Spinner.ARROW) as spinner:
        time.sleep(0.8)

    formatter.success("✓ 找到 2 个匹配策略")

    formatter.subsection("策略库匹配结果")
    print()

    formatter.box(
        "策略名称: 动量突破策略 v2.1\n"
        "描述: 基于价格突破和成交量确认的趋势跟踪策略\n"
        "性能: 收益 +45.20%, Sharpe 1.85, 最大回撤 -12.3%\n"
        "适用场景: 趋势明显的市场",
        title="🎯 策略 #1",
    )
    print()

    formatter.box(
        "策略名称: 均值回归策略 v1.5\n"
        "描述: 在震荡市场中利用价格回归均值的特性进行交易\n"
        "性能: 收益 +32.80%, Sharpe 1.62, 最大回撤 -8.5%\n"
        "适用场景: 震荡市场",
        title="🎯 策略 #2",
    )
    print()

    # ============================================================================
    # 综合分析
    # ============================================================================

    formatter.section("综合分析")

    with Spinner("运行 AI 分析引擎", frames=Spinner.FRAMES) as spinner:
        time.sleep(2.0)

    formatter.success("✓ 分析完成")
    print()

    # 情绪指标
    formatter.subsection("市场情绪分析")
    formatter.sentiment_indicator(0.05, label="综合信号强度")
    print()

    # 信号评分
    formatter.subsection("信号评分")
    print()
    print(f"  {color.bullish('✓')} 亚洲强劲 (+2.2%)     → {color.bullish('+15 分')}")
    print(f"  {color.bullish('✓')} 铜价上涨（经济向好） → {color.bullish('+10 分')}")
    print(f"  {color.bearish('✗')} 避险情绪升温         → {color.bearish('-15 分')}")
    print(f"  {color.bearish('✗')} 跨资产矛盾           → {color.bearish('-5 分')}")
    print(f"  {color.paint('─────────────────────────────────', 'border')}")
    print(f"  {color.paint('总计:', 'label')} {color.neutral('+5/100 (中性观望)')}")
    print()

    # ============================================================================
    # 交易建议
    # ============================================================================

    formatter.section("交易建议")
    print()

    formatter.box(
        "基于当前市场分析，建议采取以下操作：\n\n"
        "【仓位管理】\n"
        "• 保持观望 - 市场信号混合\n"
        "• 维持现有仓位 (40-50%)\n"
        "• 不建议此时加大仓位\n\n"
        "【关注重点】\n"
        "• 亚洲市场持续强劲，可考虑增加亚洲资产配置\n"
        "• 警惕 VIX 指数升高，市场波动风险加大\n"
        "• 跨资产信号矛盾，等待更明确方向\n\n"
        "【执行计划】\n"
        "• 短期：保持观望，密切关注市场变化\n"
        "• 中期：等待更明确的趋势信号\n"
        "• 长期：保持分散投资策略",
        title="💡 智能决策",
    )
    print()

    # 风险提示
    formatter.box(
        "⚠️  市场存在高波动风险\n"
        "⚠️  跨资产信号相互矛盾\n"
        "⚠️  建议使用止损保护现有持仓\n"
        "⚠️  本分析仅供参考，不构成投资建议",
        title="⚠️  风险提示",
    )
    print()

    # ============================================================================
    # 任务完成
    # ============================================================================

    formatter.divider()
    print()

    formatter.header("任务执行完成")

    # 统计信息
    formatter.section("执行统计")
    formatter.table(
        headers=["指标", "数值"],
        rows=[
            ["工具调用次数", "4"],
            ["数据点收集", "20 个全球指标 + 3 个加密货币"],
            ["知识库检索", "3 条相关内容"],
            ["策略匹配", "2 个策略"],
            ["总耗时", "6.7 秒"],
            ["缓存命中率", "85%"],
            ["数据成本", "$0.00"],
        ],
        alignments=["left", "right"],
    )
    print()

    formatter.success("✓ 所有工具执行成功")
    formatter.info("分析报告已生成")
    formatter.timestamp()
    print()

    # 结束语
    print(color.paint("─" * 80, "border"))
    print()
    print(color.paint("💬 ", "info") + "感谢使用 HyperTrade Agent")
    print(color.paint("📊 ", "info") + "查看完整报告: /api/agent/runs/task_20260706_001")
    print(color.paint("📖 ", "info") + "文档: https://hypertrade.ai/docs")
    print()


if __name__ == "__main__":
    try:
        simulate_agent_task()
    except KeyboardInterrupt:
        print("\n\n任务已取消")
        sys.exit(0)
