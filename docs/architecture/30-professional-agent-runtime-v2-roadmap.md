# 30 Professional Agent Runtime V2 路线图

> 状态：Proposed；等待用户确认后再激活 Sprint 111，当前生产行为和权限不变。

## 1. 目标

在 HyperTrade 内建立一个现代、内聚、可长期维护的专业 Agent Runtime。现有实现不构成必须
兼容的内部标准：只保留已经证明可靠的领域事实、外部合同、安全策略和数据；AgentKernel、
Session/Task OS、固定 Research Graph、客户端与 UI 中不合理的结构允许直接重构、替换和删除。

目标用户只需要描述研究任务，例如：

> 研究 BTC 在不同市场状态下更稳健的策略，使用 BitPro 完成实验与验证；证据不足时继续
> 补充研究，需要写操作时等待人工批准。

系统应能够持续完成：目标澄清、计划版本化、步骤执行、证据验证、失败分类、有界重规划、
多角色协作、上下文压缩、产物交付和人工介入。专业能力指可控、可恢复、可评测和可审计，
不等于承诺稳定盈利，也不允许绕过 paper/live/capital 权限边界。

## 2. 当前能力与真实缺口

| 能力 | 当前事实 | V2 缺口 |
|---|---|---|
| Graph Runtime | LangGraph 固定研究 DAG、条件边、并行只读角色 | 不能为开放目标动态形成版本化步骤计划 |
| Task OS | Session、Task、lease、checkpoint、pause/retry/cancel | checkpoint 主要保存运行位置，不保存完整 Mission/Plan 演进 |
| Planner | 结构化 Intent、候选工具约束、一次 schema/route repair | 没有基于 observation 的多轮有界 replan |
| Reflection | AgentKernel 有 `reflect` trace | 主要是结果摘要，不是可验证的继续/重规划/终止决策 |
| Tools | ToolRegistry、MCP/BitPro adapter、权限策略 | 能力目录偏静态，错误语义和恢复策略未统一 |
| Context | Session context policy、Memory、RAG、Evidence | 缺少按步骤编译、可追溯、受 Token 预算约束的 Context Pack |
| Multi-Agent | 固定角色目录、并发预算、角色级工具白名单 | 缺少 Supervisor 动态分工、handoff、合并和冲突裁决 |
| Artifacts | Evidence/Manifest/Experiment/BitPro refs | 缺少面向一个 Mission 的统一产物索引、版本和 diff |
| UX | CLI、Textual、Web、SSE、控制事件 | 缺少 Mission 计划树、steer、replan diff 和恢复解释 |
| Evaluation | Golden V2、provider baseline、Ragas、安全门禁 | 缺少跨长任务的目标完成、恢复、上下文和协作基准 |
| Sandbox | Skill 隔离评测、工具审批、执行风险门禁 | 缺少策略代码研发专用的短生命周期隔离工作区 |

结论：当前 HT 是治理良好的领域工作流系统，但 Agent 核心不应继续通过兼容层叠加功能。
Professional Runtime 采用新的内聚核心和分阶段垂直切换；每完成一个替代切片就删除对应旧
路径，避免长期双运行时、双状态机和 `legacy/compat/v2` 分支成为新的历史包袱。

## 2.1 保留、重构与删除原则

| 分类 | 对象 | 决策 |
|---|---|---|
| 保留 | Evidence、Manifest、StrategyCard、Experiment、审批/风险事实 | 已验证的领域事实与审计记录 |
| 保留 | MCP、BitPro/OKX 外部稳定合同 | 作为 ports/adapters 重新接入，不复制业务逻辑 |
| 保留 | ToolPolicy、Approval、idempotency、安全测试 | 权限不可因重构弱化 |
| 可重构 | PostgreSQL schema、Task/Checkpoint/Event 模型 | 允许迁移到统一 Mission event model |
| 可替换 | AgentKernel、Planner、TaskExecutor、ResearchGraph 顶层编排 | 新 Runtime 达到切片门禁后删除旧调用路径 |
| 可替换 | CLI/Web/TUI client projection | 统一 Mission API，不维持永久双接口 |
| 删除 | 重复状态、固定流程兼容分支、失去调用者的 helper/adapter | 每个 Sprint 设置 deletion budget |
| 只读归档 | 历史 Run/Task/Trace | 保留审计查询，不允许新 Runtime 双写旧表 |

