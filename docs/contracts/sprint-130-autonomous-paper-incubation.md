# Sprint 130 — Autonomous Paper Incubation

> 状态：Proposed；依赖 Sprint 129 完成。

## Goal

在明确、可撤销、仅限模拟盘的 `PaperResearchMandate` 内，让 validated candidate 自动配置并启动 BitPro Paper，
进入 Champion/Challenger/Watch 观察，按固定窗口自动继续、降级、暂停或退役。该 Sprint 首次允许受控自动
paper lifecycle mutation，但不提供 Testnet、mainnet、真实资金或 live promotion 权限。

## Dependencies

- Sprint 124 提供 Approval、DispatchIntent、effect_unknown 和 reconciliation。
- Sprint 129 提供 immutable validated candidate、StrategyCard、ValidationDecision 和完整 source hashes。
- 复用 PaperPromotion、PaperObservationWindow、PaperCohort、BitPro paper_configure/start/dashboard/events/equity。

## In Scope

- `PaperResearchMandateV1` 冻结允许策略/版本、symbols、paper capital、最大实例数、观察 horizon、成本、
  自动动作、quota、有效期、审批人、policy hash 和 kill switch。
- mandate 默认允许 configure/start/observe/reduce/pause/retire 中明确列出的动作；未列动作 deny。
- validated candidate intake 固定 denominator；缺 validation、过期、hash mismatch 或来源不健康者保留 rejected reason。
- 自动 configure/start 使用 Sprint 124 DispatchIntent、幂等键、外部 operation id 和 reconciliation。
- 30/60/90 天不可变 ObservationWindow，按相同 market/symbol/timeframe/cost/bucket 比较 Champion/Challenger。
- 自动判断 continue_observing、paper_degraded、pause、retire_candidate；return 只在数据/风险/稳定性之后比较。
- data gap、BitPro unhealthy、effect_unknown、异常成交或风险阈值触发停止新增 Paper 动作并告警。
- 每次自动动作记录 mandate snapshot、reason、Evidence、before/after state、actor、ToolCall 和 Outcome link。
- 操作员可 revoke/pause mandate；revoke 后禁止新动作，并对已运行实例按 policy 进入 observe-only 或安全暂停。
- UI/API/CLI 展示 cohort、窗口、动作、unknown、reconciliation 和 kill switch，不在客户端重算状态。

## Out of Scope

- Testnet/mainnet/live order、真实账户、资金划转或 LiveTradingMandate。
- 自动提高 paper capital、扩大 symbols、增加杠杆或延长 mandate。
- 少于最小观察窗口时自动选 Champion，或仅按总收益决定继续/退役。
- 把 Paper 结果改写成回测结论或未来收益保证。
- 无幂等/对账能力的 paper mutation 自动重试。

## Done Means

1. 只有 validated、版本/hash 完整且在有效 PaperResearchMandate 内的 candidate 能自动 configure/start。
2. mandate 之外的策略、symbol、capital、动作或过期请求在 dispatch 前被拒绝。
3. paper configure/start/pause/retire 在所有 crash boundary 下不产生重复实例或 ghost action。
4. effect_unknown 时停止后续生命周期动作，reconciliation 后才进入确定状态。
5. 30/60/90 天窗口严格可比；窗口不足、来源过期或成员少于两名时不产生 Champion。
6. 高收益但回撤、稳定性、成本、数据质量或 regime coverage 失败的成员不能成为 Champion。
7. kill switch/revoke 阻止新动作，历史 Paper、Outcome、ToolCall 和审批记录保持可查询。
8. 操作员能看到自动动作的准确 reason、证据、mandate、before/after 和 unknown。
9. static/runtime gate 证明 paper controller 无 Testnet/live/order/capital adapter 或 credential。
10. 生产 Paper canary 只使用预先批准的小额模拟实例，不触发任何真实资金动作。

## Verification

```bash
uv run pytest tests/test_paper_research_mandates.py -q
uv run pytest tests/test_autonomous_paper_incubation.py -q
uv run pytest tests/test_paper_effect_reconciliation.py -q
uv run pytest tests/test_paper_cohorts.py tests/test_portfolio_observation_windows.py -q
uv run pytest tests/test_agent_tool_policy.py -q
./scripts/check.sh
git diff --check
```

生产 canary 前后必须核对 Testnet/live intent/order、真实余额和持仓均无变化；Paper mutation 的授权、幂等、
外部引用和 Outcome 全部可审计。

## Handoff

Sprint 131 使用稳定 Paper cohort、BitPro 对齐收益和当前 regime 建立自动 Shadow 组合配置。Paper Champion
不是 Live 资格，不能绕过 Shadow 与 LiveTradingMandate。
