"""
Agent 输出优化需求分析

需要优化的输出类型：
1. 工具调用结果输出
2. 市场数据输出
3. 策略分析输出
4. 执行状态输出
5. 错误信息输出
6. Agent 推理过程输出
7. 最终回答输出

优化目标：
- 结构化、层次清晰
- 使用 emoji 增强可读性
- 关键信息突出显示
- 减少冗余信息
- 统一的视觉风格
"""

from __future__ import annotations

from typing import Any


class AgentOutputFormatter:
    """统一的 Agent 输出格式化器"""

    @staticmethod
    def format_tool_result(tool_name: str, result: Any) -> str:
        """格式化工具调用结果

        Args:
            tool_name: 工具名称
            result: 工具返回结果

        Returns:
            格式化后的字符串
        """
        # 根据不同工具类型使用不同格式化策略
        if tool_name == "world_model_snapshot":
            return AgentOutputFormatter._format_world_model(result)
        elif tool_name == "global_market_snapshot":
            return AgentOutputFormatter._format_global_market(result)
        elif tool_name == "market_intelligence":
            return AgentOutputFormatter._format_market_intelligence(result)
        elif tool_name == "rag_search":
            return AgentOutputFormatter._format_rag_search(result)
        elif tool_name == "memory_search":
            return AgentOutputFormatter._format_memory_search(result)
        elif tool_name == "strategy_library_search":
            return AgentOutputFormatter._format_strategy_search(result)
        else:
            # 默认格式化
            return AgentOutputFormatter._format_generic(tool_name, result)

    @staticmethod
    def _format_world_model(data: dict[str, Any]) -> str:
        """格式化世界模型输出"""
        from hypertrade.world_model.formatters import format_world_model_snapshot

        return format_world_model_snapshot(data)

    @staticmethod
    def _format_global_market(data: dict[str, Any]) -> str:
        """格式化全球市场输出"""
        from hypertrade.world_model.formatters import format_global_market

        return format_global_market(data)

    @staticmethod
    def _format_market_intelligence(data: dict[str, Any]) -> str:
        """格式化市场情报输出"""
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("📊 市场情报 (Market Intelligence)")
        lines.append("=" * 70)

        symbol = data.get("symbol", "Unknown")
        lines.append(f"\n币种: {symbol}")

        # 价格数据
        if "price_data" in data:
            pd = data["price_data"]
            lines.append("\n【价格数据】")
            lines.append(f"  当前价格: ${pd.get('price', 0):.4f}")
            lines.append(f"  24h 变化: {pd.get('change_24h', 0):+.2f}%")
            lines.append(f"  成交量: ${pd.get('volume_24h', 0):,.0f}")

        # 资金费率
        if "funding_rate" in data:
            fr = data["funding_rate"]
            lines.append("\n【资金费率】")
            lines.append(f"  当前费率: {fr.get('current', 0):.4f}%")
            lines.append(f"  预测费率: {fr.get('predicted', 0):.4f}%")

        # OI 数据
        if "open_interest" in data:
            oi = data["open_interest"]
            lines.append("\n【持仓量】")
            lines.append(f"  当前 OI: ${oi.get('value', 0):,.0f}")
            lines.append(f"  24h 变化: {oi.get('change_24h', 0):+.2f}%")

        lines.append("=" * 70)
        return "\n".join(lines)

    @staticmethod
    def _format_rag_search(data: dict[str, Any]) -> str:
        """格式化知识库搜索输出"""
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("📚 知识库搜索结果 (Knowledge Base)")
        lines.append("=" * 70)

        hits = data.get("hits", [])
        if not hits:
            lines.append("\n❌ 未找到相关内容")
        else:
            lines.append(f"\n找到 {len(hits)} 条相关内容：\n")
            for i, hit in enumerate(hits, 1):
                lines.append(f"{i}. 📄 {hit.get('title', 'Untitled')}")
                lines.append(f"   来源: {hit.get('source_path', 'Unknown')}")
                lines.append(f"   相关度: {'⭐' * min(5, int(hit.get('score', 0) * 5))}")

                content = hit.get("content", "")
                if content:
                    preview = content[:150] + "..." if len(content) > 150 else content
                    lines.append(f"   内容: {preview}")
                lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    @staticmethod
    def _format_memory_search(data: dict[str, Any]) -> str:
        """格式化记忆搜索输出"""
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("🧠 记忆搜索结果 (Memory)")
        lines.append("=" * 70)

        items = data.get("items", [])
        if not items:
            lines.append("\n❌ 未找到相关记忆")
        else:
            lines.append(f"\n找到 {len(items)} 条记忆：\n")
            for i, item in enumerate(items, 1):
                kind = item.get("kind", "unknown")
                content = item.get("content", "")
                tags = item.get("tags", [])
                usage = item.get("usage_count", 0)

                kind_emoji = {
                    "market_summary": "📊",
                    "strategy_note": "📝",
                    "insight": "💡",
                    "decision": "🎯",
                }

                emoji = kind_emoji.get(kind, "📌")
                lines.append(f"{i}. {emoji} {kind}")
                lines.append(f"   使用次数: {usage} 次")
                if tags:
                    lines.append(f"   标签: {', '.join(tags)}")

                preview = content[:100] + "..." if len(content) > 100 else content
                lines.append(f"   内容: {preview}")
                lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    @staticmethod
    def _format_strategy_search(data: dict[str, Any]) -> str:
        """格式化策略库搜索输出"""
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("📖 策略库搜索结果 (Strategy Library)")
        lines.append("=" * 70)

        strategies = data.get("strategies", [])
        if not strategies:
            lines.append("\n❌ 未找到相关策略")
        else:
            lines.append(f"\n找到 {len(strategies)} 个策略：\n")
            for i, strat in enumerate(strategies, 1):
                name = strat.get("name", "Unnamed")
                desc = strat.get("description", "")
                performance = strat.get("performance", {})

                lines.append(f"{i}. 🎯 {name}")
                if desc:
                    lines.append(f"   描述: {desc}")

                if performance:
                    sharpe = performance.get("sharpe_ratio", 0)
                    returns = performance.get("total_return", 0)
                    lines.append(f"   表现: 收益 {returns:+.2f}%, Sharpe {sharpe:.2f}")

                lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    @staticmethod
    def _format_generic(tool_name: str, result: Any) -> str:
        """通用格式化"""
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append(f"🔧 {tool_name}")
        lines.append("=" * 70)

        if isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, (list, dict)):
                    lines.append(f"{key}: {len(value)} 项")
                else:
                    lines.append(f"{key}: {value}")
        else:
            lines.append(str(result))

        lines.append("=" * 70)
        return "\n".join(lines)

    @staticmethod
    def format_error(error_type: str, error_message: str) -> str:
        """格式化错误信息

        Args:
            error_type: 错误类型
            error_message: 错误消息

        Returns:
            格式化后的错误信息
        """
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("❌ 错误 (Error)")
        lines.append("=" * 70)
        lines.append(f"\n类型: {error_type}")
        lines.append(f"消息: {error_message}")
        lines.append("\n💡 建议:")

        # 根据错误类型给出建议
        if "timeout" in error_message.lower():
            lines.append("  • 请求超时，请稍后重试")
        elif "api" in error_message.lower():
            lines.append("  • API 连接失败，请检查网络")
        elif "permission" in error_message.lower():
            lines.append("  • 权限不足，请检查配置")
        else:
            lines.append("  • 请查看详细日志了解更多信息")

        lines.append("=" * 70)
        return "\n".join(lines)

    @staticmethod
    def format_thinking(content: str, step: int = 0) -> str:
        """格式化 Agent 思考过程

        Args:
            content: 思考内容
            step: 步骤编号

        Returns:
            格式化后的思考过程
        """
        if step > 0:
            return f"\n💭 思考 ({step}): {content}\n"
        else:
            return f"\n💭 {content}\n"

    @staticmethod
    def format_final_answer(answer: str) -> str:
        """格式化最终回答

        Args:
            answer: 回答内容

        Returns:
            格式化后的回答
        """
        lines = []
        lines.append("\n" + "=" * 70)
        lines.append("💬 回答 (Answer)")
        lines.append("=" * 70)
        lines.append(f"\n{answer}")
        lines.append("\n" + "=" * 70)
        return "\n".join(lines)
