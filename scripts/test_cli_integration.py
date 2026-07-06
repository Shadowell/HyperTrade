#!/usr/bin/env python3
"""模拟 CLI 调用，测试新的渲染器集成"""

import sys
sys.path.insert(0, "backend/src")

from hypertrade.cli import render_run

# 模拟完整的 Agent 运行结果（从远程 API 返回的数据格式）
mock_agent_run = {
    "id": "run_test_20260706",
    "status": "completed",
    "tool_calls": [
        {
            "tool_name": "world_model_snapshot",
            "status": "success",
            "duration_ms": 1200,
        },
        {
            "tool_name": "global_market_snapshot",
            "status": "success",
            "duration_ms": 800,
        },
        {
            "tool_name": "rag_search",
            "status": "denied",
            "duration_ms": 0,
        },
    ],
    "trace_events": [
        {"tool_name": "world_model_snapshot", "status": "success"},
        {"tool_name": "global_market_snapshot", "status": "success"},
        {"tool_name": "rag_search", "status": "denied"},
    ],
    "final_answer": """## 全球市场分析报告

当前全球市场呈现**混合信号**，投资者需要保持谨慎。

### 📊 市场制度分类

根据多维度分析，当前市场状况如下：

- **风险制度**: ⚖️ Mixed - 信号冲突，多空分歧明显
- **波动率制度**: ⬆️ Elevated - VIX 指数 16.5，波动偏高
- **美元压力**: ➖ Neutral - DXY 100.87，持平
- **利率压力**: ➖ Neutral - 10Y美债收益率 4.485%
- **跨资产信号**: ⚡ Conflicting - 不同资产类别信号矛盾

### 🌍 关键市场表现

**美国市场** 🇺🇸
- 标普500: **-0.35%** (5,900.5点)
- 纳斯达克: **-0.52%** (19,200.2点)
- 罗素2000: **-0.28%** (2,050.3点)

市场情绪偏弱，科技股领跌。

**亚洲市场** 🇨🇳
- 恒生指数: **+2.15%** (20,100.8点) ✓
- 日经225: **+1.88%** (38,500.3点) ✓
- 上证指数: **+1.35%** (3,150.2点) ✓
- 韩国KOSPI: **+0.95%** (2,650.5点) ✓

亚洲市场表现强劲，受益于政策支持和经济数据改善。

**欧洲市场** 🇪🇺
- Euro Stoxx 50: **+0.15%** (4,850.2点)
- FTSE 100: **+0.08%** (8,200.5点)

欧洲市场小幅上涨，交投清淡。

**波动率指标** 📈
- VIX: 16.5 ⚠️ (偏高水平)
- 市场恐慌情绪有所升温

### 💹 加密货币市场

- **BTC**: $67,850.25 (**+2.35%**) - 趋势向上，强势
- **ETH**: $3,456.78 (**-1.23%**) - 短期回调
- **SOL**: $156.32 (**+4.56%**) - 表现强劲

### 🎯 交易建议

基于以上分析，给出以下建议：

**仓位管理**
1. **保持观望** - 市场信号混合，方向不明确
2. **维持现有仓位** - 建议保持 40-50% 仓位水平
3. **不建议加仓** - 等待更明确的趋势信号

**区域配置**
1. **关注亚洲市场** - 表现强劲，可考虑适度增配
2. **美国市场观望** - 等待调整后的入场机会
3. **欧洲市场中性** - 保持现有配置即可

**风险控制**
1. **使用止损** - VIX 偏高，波动风险加大
2. **分散投资** - 不要过度集中单一市场
3. **保留现金** - 留有余地应对突发情况

### ⚠️ 风险提示

- 市场存在高波动风险
- 跨资产信号相互矛盾，增加不确定性
- 地缘政治风险依然存在
- 建议使用止损保护现有持仓
- **本分析仅供参考，不构成投资建议**

---

**数据来源**: yfinance + Alpha Vantage
**分析时间**: 2026-07-06 10:30:00 UTC
**缓存命中率**: 85%
**数据成本**: $0.00
""",
    "report_markdown": "",  # 使用 final_answer 而不是 report_markdown
}

print("=" * 80)
print("测试: CLI 渲染器集成 (render_run)")
print("=" * 80)
print()
print("模拟执行: uv run ht ask '全球市场现在是什么状态？分析一下'")
print()
print("=" * 80)
print()

# 调用 CLI 的 render_run 函数
render_run(mock_agent_run)

print()
print("=" * 80)
print("✅ 测试完成")
print("=" * 80)
