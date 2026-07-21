# Sprint 133 — Live Canary Execution and Reconciliation

> 状态：Proposed；依赖 Sprint 132 完成。实施与每次生产 Canary 均需要产品所有者明确授权。

## Goal

在单一、小额、有限策略/标的/期限的 LiveTradingMandate 内，完成第一条真实 Live Canary 垂直路径：策略进入、
目标风险调整、保护性退出、订单/持仓/成交对账和故障回滚。系统首先证明不越权、不重复、不在未知状态加仓，
而不是证明盈利。

## Dependencies

- Sprint 132 的 mandate、Risk Engine、独立 live identity、kill switch 和 BitPro 双侧校验通过。
- Sprint 124 的 DispatchIntent/effect_unknown/reconciler 通过所有 crash boundary。
- Canary strategy 已通过 Sprint 129 validation、Sprint 130 Paper 和 Sprint 131 Shadow eligibility。

## In Scope

- `LiveCanaryPlanV1` 固定一个 account/environment、有限 symbols/strategy versions、最大资本、最大持仓、
  最大订单、有效期、退出计划、观察指标和 abort thresholds。
- Canary 启动要求操作员对准确 plan/mandate hash 作一次不可复用批准；Agent 不生成批准文本或签名。
- 使用 BitPro reviewed live contract 执行 mandate 内 promote/start/target adjustment/exit/cancel；禁止 transfer。
- 每个动作先写 DispatchIntent，使用唯一 idempotency key、external operation id、fencing 和 expected state。
- `LiveExecutionReconciler` 对账 BitPro/交易所订单、成交、持仓、余额和目标暴露，处理乱序、部分成交和断连。
- effect_unknown 时冻结 risk-increasing dispatch，只允许已授权的 cancel/reduce/exit 与人工接管。
- slippage、reject、latency、position mismatch、daily loss、drawdown、data/source health 和 heartbeat 触发 abort。
- abort 进入 reduce-only/cancel/exit 状态机，保存每步 intent/result/reconcile；无法自动平仓时升级人工紧急处理。
- Canary Outcome 分层记录预期/实际信号、订单、成交、成本、PnL、偏差、故障和操作员干预。
- 生产 rollout 从单策略、单标的、最小资本开始，不因早期盈利自动扩容。

## Out of Scope

- 多策略自主组合、自动扩大资本、增加标的、提高杠杆或自动续期；属于 Sprint 134 或后续新合同。
- 资金划转、提现、跨账户操作、未知订单类型或绕过 BitPro live preflight。
- 高频/低延迟策略、LLM 逐笔下单或把自然语言直接映射为订单。
- effect_unknown 时自动重复 order、promote 或 start。
- 以 Canary 盈利作为开放更大权限的唯一门槛。

## Done Means

1. Canary 所有 live action 都绑定同一有效 plan/mandate、RiskDecision、Approval、DispatchIntent 和 operation id。
2. 任一 args、strategy version、account、symbol、capital 或 expiry 越界在 BitPro dispatch 前被拒绝。
3. 在 intent、request、ack、partial fill、fill、position update 和 terminal event 边界注入崩溃，不产生重复订单。
4. effect_unknown 自动冻结加仓，reconciler 确认 committed/not_committed 后才继续；持续 unknown 转人工接管。
5. 部分成交、乱序事件和 position mismatch 不造成错误 completed 或反向重复下单。
6. kill switch、mandate revoke、loss/drawdown 和 source failure 能进入 reduce-only/cancel/exit，并留下完整审计。
7. fail-safe 退出不能建立反向仓位或超过 reduce amount。
8. Canary 结束后 BitPro/交易所持仓、订单、HyperTrade projection 和 Outcome Ledger 对账一致。
9. 无越权交易、重复订单、未知状态加仓、无证据晋级和 false completion。
10. 任何扩资、多策略或延长期限都需要新合同与新 mandate，不能由 Canary 自动完成。

## Verification

```bash
uv run pytest tests/test_live_canary_plan.py -q
uv run pytest tests/test_live_execution_outbox.py -q
uv run pytest tests/test_live_execution_reconciliation.py -q
uv run pytest tests/test_live_canary_fault_injection.py -q
uv run pytest tests/test_live_kill_switch.py -q
./scripts/check.sh
git diff --check
```

先在隔离 Testnet/fake exchange 完成全故障矩阵，再由产品所有者明确授权一次生产小额 Canary。生产验收不得
在文档、日志或 artifact 保存 credential、完整账户响应或可重放批准材料。

## Handoff

Sprint 134 只在 Sprint 133 完整结束、全部对账一致且安全 P0/P1 为零后，允许多策略授权内自主组合 Pilot。
任何安全门禁失败都回退到 Paper/Shadow，不进入 Sprint 134。
