# 06 Memory / 记忆

## ResearchMemory v1

`memory/research.py` defines the shared, versioned ARC development-evidence projection.
AVO curation and `MemoryService.research_context` use the same bounded projector;
the persisted ARC receipt remains authoritative, including negative outcomes.
`project_research` applies source-bound invalidation tombstones from `memory_items`.
Tombstones are disabled audit rows and cannot be deleted through ordinary Memory deletion.
No summary copies are persisted. Old records keep unknown config/cost identities;
unknown observations are never identity, causal, approval, or promotion evidence.
An explicit target cost identity filters missing or mismatched receipts. The manifest
records excluded sources/reasons, quotas, and scan truncation. Reads require an explicit
symbol, timeframe and frozen research window; generic prompt recall cannot bypass them.

### Paired AVO evaluation

Run the evaluator in a dedicated process/container with a persistent experiment directory:

```bash
python -m hypertrade.evals.memory_ablation create /eval/pair-01 --goal /eval/goal.json --records /eval/records.json
python -m hypertrade.evals.memory_ablation run /eval/pair-01
python -m hypertrade.evals.memory_ablation status /eval/pair-01
```

The input is a clean `ARCGoalV1`: explicit Provider/model and research windows, unused
budget, `research_mode=avo`, version-bound review enabled and `arc_windowed_v1` policy.
The input human/agent review mode is preserved. Paper authorization, feedback/evolution
context and existing research IDs are rejected. Records use the original development
receipt shape consumed by `curate_memory`; they must be exported from authoritative
sources after invalidation checks, not reconstructed from generated summaries.

The records file may contain authoritative ARC receipt inputs or the exact bounded
`ResearchMemoryV1` output from `MemoryService.research_context`; versioned entries are
strictly revalidated for their content hash, scope, window, capital, cost target and
contamination marker. `manifest.json` freezes controls, curated corpus, selection exclusions, runtime hash and
counterbalanced arm order. ARC assigns each arm a separate operational research ID;
these IDs isolate BitPro creation/backtest idempotency without changing model controls.
`journal.db` holds authoritative budgets, events and receipts; `requests.jsonl` records
the actual post-injection request hashes, and `result.json` is a rebuildable result view.
Interrupted model calls remain charged and missing usage stays unknown. Unsettled tool
effects are not retried. Restart with `run` to resume; runtime or manifest drift is rejected.

The runner calls research/validation only; it does not run the worker or invoke Paper
review/configure/start. Both arms share ordinary AVO validation and budget accounting.
Differences cover calls, backtests, candidates, reported tokens, development passes and
repeated experiments against the same frozen corpus. Missing cost/data-snapshot identity,
unreported spending and uncontrolled provider sampling remain explicit unknowns. A single
pair never establishes memory effectiveness, strategy profitability or causality.

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

## Sprint 46 Update

New `strategy_knowledge` writes use a versioned `StrategyEvidence` JSON payload
inside `MemoryItem.content` instead of relying on semi-structured text parsing.
The current schema version is `strategy_evidence.v1`. Memory table shape,
`kind + content` exact dedupe, tags, source run/tool audit fields, and ordinary
Memory search behavior are unchanged.

The schema records strategy key, experiment/research/backtest ids, optional
BitPro result id, variant id/count, parameters, string-preserved metrics,
gate results, failure reasons, source data, next experiment guidance,
boundaries, and pass/fail status. `StrategyLibraryService` parses this payload
first and falls back to the legacy text-card parser when older production
memories do not contain the schema. Missing structured fields surface as `n/a`,
empty strings, empty lists, or empty maps rather than invented values.

## Sprint 76 Update

The Agent Flight Recorder correlates explicit `memory_search` and
`memory_write` tool results with the current run timeline. It exposes Memory ids
and bounded content previews from the existing audited Memory rows; it does not
create a second Memory store or copy private reasoning into Memory. Historical
items read by a run retain their original `source_run_id` and `source_tool`.

## 2026-11-18 Production Cognitive-Operational Memory Unification

Production Agent upgrades bridge the operational `MemoryItem` ledger and the
three-tier ARC cognitive memory store (`ArcHypothesisNode`, `ArcEpisodicMemory`,
`ArcSemanticAssertion`):

- **Cross-mission lineage recall & race verdicts (`memory/arc_integration.py`)**:
  `ingest_projection` stamps `lineage_key` (`f"{target_id}:{source_strategy_id}"`)
  when `evolution_context` identifies a source parent and appends up to 10 prior
  `ArcHypothesisNode` rows from earlier missions for the same lineage while
  keeping per-mission `tree_id = f"arc:{mission_id}"` isolation intact. It also
  ingests `paper_observation_ended` forward race verdicts (`won`,
  `lost_futility`, `lost_exam`)—with `projection.paper_outcome` fallback—into
  `paper_race_won` / `paper_race_lost` episodes and updates hypothesis status.
