# Sprint 110 QA — Shadow Portfolio & Capital Governance

## Verdict

PASS。Gate H 与 Sprint 106–110 路线关闭。Shadow Portfolio 只产生不可变的假设研究方案和
人工复核事实，生产不存在从 proposal/review 到资金、paper 或订单的调用路径。

## Contract Coverage

| 门禁 | 证据 | 结果 |
|---|---|---|
| 固定分母与版本 | cohort/window/Card/label refs + source/content hash；生产 intake 3 | PASS |
| 单一可比组 | 跨 comparison group fixture 返回 0 scenario | PASS |
| 标签与时效 | 最新 accept 且 proposal/decision 均未过期才 eligible | PASS |
| 模板白名单 | 仅 equal-weight、inverse-volatility、capped risk-budget proxy | PASS |
| 证据依赖 | 缺 volatility 抑制后两项；缺 capacity/liquidity 抑制 risk-budget | PASS |
| 权重约束 | Decimal sum=1、max cap；不可行 cap fail closed | PASS |
| 假设边界 | scenario/impact hypothetical；无 exchange/account/order payload | PASS |
| 人工复核 | accept/reject/hold 独立、幂等、有时效，所有权限 false | PASS |
| 执行隔离 | 静态 import 审计与生产业务表前后计数 | PASS |
| 多界面同投影 | REST、CLI、Textual、Web 使用 `ShadowPortfolioService` | PASS |

## Automated Evidence

- `tests/test_shadow_portfolios.py`: 9 passed；相关 API/CLI/TUI/portfolio suite 109 passed。
- `./scripts/check.sh`: frontend lint、9 tests、production build；Ruff；mypy 149 source files；
  523 Python tests，全部通过。
- 临时 PostgreSQL：全链 upgrade、`0022 -> 0021 -> 0022` 往返，最终两张 Shadow 表存在。

## Production Evidence

- Commit `a855a8e163f9252ba11af8185bc6dab808c804fd`；workflow `29391103674` success。
- API/Nginx health、Alembic `0022_shadow_portfolios (head)`、4 个 Shadow OpenAPI paths、
  `/harness/portfolio` HTTP 200、host `/shadow list` 和近五分钟 API/worker 日志通过。
- proposal `shpf_5bfd4d97d12646d8a303`：cohort `pcoh_cbf6b383e7b448d7a36f`、window
  `pwin_c23b2d48cfab40eeb3f9`、version 1、intake 3、eligible 0、scenario 0、`needs_data`。
- unknowns 为 `paper_cohort_needs_data` 与 `insufficient_accepted_comparable_members`；相同请求
  重放 `same_id=true`、`idempotent=true`。
- persisted forbidden key audit=false；所有 hypothetical/execution/capital/paper/order flags 正确。
- 前/后计数：ShadowReview 0/0、PaperPromotion 0/0、PaperReviewRequest 0/0、paper order 10/10、
  live intent 1/1；唯一预期写入为一个 immutable Shadow proposal。

## Residual Risk

- 生产没有 accepted comparable cohort，故正向三模板由 deterministic fixtures 验证，生产只
  验证真实 fail-closed 路径；不能为了演示而伪造 label 或 portfolio evidence。
- risk-budget 仍是有限研究 proxy，不含协方差、尾部风险、真实容量冲击或账户约束。若未来
  建立真实资本治理，必须创建新路线与权限合同，不得复用 Shadow review accept。
