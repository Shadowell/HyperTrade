# Sprint 129 — Unified Strategy Validation Funnel

> 状态：Active — Sprint 127–128 Gate 已关闭，开始实现统一 Research Quarantine 与验证漏斗。

## Goal

建立统一 Research Quarantine，对已有策略进化候选和全新策略候选执行同一套真实数据、锁定样本外、
walk-forward、成本、regime、参数稳定性和多重测试门禁。只有确定性验证结果可以产生 `validated`，模型解释、
新颖性或训练集高收益均不能降低门槛。

## Dependencies

- Sprint 127–128 提供 immutable candidate、frozen hypothesis/StrategySpec、trial family 和完整尝试预算。
- Sprint 126 提供真实 BitPro return series、aligned matrix 和 execution evidence contract。
- 复用 ExperimentLedger、RobustnessValidation、StrategyCard V2、BitPro backtest matrix 和 sandbox artifacts。

## In Scope

- `ValidationPolicyV2` 冻结数据分割、locked OOS、walk-forward folds、purge/embargo、min trades、cost/slippage/
  funding、drawdown、tail risk、parameter neighborhood、regime coverage 和 missing-data policy。
- `TrialFamilyV1` 记录本次及关联研究中的候选/参数尝试数，防止只报告最佳结果。
- 对已有与全新策略使用相同 required gates；新策略可增加而不能减少 novelty-specific falsification checks。
- 计算或引用 Probabilistic/Deflated Sharpe、selection-bias/overfit diagnostic、稳定区间和跨窗口分布；指标缺失为 unknown。
- 对真实成本、滑点、资金费、延迟、容量和流动性进行压力情景；不使用零成本默认值。
- regime 验证使用当时可得的状态或明确 ex-post research label，并区分，禁止把 ex-post label 当实时可用特征。
- `ValidationDecisionV2` 只能是 validated/rejected/needs_data/needs_review，包含每个 gate、reason、source 和 unknown。
- 生成 immutable validation artifact/content hash，并更新 candidate StrategyCard；不覆盖旧 validation。
- 独立 verifier 检查 hypothesis freeze time、OOS access ledger、trial count、artifacts 和 BitPro refs。
- 提供同策略/同 trial family 重放、policy diff 和 validation version comparison。

## Out of Scope

- 自动 paper start、Champion 标签、组合权重或 live mutation。
- 以单一 return/Sharpe 排名自动选择 winner。
- 删除失败 trial、重置尝试次数、移动 OOS 边界或在看到结果后放宽 gate。
- 使用 synthetic K 线、随机收益、模型估计成本或 Memory 代替 BitPro Evidence。
- 承诺 validated 策略会盈利。

## Done Means

1. 已有与全新策略候选都通过同一个 `ValidationPolicyV2` 状态机和 required gate 集合。
2. locked OOS 在 hypothesis/候选冻结前不可见；任何越界访问使 trial family invalid。
3. 所有尝试计入 TrialFamily；删除失败结果或只提交最佳候选不能改善选择偏差指标。
4. 数据、成本、资金费、交易数、Artifact 或 regime 覆盖不足时 fail closed 为 needs_data/needs_review。
5. 训练收益更高但 OOS、成本、回撤、稳定性或过拟合门禁失败的候选被 rejected。
6. 参数邻域出现尖峰、跨 fold 不稳定或依赖单一 regime 时明确暴露风险，不被平均收益隐藏。
7. 相同 candidate/policy/source hash 重放得到相同 decision；来源变化追加新 validation version。
8. LLM 不能写 gate result、覆盖 verifier 或直接创建 validated StrategyCard。
9. validation 前后 paper/live/order/capital 状态不变。
10. 真实 BitPro canary 至少验证一个 rejected 和一个非伪造 validated/needs_review 路径，结果不宣称未来盈利。

## Verification

```bash
uv run pytest tests/test_validation_policy_v2.py -q
uv run pytest tests/test_trial_family_accounting.py -q
uv run pytest tests/test_locked_oos_access.py -q
uv run pytest tests/test_unified_strategy_validation.py -q
uv run pytest tests/test_robustness_validation.py tests/test_experiment_ledger.py -q
./scripts/check.sh
git diff --check
```

隔离评测覆盖数据窥视、结果后改假设、删除失败 trial、零成本、参数尖峰、regime 泄漏、Artifact 缺失和 provider
诱导放宽门禁。生产只读/回测 canary 不调用 Paper 或 Live。

## Handoff

Sprint 130 只消费 immutable `ValidationDecisionV2(validated)`，在 PaperResearchMandate 内自动孵化候选。
Validation accept 不是 Paper 或 Live 授权。
