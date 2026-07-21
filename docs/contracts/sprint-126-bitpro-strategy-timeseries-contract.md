# Sprint 126 — BitPro Strategy Time-Series and Execution Evidence Contract

> 状态：Completed — 双侧合同、PR/部署、真实 paper 只读 canary 与 HyperTrade fail-closed 验证均通过。

## Goal

通过版本化 BitPro MCP/API 合同向 HyperTrade 提供可比较的策略收益序列、对齐矩阵和执行质量摘要，使参数
优化、新策略验证、regime 条件表现和组合风险计算基于同一真实数据口径。HyperTrade 只保存有界摘要、hash
与来源引用，不直连 BitPro 数据库，也不复制完整行情、订单或策略运行逻辑。

## Dependencies

- BitPro 继续拥有 K 线、策略代码、回测、Paper、Live、订单、持仓和账户真相。
- Sprint 125 Outcome Ledger 可保存 version/source/content hash 和 bounded artifact references。
- 新合同必须先通过 `bitpro_capabilities` 发现并冻结 reviewed contract version。

## In Scope

- 定义 `StrategyReturnSeriesV1`：strategy/version、source layer、symbols、timeframe、start/end、bucket、timezone、
  gross/net return、equity/return points、cost model、fees、slippage、funding、as-of 和 freshness。
- 定义 `AlignedStrategyReturnMatrixV1`：固定成员、共同窗口、缺失策略、对齐方法、sample count、source hashes
  和不可比较 reason codes。
- 定义 `StrategyExecutionQualityV1`：signal/order/fill count、fill ratio、latency、slippage、reject/cancel、
  exposure、turnover、data gaps 和 bounded error summary。
- 明确 backtest、paper、live 三层来源，禁止跨层拼接成一个连续收益序列。
- 提供分页、最大点数、压缩/bucket、时间范围和响应大小上限；拒绝无限原始序列。
- 合同包含 schema/contract version、producer、event/as-of/recorded time、currency、precision 和 content hash。
- HyperTrade adapter 校验 schema、hash、时间顺序、重复点、未来点、缺失成本和来源健康。
- 同一 request/source version 幂等；BitPro 数据修正产生新 source hash，旧 Outcome/Artifact 引用保持可追溯。
- 建立 connector contract/e2e fixture，禁止 synthetic 或 mock 数据进入 production acceptance。

## Out of Scope

- HyperTrade 直连 BitPro 数据库、复制完整 K 线、订单、成交或账户历史。
- 在 HyperTrade 重算 BitPro 策略信号、PnL 或交易业务规则。
- 自动策略排名、参数优化、组合权重或 paper/live mutation。
- 把不同成本、窗口、币种、周期或来源层强行对齐。
- 在数据不足时填充默认波动率、默认收益或虚构点。

## Done Means

1. 同一策略版本和窗口可获得版本化、成本后、时序正确的 backtest 或 paper return series。
2. 对齐矩阵固定 denominator；任一成员缺失都保留并给出 reason，不从比较中静默消失。
3. 不同 source layer、cost model、currency、timeframe 或 bucket 默认不可比较。
4. 任一未来时间点、重复冲突、hash 不匹配、缺失成本或超范围响应被 HyperTrade adapter 拒绝。
5. BitPro 数据修正产生新 source hash；旧 Outcome、Card 和 cohort 保持引用旧版本。
6. 响应有确定上限和分页，生产请求不能拉取无限历史或原始账户敏感载荷。
7. ExecutionQuality 可以区分策略失效、数据缺口和执行偏差所需的关键事实。
8. HyperTrade 数据库只保存 bounded summaries、hash 和 refs，不复制完整 BitPro source-of-truth。
9. 合同兼容性检查在 BitPro/HyperTrade 双侧 CI 运行，未知版本 fail closed。
10. 本 Sprint 不创建、启动、暂停或交易任何策略。

## Verification

HyperTrade 侧：

```bash
uv run pytest tests/test_bitpro_strategy_timeseries_contract.py -q
uv run pytest tests/test_bitpro_aligned_return_matrix.py -q
uv run pytest tests/test_bitpro_execution_quality.py -q
uv run pytest tests/test_connector_contracts.py -q
./scripts/check.sh
git diff --check
```

BitPro 侧必须有对应 schema、producer 和真实历史数据 integration tests。生产只读 canary 选择小窗口的已知
策略，核对版本、点数、成本、hash 和修正语义；不得保存账户 secret 或完整原始响应。

## Handoff

Sprint 127 使用 Outcome Ledger 与 BitPro 时序合同实现已有策略的有界参数/规则进化；Sprint 128 在相同数据
边界上实现完全新策略发现。任何一个下游 Sprint 都不能绕过本合同直读数据库。