判断标准不是“以前投入很多”，而是正确性、可测试性、内聚性、可观测性、安全边界和未来
维护成本。没有事实证明有价值的旧实现，不作为新架构约束。

## 3. 目标用户工作流

```mermaid
flowchart TD
  GOAL["用户提交开放研究目标"] --> MISSION["Durable AgentMission"]
  MISSION --> PLAN["Plan V1 · 有界步骤和完成条件"]
  PLAN --> STEP["领取下一可执行步骤"]
  STEP --> CONTEXT["编译 Context Pack"]
  CONTEXT --> TOOLS["模型或工具执行"]
  TOOLS --> VALIDATE["结构、来源、权限和结果验证"]
  VALIDATE -->|"通过"| COMMIT["提交 Observation / Artifact refs"]
  VALIDATE -->|"可恢复失败"| RECOVER["同计划恢复策略"]
  VALIDATE -->|"计划假设失效"| REPLAN["生成 Plan Vn+1 diff"]
  RECOVER --> STEP
  REPLAN --> PLAN
  COMMIT --> DECIDE{"Mission 完成条件满足?"}
  DECIDE -->|"否"| STEP
  DECIDE -->|"需要授权"| APPROVAL["人工批准或 steer"]
  APPROVAL --> PLAN
  DECIDE -->|"是"| REPORT["证据绑定的最终交付"]
```

用户可随时查看计划、当前步骤、预算、证据和阻塞原因；pause/cancel 立即记录控制意图，
运行时在安全点停止。用户 steer 生成新事件和新 Plan version，不覆盖历史计划。

## 4. 核心架构原则

1. 采用模块化单体与 ports-and-adapters：`runtime/domain` 不依赖 FastAPI、SQLAlchemy、具体
   provider、MCP 或交易服务；application 只依赖 port protocol，adapter 承担基础设施转换。
2. PostgreSQL Mission event log 与 projection 是新 Runtime 的 canonical source；LangGraph
   只负责执行状态图，不成为业务事实源。
3. 不保存模型 private chain-of-thought。只保存结构化 reason code、短 decision summary、
   source refs、tool observations 和状态转换依据。
4. 每次模型/工具调用前原子预留 Token、时间、工具调用和并发预算；失败也计入用量。
5. Replan 不是无限重试：默认最多 3 个 Plan versions、每版最多 12 步、每步最多 2 次
   attempt；合同可收紧但不能由模型扩大。
6. 写工具、外部副作用、paper/live/capital 操作继续由既有 ToolPolicy/Approval/Risk gate 决定；
   Planner 和 Supervisor 不能授予权限。
7. Tool、Memory、RAG、Evidence 和 Artifact 输入均使用版本/内容哈希；不可复现或过期来源
   显式变成 unknown。
8. 只读、独立且预算允许的步骤可并行；写步骤、共享状态步骤和人审步骤串行。
9. 结束必须基于结构化完成条件和验证结果，不以模型声称“完成”为准。
10. 固定 Research Graph 只作为迁移期 adapter；动态团队达到能力/安全等价后删除其顶层编排，
    可复用的角色、schema 和工具下沉到新 ports，不保留永久 legacy runtime。
11. 不引入 Celery/Redis/Temporal 第二套任务真相源；新 Runtime 使用 async SQLAlchemy/
    psycopg、PostgreSQL lease/outbox 和 AnyIO structured concurrency。达到跨服务规模瓶颈后
    再以数据决定是否采用 Temporal。
