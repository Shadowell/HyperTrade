# Sprint 131 — Regime-Aware Shadow Portfolio Allocator

> 状态：Proposed；依赖 Sprint 130 完成。

## Goal

根据当前市场 regime 概率、策略条件表现、Paper cohort、相关性、容量、流动性和交易成本，自动产生有约束、
带迟滞的 Shadow Portfolio 目标权重与策略资格状态。该 Sprint 允许自动研究组合，但所有结果仍是
`execution_authorized=false` 的影子方案，不调真实资金、不发送订单。

## Dependencies

- Sprint 126 提供 BitPro 对齐收益矩阵与执行质量。
- Sprint 130 提供完整、可比较、未过期的 Paper Champion/Challenger cohort 和 ObservationWindow。
- 复用 WorldState、PortfolioAssessment V2、StrategyCard V2 和现有 ShadowPortfolioService 的不可变 scenario。

## In Scope

- `MarketRegimeSnapshotV2` 输出 trend/range/high_volatility/stress/liquidity/correlation 概率、confidence、
  source/as-of、freshness、model/policy version、转换证据和 unknown。
- regime 特征只使用决策时可得数据；ex-post label 单独标记，只用于研究验证，不能进入实时资格输入。
- `StrategyEligibilityV1` 对每个版本输出 eligible/observe/reduce/pause/retire/unknown、reason、Evidence、有效期。
- 资格先于权重计算；不合格、过期、未覆盖 regime、数据缺口或执行异常策略不能因预期收益高而入选。
- `ShadowAllocationPolicyV2` 支持 equal weight、inverse volatility、capped risk contribution 和有界 constrained
  risk-adjusted template；每种模板有固定公式、输入、policy hash 和不可行原因。
- 权重约束覆盖单策略/单标的 cap、相关性、风险贡献、容量、流动性、最大换手、成本、最小/最大成员数。
- 使用 entry/exit 双阈值、最小驻留时间、冷却期、连续窗口确认和最大单次权重变化防止频繁切换。
- `ShadowPortfolioTargetV2` 记录当前/目标权重、estimated turnover/cost、stress、unknown、source hash 和 expiry。
- 历史 walk-forward/replay 比较静态基准、旧 Shadow 和新 policy，严格使用当时可见状态。
- API/CLI/Web 展示资格、权重差异、成本和 reason；客户端不重算 regime、资格或权重。

## Out of Scope

- Paper 或 Live 的真实权重变更、start/pause/retire、订单、资金或账户调用。
- LLM 直接输出权重，或用自然语言覆盖确定性约束。
- 无界均值方差优化、杠杆、做空扩权、收益最大化黑盒或在线强化学习。
- 用默认值填补 volatility、capacity、liquidity、correlation、cost 或 regime unknown。
- 把 Shadow 优势描述成未来盈利保证。

## Done Means

1. 每个策略先产生可解释 eligibility；不合格成员保留在 denominator 并显示 reason。
2. regime snapshot 包含概率、confidence、来源、时点和 unknown，不能只输出单一标签。
3. 任一 required volatility/correlation/capacity/liquidity/cost 缺失时，相应模板不可生成，不填默认值。
4. 所有目标权重和精确为 1 或明确 infeasible，且满足 cap、风险贡献、容量和换手约束。
5. entry/exit hysteresis、dwell、cooldown 和 max delta 在边界状态下阻止无意义频繁切换。
6. 历史 replay 无未来数据，使用当时可见 regime 与 source version，并计入真实成本和换手。
7. Shadow proposal 不包含 exchange order payload，顶层 execution/capital/paper/live authorization 均为 false。
8. 相同 source/policy/request 幂等；新事实追加 target version，旧 target/review 不改变。
9. 引擎前后 PaperPromotion、Paper action、Live intent/order、余额和持仓状态不变。
10. 操作员能解释每个成员为什么进入、退出、降权或保持，以及预计成本和未知项。

## Verification

```bash
uv run pytest tests/test_market_regime_snapshot_v2.py -q
uv run pytest tests/test_strategy_eligibility.py -q
uv run pytest tests/test_regime_shadow_allocator.py -q
uv run pytest tests/test_shadow_portfolios.py tests/test_paper_cohorts.py -q
uv run pytest tests/test_no_lookahead_portfolio_replay.py -q
./scripts/check.sh
git diff --check
```

验收覆盖 regime 临界抖动、unknown、相关性突升、成本恶化、容量缺失、不可行 cap、窗口过期和 source 修正。

## Handoff

Sprint 132 把 Shadow eligibility/target 作为 LiveTradingMandate 的候选输入，但 Shadow proposal 或人工 accept
本身都不构成实盘授权。
