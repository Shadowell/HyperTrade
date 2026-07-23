# Sprint 132 — LiveTradingMandate and Deterministic Risk Engine

> 状态：Awaiting explicit owner approval；Sprint 131 已完成。该 Sprint 是 mainnet 边界变更，实施前必须
> 再次获得产品所有者明确批准。

## Goal

建立 BitPro 与 HyperTrade 共同验证的 `LiveTradingMandateV1`、独立 live execution identity 和确定性 Risk Engine，
让未来自动实盘只能在操作员预先批准、可撤销、会过期的资本与动作包络内运行。本 Sprint 只交付授权、预检
和拒绝证明，不发送真实订单、不自动进入实盘。

## Dependencies

- Sprint 124 的 Approval、DispatchIntent、effect_unknown 和 reconciliation 合同已通过故障验收。
- Sprint 129–131 提供 validated StrategyCard、Paper evidence、eligibility 和 Shadow target。
- BitPro 必须新增 reviewed mandate token/contract 验证；不能让 Agent 伪造现有 live confirmation 字段。

## In Scope

- `LiveTradingMandateV1` 冻结 tenant/operator、account、environment、market、symbols、strategy versions、
  total/per-strategy/per-symbol capital、leverage、order types、allowed actions、validity 和 policy hash。
- 风险阈值覆盖日亏损、策略/组合回撤、CVaR、暴露、相关性、流动性、滑点、换手和单次权重变化。
- 区分 risk_increasing 与 risk_reducing 动作；增加风险要求完整资格与健康，降低风险可使用更窄 fail-safe scope。
- mandate 必须由独立操作员明确创建/批准，Agent 不得推断、自动填写确认、扩大 scope 或自动续期。
- BitPro 返回签名/不可伪造 mandate reference，并在每个 live preflight/mutation 重新校验当前有效性与 args hash。
- `LiveRiskDecisionV1` 对每个 proposed action 返回 allow/deny/unknown、全部 gate、current/after exposure 和 reason。
- deny 不可被模型、普通 Approval、收益预测或客户端覆盖；unknown 禁止增加风险。
- 全局、账户、策略 kill switch，mandate revoke/expire 和 reduce-only mode 使用持久事件并跨 worker 生效。
- research/paper/live-read/live-write 使用不同 service identity、网络与凭证；研究 worker 物理拿不到 live credential。
- API/CLI/Web 提供 mandate diff、preflight、revoke、kill switch 和审计，不展示 credential 或可重放签名材料。

## Out of Scope

- 真实 live_promote、下单、撤单、划转或账户资金变更；属于 Sprint 133。
- 自动创建、批准、续期或扩大 LiveTradingMandate。
- 用 Web/CLI 普通登录身份代替独立高风险审批身份。
- 配置开关绕过 BitPro mandate validation 或部署 live credential 到通用 worker。
- 承诺 mandate 内动作安全或盈利；Risk Engine 只能执行已定义约束。

## Done Means

1. mandate 精确绑定账户、环境、策略版本、标的、额度、动作、风险阈值、有效期和 policy hash。
2. Agent 无法创建、批准、续期、扩额、升杠杆或改变账户；所有尝试在 dispatch 前 deny。
3. BitPro 和 HyperTrade 对同一 mandate/action canonical hash 计算一致，篡改任一字段都会失效。
4. risk_increasing 动作在资格、数据、Paper、regime、账户或执行健康任一 unknown 时被拒绝。
5. risk_reducing 仅允许 mandate 声明的减仓/退出动作，不能借 fail-safe 建立反向新仓。
6. revoke、expiry 和 kill switch 跨 worker 立即阻止新风险动作，并产生可重放事件。
7. Risk Engine property tests 对任意 action sequence 不允许越过资本、杠杆、损失、回撤和暴露硬上限。
8. live-write credential 只存在于独立、默认禁用的部署单元；API/research/paper worker 物理缺席。
9. public projection 不泄漏 account secret、credential、mandate signing material 或 private reasoning。
10. 本 Sprint 生产验收只做 read-only preflight/deny canary，真实订单和余额变化为零。

## Verification

```bash
uv run pytest tests/test_live_trading_mandates.py -q
uv run pytest tests/test_live_risk_engine.py -q
uv run pytest tests/test_live_mandate_policy_properties.py -q
uv run pytest tests/test_live_identity_isolation.py -q
uv run pytest tests/test_approval_lifecycle.py tests/test_agent_tool_policy.py -q
./scripts/check.sh
git diff --check
```

生产验收检查 live-write 部署默认关闭、通用 worker 无凭证、篡改 mandate fail closed、kill switch/revoke 生效，
且账户余额、持仓、订单和资金均不变化。

## Handoff

Sprint 133 在一个明确批准的小额 Canary mandate 下接入真实执行、outbox 和对账。没有 Sprint 132 的双侧
mandate validation，不得通过环境变量直接启用自动 live mutation。
