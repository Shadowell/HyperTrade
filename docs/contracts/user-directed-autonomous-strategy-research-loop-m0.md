# User-Directed Contract — Autonomous Strategy Research Loop M0

> 状态：Active。
>
> 激活原因：产品所有者于 2026-07-24 明确要求按最高目标改造 HyperTrade，并先完成最小闭环。
>
> 优先级：当前最高。Sprint 132–134 的实盘路线保持未激活，不与本合同并行实施。

## Goal

把 HyperTrade 已有的 Provider、Mission、BitPro 策略/回测、统一验证和 Paper Incubation 能力串成一个
目标驱动的自主研究闭环：

> 用户提交一次自然语言策略目标；Agent 自主产生多个候选、写策略、真实回测、根据证据迭代；通过门禁的
> 候选在明确 Paper 预授权内自动进入模拟盘；预算内没有候选通过时交付失败证据并询问是否继续。

详细设计以
[目标驱动的自主策略研究闭环 M0](../architecture/36-goal-driven-autonomous-research-loop-m0.md)
为准。

## User-Visible Outcome

用户只需要：

```text
/research 研究一个收益稳定、最大回撤不超过15%的BTC策略，满足要求后上模拟盘
```

用户最终得到且只能得到以下一种明确结果：

1. `paper_observing`：候选通过确定性验证，并在有效预授权内确认启动模拟盘。
2. `needs_operator`：没有候选通过、预算耗尽、缺少关键数据、需要复核或外部副作用状态不明。
3. `canceled`：用户明确取消。
4. `failed`：不可恢复的系统失败，包含错误分类和可采取的下一步。

停止运行、生成报告或模型声称完成，都不能单独构成任务完成。

## In Scope

- 新增版本化 `ResearchGoalV1`、预算、候选、失败诊断和 Paper 预授权合同。
- 新增持久化 `AutonomousResearchController` 和合法/非法状态迁移。
- 复用 canonical Mission event、worker lease/fencing、CompletionProof 和 SSE。
- 通过现有 `ChatProvider` 接入一个真实 Provider。
- 生成至少两个实质不同、可证伪的策略候选和 BitPro `BaseStrategy` 代码。
- 复用 Strategy Discovery 的不可变候选、新颖性和重复检测。
- 从 `ResearchOrchestrator` 抽取单候选 BitPro 实验执行器。
- 调用真实 BitPro health、data、strategy validate/create、backtest 和 result。
- 自动调用 `UnifiedStrategyValidationService`。
- 根据确定性失败证据生成下一候选，直到通过或预算耗尽。
- 从用户任务开始时创建的 Paper 预授权派生 candidate-bound 窄授权。
- 复用 Paper Incubation 的 configure/start/observe、Approval、DispatchIntent、幂等和 reconciliation。
- 新增单一 API、SSE 和 CLI 产品入口。
- 保留全部失败候选、trial、外部引用、验证 Gate、预算和模型 provenance。

## Out of Scope

- 第二个真实 Provider、自动 Provider 评分或模型路由优化。
- 已有 BitPro 策略优化和 Champion/Challenger。
- StockPro。
- 多标的、多周期和组合搜索。
- 多 Agent ResearchGraph 作为默认执行路径。
- Web 工作台重做。
- RAG、长期 Memory、Skill 自动发布。
- Testnet、Live、订单、资金划转或实盘授权。
- Sprint 132、133、134 的任何实现。
- 删除旧 API、CLI、表或 LangGraph 依赖。

## Safety Boundaries

1. M0 的 `live_allowed` 必须恒为 `false`。
2. 研究 Capability Catalog 不得出现 live、order、transfer 或 account mutation。
3. LLM 只能提出目标解释、候选、代码、实验和失败后的下一假设。
4. LLM 不能修改预算上限、验证 policy、Paper 授权、状态迁移和完成证明。
5. 所有代码先经过 BitPro `strategy_validate_code`，再允许 `strategy_create`。
6. 所有晋级由确定性统一验证服务决定。
7. Paper 只能使用任务创建时由认证用户明确提交的、可撤销、会过期的预授权。
8. 派生 Paper 授权只能收窄父授权并精确绑定 candidate/validation/manifest fingerprint。
9. 所有外部写入使用 content-bound idempotency、write-ahead intent 和 external operation ID。
10. `effect_unknown` 必须先 reconciliation；禁止盲目重发和任务完成。
11. 研究和 Paper worker 物理不持有 Live credential。
12. 报告必须包含 `not_investment_advice` 和 `no_profit_guarantee`。

