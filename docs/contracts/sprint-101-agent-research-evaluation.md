# Sprint 101 - Agent Research Evaluation

> 状态：Completed；2026-07-15 已通过本地、生产与隔离环境验收；
> provider-backed baseline 仅允许指向 Sprint 94 隔离环境。

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

## Implementation Record

- required `AgentEvalSuite` 由 14 条扩展为 38 条，其中
  `research_os_golden_v1` 固定包含 24 条 authored cases。
- Hypothesis 状态机覆盖 Task transition、Node attempt/replay 和 SSE high-water
  cursor；确定性 fault injector 覆盖 Provider、BitPro、Worker 与 SSE。
- Promptfoo 固定为 `0.121.19`，六条攻击在隔离 API 上 6/6 通过，工具调用和
  write dispatch 均为 0。
- Ragas 对两轮各 24 条真实 Provider 轨迹完成评分；工具准确率均为 0.0833，
  node sequence 均为 0，task status match 均为 0.5833。该结果明确证明通用
  Agent 入口尚不能替代专用 Research Graph，不作为 paper/live 授权。
- `agent-eval` 独立 Docker target 固定可选依赖和脚本，生产镜像不携带 Ragas；
  runner 不依赖宿主机 Python/`uv`。
- 最终两轮产物 comparison 为 `stable_or_improved`、0 regression；递归字段扫描
  确认不含 prompt、report、tool args、input/output、credential 或 private reasoning。
- 最终 `./scripts/check.sh` 通过：前端 lint/test/build、Ruff、mypy 与 426 个
  Python tests。部署 workflows `29356068416`、`29356648230`、`29357192814`、
  `29357931595` 均成功。
