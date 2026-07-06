#!/usr/bin/env python3
"""HyperTrade UI Enhancement Demo - 展示所有用户交互优化"""

import sys
import time
from datetime import datetime

# 确保可以导入 hypertrade 模块
sys.path.insert(0, "backend/src")

from hypertrade.ui.colors import Color, ColorTheme
from hypertrade.ui.config import ConfigManager
from hypertrade.ui.formatter import EnhancedFormatter
from hypertrade.ui.progress import ProgressBar, Spinner


def demo_colors():
    """演示彩色输出"""
    print("\n" + "=" * 80)
    print("演示 1: 彩色终端输出")
    print("=" * 80 + "\n")

    color = Color()

    # 基本颜色
    print("【基本颜色】")
    print(f"  常规文本: {color.paint('这是普通文本', 'value')}")
    print(f"  标签: {color.paint('标签', 'label')}")
    print(f"  静音: {color.paint('次要信息', 'muted')}")
    print(f"  加粗: {color.bold('重要信息')}")
    print(f"  斜体: {color.italic('斜体文本')}")
    print(f"  下划线: {color.underline('下划线文本')}")

    # 状态颜色
    print("\n【状态指示】")
    print(f"  {color.success('✓ 成功')}")
    print(f"  {color.error('✗ 错误')}")
    print(f"  {color.warning('⚠ 警告')}")
    print(f"  {color.info('ℹ 信息')}")

    # 交易颜色
    print("\n【交易信号】")
    print(f"  {color.bullish('↑ 看涨 / 多头')}")
    print(f"  {color.bearish('↓ 看跌 / 空头')}")
    print(f"  {color.neutral('→ 中性 / 观望')}")

    # 情绪指标
    print("\n【市场情绪】")
    print(f"  {color.sentiment(0.8)} (0.8 - 强烈看涨)")
    print(f"  {color.sentiment(0.3)} (0.3 - 看涨)")
    print(f"  {color.sentiment(0.0)} (0.0 - 中性)")
    print(f"  {color.sentiment(-0.3)} (-0.3 - 看跌)")
    print(f"  {color.sentiment(-0.8)} (-0.8 - 强烈看跌)")

    # 百分比变化
    print("\n【价格变化】")
    print(f"  BTC: {color.change_percent(5.23)}")
    print(f"  ETH: {color.change_percent(-2.45)}")
    print(f"  SOL: {color.change_percent(0.00)}")

    # 价格格式化
    print("\n【价格显示】")
    print(f"  BTC: {color.price(67850.25)}")
    print(f"  ETH: {color.price(3456.78)}")
    print(f"  SOL: {color.price(156.32)}")