12. 不双写新旧状态。迁移使用一次性 backfill 或只读历史 adapter；新 Mission 只写新模型。
13. 每个 Sprint 同时交付新增能力、迁移切片和旧代码删除清单，禁止只增不减。

## 5. 目标组件

```mermaid
flowchart LR
  UI["CLI / Textual / Web / REST-SSE"] --> CONTROL["Mission Control API"]
  CONTROL --> STORE["PostgreSQL Mission Store"]
  WORKER["AnyIO Mission Worker"] --> STORE
  WORKER --> LOOP["Adaptive Agent Loop"]
  LOOP --> PLANNER["Structured Planner / Replanner"]
  LOOP --> CONTEXT["Context Compiler"]
  LOOP --> EXECUTOR["Governed Step Executor"]
  LOOP --> VALIDATOR["Observation Validator"]
  EXECUTOR --> REGISTRY["Capability + Tool Registry"]
  REGISTRY --> MCP["MCP / BitPro / Read APIs"]
  REGISTRY --> GRAPH["Migration-only Research Graph Adapter"]
  CONTEXT --> MEMORY["Memory / RAG / Evidence"]
  VALIDATOR --> ARTIFACT["Mission Artifact Index"]
  LOOP --> TEAM["Bounded Multi-Agent Supervisor"]
  TEAM --> EXECUTOR
  TELEMETRY["Trace / Metrics / Eval"] --> STORE
  LOOP --> TELEMETRY
```

### 5.1 Mission Control

新增 `AgentMissionV1`：

- `mission_id`、`session_id`、`objective`、`success_criteria`、`constraints`；
- `status`、`active_plan_version`、`current_step_id`；
- `budget`/`usage`、deadline、max plan versions/steps/attempts；
- `permission_profile_ref`、`context_policy_ref`、`created_by`；
- terminal result、unknowns、artifact manifest ref。

Mission 状态机建议为：

```text
draft -> planning -> running -> waiting_approval | waiting_input | retry_wait
running -> replanning -> running
* -> paused | canceled
running -> completed | failed | budget_exhausted
```

所有状态转换写 append-only event，并使用 optimistic version 防止 worker/control 并发覆盖。

### 5.2 Plan 与 Step

`AgentPlanV2` 为不可变版本：

- plan version、parent version、trigger observation/event；
- goal interpretation、assumptions、completion checks；
- 有向无环 step graph、依赖、read/write classification；
- 每步输入 contract、allowed capabilities、expected output、validation、budget；
- plan diff：kept/added/removed/replaced steps 和原因码。

`AgentStepV2` 不允许模型直接写任意工具名，只引用当前 Capability Catalog 中的稳定
capability id。Step attempt 单独记录，retry 不覆盖前一次 observation。

### 5.3 Adaptive Agent Loop

使用 LangGraph `StateGraph` 表达以下稳定控制拓扑，但放在新 `hypertrade/runtime` 内，不继续
扩展当前 AgentKernel 单体：

```text
load_mission -> compile_context -> select_next_step -> approval_check
-> execute_step -> validate_observation -> progress_check
-> continue | recover | replan | wait_human | finalize
```

动态性来自数据库中的 Plan graph，不通过运行时生成新的 Python/LangGraph 节点。这样可继续
使用固定安全点、Task control、checkpoint 和评测，同时让步骤计划动态变化。

### 5.4 Replan 策略

只有以下事件允许触发 replan：

- capability/source 在 pre-dispatch 后确认不可用；
- observation 违反 expected schema/source/quality；
- 实验否定关键假设；
- 用户 steer 改变目标、约束或优先级；
- 剩余预算不足以执行当前计划但仍可形成降级交付；
- 依赖 step 失败且存在合同允许的替代路径。

同参数 transport retry、schema repair 和 replan 分开计数。Replanner 输出完整新 Plan 与 diff，
Validator 检查 DAG、预算、工具权限、循环依赖和完成条件后才可激活。

### 5.5 Context Compiler

不把完整聊天、工具原始输出和全部 Memory 拼进 prompt。每个 Step 编译
`AgentContextPackV1`：

