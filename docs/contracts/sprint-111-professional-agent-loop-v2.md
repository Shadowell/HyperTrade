# Sprint 111 - Professional Agent Loop V2

> 状态：Draft；等待用户确认 Professional Agent Runtime V2 路线后激活。

## Goal

在不替换现有 Task OS、固定 Research Graph 和工具治理的前提下，建立一个可持久化、可验证、
可暂停/恢复/steer、最多有限次数重规划的单 Mission 自主循环，使 HT 能够围绕开放研究目标
连续推进，而不是执行一次固定 Graph 后立即结束。

## In Scope

- strict `AgentMissionV1`、`AgentPlanV2`、`AgentPlanStepV2`、`AgentReplanDecisionV1`、
  `AgentSteeringEventV1` 和 terminal outcome schemas。
- PostgreSQL immutable Mission/Plan version/Step attempt/Steering event persistence 与 Alembic。
- Mission 状态机、optimistic version、预算、deadline、max plan/step/attempt/replan 上限。
- 固定 LangGraph adaptive control topology：plan、select、execute、validate、progress、recover、
  replan、wait_human、finalize。
- 现有 Agent tools 与固定 Research Graph 作为受治理 step executor；不增加工具权限。
- observation validator：schema、source ref、tool policy、expected outcome、unknown 与完成条件。
- replan 触发分类、完整新 Plan、plan diff、DAG/预算/权限验证；旧 Plan 永不覆盖。
- pause/resume/cancel/retry 与新 steer 控制；安全点中断、checkpoint 和 lease recovery。
- REST/SSE、CLI `/missions`、Textual Mission 基础视图；Web 只需计划/步骤/预算/状态投影。
- deterministic scenario、fault injection 和零越权 dispatch 测试。

## Out of Scope

- Sprint 112 Capability Catalog/MCP 动态 discovery 和新工具自动接入。
- Sprint 113 完整 Context Pack、自动压缩、Artifact Index 和新 Memory 算法。
- Sprint 114 动态多 Agent Supervisor；本 Sprint 每步只有一个 executor。
- Sprint 115 代码生成、shell、Docker sandbox、worktree 或 BitPro 策略导入。
- 任意 paper/live/order/capital 权限变化、自动 approval 或自动后台启用。
- 无限循环、模型自定义预算、private chain-of-thought persistence。
- 迁移或删除现有 AgentTask/ResearchGraph API。

## Technical Plan

1. Pydantic contracts 使用 `extra=forbid`；Mission success criteria 必须是可验证 predicate，不接受
   “结果很好”等自由文本作为唯一完成条件。
2. Alembic `0023` 拟新增 `agent_missions`、`agent_plan_versions`、`agent_step_attempts`、
   `agent_steering_events`。Plan version 和 attempts append-only，Mission row 只保存 active pointer。
3. Mission version 用 compare-and-swap 更新；worker lease 与用户 control 冲突时 control 优先，
   worker 在下一个 pre/post-dispatch safe point 停止。
4. 默认上限：3 plan versions、12 steps/version、2 attempts/step、4 model calls/step；所有调用
   复用现有 atomic budget reservation，模型不能返回更高数值。
5. Planner 只可引用现有 ToolRegistry capability 或 `research_graph` executor；未知名称、写权限
   不匹配、循环依赖、孤立依赖和不可验证 completion check 均拒绝激活。
6. Adaptive topology 固定在代码中；数据库 Plan 决定哪个 step 可执行，不动态编译任意 Python
   节点。每个节点写 Task/Mission event 和 bounded checkpoint。
7. `StepObservationV2` 保存 status、structured result summary、source refs、artifact refs、unknowns、
   error category 和 usage，不保存 prompt、raw provider output 或 private reasoning。
8. recover 只处理同计划 transport/rate/temporary source 错误；schema repair 最多一次；关键假设
   失效、用户 steer 或 capability 永久不可用才进入 replan。
9. Replanner 生成完整新 Plan、parent version 和 diff。Validator 再检查目标保持、用户约束、
   DAG、权限、预算和剩余完成路径；失败则 `waiting_input` 或 `failed`，不自循环。
10. completion validator 以 Step observations/Evidence/Artifact refs 评估 success criteria；模型的
    `completed=true` 仅是候选意见，不能直接终结 Mission。
11. steer 记录用户 delta、reason 和 actor；运行中 Mission 进入 `replanning`，paused Mission 保持
    paused 并在 resume 后应用；历史 objective/plan 不被覆盖。
12. API 提供 create/list/get、plan versions/diff、event cursor/SSE、control 和 steer；CLI/TUI/Web
    不在客户端重建状态机。
13. feature flags 默认关闭；本地和生产 smoke 仅运行只读、零交易权限、严格预算 Mission。

## Done Means

- 一个开放目标可以形成严格 Plan，逐步执行现有只读工具/Research Graph，并基于 observation
  自动 continue、recover、replan、wait_human 或 finalize。
- Mission/Plan/Step/Attempt/Event 跨 API 重启保持一致；过期 lease 从最后完整 checkpoint 恢复，
  不重复已提交的有副作用步骤。
- 每次 replan 都有 immutable parent/diff/trigger；超过上限明确 `budget_exhausted` 或
  `waiting_input`，不存在无限循环。
- pause/cancel/steer 在安全点生效；steer 生成新 Plan version，不覆盖历史。
- success criteria 未满足时不能 completed；source/tool unknown 不会被模型文本掩盖。
- Planner/Replanner 不能引用未注册工具、扩大权限/预算或绕过 approval。
- REST/SSE、CLI、Textual、Web 显示同一 Mission/Plan/Step/Event 投影。
- 现有 AgentTask、ResearchGraph、paper/live/order/capital tests 无回归。
- 全仓检查、PostgreSQL migration 往返和生产 flag-off/只读 smoke 通过。

## Verification

```bash
uv run pytest tests/test_agent_missions.py tests/test_adaptive_agent_loop.py -q
uv run pytest tests/test_agent_tasks.py tests/test_research_graph.py tests/test_tui_app.py -q
uv run alembic upgrade head
uv run alembic downgrade 0022_shadow_portfolios
uv run alembic upgrade head
./scripts/check.sh
```

Required deterministic scenarios:

- 正常三步 Mission 完成；completion evidence 缺失时拒绝 completed。
- 第一步 temporary timeout 同计划恢复；schema invalid 只 repair 一次。
- capability 永久不可用触发一次 replan，并以替代只读路径完成。
- 实验否定关键假设后 Plan V2 删除无效步骤、增加验证步骤，Plan V1 保持不变。
- 用户 steer 修改 symbol/timeframe 后生成 Plan Vn+1，并保留旧目标/事件。
- pause/cancel 在 pre/post-dispatch safe point 生效；worker lease 过期从 checkpoint 恢复。
- 循环 DAG、未知工具、预算扩大、越权写工具、超过 plan/attempt 上限全部失败关闭。
- 前后比较 PaperPromotion、PaperReviewRequest、paper order、live intent 和 capital 状态不变。

## Handoff

- Gate I 通过后才创建/激活 Sprint 112 focused contract。
- Sprint 112 只能增强 capability/observation contract，不能放宽 Sprint 111 的 Mission 预算、
  plan validation、approval 或终止门禁。

## Assumptions To Review

- 首版默认限制是否采用 3 plan versions、12 steps/version、2 attempts/step、4 model calls/step。
- Web 首版是否只做只读 Mission 计划树，把完整 steer/control 优先放在 CLI/Textual。
- 生产 canary 是否只允许 market/RAG/Memory/BitPro read 和固定 Research Graph。
