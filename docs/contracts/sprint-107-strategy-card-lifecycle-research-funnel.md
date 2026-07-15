# Sprint 107 - StrategyCard Lifecycle & Research Funnel

> 状态：Completed；2026-07-15 完成本地、PostgreSQL 与生产验收，Gate F 关闭。

## Goal

让每个已登记 ExperimentManifest 的研究候选立即拥有稳定 lineage、明确 version 和可重建的
StrategyCard V2，即使尚无 Evidence、Validation 或 PaperPromotion 也保持可见；同时以固定
denominator 投影 Task → Spec → Manifest → Evidence → Validation → Paper → Card 研究漏斗。

## In Scope

- `StrategyLineageV1`、`StrategyVersionV1`、`StrategyCardV2` 和 completeness 合同。
- Manifest 登记时幂等创建 lineage/version；历史 Manifest 确定性回填。
- 基于 Manifest、ExperimentExecution/Evidence、RobustnessValidation、PaperPromotion、
  Paper Snapshot、Monitor 和 governed Memory refs 构建不可变 Card snapshot。
- 事实驱动的 researching/testing/validation_rejected/validated/paper_pending/observing/
  degraded/review_required/retired 生命周期投影。
- 独立人工 lifecycle decision event；不改写历史 snapshot。
- fixed-denominator research funnel、API/CLI/Textual/Web 只读投影。
- PortfolioAssessment 消费 V2 Card，使只有 Manifest 的候选也可见但保持 unknown。

## Out of Scope

- 修改 StrategySpec、Manifest、Evidence、Validation、Paper 或 Monitor 的事实内容。
- 自动创建/启动/暂停 paper，自动 promotion/retirement 或任何 live/capital/order 动作。
- 以 completeness、收益率或生命周期状态表示盈利概率或自动排名。
- Sprint 108 的完整收益序列、组合观察窗口、容量/流动性计算。
- 允许客户端直接写 Card、lineage、version 或 snapshot。

## Technical Plan

1. 发布 strict Pydantic V2 schema；lineage key 由 mandate + strategy key 的规范化身份组成，
   version identity 绑定 Manifest fingerprint，不使用可变 execution/status 字段。
2. Alembic 新增 lineage、version、snapshot 和 lifecycle decision 四张表；Manifest/version、
   lineage/version number、snapshot content hash 和 decision idempotency 建唯一约束。
3. 在 `ExperimentLedgerService.register` 成功取得 Manifest 后调用独立 projection service；
   该服务只能读事实表并写自身投影表，失败不能触发 BitPro 或交易副作用。
4. 对现有 Manifest 提供幂等 reconcile/backfill；无法关联的数据写 unknown/missing_fields，
   不跳过 candidate，也不伪造 paper/validation 状态。
5. 每次读取或显式 reconcile 时按确定性 precedence 计算 lifecycle、source refs、freshness、
   completeness 和 content hash；内容变化追加 snapshot，不覆盖旧行。
6. lifecycle decision 仅允许 accept/reject/hold/retire_review 等研究复核事实，绑定 actor、
   reason、idempotency 和当前 version/snapshot；它不能调用 Paper/BitPro/Live adapter。
7. funnel 以 Manifest candidate 为 denominator，分阶段公开 reached/missing/rejected/unknown，
   并提供 source ids 和计数一致性校验。
8. 替换旧 `StrategyCardService` 的 PaperPromotion-only 枚举，保留必要 V1 兼容字段；
   PortfolioAssessment 对 incomplete Card 生成显式 unknown 而不是让 candidate 消失。
9. FastAPI、CLI、Textual 和 Web 复用同一服务投影；客户端无 completeness/lifecycle 算法。
10. 增加 schema、幂等/并发、backfill、snapshot immutability、funnel denominator、未知值、
    API/UI 和 forbidden-import 测试，并执行 PostgreSQL upgrade/downgrade/upgrade。

## Done Means