def demo_formatter():
    """演示增强格式化器"""
    print("\n" + "=" * 80)
    print("演示 2: 增强格式化输出")
    print("=" * 80 + "\n")

    formatter = EnhancedFormatter()

    # Header
    formatter.header("HyperTrade 交易系统", subtitle="AI 驱动的量化交易平台")

    # Section
    formatter.section("系统状态")
    formatter.kv("运行模式", "Production", indent=1)
    formatter.kv("数据库", "PostgreSQL", indent=1)
    formatter.kv("缓存", "Redis", indent=1)
    formatter.kv("队列", "Celery", indent=1)

    # Subsection
    formatter.subsection("市场连接")
    formatter.kv("OKX", "✓ 已连接", indent=2)
    formatter.kv("Binance", "✓ 已连接", indent=2)
    formatter.kv("BitPro", "✓ 已连接", indent=2)

    # List items
    formatter.section("活跃策略")
    formatter.list_item("动量突破策略 v2.1 - 运行中")
    formatter.list_item("均值回归策略 v1.5 - 运行中")
    formatter.list_item("网格交易策略 v3.0 - 暂停")

    # Status messages
    formatter.section("最近事件")
    formatter.success("策略 #42 触发买入信号")
    formatter.info("市场数据已更新")
    formatter.warning("VIX 指数升至 18.5")
    formatter.error("策略 #15 执行失败")

    # Table
    formatter.section("持仓概览")
    headers = ["币种", "数量", "成本价", "当前价", "盈亏%"]
    rows = [
        ["BTC", "0.5", "$65,000", "$67,850", "+4.38%"],
        ["ETH", "10", "$3,200", "$3,456", "+8.00%"],
        ["SOL", "100", "$150", "$156", "+4.00%"],
    ]
    formatter.table(headers, rows, alignments=["left", "right", "right", "right", "right"])

    # Box
    formatter.section("风险提示")
    formatter.box(
        "加密货币交易具有高风险性。\n"
        "请确保您了解相关风险并谨慎投资。\n"
        "本系统仅供研究和学习使用。",
        title="⚠️ 重要提示",
    )

    # Market price
    formatter.section("实时行情")
    formatter.market_price("BTC-USDT", 67850.25, 2.35)
    formatter.market_price("ETH-USDT", 3456.78, -1.23)
    formatter.market_price("SOL-USDT", 156.32, 4.56)

    # Sentiment indicator
    formatter.section("市场情绪")
    formatter.sentiment_indicator(0.65, label="综合情绪")
    formatter.sentiment_indicator(0.35, label="恐慌指数")
    formatter.sentiment_indicator(-0.15, label="贪婪指数")

    # Timestamp
    formatter.section("系统时间")
    formatter.timestamp()

    # Divider
    formatter.divider()


def demo_progress():
    """演示进度指示器"""
    print("\n" + "=" * 80)
    print("演示 3: 进度指示器")
    print("=" * 80 + "\n")

    color = Color()

    # Progress bar
    print(color.paint("【进度条】", "section"))
    print("加载市场数据...\n")

    progress = ProgressBar(100, prefix="处理: ", suffix="完成")
    for i in range(101):
        progress.update(i)
        time.sleep(0.02)
    progress.finish()

    print("\n")

    # Spinner - basic
    print(color.paint("【基础旋转器】", "section"))
    spinner = Spinner("分析市场趋势")
    spinner.start()
    time.sleep(2)
    spinner.stop(color.success("✓ 分析完成"))

    print("")

    # Spinner - different styles
    print(color.paint("【不同风格的旋转器】", "section"))

    styles = [
        ("FRAMES", Spinner.FRAMES, "默认风格"),
        ("DOTS", Spinner.DOTS, "点状风格"),
        ("ARROW", Spinner.ARROW, "箭头风格"),
        ("CIRCLE", Spinner.CIRCLE, "圆形风格"),
        ("GROWING", Spinner.GROWING, "增长风格"),
    ]

    for name, frames, desc in styles:
        spinner = Spinner(f"测试 {desc}", frames=frames, interval=0.1)
        spinner.start()
        time.sleep(1.5)
        spinner.stop(color.success(f"✓ {desc} 完成"))
        time.sleep(0.3)


