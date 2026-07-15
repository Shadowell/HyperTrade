# Sprint 109 - Champion–Challenger Paper Incubation

> 状态：Active；2026-07-15 在 Sprint 108 组合证据验收后自动进入实施。

## Goal

把已提交的 StrategyCard V2、Paper 事实与 PortfolioObservationWindow 组织为版本化、严格可比、
人工复核的 paper cohort；系统可以提出有依据且有时效的 Champion/Challenger/Watch 标签建议，
但不得用单一收益率排名，也不得自动 start/pause/promote/retire 任何策略。

## In Scope

- `PaperCohortV1`、`PaperCohortMemberV1`、comparability report 和 label review schema。
- 只读消费 Card snapshot/version、PaperPromotion status、RobustnessValidation、ObservationWindow
  summary/source hash 和 governed Memory refs。
- 30/60/90 天固定观察 horizon；market/symbol/timeframe/cost/bucket/window 必须完全一致。
- OOS/validation、paper return、cost、drawdown、volatility/stability、regime coverage、freshness、
  data gaps 与 decay 的多维比较。
- fixed denominator：选定/全部 V2 Card 均进入 intake；不合格成员保留 rejected/unknown reason。
- immutable cohort snapshot、稳定 cohort key/version、内容哈希和幂等 rebuild。
- Champion/Challenger/Watch 只作为 proposal；accept/reject/hold 写独立人工决定并带有效期。
- API、CLI `/cohorts`、Textual Portfolio 和 Web Portfolio 共享服务端投影。

## Out of Scope

- 自动调用 paper configure/start/pause/stop/promote/retire，或写 PaperPromotion/PaperReviewRequest。
- live/testnet order、资金权重、调仓、风险预算和 Sprint 110 shadow portfolio proposal。
- 以 total return、Sharpe 或任一单指标自动选 Champion；跨口径强行排名。
- 从 BitPro 重新拉原始序列、直连 BitPro 数据库或在 HyperTrade 复制完整 paper 历史。
- 将人工 accept 当作执行授权、实盘资格或未来盈利保证。

## Technical Plan

1. 定义 strict Pydantic 合同：cohort request 绑定 observation window id、horizon、Card ids、
   min samples、max data-gap rate、label validity 和 idempotency；拒绝重复 Card。
2. Alembic `0021` 新增 `paper_cohort_snapshots` 与 `paper_cohort_label_decisions`。cohort key +
   version、source/content hash、decision idempotency 建唯一约束；snapshot 永不覆盖。
3. cohort intake 以 V2 Card denominator 开始。只有 paper 状态为 observing/degraded/review_required、
   window member 可用且 version/source refs 完整的成员才进入 comparability grouping。
4. comparability key 必须包含 market type、排序后的 symbols/timeframes、Manifest cost model、
   horizon days、bucket minutes 和 observation policy version；任一字段 unknown 即不可比较。
5. 对每个成员投影 validation/OOS 状态、paper status、total return、drawdown、volatility、
   sample count、freshness、capacity/liquidity、regime coverage 和 data gaps；不读取原始序列。
6. decay 仅比较相同 card version、相同 cohort key 的当前/前一 committed window summary；来源
   不同口径、窗口重叠不足或无前值时为 unknown，不根据短期收益变化自动退役。
7. `comparable=true` 需要相同 key、完整 horizon、样本门槛、fresh source、validation 通过且无
   critical data gap；失败成员保留在 intake，并公开 reason codes。
8. proposal policy 使用可解释的 lexicographic gates：先证据完整/validation/data quality，后
   drawdown/stability/regime coverage，return 只作为同口径附属证据；不得形成资金排名。
9. 每个有两个及以上 comparable members 的 group 最多提出一个 `champion_candidate`，其余为
   `challenger`/`watch`；不足两名时全部 `watch` 且 reason=`insufficient_comparable_members`。
10. label proposal 包含 policy version/hash、全部 metric/source refs、unknowns、valid_until 和
    `execution_authorized=false`。人工决定仅能 accept/reject/hold，绑定 snapshot/member/proposal。
11. rebuild 对同一 request/source/content 幂等；来源事实变化追加新 version/snapshot，旧标签
    decision 保持历史且不会自动迁移到新 version。
12. API 提供 build/list/get/diff/decision；CLI/Textual/Web 显示 intake、可比率、标签、过期、
    reasons 和 source refs，客户端不重算分组/排名。
13. 静态与运行时测试禁止 cohort package 导入 BitPro adapter、paper service、live/order/capital；
    测试 decision 前后 PaperPromotion/PaperReviewRequest/订单计数不变。

## Done Means

- 全部 V2 Card 进入固定 intake denominator；无 paper/window 的候选不消失且明确 rejected reason。
- 只有完全相同 market/symbol/timeframe/cost/horizon/bucket 的成员进入同一 comparable group。
- 每个成员公开 Card/version/window/source hash、sample/freshness、全部比较指标和 unknowns。
- 少于完整 30/60/90 天或样本不足时没有 Champion proposal；不同口径绝不混排。
- Champion proposal 不是单收益排名，可从 policy gates 与证据逐项解释。
- label accept/reject/hold 只写审计事实，有有效期，`execution_authorized=false`。
- rebuild 幂等且 facts 变化追加版本；历史 snapshot/decision/content hash 不变。
- API/CLI/Textual/Web 共享服务端投影，无客户端 comparability/label 算法。
- PostgreSQL migration 可逆、`./scripts/check.sh` 与生产 no-eligible-cohort/read-only smoke 通过。
- 构建/决定前后 paper promotion/review、paper order、live intent 和 capital 状态不变。

## Verification

```bash
uv run pytest tests/test_paper_cohorts.py -q
uv run pytest tests/test_portfolio_observation_windows.py tests/test_strategy_card_v2.py -q
uv run pytest tests/test_tui_app.py tests/test_cli.py -q
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
./scripts/check.sh
```

Manual/production checks:

- 用同口径两成员、不同 cost/bucket、窗口不足、stale、validation rejected fixtures 验证分组。
- 验证 return 更高但 drawdown/stability/data quality 更差时不会仅凭 return 成为 Champion。
- 重复 build 与 decision，确认 version/snapshot/decision 幂等；改变 window source 后追加版本。
- 审计 package imports/calls 和业务表计数，确认没有 paper/live/order/capital dispatch。
- 生产没有完整 cohort 时返回 needs_data/0 champion，不创建模拟成员或 paper 实例。

## Risks / Notes

- 生产当前只有一个 available window member 且无 PaperPromotion；正确验收结果预计是
  no eligible/comparable cohort，而不是 Champion。
- Manifest cost model 可能历史缺失；必须标为 `cost_model_unknown`，不可从默认值猜测。
- 30 天 horizon 是完整观察定义，不等于只看请求参数；sample start/end 必须覆盖门槛。
- Champion 是 paper research label，不是资金、实盘或策略优越性的永久结论。

## Handoff

- Gate G 只有在 cohort 可比性、人工决定和零 paper lifecycle dispatch 均验收后关闭。
- Gate G 通过后才激活 Sprint 110；Shadow Portfolio 只能消费有效、未过期且来源版本明确的
  cohort/observation evidence，仍不得执行订单或资金动作。
