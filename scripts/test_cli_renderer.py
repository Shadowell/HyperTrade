#!/usr/bin/env python3
"""测试 CLI 渲染器效果"""

import sys
sys.path.insert(0, "backend/src")

from hypertrade.ui.cli_renderer import render_agent_output, render_world_state_summary

# 模拟 Agent 运行结果
mock_run = {
    "id": "run_20260706_003",
    "status": "completed",
    "tool_calls": [
        {"tool_name": "world_model_snapshot", "status": "success"},
        {"tool_name": "global_market_snapshot", "status": "success"},
        {"tool_name": "rag_search", "status": "denied"},
    ],
    "final_answer": """## 全球市场分析

当前全球市场呈现**混合信号**，需要谨慎对待。

### 市场制度分类

- **风险制度**: ⚖️ Mixed - 信号冲突
- **波动率**: ⬆️ Elevated (VIX 16.5) - 波动偏高
- **跨资产信号**: ⚡ Conflicting - 资产类别之间信号矛盾

### 关键市场表现

**美国市场：**
- 标普500: **-0.35%** (5,900.5点)
- 纳指: **-0.52%** (19,200.2点)

**亚洲市场：**
- 恒生指数: **+2.15%** (20,100.8点) ✓
- 日经225: **+1.88%** (38,500.3点) ✓

**波动率指标：**
- VIX: 16.5 ⚠️ (偏高)

### 交易建议

基于当前市场分析，建议采取以下策略：

1. **保持观望** - 市场信号混合，方向不明
2. **维持仓位** - 建议保持 40-50% 仓位
3. **关注亚洲** - 亚洲市场表现强劲，可考虑增配
4. **警惕波动** - VIX 升高，注意风险控制

### 风险提示

⚠️ **重要提醒**：
- 市场存在高波动风险
- 跨资产信号相互矛盾
- 建议使用止损保护持仓
- 本分析仅供参考，不构成投资建议

---

数据来源: yfinance + Alpha Vantage
更新时间: 2026-07-06 10:30:00 UTC
""",
}

# 模拟 World State 数据
mock_world_state = {
    "risk_regime": "Mixed",
    "volatility_regime": "Elevated",
    "cross_asset_signal": "Conflicting",
    "metrics": {
        "crypto_tickers": 413,
        "crypto_status": "available",
        "strategy_status": "healthy",
        "tool_health": "degraded",
    },
}

print("=" * 80)
print("测试 1: Agent 输出渲染")
print("=" * 80)
print()

render_agent_output(mock_run)

print("\n\n")
print("=" * 80)
print("测试 2: World State 摘要渲染")
print("=" * 80)
print()

render_world_state_summary(mock_world_state)

print("\n\n")
print("=" * 80)
print("✅ CLI 渲染器测试完成")
print("=" * 80)