- mission objective/constraints/success checks；
- active plan 和当前 step contract；
- dependency observations 的 bounded summary/ref/hash；
- 相关 Evidence、Memory、RAG citation 和 Artifact refs；
- 当前 capability schema/policy hash；
- remaining budget、已知 unknowns、用户最新 steer；
- context manifest、token estimate 和截断记录。

选择顺序：安全/权限约束 > 当前 Step 必需事实 > 依赖结果 > 已批准 Evidence > Memory/RAG
补充背景。超预算时先删除低相关背景，再压缩依赖摘要；不能删除权限、success criteria、
source refs 或 unknowns。

### 5.6 Capability 与 Tool Runtime

Capability Catalog 在静态 ToolRegistry 之上增加版本化投影：

- capability id/version、provider/connector、input/output JSON Schema；
- read/write/destructive 分类、approval、idempotency、timeout、rate/budget policy；
- health/freshness、contract hash、last verified；
- error taxonomy：invalid_input、permission_denied、source_unavailable、timeout、rate_limited、
  contract_mismatch、partial_result、unsafe_request、unknown_failure。

MCP/OpenAPI discovery 只创建待审核 capability proposal；不能自动把新工具加入生产 allowlist。
Executor 对 output 再做 Pydantic validation 和 provenance binding，模型不能把文本当成功结果。

### 5.7 Multi-Agent Supervisor

角色来自受版本控制的 Role Catalog，不允许模型创建无限角色。首版角色：

- mission_planner；
- market/data researcher；
- strategy researcher；
- experiment operator；
- risk/robustness critic；
- evidence reviewer；
- synthesis editor。

Supervisor 输出 `AgentAssignmentV1`，明确 step、role、allowed capabilities、context pack、预算和
expected artifact。只读独立分支使用 `asyncio.TaskGroup` 并受现有原子预算 reservation 控制；
handoff 只传结构化 result/ref，不传 private reasoning。合并时 Critic 检查矛盾、证据覆盖和
未解决 unknown，不以多数投票替代证据。

### 5.8 Mission Artifact Index

统一索引已有外部/内部产物，不复制 BitPro 完整 artifact：

- artifact id/kind/schema/content hash/source owner；
- mission/plan/step/attempt refs；
- immutable URI 或外部 stable id；
- bounded preview/metrics、citation/provenance；
- supersedes/diff relation、retention/sensitivity；
- `materialized=false` 表示仅保存外部引用。

最终报告只能引用 Artifact Index、Evidence 或已验证 Observation。无法读取的 artifact 保持
unavailable，不由模型补造。

### 5.9 Sandboxed Research Development

当 Mission 需要生成或修改策略代码时，使用独立 sandbox service：

- 每次 Mission/Step 创建短生命周期 Docker 容器或受限 worktree；
- 只挂载临时 workspace、只读 SDK/fixtures，不挂载生产 `.env`、Docker socket 或主机密钥；
- CPU、内存、进程、网络域名、运行时间和输出大小限制；
- patch、测试命令、退出码和 artifact hash 写审计；
- 只有人工批准的 patch/StrategySpec 可以进入 BitPro 导入流程；
- sandbox 永远不能访问 live/testnet/mainnet order 工具。

首版不实现通用 shell Agent；只支持策略模板、受限文件类型和白名单 test/build 命令。

## 6. 技术选型

