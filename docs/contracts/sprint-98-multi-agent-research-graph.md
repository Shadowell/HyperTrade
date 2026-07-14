# Sprint 98 - Multi-Agent Research Graph V1

> 状态：Completed；2026-07-14 本地验收与生产部署通过。

## Goal

使用 LangGraph 和 HyperTrade 的 Task/Evidence/Tool Policy 构建第一个受预算、可恢复、
可评测的专业研究角色图，而不是让一个 Agent 临时扮演全部研究职能。

## In Scope

- 固定研究 DAG：preflight、data quality、market regime、technical、derivatives、event、
  synthesis、bull/bear、strategy engineer、BitPro validation、validation reviewer、risk committee。
- role definition、prompt version、input/output schema 和 tool allowlist。
- 根据 mandate、capabilities 和预算选择可选节点。
- 独立只读分支有限并发、per-role/global budget 和 node checkpoint。
- provider/schema/timeout 重试与结构化失败。
- 图、节点、role、tool policy 和 evidence 的 API/trace projection。

## Out of Scope

- 动态生成任意 Agent、任意 shell/filesystem/network tool。
- role 直接创建 BitPro strategy、启动 paper、操作 live/testnet。
- 自动 paper/live 晋升和自动资金分配。
- 无限制并行和无预算辩论。

## Deliverables

- `ResearchGraphRuntime`、`RoleExecutor`、`ResearchGraphSelector`、`TaskBudgetGuard`。
- 版本化 role definitions/prompts/schemas。
- LangGraph topology 和 HyperTrade checkpoint adapter。
- role tool-policy matrix、节点事件、报告与测试。

## Implementation Plan

1. 固定 GraphState 和节点 input/output refs，禁止把 raw credential/行情放入状态。
2. 定义必需节点、可选节点、条件边和失败/unknown 分支。
3. 创建 role catalog；每个 role 固定 prompt hash、schema、tool allowlist 和预算默认值。
4. 实现 ToolRegistry、mandate、role、execution mode、operator policy 的权限求交。
5. 实现 RoleExecutor：provider 调用、一次 schema repair、EvidenceService 写入。
6. 实现有限并发和 provider/BitPro semaphore；默认最大 2 个只读 role 并行。
7. 接入 Task Node/Checkpoint/Event；失败只重试当前节点。
8. 将 Strategy Engineer 输出交给既有 ResearchOrchestrator，而非直接 MCP 写入。
9. 实现 graph/task/evidence projection 和 CLI/API 查询。
10. 完成 topology、role、budget、安全、故障和确定性测试。

## Done Means

- 每个节点都有可查询状态、版本、预算、工具策略、evidence ids 和 checkpoint。
- 缺衍生品/事件数据时输出 data gap，不编造数据，也不阻塞可继续分支。
- 必需节点不可被 planner/prompt 跳过。
- 任一 role 选择 paper/live write tool 都在 dispatch 前被拒绝。
- provider/worker 失败后只重跑失败节点，成功 evidence 不重复。

## Verification

```bash
uv run pytest tests/test_research_graph.py tests/test_research_roles.py -q
uv run pytest tests/test_agent_tool_policy.py tests/test_research_orchestrator.py -q
./scripts/check.sh
```

Manual/QA：

- 创建一个完整 mandate，观察每个 role/node/evidence 的顺序和预算。
- 禁用事件或衍生品 connector，确认图以 data gap 继续且置信度下降。
- 注入危险 prompt，确认没有 paper/live dispatch。

## Risks / Notes

- LangGraph 负责 topology/execution，PostgreSQL Task/Node/Event 才是业务事实源。
- 多角色意见不是多数投票；最终 gate 依赖结构化 evidence 和确定性 validation。
- 并发必须受 provider rate limit、BitPro capacity 和 mandate budget 限制。

## Handoff

- 下一步：Sprint 99 为 Graph 产生的每次策略实验建立不可变指纹和复现账本。

## Implementation Record

- 固定 13-role LangGraph、版本化 prompts/schemas、role selector 和结构化 provider
  adapter 已实现；必需角色不能被 planner 跳过，可选角色缺能力时写 data gap。
- ToolRegistry/operator/role 三方权限求交、危险参数检查、dispatch 前拒绝和
  provider/BitPro/read semaphore 已实现；没有 role 具备 paper/live write 权限。
- 全局预算原子预留/结算、node attempts、checkpoint、pause/cancel safe points、失败节点
  retry/replay、worker dispatch 和 Task/Event projection 已实现。
- StrategySpec 通过既有 ResearchProgram/ResearchOrchestrator 队列交接；研究图不直接
  创建 BitPro strategy。API 与 CLI 图查询已实现。
- 生产 smoke 暴露并修复了工具计划占位符和 schema repair 后全图终止问题；无效模型
  输出现在 fail-closed 为 Evidence V2 data gap，且 retry 会清空实时错误投影，历史错误
  仍保留在事件流。
