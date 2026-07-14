# Sprint 97 - Research Evidence Contract

> 状态：Active，Sprint 96 已完成；2026-07-14 经操作员批准进入实施。

## Goal

建立 append-only、可引用、可过期、可冲突的 `ResearchEvidence` 合同，使后续多 Agent
角色只能输出有来源的事实、显式推断、反例或数据缺口。

## In Scope

- Pydantic Evidence V2 discriminated-union schemas。
- `research_evidence` 及关系/索引 migration。
- canonical JSON、SHA-256 hash、去重、supersede、expire 和 query 服务。
- tool、BitPro result、snapshot、RAG citation、Memory 等 source ref。
- 旧 StrategyEvidence/Memory 的只读适配。
- Evidence REST read API 和管理员受控 append API。

## Out of Scope

- 多 Agent 图、自动事实裁决、向量图数据库。
- 让 Memory 成为市场事实的唯一来源。
- 删除或原地改写历史 evidence。
- 保存完整 BitPro artifacts 或原始行情。

## Deliverables

- Evidence schema、service、repository、API 和 serializer。
- 来源可用性、过期和冲突规则。
- evidence graph projection 和安全报告块。
- hash/schema/property tests、legacy adapter tests 和文档。

## Implementation Plan

1. 定义 `EvidenceScope`、`EvidenceSourceRef` 和四种 evidence payload。
2. 固定 UTC、Decimal、空值、列表排序和 canonical JSON 规则。
3. 创建 append-only 表、支持/反对/supersede 关系和查询索引。
4. 实现 `EvidenceService.append()`，拒绝无来源 fact 和悬空 inference。
5. 实现 expire/supersede；只更新状态和关系，不修改历史 claim/payload。
6. 实现来源健康检查，来源不可用时生成 data gap，而非级联删除。
7. 将 BitPro research evidence、RAG citation 和 Paper Snapshot 映射为 source ref。
8. 增加 API、报告 projection 和审计 trace。
9. 增加 StrategyEvidence/Memory 只读兼容适配器。
10. 完成 schema、hash、冲突、过期和安全回归测试。

## Done Means

- `fact` 没有合格 source 时不能写入 active evidence。
- `inference` 必须引用 supporting evidence；反例必须指向被挑战记录。
- 同一 canonical 内容得到稳定 hash，重复写返回现有记录。
- 过期/冲突 evidence 在查询和报告中明确显示，不被静默当成有效事实。
- 旧策略证据仍可查询，但明确显示 legacy schema。

## Verification

```bash
uv run pytest tests/test_research_evidence_schema.py tests/test_research_evidence_service.py -q
uv run pytest tests/test_strategy_evidence.py tests/test_rag_citations.py -q
./scripts/check.sh
```

## Risks / Notes

- JSON 字段顺序、Decimal 和时间格式若不固定会破坏 hash，必须先锁规范再迁移。
- Evidence confidence 是声明属性，不是概率保证；事实也不能默认 100% 可靠。
- Agent 不直接获得 evidence mutation API，只提交 schema output 给受信服务。

## Handoff

- 下一步：Sprint 98 使用 Evidence V2 作为每个研究角色的唯一输出合同。

## Implementation Record

- 本地实现完成：Pydantic V2 schema、Alembic `0013`、append-only repository/service、
  来源适配、REST、graph/report projection 和 legacy adapter。
- 聚焦回归 `25 passed`；migration `upgrade -> downgrade -> upgrade` 通过；
  `./scripts/check.sh` 全部通过，Python `361 passed`。
- 生产 PostgreSQL migration、远程 append/read/graph/lifecycle smoke 尚待实现提交部署后
  验证；完成前 Sprint 保持 Active。