| 层 | 选择 | 原因 |
|---|---|---|
| Architecture | 模块化单体、DDD-lite、ports-and-adapters | 新核心不依赖 UI、ORM 或 provider 细节 |
| Runtime | Python、LangGraph `StateGraph`、AnyIO | async-native structured concurrency 与固定安全拓扑 |
| Contracts | Pydantic v2、JSON Schema、Decimal/UTC | 严格输入输出和跨界面一致性 |
| Canonical State | PostgreSQL JSONB/event tables、SQLAlchemy Async、Alembic | 事务事件、projection、lease 和 outbox |
| Worker | AnyIO TaskGroup、DB lease/heartbeat | 不引入第二套队列；支持取消域和有界并行 |
| Tools | MCP + ToolRegistry + reviewed Capability Catalog | 动态发现与生产 allowlist 分离 |
| Context | 自定义 Context Compiler + Memory/RAG/Evidence | 领域来源和审计要求不能交给通用框架猜测 |
| Vector Search | pgvector | 复用现有 RAG/Memory 存储 |
| Artifacts | PostgreSQL metadata + external stable refs；后续可接 S3/MinIO | 不复制 BitPro raw artifacts |
| Sandbox | Rootless Docker/受限容器 + ephemeral workspace | 隔离生成代码和测试副作用 |
| Streaming | FastAPI SSE + cursor events | 复用现有 CLI/Web/TUI 进度协议 |
| UX | Rich CLI、Textual、React/TypeScript | 现有三种 operator surfaces |
| Telemetry | OpenTelemetry semantic spans + bounded domain events | 从第一条新 Runtime 路径就可观测 |
| Evaluation | pytest golden suites、isolated provider baseline、Ragas/Promptfoo | 覆盖确定性门禁和模型波动 |

明确不引入 AutoGen/CrewAI 作为新核心，它们会再次形成框架主导的 Agent/Memory/Tool 状态。
旧 Task OS 也不因已经存在而自动保留；新 Mission event model 验收后，旧表转为只读历史并
删除新写入路径。Temporal、Kafka、Redis/Celery、Kubernetes 只在 PostgreSQL lease 和 Docker
Compose 出现有证据的规模瓶颈后另行决策。

## 7. Sprint 路线

| Sprint | 主题 | 核心交付 | 门禁 |
|---|---|---|---|
| 111 | Runtime Foundation & Mission Loop | 新内核、Mission event model、bounded replan、首条垂直切换 | Gate I |
| 112 | Capability & Tool Runtime V2 | reviewed capability catalog、typed observation、恢复策略 | Gate J1 |
| 113 | Context & Artifact Engine | context pack、token ledger、compaction、mission artifact index | Gate J2 |
| 114 | Bounded Multi-Agent Supervisor | 动态分工、并行、handoff、critic merge | Gate K |
| 115 | Sandboxed Strategy Development | 受限工作区、patch/test artifact、人工导入门禁 | Gate L |
| 116 | Full Cutover, UX & Readiness | Mission UI、长任务基准、旧 Runtime 删除和发布门禁 | Gate M |

### 7.1 Sprint 111：Runtime Foundation & Mission Loop

具体技术：`hypertrade/runtime` 模块化核心、domain/application/ports/adapters 分层、Pydantic
Mission/Plan/Replan contracts、async SQLAlchemy、PostgreSQL event/projection、AnyIO worker、
LangGraph 固定 adaptive topology、OpenTelemetry、optimistic locking 和 SSE cursor events。

范围：先做架构 fitness audit，把组件标记 keep/rewrite/delete；然后完成一个开放只读研究 Mission
的端到端新路径。现有工具通过 port adapter 接入，但新 Mission 不写旧 Task/Run 状态。最多
3 个 Plan versions、12 steps/version、2 attempts/step。新路径验收后，默认 ask/canary 切到新
Runtime，并删除被替代的 AgentKernel/TaskExecutor 分支，而不是保留永久 fallback。

### 7.2 Sprint 112：Capability & Tool Runtime V2

具体技术：Capability Catalog Pydantic/JSON Schema、MCP capability snapshot、contract hash、
ToolObservationV2、error taxonomy、preflight、circuit state、idempotency binding、policy validator。

范围：把可用的 ToolRegistry/MCP adapter 迁移为新 port；Planner 只引用 capability id；对
timeout/rate/source/contract 错误使用确定性恢复矩阵。验收后删除 legacy planner tool mapping、
重复 local/remote invocation 逻辑；发现的新工具默认 pending，不自动启用。

