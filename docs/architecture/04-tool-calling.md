# 04 Tool Calling / 工具调用

## English

ToolRegistry is the single catalog for agent-callable tools. Sprint 01 tools are market summary, ticker reads, RAG search, memory write/search, strategy/backtest/paper placeholders, and live order intent.

Policy:

- non-live tools can run automatically from chat
- live order intent requires approval
- every tool call must create a trace event
- large outputs should be summarized before entering model context

## 中文

ToolRegistry 是 Agent 可调用工具的唯一目录。Sprint 01 包含行情归纳、ticker 读取、RAG 搜索、Memory 写入/搜索，以及策略、回测、模拟盘、实盘订单意图的扩展位。

策略：

- 非实盘工具可由聊天自动触发
- 实盘订单意图必须审批
- 每次工具调用必须生成 trace event
- 大结果进入模型上下文前要摘要

