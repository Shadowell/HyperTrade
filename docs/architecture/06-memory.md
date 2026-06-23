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

Strategy experiments also write source-bound `strategy_knowledge` memory items.
These are compact evidence cards, not generated strategy claims: each item
points back to the experiment/backtest ids and includes winner, parameters,
metrics, evidence gates, data selection, and next-experiment guidance. They use
the same audited Memory lifecycle and can be found with
`kind=strategy_knowledge`, strategy-key tags, or winning-variant tags.

## Sprint 44 Update

Strategy library memory keeps the same Memory table as the source of truth.
`StrategyLibraryService` parses active `strategy_knowledge` cards and returns
strategy-level summaries: evidence count, pass/fail count, best evidence,
latest evidence, variant summaries, failure reasons, next experiments, and
source memory ids. API `/api/strategy/library`, CLI `/strategy library`, and
Agent tool `strategy_library_search` all read this aggregation instead of
creating a separate strategy-library table.

New strategy knowledge cards include `variant_count`, `gate_results`, and
`failure_reasons` fields so failed experiments can be reused as evidence rather
than disappearing from future research.

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

策略实验也会写入带来源的 `strategy_knowledge` 记忆。这类条目是紧凑的证据卡，不是生成式策略结论：每条都回指 experiment/backtest id，并包含胜出版本、参数、指标、证据门槛、数据选择和下一轮实验建议。它们沿用同一套可审计 Memory 生命周期，可通过 `kind=strategy_knowledge`、策略 key 标签或胜出版本标签检索。

## Sprint 44 更新

策略库记忆仍以同一张 Memory 表作为唯一来源。`StrategyLibraryService`
解析 active 的 `strategy_knowledge` 证据卡，聚合为策略级摘要：证据数、
通过/失败数、最佳证据、最新证据、版本摘要、失败原因、下一轮实验和来源
memory ids。API `/api/strategy/library`、CLI `/strategy library` 与 Agent
工具 `strategy_library_search` 都读取这层聚合，不新增独立策略库表。

新的策略知识卡会写入 `variant_count`、`gate_results` 和
`failure_reasons`，让失败实验也能作为未来研发的可检索证据，而不是被忽略。