### 7.3 Sprint 113：Context & Artifact Engine

具体技术：ContextPack manifest、token estimator/ledger、deterministic relevance tiers、bounded
summarizer、pgvector retrieval、Artifact Index、content hash、source/supersede relation。

范围：每 Step 独立编译 context；记录保留/丢弃原因；完整聊天和 raw artifacts 不入 prompt。
最终报告强制引用 mission artifacts。验收后删除 AgentKernel 内分散的 prompt/context 拼装路径。

### 7.4 Sprint 114：Bounded Multi-Agent Supervisor

具体技术：Role Catalog、Assignment/Handoff/Merge contracts、AnyIO TaskGroup、atomic
budget reservations、PostgreSQL node/attempt events、Critic schema 和 conflict ledger。

范围：Supervisor 可在白名单角色中选择最多 4 个并行只读 assignments；写步骤串行。合并保留
冲突和少数证据。达到固定 Research Graph 质量/安全等价后，下沉可复用角色并删除其顶层固定
DAG，不做自由对话群、无限辩论或角色自我复制。

### 7.5 Sprint 115：Sandboxed Strategy Development

具体技术：rootless Docker、ephemeral workspace/worktree、resource/network policy、命令白名单、
unified diff、pytest/SDK contract tests、artifact hash、approval-bound import manifest。

范围：只允许策略模板与测试文件；生成 patch 后运行 lint/test/limited backtest，展示 diff，人工
批准后才能交给 BitPro 的稳定导入接口。无 shell 出网、无秘密、无 Docker socket、无交易权限。

### 7.6 Sprint 116：Full Cutover, Professional UX & Readiness

具体技术：FastAPI REST/SSE cursor、Textual tree/timeline、React Mission workspace、event replay、
golden long-horizon scenarios、fault injection、isolated provider matrix、OpenTelemetry exporter。

范围：统一展示 Mission/Plan/Step/Artifact/Budget；用户可 pause/resume/cancel/steer/approve；构建
与 Hermes/TradingAgents/Claude Code 工作方式相对应但面向 HT 领域的自有任务集。完成所有入口
切换、历史数据只读归档、旧 API deprecation 和 AgentKernel/legacy runtime 删除，不复制其实现。

## 8. 发布门禁

### Gate I：Adaptive Mission Safety（Sprint 111）

- 计划和每次 replan 可验证、可 diff、不可覆盖历史；
- pause/cancel/steer 在安全点生效，重启从 checkpoint 恢复；
- 循环、预算、步骤和 attempt 上限不能被模型扩大；
- 至少 20 个确定性 scenario 中无越权 dispatch、无无限循环、无虚假 completed。
- 新 Runtime domain 层无 FastAPI/SQLAlchemy/provider/MCP concrete imports；新 Mission 不双写旧表。
- 首条 canary 路径不再调用旧 AgentKernel，替代代码有明确删除 diff，而不是新增兼容包装。

### Gate J：Tool + Context Integrity（Sprint 112–113）

- 100% tool call 绑定 catalog version、policy hash、validated observation；
- error taxonomy 覆盖率、恢复分支和 circuit 行为可重复；
- Context Pack 关键约束保留率 100%，引用/来源覆盖达到合同门槛；
- prompt/context/artifact 不保存 credential、private reasoning 或 raw BitPro series。

### Gate K：Team Coordination（Sprint 114）

- 并行分支原子预算不超限，handoff 有 schema/source refs；
- 冲突不被多数投票或 final writer 覆盖；
- 单 Agent fallback 与多 Agent 路径均可完成相同安全门禁；
- 增加 Agent 数量必须在固定基准上证明质量或延迟收益。

### Gate L：Sandbox Isolation（Sprint 115）

- sandbox 无生产 secrets、Docker socket、非白名单网络和交易工具；
- timeout/resource/output limits 可强制终止；
- 所有 patch、命令、退出码和 artifacts 可审计；
- 未经人工批准不能导入 BitPro 或修改主仓库。

