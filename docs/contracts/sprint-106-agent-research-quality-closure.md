# Sprint 106 - Agent Research Quality Closure

> 状态：Active；2026-07-15 经操作员明确批准开始实施。

## Goal

修正 provider-backed Agent 评测的 cohort 和 denominator 语义，并通过结构化意图、
候选工具权限求交和一次受限 repair，使普通工具任务与 Research Graph 任务分别达到可验证的
路由、来源、状态和安全门槛。在门槛通过前，不扩大生产后台研究吞吐量。

## In Scope

- `chat_answer`、`tool_required`、`research_graph`、`safety` 固定评测 cohort。
- `ResearchIntentV2`、`ToolPlanV2` 和版本化 metric contract。
- ToolRegistry/connector/role/mandate/policy 求交后的 bounded candidate tool set。
- schema/source/policy 失败时最多一次 planner repair，随后显式失败关闭。
- Task terminal status、Research Graph critical sequence 和 source-bound answer 评分。
- deterministic gate、隔离 provider 双运行 baseline、模型诊断矩阵。
- API/CLI/TUI/Web 只读质量摘要和失败分类投影。

## Out of Scope

- StrategyCard V2 或研究漏斗实现；它属于 Sprint 107。
- 生产 background trigger 启用或配额提升。
- Provider fine-tuning、训练新模型或让模型修改自身 prompt/Skill。
- 以收益、回测排名或 paper PnL 评价 Agent 质量。
- 任何 BitPro/paper/testnet/live mutation 权限变化。
- 恢复 keyword-driven kernel 业务路由。

## Technical Plan

1. 审计 `research_os_golden_v1` 每个 case 的 execution mode、required/forbidden tools、
   expected source、terminal status 和 graph applicability。
2. 发布新的 versioned eval manifest；case cohort 与 denominator 成为合约字段，缺失即失败。
3. 让 baseline runner 分 cohort 输出 accuracy/F1/coverage/status/sequence，不再把普通 chat
   case 计入 Research Graph sequence。
4. 定义 `ResearchIntentV2`：intent family、execution mode、required source class、read/write
   boundary、unknown/data freshness requirements。
5. 定义 `ToolPlanV2`：selected tools、source rationale code、required args presence、policy
   projection；不持久化自然语言 reasoning。
6. 在调用 planner 前，通过 ToolRegistry、connector health、role、mandate、evaluation mode
   和 RiskGovernancePolicy 生成 bounded candidate set。
7. 对无效 schema、缺 required source 或 policy-forbidden selection 执行最多一次 repair；
   repair 使用相同或更窄候选集，不能扩大权限。
8. 增加 route/source/task/graph/safety 的确定性回归、property tests 和 fault injection。
9. 扩展隔离 runner 连续运行两次，并输出 prompt-free comparison artifact。
10. 在现有操作界面投影 aggregate 指标、cohort、失败分类、baseline/version；客户端不实现
    评分逻辑。

## Deliverables

- versioned quality/eval schemas、case manifest 和 aggregate scorer；
- constrained planner candidate-set 与 single-repair orchestration；
- deterministic/isolated tests、privacy checks 和 comparison artifact；
- read-only API/CLI/TUI/Web quality projection；
- Sprint 技术记录、架构、README、spec/progress 和 QA 更新。

## Done Means

- deterministic suite 100% 通过；
- safety cohort 的危险工具 dispatch 为 0，拒绝证据覆盖率为 100%；
- tool-required cohort 的 required tool/source route accuracy ≥ 85%；
- source-bound answer coverage ≥ 95%；
- research-graph cohort 的关键节点顺序/完成率 ≥ 95%；
- terminal Task status match ≥ 95%；
- 两次完整隔离 provider baseline 都达到门槛，且失败 case 未从 denominator 删除；
- aggregate artifact 不含 prompt、tool args、raw output、credentials 或 private reasoning；
- production trigger 仍保持禁用，paper/live/资金权限无变化。

## Verification

```bash
uv run pytest tests/test_agent_research_quality_v2.py -q
uv run pytest tests/test_agent_planner_routing_v2.py tests/test_research_os_eval_v2.py -q
uv run pytest tests/test_research_graph_roles.py tests/test_agent_task_execution.py -q
./scripts/check.sh
HYPERTRADE_EVAL_TARGET=isolated \
HYPERTRADE_EVAL_BASE_URL=http://127.0.0.1:4334 \
./scripts/run_agent_eval_baseline.sh
```

Manual/QA：

- 检查普通 chat case 不再影响 graph sequence denominator。
- 构造 provider 选择错误来源、未知工具、write tool 和无效 schema，确认只 repair 一次。
- 比较两次 baseline 的固定 case 数、cohort denominator、失败分类、Token 和耗时。
- 确认隔离 eval 容器没有生产数据库、BitPro 数据挂载或 mutation dispatch。

## Risks / Notes

- 当前 0.0833 聚合 accuracy 不能直接与新 cohort 指标比较；必须同时保存旧/新定义说明，
  禁止宣称无口径变化的数量级提升。
- 候选工具集过窄会造成 false negative；所有过滤必须有 policy/source reason code。
- 单次 repair 可能提高 Token/延迟，必须报告但不能增加第二次隐式重试。
- 若默认 provider 无法连续达到门槛，Sprint 保持未完成；不能通过降低安全或来源门槛放行。

## Handoff

- Gate E 通过后创建并激活 Sprint 107 合同，实施 StrategyCard V2、稳定 lineage/version、
  incomplete projection 和 research funnel。
- Gate E 未通过时继续修复 Sprint 106，不启用后台研究或提前开发 Shadow Portfolio。

## Implementation Record

- 2026-07-15：完成 V2 manifest、cohort scorer、structured intent/plan、bounded candidate
  intersection、single repair、double-run gate 及 API/CLI/TUI/Web 只读投影。
- 本地 focused tests 及 `./scripts/check.sh` 已通过：frontend lint/9 tests/build、Ruff、
  mypy（142 source files）和 486 Python tests。
- 首次隔离 baseline 在第 2 个 case 因 Codex `ReadTimeout` 返回 503；采集器未删除失败
  case。后续修复把 authored eval 候选集收窄为 0/唯一 required tool，并将 case timeout
  调整为 30–600 秒边界内可配置（默认 300 秒）。
- 第二次隔离运行暴露 V1 系统故障场景文本与其 required tool 语义不一致。V2 manifest
  现将确定性 `prompt` 和模型可执行 `provider_prompt` 分离；采集器仅发送后者，两者映射
  到同一 authored intent，轨迹不保留任一提示词。49 个定向回归测试通过。
- 首个完整 26/26 provider run 的 tool/source route、Task status 与 6/6 safety denial 通过，
  unsafe dispatch 为 0；门禁仍因 citation 0/1、Graph critical sequence 0.75 失败。根因是
  `report_json.graph` 在 `final_report` 前取快照，以及 market candle 未生成 bounded source
  citation。第二轮 case 2 同时遇到上游 520。修复将 terminal graph 快照后移、为可用 OKX
  candle 生成无 raw payload 的来源引用，并只在任何 tool dispatch 前重试一次瞬时 Codex
  429/5xx/transport failure。
- 隔离 provider 双运行和生产 SHA/health/log 验收尚未执行，因此 Sprint 状态保持 Active。
