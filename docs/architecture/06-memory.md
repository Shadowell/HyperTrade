# 06 Memory / 记忆

## English

Memory is automatic but audited. Every memory item stores kind, content, source run id, source tool, timestamps, and disabled status.

Sprint 01 supports:

- automatic memory writes from AgentKernel
- listing active memories
- disabling memory items
- deleting memory items in service code

This prevents silent self-reinforcement while still showing the full agent memory lifecycle.

## 中文

Memory 自动写入，但必须可审计。每条 memory 记录 kind、content、source run id、source tool、时间戳和 disabled 状态。

Sprint 01 支持：

- AgentKernel 自动写入 memory
- 查看 active memory
- 禁用 memory
- service 层删除 memory

这样既能展示完整 Memory 生命周期，又避免 Agent 悄悄自我强化。

