# Sprint 127 — Existing Strategy Evolution Engine

> 状态：Active — Sprint 126 Gate 已关闭，开始实现已有策略的有界候选进化引擎。

## Goal

让 HyperTrade 从已结算 Outcome、策略衰减和 regime 条件表现中，为已有策略自动提出有界参数与规则候选，
生成不可变候选版本并注册可复现实验。该引擎负责提出和排队候选，不负责宣布策略有效、自动进入 Paper 或
修改正在运行的策略版本。

## Dependencies

- Sprint 125 Outcome Ledger 提供 settled outcomes、LessonCandidate、失败模式和 lineage。
- Sprint 126 提供真实、版本化、成本后的策略收益序列和执行质量。
- 复用 ResearchMandate、StrategySpec、ExperimentManifest、BitPro dynamic DB strategy 和 sandbox validation。

## In Scope

- `EvolutionMandateV1` 定义允许的策略、symbols、timeframes、参数边界、可变规则、禁止字段、候选/回测预算、
  数据窗口政策和停止条件。
- `StrategyDecayAssessmentV1` 区分 performance decay、regime mismatch、execution drift、data quality 和 unknown。
- 仅从 settled Outcome 和 fresh BitPro Evidence 触发候选；短期单次亏损不能单独触发重写。
- 参数候选使用 bounded grid/random/Bayesian proposal 接口，但统一受 max candidates、max trials、wall/token
  budget 和 deterministic seed 约束。
- 规则候选只能修改 StrategySpec 声明的 entry/exit/filter/risk 插槽；不得扩大 symbol、market、account 或权限。
- 每个候选产生新的 immutable `StrategyCandidateVersionV1`、code/config digest、parent version 和 proposal reason。
- 正在 paper/live 的版本不可原地修改；BitPro 侧使用新的 dynamic DB candidate/version，旧版本继续可重放。
- 候选在进入回测前通过 schema、source、`BaseStrategy`、sandbox、dependency 和 duplicate fingerprint 检查。
- 保存被拒绝、重复、预算终止和生成失败候选，避免后续重复搜索同一区域。
- 暴露 API/CLI/Web 只读研究队列和 diff，不允许客户端直接批准 Paper/Live。

## Out of Scope

- 从零提出全新 Alpha 假设或新策略族；属于 Sprint 128。
- 完整 OOS/walk-forward/多重测试门禁；属于 Sprint 129。
- 自动 paper start/pause/retire、组合调权或 live mutation。
- 无界遗传搜索、在线强化学习、自动增加候选预算或以训练收益作为唯一目标。
- 修改 BitPro 文件、registry、服务进程或直连数据库。

## Done Means

1. 对一个已有策略和 settled decay Outcome，系统生成不超过 mandate 上限的参数/规则候选。
2. 每个候选绑定 parent version、StrategySpec diff、Outcome/Evidence refs、预算、seed、code/config digest 和原因。
3. active paper/live 策略版本在候选生成前后 hash 不变；候选使用独立不可变版本。
4. 越界参数、未声明规则、扩大 symbol/tool/permission、未知依赖和 sandbox 失败候选被拒绝。
5. 相同 parent/data/proposal/seed 得到同一 fingerprint，不重复创建物理策略或实验。
6. 单次亏损、未结算窗口、过期数据、effect_unknown 或无法分类衰减时只返回 unknown/needs_review。
7. 候选预算、模型调用、工具调用和 wall time 均可证明未超限；预算耗尽后停止生成。
8. 被拒绝候选和原因进入 ledger，下一轮不会在相同证据下重复搜索。
9. 引擎不调用 paper/live/order/capital adapter，静态与运行时检查均为零 dispatch。
10. 用户可以读取候选 diff、lineage、数据范围、unknowns 和下一步验证状态。

## Verification

```bash
uv run pytest tests/test_strategy_decay_assessment.py -q
uv run pytest tests/test_strategy_evolution_engine.py -q
uv run pytest tests/test_strategy_candidate_versions.py -q
uv run pytest tests/test_strategy_sandbox.py tests/test_experiment_ledger.py -q
uv run pytest tests/test_research_roles.py -q
./scripts/check.sh
git diff --check
```

验收包含参数越界、重复候选、预算耗尽、active version 不变、未结算 Outcome、数据缺口和恶意规则扩权。

## Handoff

Sprint 128 增加不依赖 parent strategy 的全新策略发现；Sprint 129 将两类候选放入同一个确定性验证漏斗。
