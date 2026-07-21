# Sprint 134 — Authorized Autonomous Portfolio Pilot

> 状态：Proposed；依赖 Sprint 133 成功关闭。进入开发和每次生产 Pilot 都需要产品所有者明确授权。

## Goal

在严格有限的 LiveTradingMandate 内运行首个多策略自主组合 Pilot：HyperTrade 根据当前 regime、validated
StrategyCard、Paper/Live Outcome 和组合风险，自动决定策略 eligibility、进入、退出、降权和加权；BitPro
负责确定性信号与执行，Risk Engine 对每个动作实施硬门禁。Pilot 的目标是验证完整自治闭环和资本保护，
不承诺盈利，也不自动扩容。

## Dependencies

- Sprint 133 Canary 完成且无越权、重复订单、未知状态加仓、错误终态或未对账副作用。
- 至少两个策略拥有 Sprint 129 validation、Sprint 130 完整 Paper window、Sprint 131 Shadow target 和未过期证据。
- Sprint 132 mandate/Risk Engine、独立 live identity、kill switch 和 operator takeover 已生产验证。

## In Scope

- `AutonomousPortfolioPilotV1` 固定 account、symbols、strategy versions、最大总/单策略资本、最大杠杆、
  rebalance cadence、allowed actions、regime policy、hysteresis、cost/turnover cap、期限和 benchmark。
- 每个周期重新获取 current regime、strategy eligibility、BitPro live state、source health 和 remaining risk budget。
- 只有 eligible 且在 mandate 内的策略可进入；pause/retire/unknown 策略不能获得新增暴露。
- 目标权重来自 Sprint 131 reviewed allocator version，并在当前 live constraints 下重新做 deterministic feasibility。
- 进入、加权、降权、退出和撤单分别产生 RiskDecision、DispatchIntent、ToolCall、reconciliation 和 Outcome。
- 使用 dwell、cooldown、entry/exit threshold、max delta 和 turnover/cost gate，禁止噪声驱动频繁切换。
- 组合/策略回撤、相关性突升、执行偏差、regime unknown、数据过期或 reconciliation gap 自动降低风险。
- Exploration 只在 Research/Paper 发生；Pilot 不能把未经 Sprint 129–131 的新候选直接加入 Live。
- 操作员可随时 pause/revoke/kill/take over；恢复需要重新 preflight 当前账户、持仓、订单和 mandate。
- Pilot 报告比较预先声明 benchmark，分解策略选择、配置、成本、执行和市场状态贡献，不做事后改 benchmark。

## Out of Scope

- 自动扩大资本、标的、市场、账户、杠杆、策略集合、权限或 Pilot 期限。
- 未经完整研究生命周期的新策略直接进入 Live。
- LLM 逐笔下单、在线修改 live strategy code/parameter 或关闭 Risk Engine。
- 资金划转、提现、跨账户、无限组合优化或高频执行。
- 因短期盈利自动宣布北极星完成或进入无上限生产规模。

## Done Means

1. Pilot 只使用 mandate 固定的策略版本、标的、账户、资本、动作和 allocator/policy hash。
2. 系统能在至少一次 eligibility 改变中自动完成进入/退出或降权，并可从事件与 Evidence 重放完整原因。
3. 所有目标权重满足资本、杠杆、暴露、相关性、流动性、成本、换手和最大 delta 约束。
4. regime 抖动不会导致频繁交易；hysteresis、dwell 和 cooldown 的实际效果可量化。
5. 数据、账户、订单、持仓或 external effect 任一 unknown 时禁止增加风险并进入安全状态。
6. kill switch、revoke 和 operator takeover 在规定时限内停止新风险并完成对账。
7. 新策略发现仍停留在 Research→Validation→Paper→Shadow 路径，不能跳级进入 Pilot。
8. Pilot 期间越权交易、重复订单、未知状态加仓、无证据晋级和 false completion 均为零。
9. 报告按预先声明 benchmark 展示成本后结果、回撤、CVaR、换手、执行偏差和 unknown，不承诺未来盈利。
10. Pilot 结束不会自动扩资；是否继续、扩大或退回 Paper 由新的人工决定和后续合同确定。

## Verification

```bash
uv run pytest tests/test_autonomous_portfolio_pilot.py -q
uv run pytest tests/test_live_portfolio_risk_properties.py -q
uv run pytest tests/test_live_portfolio_fault_injection.py -q
uv run pytest tests/test_regime_shadow_allocator.py -q
uv run pytest tests/test_live_execution_reconciliation.py -q
./scripts/check.sh
git diff --check
```

生产 Pilot 必须使用明确授权的极小资本、有限策略/标的和固定期限；持续输出账户/订单/持仓对账、安全指标、
benchmark 和 kill-switch readiness。任何 P0/P1 安全失败立即终止并回退。

## Handoff

Sprint 134 是北极星的首个有限 Pilot，不是无限自治生产授权。Pilot 关闭后，根据真实 Outcome 决定是否另立
扩容、更多市场、更多策略族或长期运营合同；不得在本合同内自动扩大范围。
