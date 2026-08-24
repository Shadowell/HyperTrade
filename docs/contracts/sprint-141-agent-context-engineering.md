# Sprint Contract: Agent Context Engineering (P1-4 自主性基建)

## Sprint Name

`agent-context-engineering`

## Goal

给 planner 循环补上上下文工程地基：token 计量、超限压缩（compaction）、
压缩可观测。此前历史只靠 MAX_ITERATIONS=8 硬顶和水冷截断单条工具输出，
总历史无界增长没有管理；压缩落地后迭代上限可放宽到 12，为长程研究任务
（主线：多轮回测→门禁→晋升）腾出空间。

## In Scope

- 新模块 `agent/context.py`：
  - CJK 感知的确定性 token 估算（无外部依赖）。
  - `compact_messages`：按协议分组压缩——(assistant.tool_calls + 其 tool 结果)
    为一个组，旧组合并为单条带摘要的 assistant 消息（保持 OpenAI 消息协议
    合法性：tool 消息必须紧跟对应 assistant），system+首条 user 永远保留，
    最近 N 组原样保留。
- planner 集成：每次 provider 调用前估算历史 token，超预算触发一次压缩；
  `PlannerResult.context_compactions` / `history_tokens_last`；
  `ModelCallRecord.history_tokens`；MAX_ITERATIONS 8→12。
- observability：run 投影增加 `context` 块（压缩次数、末次历史 token 估算）。

## Out of Scope

- 跨 run 会话记忆整合（mission thread turn 已覆盖部分；后续合同）。
- LLM 驱动的语义摘要压缩（本轮用确定性结构化摘要，零额外 LLM 成本）。
- provider 层 token 流式。

## Deliverables

- `agent/context.py`、`agent/planner.py`、`agent/kernel.py` 改动。
- `tests/test_agent_context.py`：估算器、协议合法性、触发阈值、
  planner 端到端压缩、observability 块。

## Done Means

- 大历史在 provider 调用前被压缩到预算内，且消息序列仍满足
  assistant→tool 配对协议（测试逐条断言）。
- 小历史零改动（字节不变）。
- 压缩次数与历史规模进入 run observability。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_agent_context.py tests/test_agent_planner.py tests/test_agent_observability.py
./scripts/check.sh
```

## Risks / Notes

- 压缩丢弃旧工具结果细节：被压缩组的摘要保留工具名+结果前缀，操作者可从
  trace 审计完整原文（trace 不受压缩影响）。
- token 估算为启发式，仅用于触发阈值，不用于计费。

## Handoff

- Next likely step: P1-5 标准 MCP 客户端层。