### Gate M：Professional Readiness（Sprint 116）

- 两次隔离长任务基准均达到 goal completion、tool correctness、evidence、recovery、Task state、
  budget 和 safety 门槛；
- fault injection 覆盖 provider、MCP、DB lease、schema、source stale 和用户 steer；
- CLI/TUI/Web 对同一 Mission 投影一致，运行可 replay；
- 生产 feature flag 默认关闭，通过 canary 后才按管理员明确动作启用。
- 所有新入口切换完成，旧 runtime 无生产调用者；历史只读查询保留，旧写路径和兼容层删除。

## 9. 核心评测指标

- goal completion correctness，不以模型自报完成计分；
- plan validity、replan precision、无效 plan churn；
- tool/capability selection、argument/schema correctness；
- source/citation coverage、unknown preservation、artifact reproducibility；
- retry/recovery success、false recovery、loop/budget violations；
- checkpoint resume、steer incorporation、Task/Event consistency；
- context constraint retention、token efficiency、stale-context rate；
- handoff completeness、conflict preservation、多 Agent 增益；
- unsafe dispatch、approval bypass、secret/raw artifact leakage 必须为 0。

收益、Sharpe 或短期 paper 表现不是 Agent Runtime 发布指标。

## 10. 数据模型与 API 方向

建议按 Sprint 逐步新增。新 Runtime 采用事件表 + 读 projection，不复制旧 Task 状态：

```text
0023: agent_missions, agent_plan_versions, agent_step_attempts, agent_steering_events
0024: agent_capability_snapshots, agent_tool_observations
0025: agent_context_packs, mission_artifacts
0026: agent_assignments, agent_handoffs, agent_conflicts
0027: sandbox_runs, sandbox_artifacts, sandbox_import_reviews
```

API 前缀统一为 `/api/agent/missions`：create/list/get、plan/diff、events/stream、control、steer、
artifacts、assignments。现有 `/api/agent/tasks` 仅保留历史读取窗口，禁止双写；客户端迁移完成
后删除旧写端点。Mission/Step 是新运行时的唯一工作状态，不再维护 Mission→旧 Task 镜像。

## 11. Feature Flags 与部署

```text
AGENT_MISSION_V2_ENABLED=false
AGENT_ADAPTIVE_REPLAN_ENABLED=false
AGENT_CAPABILITY_CATALOG_V2_ENABLED=false
AGENT_CONTEXT_PACK_V1_ENABLED=false
AGENT_DYNAMIC_TEAM_ENABLED=false
AGENT_STRATEGY_SANDBOX_ENABLED=false
```

每个 flag 独立，后续 flag 不能绕过前置 Gate。生产 canary 先使用只读研究 Mission、零 paper/
live/capital 权限、严格预算和单并发；provider benchmark 继续在隔离环境执行。

## 12. 明确不做

- 不构建无限自主、无限 Token、无限 Agent 或无终止条件的循环；
- 不保存或展示模型 private chain-of-thought；
- 不让模型动态扩大 tool/role/permission/budget；
- 不因为“兼容”保留两套 canonical Task OS 或永久 legacy adapter；
- 不允许生成代码直接进入生产或 BitPro；
- 不因为专业 Agent Runtime 而开放 mainnet、自动 paper promotion 或自动资本配置；
- 不宣称完成此路线即可稳定盈利。

## 13. 实施入口

- 第一份拟议合同：`docs/contracts/sprint-111-professional-agent-loop-v2.md`。
- 用户确认路线后，将 Sprint 111 从 Draft 改为 Active；其他 Sprint 在前一 Gate 关闭后逐一创建
  focused contract，不提前并行开发。
- Sprints 96–105 基础：`docs/architecture/27-agent-research-os-roadmap.md`。
- Sprints 106–110 研究运营：`docs/architecture/29-research-operations-shadow-portfolio-roadmap.md`。
- 当前详细技术基础：`docs/architecture/28-agent-research-os-technical-design.md`。
