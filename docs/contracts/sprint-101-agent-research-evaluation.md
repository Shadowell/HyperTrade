# Sprint 101 - Agent Research Evaluation

> 状态：Proposed，依赖 Sprint 96–100 和 Sprint 94 隔离评测环境。

## Goal

把 Session/Task 恢复、多 Agent 角色、Evidence、预算、实验复现和鲁棒性门禁纳入
确定性与隔离评测，使“专业 Agent”能力有可重复验收标准。

## In Scope

- 扩展 required `AgentEvalSuite` 和 pytest regression gate。
- 使用 Hypothesis 覆盖 Task/Node 状态机组合。
- authored `research_os_golden_v1` cases 和 sanitized trajectory schema。
- provider/BitPro/worker/SSE fault injection。
- Promptfoo 危险工具/prompt injection checks、Ragas role/tool trajectory score。
- metadata-only Langfuse node spans（继续 opt-in）。

## Out of Scope

- 用 LLM judge 决定是否允许交易。
- 在生产 API 运行 provider-backed adversarial/golden suite。
- 保存或提交生产 prompt、报告、raw tool output 或 credential。
- 使用回测收益作为 Agent eval 总分。

## Deliverables

- Research OS deterministic eval cases、stateful/property tests。
- `research_os_golden_v1` reference 和 isolated runner。
- fault-injection fixtures/adapters 和安全轨迹 projection。
- 恢复、安全、预算、证据和隐私报告指标。
- 更新评测架构文档和 isolated deployment runbook。

## Implementation Plan

1. 定义评测 taxonomy、case schema、通过条件和隐私字段 allowlist。
2. 为 Task 状态机、lease、checkpoint、event cursor 建立 deterministic cases。
3. 为 role selection、tool matrix、Evidence schema 和 budget 建立 cases。
4. 增加 fake provider/BitPro/worker crash/SSE disconnect fault injectors。
5. 加入 Hypothesis state machine，随机生成合法/非法控制序列。
6. 编写至少 24 个 authored Research OS golden cases。
7. 扩展 Promptfoo isolated safety suite，验证 write-like dispatch 为 0。
8. 扩展 Ragas trajectory 以识别 role/node/tool sequence，不评分私有文本。
9. 增加 metadata-only node spans 和本地 exporter failure handling。
10. 在 Sprint 94 isolated target 完成两次可比较 baseline，并记录差异。

## Done Means

- required CI 可以离线验证状态、Evidence、预算和安全合同。
- provider-backed Research OS baseline 只能指向 explicit isolated target。
- worker crash、BitPro timeout、provider schema failure 和 SSE 断线都有恢复评测。
- 所有危险工具尝试在 dispatch 前拒绝，实际 dispatch 数为 0。
- 生成 artifacts 不包含 prompt/report/argument/raw output/credential。

## Verification

```bash
uv run pytest tests/test_agent_research_evals.py tests/test_task_state_machine_properties.py -q
./scripts/run_promptfoo_isolated.sh
./scripts/run_agent_eval_baseline.sh
./scripts/check.sh
```

## Risks / Notes

- Hypothesis 失败示例必须固化为 regression case，避免只依赖随机种子。
- baseline 分数是诊断证据，不能直接授权 paper/live。
- Langfuse exporter 失败不得影响生产 Agent Task。

## Handoff

- 下一步：Sprint 102 在稳定 Task/Event/Eval 合同上构建 TUI。
