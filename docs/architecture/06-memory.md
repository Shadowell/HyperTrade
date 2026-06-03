# 06 Memory / 记忆

## English

Memory is automatic but audited. Every memory item stores kind, content, source run id, source tool, timestamps, and disabled status.

Sprint 01 supports:

- automatic memory writes from AgentKernel
- listing active memories
- disabling memory items
- deleting memory items in service code

This prevents silent self-reinforcement while still showing the full agent memory lifecycle.

## Sprint 27 Update

Memory v2 adds policy and retrieval metadata:

- `importance`
- `tags`
- `confidence`
- `last_used_at`
- `usage_count`

Writes deduplicate exact active memory content by kind, merge tags, and increment usage. Search supports query, kind, and tag filters through API `/api/memory`, CLI `/memory search <query>`, and the frontend Memory Manager.

## 中文

Memory 自动写入，但必须可审计。每条 memory 记录 kind、content、source run id、source tool、时间戳和 disabled 状态。

Sprint 01 支持：

- AgentKernel 自动写入 memory
- 查看 active memory
- 禁用 memory
- service 层删除 memory

这样既能展示完整 Memory 生命周期，又避免 Agent 悄悄自我强化。

## Sprint 27 更新

Memory v2 增加策略和检索元数据：

- `importance`
- `tags`
- `confidence`
- `last_used_at`
- `usage_count`

写入时会按 kind + content 对 active memory 做精确去重，合并 tags 并增加使用次数。检索支持 query、kind、tag，可通过 API `/api/memory`、CLI `/memory search <query>` 和前端 Memory Manager 使用。
