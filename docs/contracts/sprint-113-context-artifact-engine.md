# Sprint 113 - Context and Artifact Engine

> 状态：Active；Sprint 112 Gate J1 已于 2026-07-15 关闭。

## Goal

为每个 Mission Step 编译确定、受预算约束、可审计的 Context Pack，并建立 Mission 级 Artifact
Index。Context 不再由分散 prompt 拼接决定；最终完成结论必须能追溯到已验证 Observation、Evidence
或 Artifact ref，完整聊天、raw BitPro 序列、凭证与 private reasoning 不得进入上下文或索引。

## In Scope

- strict ContextSourceV1、ContextPackV1、ContextDecisionV1、ContextTokenLedgerV1、
  MissionArtifactV1 和 ArtifactRelationV1。
- deterministic source tiers：Mission constraints、current Plan/Step、validated observations、
  Evidence、governed Memory、RAG citation、prior artifacts；同层使用稳定排序与内容哈希。
- Context Compiler port 与内存/SQLAlchemy adapter；按 Step 单独编译，记录 include/drop/reason、
  source version/hash、freshness、token estimate 和最终 manifest hash。
- 可替换 token estimator；生产基线使用确定 UTF-8/word heuristic，不依赖 provider tokenizer。
- hard token ledger：关键约束 100% 保留；超预算先丢低相关来源，再对允许的长文本做 bounded
  extractive compaction；不得让模型扩大预算或压缩掉 provenance。
- Artifact Index：immutable version、content hash、media type、size、producer、source refs、
  supersedes/derived-from 关系；仅保存 bounded inline metadata 或稳定 external ref。
- ToolObservation artifact refs 注册与 Mission 完成/报告引用验证。
- `/api/agent/missions/{id}/context-packs`、`/artifacts`、artifact detail/relations API。
- migration `0025_agent_context_artifacts`；删除新 Runtime 中重复的 context/prompt 拼装分支。

## Out of Scope

- Sprint 114 多 Agent assignment/handoff/merge。
- Sprint 115 代码 workspace、shell、Docker sandbox、patch 或 BitPro import。
- provider 生成式摘要作为 canonical context；首版 compaction 必须确定且可重放。
- 复制 BitPro raw candles/equity/orders/trades 或任意生产凭证。
- 改变 paper/live/order/capital、Capability review 或 approval 权限。

## Done Means

- 相同输入/策略/预算编译得到相同 manifest/content hashes 和 include/drop 顺序。
- Mission/Plan/Step/permission/constraints 关键块在所有预算场景保留率 100%。
- 每个 included source 有 stable ref、kind、hash、freshness 和 token estimate；每个 dropped source
  有固定 reason，不能静默丢弃。
- Context Pack 不超过 hard budget；超小预算 fail closed，不产生截断 JSON 或无来源摘要。
- Artifact 内容哈希、版本、producer、source refs 和 relation 可验证；不可读/stale/superseded 状态
  不伪装为当前有效产物。
- 最终完成引用只能来自本 Mission Artifact Index、validated Observation 或 Evidence；伪造 ref
  使 completion 失败。
- 数据库/API/events 不保存 credential、private reasoning、完整聊天或 raw BitPro series。
- 全仓检查、migration 往返、production flag-off 和 read-only canary 通过。

## Verification

```bash
uv run pytest tests/test_context_compiler.py tests/test_mission_artifacts.py -q
uv run pytest tests/test_agent_missions.py tests/test_tool_runtime_v2.py -q
./scripts/check.sh
```

Required scenarios: deterministic replay, hard-constraint retention, stable tier ordering, stale
source drop, budget exhaustion, bounded compaction, hash mismatch, artifact dedupe/version/supersede,
unknown ref refusal, secret/raw-series redaction, SQL persistence and authenticated API projection.

## Handoff

Gate J2 通过后才激活 Sprint 114。Supervisor 只能传递 Context Pack 和 Artifact refs，不能传递
hidden transcript、raw provider output，或绕过 Capability/permission/budget 门禁。
