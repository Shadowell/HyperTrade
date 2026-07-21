# Sprint 125 — Reviewed Strategy Outcome Ledger

> 状态：Active — Sprint 124 Gate 已关闭，正在实施 Reviewed Strategy Outcome Ledger。

## Goal

建立不可变、可重放的 `StrategyOutcomeV1` 账本，把已结算的研究、回测、模拟盘观察和未来实盘结果与当时的
策略版本、市场状态、证据、成本、决策和授权快照绑定。系统可以从多个 Outcome 生成 `LessonCandidateV1`，
但未经审核的经验不能进入 active Memory、Skill、策略或组合政策。

## Dependencies

- Sprint 123–124 提供可重放 Mission、CompletionProof、Approval 和 effect reconciliation 真相。
- 复用 ExperimentLedger、Evidence V2、RobustnessValidation、StrategyCard、PaperObservationWindow 和 governed Memory。
- Outcome 只引用 BitPro/HyperTrade canonical artifacts，不复制 BitPro 原始数据库。

## In Scope

- `StrategyOutcomeV1` 绑定 strategy/card/manifest/code digest、参数、数据窗口、cost model、regime、Mission、
  Evidence、Artifact、Approval、ToolCall、as-of/settled time 和 producer lineage。
- Outcome 类型覆盖 research_rejected、backtest_validated、paper_window_settled、paper_degraded 和保留给未来的
  live_window_settled；未结算窗口不能标记 settled。
- canonical content hash、幂等键和 supersedes/corrects 关系；修正追加新记录，不覆盖旧 Outcome。
- 结构化 outcome metrics、unknowns、data gaps、failure class 和 decision snapshot；不保存 private reasoning。
- `LessonCandidateV1` 绑定至少一个 settled Outcome，包含 claim、support/opposition、scope、regime、confidence
  method、validity window、producer 和 review status。
- 重复失败模式、策略衰减和 regime 条件表现可以生成候选 Memory/Strategy/PortfolioPolicy proposal。
- 冲突 Lesson 并存并显式展示，不由模型静默选边。
- 只有 reviewed active Lesson 可以进入 ContextPack retrieved layer；它仍不能替代当前市场或 BitPro Evidence。

## Out of Scope

- 自动批准 Memory、Skill、策略或组合政策。
- 自动调参、生成新策略代码或运行回测；属于 Sprint 127–129。
- 用未结算 PnL、模型自评、操作员主观标签或未来数据创建 active Lesson。
- 把相关性描述成因果关系，或承诺某 Lesson 会提高未来收益。
- paper/live/order/capital mutation。

## Done Means

1. 任一 Outcome 都能定位到准确策略版本、数据/成本窗口、Evidence、Mission 和 settled time。
2. 相同来源和 payload 重放得到同一 Outcome；同 key 不同 payload 被拒绝。
3. 来源修正追加 `corrects` 记录，旧记录 hash 与审计历史不变。
4. 未结算、缺来源、effect_unknown、无 CompletionProof 或数据过期的结果不能成为 settled Outcome。
5. LessonCandidate 必须显示支持、反对、unknown、适用 regime、有效期和 confidence method。
6. 单次偶然盈利或模型自评不能自动激活 Memory/Skill/Strategy/PortfolioPolicy。
7. 冲突 Lesson 不被删除或多数投票消解；检索结果明确 stance 和适用范围。
8. offline event/outcome replay 产生相同账本内容 hash，且 projection 不依赖聊天历史。
9. Outcome/Lesson public projection 不包含 raw orders、credentials、完整 prompts 或 private reasoning。
10. 本 Sprint 不改变 paper/live 权限或任何资金状态。

## Verification

```bash
uv run pytest tests/test_strategy_outcome_ledger.py -q
uv run pytest tests/test_lesson_candidates.py -q
uv run pytest tests/test_memory_assertions.py -q
uv run pytest tests/test_experiment_ledger.py tests/test_portfolio_observation_windows.py -q
uv run pytest tests/test_mission_reducer_replay.py -q
./scripts/check.sh
git diff --check
```

验收 fixture 覆盖成功、失败、冲突、过期、来源修正、窗口未结算、effect_unknown 和重复事件；不得以随机收益
或合成行情代替真实可引用结果。

## Local Implementation Evidence

- `StrategyOutcomeV1`、append-only correction、canonical source validation、deterministic replay hash、
  `LessonCandidateV1` review/expiry/conflict/context projection 与 migration `0033` 已实现。
- Sprint 合同及既有 Experiment、Memory、PortfolioWindow、Mission replay/Alembic 定向回归 37 passed，
  PostgreSQL offline migration 通过。完整 `./scripts/check.sh` 通过 frontend 15 tests/build、Ruff、严格 mypy
  （193 source files）与 Python 728 tests（2 个既有 OKX warnings）；部署验收待执行。

## Handoff

Sprint 126 扩展 BitPro 稳定合同，提供策略级对齐收益与执行质量数据，使 Outcome Ledger 能支持参数研究、
新策略发现和组合优化。Outcome Ledger 本身不发起研究或交易动作。