- 只有 Manifest、没有 Evidence/Paper 的候选也拥有 incomplete Card V2。
- 相同 strategy identity 复用 lineage；语义不同 Manifest 得到稳定递增 version。
- 每张 Card 可追溯到 Manifest fingerprint/version 和全部可用 source refs。
- facts 变化只追加新 snapshot；历史 snapshot/content hash 不变。
- 历史 Manifest 全量 reconcile 后 candidate 数与 funnel denominator 一致。
- missing/stale/conflicting 来源明确进入 unknown/missing_fields；completeness 不表示质量。
- PortfolioAssessment 能看到 incomplete candidate 且不伪造组合证据。
- 人工 decision 只写审计事实；静态和运行时测试证明无 BitPro/paper/live/order dispatch。
- API/CLI/Textual/Web 共享服务端结果，PostgreSQL 迁移可逆，`./scripts/check.sh` 通过。
- 部署后完成生产 backfill/read smoke，未产生 PaperPromotion 或交易写入。

## Verification

```bash
uv run pytest tests/test_strategy_card_v2.py tests/test_strategy_card_funnel.py -q
uv run pytest tests/test_strategy_cards.py tests/test_portfolio_assessment_v2.py -q
uv run pytest tests/test_strategy_card_api.py tests/test_tui_app.py -q
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
./scripts/check.sh
```

Manual/production checks:

- 对只有 Manifest 的候选执行 reconcile，确认 Card=incomplete 且未产生 promotion。
- 重复 reconcile，确认 lineage/version/snapshot 幂等；新增事实后只追加 snapshot。
- 检查 funnel 各阶段计数、unknown 和 source refs；检查 PortfolioAssessment 可见性。
- 审计相关模块 import/call 和生产日志，确认没有 BitPro/paper/live/order mutation。

## Risks / Notes

- `strategy_key` 可能跨 mandate 重名，lineage identity 必须显式包含 mandate scope。
- 历史 legacy evidence 可能无法绑定 Manifest；保留 unknown，不做模糊猜测关联。
- read-time reconcile 需防止 snapshot 风暴；相同 content hash 必须复用。
- version number 并发分配使用数据库唯一约束/锁，不能依赖进程内计数。
- PortfolioAssessment 的候选数增加会产生更多 needs_data，这是正确的覆盖率提升。

## Handoff

- Gate F 通过后创建 Sprint 108 合同，实施 bounded PortfolioObservationWindow/DataQuality。
- Gate F 未通过时继续修复身份、回填、快照或漏斗，不提前实现 paper cohort/shadow capital。

## Implementation Record

- 新增 `0019_strategy_card_v2` 的 lineage/version/snapshot/decision 四张表及唯一约束。
- `ExperimentLedgerService.register` 在 Manifest 身份边界触发 projection-only reconcile；
  历史 Manifest 可幂等 backfill，相同 content hash 不产生重复 snapshot。
- Card V2 从 execution/evidence/validation/paper/monitor/governed Memory 事实确定性投影；
  legacy promotion-only Card 保持 compat/manifest unknown，不做模糊关联。
- fixed funnel 使用 ExperimentManifest 作为 denominator；API、CLI、Textual、Web 只展示
  服务端 lifecycle/completeness/missing fields，不在客户端复算。
- 临时 PostgreSQL 已通过全链升级、`0019 -> 0018 -> 0019` 和四表存在性检查。
- 完整 `./scripts/check.sh` 通过：frontend lint/9 tests/build、Ruff、mypy（143 source
  files）及 497 Python tests。
- commit `14d686e` 经 workflow `29387796135` 部署；生产 Alembic 为 `0019`。3 个历史
  Manifest 确定性回填为 1 lineage、3 version、3 snapshot，连续两次 reconcile 未增加
  snapshot；V2 Card 与 funnel denominator 均为 3。
- 回填前后 PaperPromotion=0、paper orders=10、live order intents=1；Web strategy route、
  API health 与日志通过。完整结论见 `docs/qa/sprint-107-strategy-card-lifecycle-research-funnel.md`。
