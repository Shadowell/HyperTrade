# Sprint 105 - Portfolio Strategy Lifecycle

> 状态：Implementation complete, production acceptance pending；2026-07-15 本地验收通过。

## Goal

将单候选研究扩展到组合级策略生命周期审阅，基于状态适配、共同暴露、相关性、容量、
风险贡献和衰减证据提出研究/观察/人工复核/退役建议，但不自动分配资金或交易。

## In Scope

- `PortfolioAssessmentV2`、`StrategyLifecycleDecisionV1`。
- 复用 StrategyCard、WorldState、Paper Snapshot、Monitor、Evidence 和 BitPro read tools。
- bounded 同步收益序列相关性、共同暴露和 unknown 处理。
- capacity/liquidity、regime fit、drawdown/risk contribution、decay projection。
- 人工 review decision、API/CLI/TUI/Web portfolio surface。

## Out of Scope

- 自动资金分配、自动调仓、自动 pause/start、自动 paper/live 晋升或订单。
- 在 HyperTrade 长期复制完整权益/收益/交易序列。
- 缺样本时生成伪相关性或风险贡献。
- 以组合模型覆盖历史 backtest/paper 事实。

## Deliverables

- portfolio assessment/lifecycle schemas、service、persistence 和 policy。
- bounded BitPro/WorldState/StrategyCard evidence adapters。
- read-only recommendation actions 和人工 review workflow。
- portfolio API/CLI/TUI/Web projections、tests 和文档。

## Implementation Plan

1. 定义 assessment 输入、required/optional evidence、unknown 和有效期规则。
2. 扩展 StrategyCard projection，关联 ExperimentManifest、Validation、Paper 和 Memory assertions。
3. 获取 bounded 同步收益/权益摘要；样本不足或时间未对齐返回 unknown。
4. 计算相关性、共同 symbol/timeframe/direction/factor 暴露 proxy。
5. 汇总 regime fit、容量/流动性、drawdown、近期 paper drift 和策略衰减。
6. 生成只读动作：observe、targeted research、paper review、pause review、retire review、risk-budget review。
7. 每个动作附 evidence ids、unknown、理由、有效期和 policy version。
8. 增加人工 accept/reject/hold decision，只更新 review ledger，不调用交易 adapter。
9. 增加 API/CLI/TUI/Web 组合视图和历史 assessment diff。
10. 完成缺数据、相关性、衰减、安全边界和现有 WorldState 回归测试。

## Done Means

- 组合评估能解释策略共同暴露、相关性样本、状态适配、容量和风险缺口。
- 数据不足时明确 unknown，不输出伪精确数值。
- 所有推荐只能进入研究任务或人工 review queue。
- 没有代码路径从 PortfolioAssessment 直接调用 BitPro/paper/live mutation。
- 历史 assessment、evidence 和人工决定可追溯，不改写历史研究结论。

## Verification

```bash
uv run pytest tests/test_portfolio_assessment_v2.py tests/test_strategy_lifecycle.py -q
uv run pytest tests/test_world_model_portfolio.py tests/test_strategy_cards.py -q
./scripts/check.sh
```

Manual/QA：

- 使用收益序列充足、不足和时间错位三组 fixture 检查相关性输出。
- 创建 degraded paper candidate，确认只产生 review action 而不调用 pause/stop。
- 检查组合视图能追溯到 BitPro result、validation、paper snapshot 和 evidence。

## Risks / Notes

- 相关性和风险贡献依赖 BitPro 可用数据；不足时必须保持 unknown。
- 首版不使用自动优化器，避免看似精确但证据不足的资金建议。
- 该 Sprint 完成仍不开放主网实盘或自动提高风险预算。

## Handoff

- 路线图 Gate D 完成后，重新评审是否需要专门的组合优化、物理隔离或实盘治理路线；
  这些都必须另立合同。

## Implementation Record

- `PortfolioAssessmentService` 持久化 `portfolio_assessment.v2`，请求哈希绑定
  idempotency key；同键不同请求失败关闭。
- StrategyCard projection 关联 paper/evidence/governed Memory，并公开声明的 regime、
  capacity、liquidity、drawdown、drift 与明确 unknown。
- 相关性只读取每策略最多 50 个 paper equity 摘要，按固定时间桶对齐后计算收益；
  样本不足、错位或零方差时返回带原因的 unknown，数据库只保存统计摘要。
- 推荐动作被固定在六个只读 research/review action；模块不导入 BitPro、paper 或
  live mutation adapter。accept/reject/hold 只写审阅账本且原因/决定受幂等键绑定。
- 管理员 API、CLI `/portfolio-v2`、Textual Portfolio tab 与 Web
  `/harness/portfolio` 均委托同一服务状态机。
- PostgreSQL `0018 -> 0017 -> 0018` 可逆迁移通过；聚焦后端 23 项、前端 9 项及
  `./scripts/check.sh`（473 项 Python 测试）通过。生产证据待部署后补录。
