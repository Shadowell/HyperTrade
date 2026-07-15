# Sprint 110 - Shadow Portfolio & Capital Governance

> 状态：Active；2026-07-15 在 Gate G 通过后自动进入实施。

## Goal

把有效、未过期且人工接受的 paper cohort 标签组织为不可变、可解释、可比较的 Shadow
Portfolio 假设方案，并通过独立人工复核账本验证资本治理流程；系统不得分配资金、创建订单、
调仓或把 review accept 解释为任何执行授权。

## In Scope

- `ShadowPortfolioProposalV1`、有限 template scenario、hypothetical order impact 与 review schema。
- 只读消费 immutable PaperCohort snapshot/label decision、对应 Card snapshot 与 ObservationWindow refs。
- 固定 intake denominator；未接受、已过期、不可比或来源缺失的成员保留 exclusion/unknown reason。
- 三种有限模板：equal-weight、证据完整时 inverse-volatility、证据完整时 capped risk-budget proxy。
- Decimal 权重、权重和、单策略上限、有限 notional、费用/滑点、turnover 与固定 stress scenarios。
- immutable proposal/version/source/content hash、幂等 build、proposal diff 与 accept/reject/hold audit。
- API、CLI `/shadow`、Textual Portfolio 与 Web Portfolio 共享服务端投影。

## Out of Scope

- 写 PaperPromotion/PaperReviewRequest、paper start/pause/stop/promote/retire 或创建 paper order。
- live/testnet/mainnet intent/order、资金账户、资产划转、真实调仓、真实风险预算或执行批准。
- 无界权重优化、收益最大化、自动挑选“最佳”模板、杠杆、做空或动态参数搜索。
- 读取 BitPro 原始序列、直连 BitPro 数据库、调用 BitPro mutation adapter 或复制交易历史。
- 将 hypothetical order impact 序列化为 exchange order payload，或承诺稳定盈利。

## Technical Plan

1. strict Pydantic build 合同绑定 cohort id、有限 notional、单策略 cap、fee/slippage/stress、
   review validity 与 idempotency；拒绝多余字段、非正金额和越界参数。
2. Alembic `0022` 新增 `shadow_portfolio_proposals` 与 `shadow_portfolio_review_decisions`；
   portfolio key/version、request/source/content hash、build/review 幂等键设置唯一约束。
3. build 默认选最新 cohort，但必须固定具体 cohort id/content hash、window id/content hash、
   Card snapshot ids/content hashes、label proposal/decision ids 与 policy hash，不能消费 mutable current state。
4. intake 从 cohort 全部成员开始。eligible 要求 comparable、proposal 仍有效且其最新人工决定为
   accept；其他成员保留 `excluded`、reason codes、source refs，不能从 denominator 消失。
5. 找不到 cohort、cohort `needs_data`、少于两个 eligible members 或来源不完整时仍可保存
   `needs_data` proposal，但 scenarios 必须为空且不得伪造成员、波动率、容量或流动性。
6. equal-weight 仅在至少两个 eligible members 且 `n * max_weight >= 1` 时生成；权重使用 Decimal，
   最终和精确为 1，任一权重不超过 cap。
7. inverse-volatility 要求所有 eligible 成员 volatility 为有限正数；使用 `1/volatility` 后经
   deterministic capped normalization，不允许以缺失值、0 或默认波动率代替。
8. capped risk-budget proxy 额外要求每个 immutable Card snapshot 的 capacity 为正数且 liquidity
   明确通过；score 只由 inverse-volatility 与 bounded capacity factor 组成，再经相同 cap 算法。
9. 不产生自动 winner/recommendation。每个 scenario 公布公式、input refs、weights、constraints、
   unknowns、estimated fee/slippage、turnover assumption 和固定 loss/volatility/cost stress 结果。
10. 每个 scenario 与 order impact 均强制 `hypothetical=true`；impact 只包含 Card、target weight/
    notional 与估计成本，不包含交易所、账号、order type、client order id 或 dispatch payload。
11. proposal 顶层强制 `execution_authorized=false`、`capital_authorized=false`、
    `paper_lifecycle_authorized=false`、`orders_created=false`；人工 accept 只写 review fact。
12. review 绑定 immutable proposal/scenario、reason、actor、valid_until 与幂等键；过期 proposal
    拒绝决定。新 proposal/version 不继承旧 review。
13. API 提供 build/list/get/diff/review；CLI/Textual/Web 只展示服务端 status、coverage、scenarios、
    constraints、unknowns、impact 与 reviews，客户端不重算权重。
14. shadow package 静态禁止导入 BitPro adapter、paper service、live/order/risk execution；运行时
    测试对 PaperPromotion/PaperReviewRequest/paper order/live intent 计数做前后比较。

## Done Means

- proposal 固定 cohort/window/Card/label 决定版本和全部 source/content hash。
- 全部 cohort members 进入 fixed denominator，排除成员有明确原因；少于两个 eligible 时无方案。
- equal-weight 权重和精确为 1 且满足 cap；不可行时 fail closed。
- inverse-vol 缺任一正波动率即不生成；risk-budget 缺 capacity/liquidity 即不生成。
- 只有三个白名单模板，无收益目标、自动最佳模板、无界搜索、杠杆或做空。
- 所有 scenario/impact 为 hypothetical，顶层所有 execution/capital/paper/order 权限为 false。
- accept/reject/hold 只追加审计事实，有效期与幂等生效，不产生执行副作用。
- build 同 request/source/content 幂等；事实变化追加 version，旧 proposal/review 不改变。
- API/CLI/Textual/Web 同投影；PostgreSQL migration、全仓门禁与生产 fail-closed smoke 通过。
- 构建/复核前后 promotion/review、paper order、live intent 和任何 capital state 不变。

## Verification

```bash
uv run pytest tests/test_shadow_portfolios.py -q
uv run pytest tests/test_paper_cohorts.py tests/test_portfolio_observation_windows.py -q
uv run pytest tests/test_tui_app.py tests/test_cli.py -q
uv run alembic upgrade head
uv run alembic downgrade 0021_paper_cohorts
uv run alembic upgrade head
./scripts/check.sh
```

Manual/production checks:

- 两个/三个 accepted members 验证三模板、权重和、cap、成本、压力场景与 hypothetical impact。
- 缺 volatility 时只保留 equal-weight；缺 capacity/liquidity 时不产生 risk-budget proxy。
- cap 不可行、决定过期、cohort 无成员和 label 未接受时验证 `needs_data`/空 scenarios。
- 重复 build/review 与来源变更验证幂等、追加版本和历史不变。
- 审计 package imports、OpenAPI、持久化 JSON keys 与业务表计数，确认没有执行 payload/dispatch。
- 生产当前 0 comparable/0 label proposal，正确结果必须是 `needs_data`、0 scenarios，而不是
  自动绕过 cohort 或生成 equal-weight。

## Risks / Notes

- risk-budget 是受限、可解释的研究 proxy，不等于机构风险模型，也不是资金建议。
- volatility/capacity/liquidity 来自固定 Card/cohort 证据；unknown 必须传播，不能用行业默认值。
- 假设 notional 只用于比例、成本和压力展示，绝不映射账户余额或可用资金。
- 若未来需要真实资金治理，必须另立合同、账户/风险/审批/幂等/撤销门禁，不得复用本 Sprint
  的 review accept 作为授权。

## Handoff

- Gate H 只有在权重/证据门禁、不可变 review 和零 execution dispatch 均通过生产验收后关闭。
- Sprint 110 完成即结束 Sprint 106–110 路线；后续实盘资本治理不在本路线授权范围内。
