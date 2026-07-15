# Sprint 111 - Professional Agent Runtime Foundation

> 状态：Completed；2026-07-15 通过 Gate I、本地全仓验收与生产 PostgreSQL 验证。

## Goal

建立新的现代化 Agent Runtime 核心和第一条端到端 Mission 垂直切片。现有 AgentKernel、Task
OS 和固定 Research Graph 不是必须保留的内部合同；先完成 keep/rewrite/delete 审计，再用
模块化、async-native、事件驱动的 Mission/Plan/Step 核心替代一个生产入口，验收后删除对应
旧写路径，避免在历史实现外继续包兼容层。

## In Scope

- 现有 agent/runtime 组件 architecture fitness audit：keep/rewrite/delete、依赖图、调用者、
  数据迁移与删除清单。
- 新 `hypertrade/runtime/` 包：`domain`、`application`、`ports`、`adapters`、`api`；domain 不依赖
  FastAPI、SQLAlchemy、provider、MCP 或交易服务 concrete class。
- strict `AgentMissionV1`、`AgentPlanV2`、`AgentPlanStepV2`、`AgentReplanDecisionV1`、
  `AgentSteeringEventV1` 和 terminal outcome schemas。
- async SQLAlchemy/PostgreSQL immutable Mission event、Plan version、Step attempt、Steering event
  和 read projection persistence 与 Alembic；新 Mission 不双写旧 Task/Run 表。
- Mission 状态机、optimistic version、预算、deadline、max plan/step/attempt/replan 上限。
- 固定 LangGraph adaptive control topology：plan、select、execute、validate、progress、recover、
  replan、wait_human、finalize。
- 新 model/tool/event store/clock port protocols；现有 Provider Router、ToolRegistry 和必要领域
  服务只通过 adapter 接入，不允许新核心反向 import 旧 AgentKernel。
- observation validator：schema、source ref、tool policy、expected outcome、unknown 与完成条件。
- replan 触发分类、完整新 Plan、plan diff、DAG/预算/权限验证；旧 Plan 永不覆盖。
- pause/resume/cancel/retry 与新 steer 控制；安全点中断、checkpoint 和 lease recovery。
- OpenTelemetry mission/plan/step/model/tool spans 与 bounded domain event semantic schema。
- REST/SSE、CLI `/missions`、Textual/Web Mission 基础视图；一个只读 `ask` canary 入口切到新
  Runtime。验收后删除该入口对应的旧 AgentKernel/TaskExecutor 调用分支。
- deterministic scenario、fault injection 和零越权 dispatch 测试。

## Out of Scope

- Sprint 112 Capability Catalog/MCP 动态 discovery 和新工具自动接入。
- Sprint 113 完整 Context Pack、自动压缩、Artifact Index 和新 Memory 算法。
- Sprint 114 动态多 Agent Supervisor；本 Sprint 每步只有一个 executor。
- Sprint 115 代码生成、shell、Docker sandbox、worktree 或 BitPro 策略导入。
- 任意 paper/live/order/capital 权限变化、自动 approval 或自动后台启用。
- 无限循环、模型自定义预算、private chain-of-thought persistence。
- 全量迁移所有历史 Task/Run/ResearchGraph；本 Sprint 只切换一个垂直入口，历史查询只读。
- 为“以防万一”保留永久双写、永久 runtime fallback 或新增 `compat_v2` 业务分支。

## Technical Plan

1. Pydantic contracts 使用 `extra=forbid`；Mission success criteria 必须是可验证 predicate，不接受
   “结果很好”等自由文本作为唯一完成条件。
2. 创建 `hypertrade/runtime` 架构 fitness tests：domain import boundary、dependency direction、
   禁止 legacy AgentKernel import、无交易 adapter concrete import；为被替代路径设 deletion list。
3. Alembic `0023` 拟新增 `agent_missions`、`agent_mission_events`、`agent_plan_versions`、
   `agent_step_attempts`、`agent_steering_events`。Plan/attempt/event append-only，projection 可重建。
4. 新 store 使用 SQLAlchemy AsyncSession/psycopg async；worker 使用 AnyIO cancel scope、TaskGroup、
   DB lease/outbox，不调用同步 ORM 后再用无界 thread wrapper 模拟 async。
5. Mission version 用 compare-and-swap 更新；worker lease 与用户 control 冲突时 control 优先，
   worker 在下一个 pre/post-dispatch safe point 停止。
6. 默认上限：3 plan versions、12 steps/version、2 attempts/step、4 model calls/step；所有调用
   复用现有 atomic budget reservation，模型不能返回更高数值。
