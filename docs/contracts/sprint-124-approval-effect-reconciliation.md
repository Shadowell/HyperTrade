# Sprint 124 — Approval and External Effect Reconciliation

> 状态：Completed — 实现、全量验证、部署与只读生产 Gate 已关闭。

## Goal

建立参数级、一次性 Approval 与外部写副作用对账协议，使未来 paper/live mutation 在 dispatch 前拥有持久意图、
在超时或断连后进入 `effect_unknown` 并通过 reconciliation 确认，而不是盲目重试或错误宣布完成。本 Sprint
只交付治理与故障合同，不开放生产交易权限。

## Dependencies

- Sprint 123 的 event-sourced Mission/Attempt/ToolCall 状态和 CompletionProof 可用。
- Capability Catalog 保留 reviewed version/hash；Policy Engine 可以基于结构化 args 返回 allow/ask/deny。
- 测试使用无资金副作用的 fake/isolated adapter；生产 live-write capability 与凭证仍物理缺席。

## In Scope

- `PolicyDecisionV1` 绑定 capability/version/hash、参数、subject/account/environment、role、budget 和 policy snapshot。
- `ApprovalRequestV1`、`ApprovalGrantV1` 与 requested/pending/approved/denied/expired/revoked/consumed 状态机。
- Approval 绑定准确 args hash、资源范围、最大额度、有效期、actor 和单次消费 token；deny 不可被 Approval 覆盖。
- `DispatchIntentV1` 在外部调用前持久化，包含 idempotency key、operation scope、fencing 和 reconciliation policy。
- ToolCall 支持 dispatched/acknowledged/succeeded/failed/timed_out/effect_unknown/reconciled 状态。
- 读调用可按错误分类退避重试；写调用超时默认进入 effect_unknown，禁止自动重复 dispatch。
- `EffectReconciler` 通过外部 operation id、幂等键或只读状态查询确定 committed/not_committed/unknown。
- CompletionProof 在 Approval 未消费、ToolCall effect_unknown 或 reconciliation 未完成时拒绝 Mission 完成。
- circuit breaker、orphan recovery、审计事件和操作员告警使用持久状态，不依赖单进程内存。

## Out of Scope

- 开放真实 paper 自动 start/pause、Testnet 或 mainnet live-write。
- LiveTradingMandate、资本风险预算和组合策略资格；属于 Sprint 132。
- 让模型创建、批准或扩展自己的权限。
- 对无法提供幂等/查询能力的外部接口声称 exactly-once。
- 把普通管理员身份等同于无限交易批准。

## Done Means

1. Approval args、scope、policy hash 或 capability version 任一变化都会使旧批准失效。
2. deny 永远不能通过 Approval 覆盖；ask 在 grant 前零 dispatch。
3. Approval 只能消费一次，过期、撤销、重复消费和跨账户使用均被拒绝并审计。
4. 每个写调用先提交 DispatchIntent，外部调用不发生在数据库事务内。
5. 在 dispatch 前、外部调用中、ack 后和 terminal event 前注入崩溃，不产生重复已知副作用。
6. 超时写调用进入 `effect_unknown`，CompletionProof 失败；reconciler 确认后才进入确定终态。
7. 无法对账的 adapter 保持 unknown 并请求人工处理，不能自动重试或伪造成功。
8. circuit breaker 跨 worker 共享，恢复和人工 override 都有 reason、actor、expiry 和事件。
9. public Item 只展示有界批准/等待/未知状态，不泄漏 secret、账户原始响应或 private reasoning。
10. 生产部署不获得任何新交易凭证或 live-write capability。

## Verification

```bash
uv run pytest tests/test_policy_decisions_v2.py -q
uv run pytest tests/test_approval_lifecycle.py -q
uv run pytest tests/test_dispatch_outbox.py -q
uv run pytest tests/test_effect_reconciliation.py -q
uv run pytest tests/test_mission_completion_proof.py -q
./scripts/check.sh
git diff --check
```

故障测试必须覆盖所有 crash boundary、重复消息、乱序 ack、过期 lease、同 key 不同 payload 和外部状态持续
unknown。生产验收只验证 capability 物理缺席和 fail-closed，不发起 paper/live mutation。

## Local Implementation Evidence

- 参数级 PolicyDecision、一次性 Approval、write-ahead outbox、ToolCall effect 状态、reconciler、持久 circuit
  与 bounded public projection 已落地；生产 write environment 默认关闭。
- 四个合同测试及 CompletionProof/Alembic 定向验证共 23 passed；PostgreSQL offline migration 通过。
  完整 `./scripts/check.sh` 通过 frontend 15 tests/build、Ruff、严格 mypy 与 Python 717 tests（2 个既有 OKX
  coroutine warnings）。实现提交 `6556377` 由部署流水线 `29817939092` 成功发布。
- 生产只读验收返回 health 200、16 个 active capabilities，且 write capability 数量为 0；未发起任何
  paper/Testnet/live/order/capital mutation。Sprint 124 Gate 已关闭。

## Handoff

Sprint 125 使用 canonical events、CompletionProof 和 reconciliation 结果形成可审核的策略 Outcome Ledger。
Sprint 124 不是交易授权；后续 Sprint 仍须单独建立 Paper mandate 与 LiveTradingMandate。
