#!/usr/bin/env python3
"""测试 Agent 输出格式化效果"""

from hypertrade.agent.formatters import AgentOutputFormatter

# 测试 1: 全球市场输出
print("=" * 80)
print("测试 1: 全球市场快照格式化")
print("=" * 80)

global_market_data = {
    "status": "healthy",
    "risk_regime": "mixed",
    "volatility_regime": "elevated",
    "dollar_pressure": "neutral",
    "rates_pressure": "elevated",
    "cross_asset_signal": "conflicting",
    "tickers": [
        {"symbol": "^GSPC", "price": 5900.5, "change_pct": -0.35},
        {"symbol": "^IXIC", "price": 19200.2, "change_pct": -0.52},
        {"symbol": "^HSI", "price": 20100.8, "change_pct": 2.15},
        {"symbol": "^N225", "price": 38500.3, "change_pct": 1.88},
        {"symbol": "^VIX", "price": 16.5, "change_pct": 3.2},
    ],
    "as_of": "2026-07-06T10:30:00Z",
}

formatted = AgentOutputFormatter.format_tool_result("global_market_snapshot", global_market_data)
print(formatted)

# 测试 2: RAG 搜索输出
print("\n\n")
print("=" * 80)
print("测试 2: RAG 知识库搜索格式化")
print("=" * 80)

rag_data = {
    "hits": [
        {
            "title": "市场风险管理策略",
            "source_path": "docs/risk/market_risk.md",
            "score": 0.92,
            "content": "在高波动市场环境下，应该采取分散投资策略，降低单一资产的暴露度。建议将仓位控制在总资金的40-50%之间...",
        },
        {
            "title": "波动率交易指南",
            "source_path": "docs/strategies/volatility_trading.md",
            "score": 0.85,
            "content": "VIX 指数高于 20 时表明市场恐慌情绪升温，此时可以考虑做空波动率或者买入看跌期权保护现有持仓...",
        },
    ]
}

formatted = AgentOutputFormatter.format_tool_result("rag_search", rag_data)
print(formatted)

# 测试 3: 记忆搜索输出
print("\n\n")
print("=" * 80)
print("测试 3: 记忆搜索格式化")
print("=" * 80)

memory_data = {
    "items": [
        {
            "kind": "market_summary",
            "content": "2026-07-05 市场总结：美股三大指数全线下跌，纳指跌幅最大达0.8%。亚洲市场表现强劲，恒指涨2.1%。VIX 指数升至17.2，市场恐慌情绪升温。",
            "tags": ["market", "summary", "2026-07-05"],
            "usage_count": 5,
        },
        {
            "kind": "strategy_note",
            "content": "动量突破策略在震荡市场中表现不佳，建议切换到均值回归策略。回测显示在VIX>15时，均值回归策略的胜率提升10%。",
            "tags": ["strategy", "momentum", "mean_reversion"],
            "usage_count": 3,
        },
    ]
}

formatted = AgentOutputFormatter.format_tool_result("memory_search", memory_data)
print(formatted)

# 测试 4: 策略库搜索输出
print("\n\n")
print("=" * 80)
print("测试 4: 策略库搜索格式化")
print("=" * 80)

strategy_data = {
    "strategies": [
        {
            "name": "动量突破策略 v2",
            "description": "基于价格突破和成交量确认的趋势跟踪策略",
            "performance": {
                "sharpe_ratio": 1.85,
                "total_return": 45.2,
            },
        },
        {
            "name": "均值回归策略 v1",
            "description": "在震荡市场中利用价格回归均值的特性进行交易",
            "performance": {
                "sharpe_ratio": 1.62,
                "total_return": 32.8,
            },
        },
    ]
}

formatted = AgentOutputFormatter.format_tool_result("strategy_library_search", strategy_data)
print(formatted)

# 测试 5: 市场情报输出
print("\n\n")
print("=" * 80)
print("测试 5: 市场情报格式化")
print("=" * 80)

intelligence_data = {
    "symbol": "BTC-USDT",
    "price_data": {
        "price": 67850.25,
        "change_24h": 2.35,
        "volume_24h": 28500000000,
    },
    "funding_rate": {
        "current": 0.0085,
        "predicted": 0.0092,
    },
    "open_interest": {
        "value": 15200000000,
        "change_24h": 3.8,
    },
}

formatted = AgentOutputFormatter.format_tool_result("market_intelligence", intelligence_data)
print(formatted)

# 测试 6: 错误格式化
print("\n\n")
print("=" * 80)
print("测试 6: 错误信息格式化")
print("=" * 80)

error_formatted = AgentOutputFormatter.format_error(
    "timeout",
    "API request timeout after 30 seconds"
)
print(error_formatted)

# 测试 7: 思考过程格式化
print("\n\n")
print("=" * 80)
print("测试 7: Agent 思考过程格式化")
print("=" * 80)

thinking_formatted = AgentOutputFormatter.format_thinking(
    "市场呈现混合信号，需要更多数据来确定方向",
    step=1
)
print(thinking_formatted)

thinking_formatted = AgentOutputFormatter.format_thinking(
    "根据全球市场和加密货币市场的综合分析，建议保持观望",
    step=2
)
print(thinking_formatted)

# 测试 8: 最终回答格式化
print("\n\n")
print("=" * 80)
print("测试 8: 最终回答格式化")
print("=" * 80)

answer_formatted = AgentOutputFormatter.format_final_answer(
    "基于当前市场分析，建议采取以下操作：\n\n"
    "1. 保持 40-50% 仓位，不要过度暴露\n"
    "2. 关注亚洲市场的强劲表现，可以考虑增加亚洲资产配置\n"
    "3. VIX 指数偏高，市场波动加大，建议使用止损保护现有持仓\n"
    "4. 等待更明确的方向信号再加大仓位\n\n"
    "风险提示：以上分析仅供参考，不构成投资建议。"
)
print(answer_formatted)

print("\n\n")
print("=" * 80)
print("✅ 所有格式化测试完成！")
print("=" * 80)
