# Sprint 100 - Robustness Validation Suite

> 状态：Completed；2026-07-15 通过代码、迁移、部署和生产真实回测验收。

## Goal

把策略验证从单一回测矩阵升级为透明、受预算的鲁棒性验证：locked OOS、walk-forward、
参数敏感性、成本/滑点压力和市场状态压力，并对缺失证据 fail closed。

## In Scope

- `ValidationPolicyV2`、window planner、matrix planner 和 gate evaluator。
- locked out-of-sample、walk-forward 和时间顺序约束。
- bounded 参数邻域、费用/滑点场景和 regime 窗口。
- 交易充分性、数据完整性、结果完整性和 unknown 处理。
- validation run/result persistence、报告、API 和候选 gate 集成。

## Out of Scope

- 贝叶斯优化、遗传算法和无限参数搜索。
- 在 HyperTrade 复制回测引擎或完整数据。
- 自动按收益排序并晋升 paper/live。
- 未经单独合同的复杂统计显著性/多重检验框架。

## Deliverables

- robustness validation service 和 versioned schemas。
- BitPro 多窗口/场景编排与 budget accounting。
- `passed/failed/unknown/not_applicable` gate 模型。
- 报告、API/CLI/TUI projection 和完整测试。

## Implementation Plan

1. 定义 required/optional gate、阈值、unknown 和最终状态规则。
2. 实现不重叠窗口、locked OOS freeze 和 walk-forward planner。
3. 生成受 mandate 限制的参数邻域和成本场景。
4. 用 BitPro MCP 启动每个 window/scenario job，复用 Experiment fingerprint/idempotency。
5. 验证 result refs、metrics、交易数、时间边界和数据覆盖。
6. 计算跨窗口稳定性、参数尖峰、成本敏感和 regime 依赖摘要。
7. 输出 `validated/rejected/needs_data/needs_review`，禁止 unknown 自动通过。
8. 接入 PaperPromotion 前置 gate 和 StrategyCard projection。
9. 增加预算耗尽、部分窗口失败和 BitPro timeout 恢复。
10. 完成窗口、压力、拒绝、确定性和现有晋升回归测试。

## Done Means

- 高收益但 OOS、成本压力、交易充分性或参数敏感性失败的候选不能通过。
- locked OOS 在 candidate/parameter freeze 前不可读取。
- 每个场景都关联 manifest、BitPro job/result 和 gate 证据。
- 缺指标、缺窗口或上游部分失败明确进入 unknown/needs_data/rejected。
- 只有所有 required hard gates passed 才能进入现有 paper approval 候选列表。

## Verification

```bash
uv run pytest tests/test_robustness_validation.py tests/test_validation_windows.py -q
uv run pytest tests/test_paper_promotion.py tests/test_research_orchestrator.py -q
./scripts/check.sh
```

## Risks / Notes

- 回测数量快速增长，必须在生成 matrix 前预估并预扣 budget。
- regime 数据不足时只能返回 unknown，不能用模型描述代替窗口证据。
- 回测、paper 和未来 live 结果继续分层，不互相改写。

## Handoff

- 迁移 0015、鲁棒性服务、API、CLI、策略卡片和 paper promotion gate 已交付。
- `./scripts/check.sh` 通过：前端 lint/8 tests/build、Ruff、129 个 mypy 模块、
  403 个 Python tests。
- HyperTrade commits `bf627d4`、`119bd24`、`f7b1bea` 分别完成主体、远程 MCP
  传输和 BitPro 原生运行时契约；最终部署 workflow `29353572908` 成功。
- BitPro PR `#570`/workflow `29351668545` 修复远程 MCP lifespan，PR `#571`/
  workflow `29353194135` 修复 smoke 校验异步边界。生产生成策略返回
  `valid=true, smoke=true`。
- 生产 ResearchJob `rjob_5dcc95b103394cffb130` 完成 13 次真实 BitPro 回测、
  3 份候选证据、7 个鲁棒性场景和 16 个 artifact refs；validation
  `rvld_5f43ed2c628847ada2a5` 因 locked OOS、walk-forward、参数敏感性和成本压力
  失败而正确 `rejected`。Experiment `exex_c64e1699533c48b0a0b3` completed，未触发
  paper/live。
- 下一步：Sprint 101 把 Task、Graph、Evidence、Experiment 和 Validation 纳入系统评测。