## Implementation Slices

### Slice 1 — Domain contract and golden test

- Schema、事件、reducer、projection、状态机、非法转移和 CompletionProof。
- Fake Provider + Fake BitPro 端到端黄金测试。
- 单请求到 `paper_observing` 或 `needs_operator`。

### Slice 2 — Goal compiler and structured provider

- M0 默认 Profile。
- 一个真实 `ChatProvider`。
- 严格结构化输出、provenance、预算和错误分类。

### Slice 3 — Candidate generation and registry

- 至少两个实质不同候选。
- Discovery 新颖性、重复检测和不可变登记。
- 新路径不调用固定 `_compile_strategy()`。

### Slice 4 — Real BitPro experiment and validation

- 单候选执行器。
- 真实 BitPro validate/create/backtest/result。
- 自动统一验证和失败诊断。
- 失败后自动进入下一候选。

### Slice 5 — Derived Paper authorization

- `PaperPreauthorizationV1`。
- 确定性派生 candidate-bound Paper mandate。
- configure/start/observe 和 effect reconciliation。

### Slice 6 — Product entry and production canary

- API、SSE、CLI。
- crash/restart/duplicate/timeout/unknown-effect 故障测试。
- 一个真实 Provider + 真实 BitPro 受限 Canary。

每个 Slice 必须是独立的已验证提交。未经当前 Slice 的 Done Means，不进入下一 Slice。

## Done Means

1. 用户只提交一次自然语言目标，不需要调用 mandate/draft/queue/run/promote。
2. 真实 Provider 产生至少两个实质不同候选。
3. 候选代码和回测经真实 BitPro 执行。
4. 每个候选都有不可变 fingerprint、外部引用、指标、Gate 和终态。
5. 失败候选在预算内自动触发下一候选。
6. 通过候选只有在有效 Paper 预授权内才进入 `paper_observing`。
7. 无候选通过时进入 `needs_operator`，显示失败证据、最佳候选和“继续”选项。
8. “继续”追加版本化预算并从原 Mission 恢复，不重置历史。
9. worker 重启、重复请求和超时不造成重复策略、回测或 Paper 实例。
10. `effect_unknown` 未对账时不能继续或完成。
11. online projection 与离线 event replay 一致。
12. 所有新接口有认证、幂等、schema、权限和错误路径测试。
13. `./scripts/check.sh` 通过。
14. 生产 Canary 可以诚实结束为 `needs_operator`，但不能使用 fixture、合成结果或伪造成功。
15. Testnet、Live、订单和资金变化为零。

## Verification

实现阶段至少新增并运行：

```bash
uv run pytest tests/test_autonomous_research_domain.py -q
uv run pytest tests/test_autonomous_research_controller.py -q
uv run pytest tests/test_autonomous_research_provider.py -q
uv run pytest tests/test_autonomous_research_bitpro.py -q
uv run pytest tests/test_autonomous_research_paper.py -q
uv run pytest tests/test_autonomous_research_recovery.py -q
uv run pytest tests/test_autonomous_research_acceptance.py -q
./scripts/check.sh
git diff --check
```

生产 Canary 必须保存真实 Provider、BitPro strategy/backtest/result 和 validation 引用。任何来源缺失都保持
`needs_data` 或 `needs_operator`。

## Handoff

本合同完成后的下一优先级是：

1. 用相同控制器分析现有 BitPro Paper 策略。
2. 创建不可变 Challenger。
3. 在相同数据、窗口、成本、regime 和验证 policy 下比较 Baseline 与 Challenger。
4. 只有统计和风险证据同时通过时才宣称优化成功。
5. 稳定后实现 `StockProResearchPlatform` Adapter。

Sprint 132–134 继续保持未激活，除非产品所有者在 M0 和策略优化闭环完成后重新明确批准。