- **Zero-LLM deterministic distillation & projection (`memory/distillation.py`)**:
  `deterministic_causal_summarizer` synthesizes conservative descriptive
  heuristics from at least 2 recall-eligible episodes (extending
  `DEFAULT_DISTILLABLE_EVENT_TYPES` with `backtest_success`, `paper_race_won`,
  and `paper_race_lost`; `min_episode_count=2` by default). At the end of
  `replay_arc_cognitive_memory_once`, `sync_cognitive_to_memory_items(db)`
  distills pending regimes and projects active semantic assertions and race
  outcomes into `MemoryItem` rows (`arc_semantic_rule`, `arc_race_outcome`),
  respecting existing disabled tombstone rows.
- **Unified search, governed writes, and telemetry**: `MemoryService` adds
  `cognitive_counts()` and `list_cognitive_items()`, surfaced via
  `/api/harness/overview` (`memory.cognitive`) and `/api/memory` (`cognitive`
  and `cognitive_items` alongside `items`). In `MissionRuntime`, `memory.search`
  queries both `MemoryService` and cognitive semantic/episodic records,
  `memory.write` registers as an idempotent `research_write` capability, and
  `ThreadTurnService._consolidate_memory()` persists bounded `operator_note` or
  `strategy_observation` entries after validated turn completion.

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

## Sprint 46 更新

新的 `strategy_knowledge` 写入会在 `MemoryItem.content` 中保存版本化
`StrategyEvidence` JSON payload，不再依赖脆弱的半结构文本解析。当前 schema
版本是 `strategy_evidence.v1`。Memory 表结构、`kind + content` 精确去重、
tags、source run/tool 审计字段和普通 Memory 搜索行为保持不变。

该 schema 记录 strategy key、experiment/research/backtest id、可选 BitPro
result id、variant id/count、参数、以字符串保留精度的指标、gate results、
failure reasons、source data、下一轮实验建议、边界和 pass/fail 状态。
`StrategyLibraryService` 会优先解析这个 payload；旧生产 memory 没有 schema
时继续走 legacy 文本卡解析。缺失字段显示为 `n/a`、空字符串、空列表或空
map，不会编造数值。

## Sprint 76 更新

Agent Flight Recorder 会把显式 `memory_search` / `memory_write` 工具结果与
当前 run 时间线关联，展示现有审计 Memory 行的 id 与有限内容预览；它不会
新增第二套 Memory 存储，也不会把私有推理写入 Memory。某次 run 读取历史
Memory 时，原条目的 `source_run_id` 与 `source_tool` 保持不变。

## 2026-11-18 认知记忆与操作记忆统一闭环

- **跨 Mission 血缘召回与赛马终裁情景**（`memory/arc_integration.py`）：对存在 `evolution_context.source_strategy_id` 的任务记录 `lineage_key`（`f"{target_id}:{source_strategy_id}"`），在保留单任务 `tree_id = f"arc:{mission_id}"` 隔离的同时通过 `_append_lineage_hypotheses` 补充同源历史最多 10 条假设节点；将 `paper_observation_ended` 赛马结果（含 `paper_outcome` 回放兜底）沉淀为 `paper_race_won` / `paper_race_lost` 情景记忆并更新假设状态。
- **零模型确定性蒸馏与 `MemoryItem` 投影**（`memory/distillation.py`）：新增 `deterministic_causal_summarizer`，将 `DEFAULT_DISTILLABLE_EVENT_TYPES` 扩展纳入 `backtest_success`、`paper_race_won`、`paper_race_lost`（`min_episode_count=2`）；`replay_arc_cognitive_memory_once` 末尾调用 `sync_cognitive_to_memory_items(db)` 把活跃规则与赛马结果写入 `MemoryItem`（`arc_semantic_rule` / `arc_race_outcome`，遵守已有 `disabled` 墓碑行）。
- **统一检索、受治理写入与接口遥测**：`MemoryService` 新增 `cognitive_counts()` 与 `list_cognitive_items()`，由 `/api/harness/overview`（`memory.cognitive`）与 `/api/memory`（`cognitive`、`cognitive_items` 并保留 `items`）暴露；`MissionRuntime` 中 `memory.search` 联合检索操作记忆与认知记忆，`memory.write` 作为受治理 `research_write` 幂等能力开放，`ThreadTurnService._consolidate_memory()` 在合法 Turn 完成后自动或按显式指令沉淀 `operator_note` / `strategy_observation`。