def demo_real_world_scenario():
    """演示真实场景"""
    print("\n" + "=" * 80)
    print("演示 4: 真实交易场景模拟")
    print("=" * 80 + "\n")

    formatter = EnhancedFormatter()
    color = Color()

    # Scenario: 执行交易策略
    formatter.banner(
        "HyperTrade Agent",
        subtitle="智能交易决策系统",
        items=[
            ("模式", "Live Trading"),
            ("策略", "Momentum Breakout v2.1"),
            ("账户", "Main Account"),
        ],
    )

    # Step 1: 收集市场数据
    formatter.section("步骤 1: 收集市场数据")
    with Spinner("正在获取实时行情", frames=Spinner.FRAMES) as spinner:
        time.sleep(1.5)

    formatter.success("✓ 获取到 20 个市场指标")
    formatter.kv("数据源", "OKX + Binance", indent=1)
    formatter.kv("延迟", "< 100ms", indent=1)
    print("")

    # Step 2: 分析市场制度
    formatter.section("步骤 2: 分析市场制度")
    with Spinner("运行制度分类算法", frames=Spinner.CIRCLE) as spinner:
        time.sleep(1.5)

    formatter.success("✓ 制度分析完成")
    formatter.kv("风险制度", color.neutral("Mixed"), indent=1)
    formatter.kv("波动率", color.warning("Elevated (VIX 16.5)"), indent=1)
    formatter.kv("跨资产信号", color.warning("Conflicting"), indent=1)
    print("")

    # Step 3: 生成交易信号
    formatter.section("步骤 3: 生成交易信号")
    with Spinner("计算信号强度", frames=Spinner.GROWING) as spinner:
        time.sleep(1.5)

    formatter.success("✓ 信号生成完成")
    formatter.sentiment_indicator(0.05, label="综合信号")
    print("")
    formatter.kv("信号强度", "+5/100 (中性)", indent=1)
    formatter.kv("置信度", "Medium", indent=1)
    formatter.kv("建议仓位", "40-50%", indent=1)
    print("")

    # Step 4: 执行决策
    formatter.section("步骤 4: 交易建议")
    formatter.box(
        "基于当前市场分析，建议采取以下操作：\n\n"
        "1. 保持观望 - 市场信号混合\n"
        "2. 维持现有仓位 (40-50%)\n"
        "3. 关注亚洲市场强劲表现\n"
        "4. 警惕波动率升高风险\n\n"
        "等待更明确的方向信号再加大仓位。",
        title="💡 决策建议",
    )

    # Summary
    formatter.divider()
    formatter.timestamp()
    formatter.info("分析耗时: 4.5 秒")


def demo_config_display():
    """演示配置显示"""
    print("\n" + "=" * 80)
    print("演示 5: 配置管理")
    print("=" * 80 + "\n")

    config_manager = ConfigManager()
    config_manager.show_config()


def demo_theme_comparison():
    """演示不同主题对比"""
    print("\n" + "=" * 80)
    print("演示 6: 主题对比")
    print("=" * 80 + "\n")

    themes = {
        "默认主题": ColorTheme.default(),
        "深色主题": ColorTheme.dark(),
        "浅色主题": ColorTheme.light(),
    }

    for theme_name, theme in themes.items():
        print(f"\n【{theme_name}】")
        color = Color(theme=theme)

        print(f"  标题: {color.paint('HyperTrade', 'title')}")
        print(f"  命令: {color.paint('/price BTC', 'command')}")
        print(f"  成功: {color.success('操作成功')}")
        print(f"  错误: {color.error('操作失败')}")
        print(f"  看涨: {color.bullish('+5.23%')}")
        print(f"  看跌: {color.bearish('-2.45%')}")


def main():
    """主函数"""
    formatter = EnhancedFormatter()

    # Welcome banner
    formatter.banner(
        "HyperTrade UI Enhancement Demo",
        subtitle="用户交互优化演示",
    )

    print("这个演示将展示 HyperTrade Agent 的所有用户交互优化：")
    print("")
    formatter.list_item("✨ 彩色终端输出")
    formatter.list_item("📊 增强的格式化输出")
    formatter.list_item("⏳ 进度条和旋转器")
    formatter.list_item("🎨 多主题支持")
    formatter.list_item("⚙️  配置管理界面")
    formatter.list_item("🎯 真实场景模拟")
    print("")

    input("按 Enter 开始演示...")

    # Run demos
    demo_colors()
    input("\n按 Enter 继续...")

    demo_formatter()
    input("\n按 Enter 继续...")

    demo_progress()
    input("\n按 Enter 继续...")

    demo_real_world_scenario()
    input("\n按 Enter 继续...")

    demo_config_display()
    input("\n按 Enter 继续...")

    demo_theme_comparison()

    # Final message
    print("\n")
    formatter.divider()
    formatter.header("演示完成！")
    formatter.success("所有 UI 优化功能已展示完毕")
    formatter.info("您可以通过配置文件自定义这些设置")
    formatter.info("配置文件位置: ~/.hypertrade/config.json")
    print("")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n演示已取消")
        sys.exit(0)