7. Planner 只可引用受审核 tool port capability；未知名称、写权限
   不匹配、循环依赖、孤立依赖和不可验证 completion check 均拒绝激活。
8. Adaptive topology 固定在新 runtime adapter 中；数据库 Plan 决定哪个 step 可执行，不动态
   编译任意 Python 节点。每个节点只写新 Mission event 和 bounded checkpoint。
9. `StepObservationV2` 保存 status、structured result summary、source refs、artifact refs、unknowns、
   error category 和 usage，不保存 prompt、raw provider output 或 private reasoning。
10. recover 只处理同计划 transport/rate/temporary source 错误；schema repair 最多一次；关键假设
   失效、用户 steer 或 capability 永久不可用才进入 replan。
11. Replanner 生成完整新 Plan、parent version 和 diff。Validator 再检查目标保持、用户约束、
   DAG、权限、预算和剩余完成路径；失败则 `waiting_input` 或 `failed`，不自循环。
12. completion validator 以 Step observations/Evidence/Artifact refs 评估 success criteria；模型的
    `completed=true` 仅是候选意见，不能直接终结 Mission。
13. steer 记录用户 delta、reason 和 actor；运行中 Mission 进入 `replanning`，paused Mission 保持
    paused 并在 resume 后应用；历史 objective/plan 不被覆盖。
14. API 提供 create/list/get、plan versions/diff、event cursor/SSE、control 和 steer；CLI/TUI/Web
    不在客户端重建状态机。
15. canary 前后对比新旧输出合同，但不双写状态。通过后将目标入口默认指向新 Runtime，删除旧
    调用分支和无调用者 helper；rollback 通过部署版本完成，不在代码中永久保留双 Runtime。
16. feature flags 默认关闭；本地和生产 smoke 仅运行只读、零交易权限、严格预算 Mission。

## Done Means

- 一个开放目标可以形成严格 Plan，逐步执行现有只读工具/Research Graph，并基于 observation
  自动 continue、recover、replan、wait_human 或 finalize。
- Mission/Plan/Step/Attempt/Event 跨 API 重启保持一致；过期 lease 从最后完整 checkpoint 恢复，
  不重复已提交的有副作用步骤。
- 新 Runtime domain/application 依赖方向通过静态 fitness tests；Mission store 可从 event log
  重建 projection，且新 Mission 从未写入旧 Task/Run 表。
- 每次 replan 都有 immutable parent/diff/trigger；超过上限明确 `budget_exhausted` 或
  `waiting_input`，不存在无限循环。
- pause/cancel/steer 在安全点生效；steer 生成新 Plan version，不覆盖历史。
- success criteria 未满足时不能 completed；source/tool unknown 不会被模型文本掩盖。
- Planner/Replanner 不能引用未注册工具、扩大权限/预算或绕过 approval。
- REST/SSE、CLI、Textual、Web 显示同一 Mission/Plan/Step/Event 投影。
- canary ask 入口只调用新 Runtime；替代范围内旧 AgentKernel/TaskExecutor 分支、重复 adapter
  和无调用者代码已删除，有明确负代码/删除清单。
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
- 验证新 Mission 表有写入而旧 AgentTask/AgentRun 表计数不变；import graph 无反向依赖。

## Handoff

- Gate I 通过后才创建/激活 Sprint 112 focused contract。
- Sprint 112 只能增强 capability/observation contract，不能放宽 Sprint 111 的 Mission 预算、
  plan validation、approval 或终止门禁。

## Implementation Record

- 新核心：`backend/src/hypertrade/runtime`，domain/application/ports/adapters 单向依赖。
- 数据迁移：`0023_agent_missions`；生产 `0023 -> 0022 -> 0023` 通过。
- API：Mission create/list/get/run/control/steer/cursor events/SSE；运行 flag 默认关闭。
- 验收：`./scripts/check.sh` 通过 547 个 Python 测试和 9 个前端测试；QA 见
  `docs/qa/sprint-111-professional-agent-runtime-foundation.md`。
- 生产：SHA `6435110`、workflow `29425203712`、只读 canary 完成且旧 Task/Run 计数不变。

## Assumptions To Review

- 首版默认限制是否采用 3 plan versions、12 steps/version、2 attempts/step、4 model calls/step。
- 默认允许破坏内部 Python API；历史 REST 读取保留一个明确 deprecation window，不保留旧写入。
- Web 首版做 Mission 计划树与基本 control/steer，不以旧 Harness 组件结构限制新页面。
- 生产 canary 是否只允许 market/RAG/Memory/BitPro read ports，不启用任何写 capability。
