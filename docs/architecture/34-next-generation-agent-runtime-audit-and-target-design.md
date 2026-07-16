# 34 下一代专业 Agent Runtime：真实审计与目标架构

> 状态：目标架构提案（2026-07-16）
> 适用范围：HyperTrade Agent 控制面、CLI/Web/TUI/Desktop 协议、Mission Runtime、工具治理、
> 多 Agent 研究、交易安全和评测。
> 事实边界：本文件基于代码、测试、数据库模型、运行事件和代表性真实请求审计；它不是对当前实现的
> 完成声明。当前实现快照见 [33 System Architecture](33-system-architecture.md)，首个切换合同见
> [Sprint 121](../contracts/sprint-121-canonical-thread-turn-protocol.md)。

## 1. Executive diagnosis

### 1.1 证据摘要

- 生产代码：`main.py` 的同一 `/api/agent/runs` 入口仍可进入 Mission 或 `AgentKernel`；`cli.py` 也有本地
  Mission/legacy 双构造。数据库同时定义 Run、Session、Task、Mission 和不完整的 MissionEvent。
- 客户端：Desktop 发送最近 8 条用户文本，Remote CLI/Web 没有相同的服务端多轮历史；TUI 依据 adapter
  方法是否存在选择 Mission 或 Task。没有 durable Thread/Turn/Item 聚合。
- 运行：三个代表性单轮只读/安全请求行为正确；真实 CLI 两轮“比较 A/B”→“后者”错误绑定为 A。
- 测试：71 条 Mission/worker/context/supervisor/tool 定向测试通过，但现有 100 题 runner 人工注入
  `prior_turns`，没有证明真实 CLI/Web 多轮路径。
- 状态：`update_usage`、`set_current_step` 等 projection 更新没有足够 domain event；仅靠现有 event log 无法
  重建 Mission。Supervisor 默认使用 canned test worker，Mission Approval 也没有形成持久闭环。

### 1.2 结论

HyperTrade 已经拥有一组有价值的交易研究基础设施：BitPro 外部事实边界、受审核 Capability Catalog、
有界 Observation、来源引用、Mission/Plan/Step/Attempt、SQL lease、研究证据、策略实验、回测/模拟盘只读
事实和主网禁用边界。这些不是演示代码，应该保留。

但当前系统还不能称为“现代化专业 Agent Runtime”。它更准确的描述是：**一个受治理的交易研究能力层，
外加正在替换旧 AgentKernel/AgentTask 的 Mission 调度器**。固定 100 题评测达到 100/100，证明的是已知
任务集上的投影和路由质量，不证明跨客户端的多轮语义、可重放状态、批准闭环、故障恢复或真实多 Agent
自治已经完成。

### 1.3 三个根因

1. **没有唯一的 Agent 协议和聚合根。** `AgentRun`、`AgentSession`、`AgentTask`、`AgentMission` 同时存在；
   `/api/agent/runs` 仍可在 Mission 与旧 `AgentKernel` 之间分流，CLI、Web、TUI、Desktop 对历史、事件和
   完成状态的理解不同。系统没有服务端持久化的 Thread/Turn/Item 真相源。
2. **默认循环仍是“规则路由 + 顺序工具调度”，而不是显式、可验证、可恢复的 Agent 控制循环。** Context
   Pack 在步骤前被编译，却没有成为推理/执行输入；Supervisor 没有接入默认 Mission loop；Approval、
   Checkpoint、Verifier、Reducer、Completion Verification 不是同一个状态协议中的一等对象。
3. **评测优化了固定提示词和最终投影，没有覆盖真实跨端语义与分布式故障不变量。** 100 题 runner 会直接
   注入人工编写的 `prior_turns`，而真实 CLI/Web 不提供同等上下文；Desktop 只传最近用户文本。近期精确
   ticker、生产长度投影和多轮代词失败都说明评测存在盲区。

### 1.4 代表性运行证据（2026-07-16）

| 请求 | 实际结果 | 诊断 |
| --- | --- | --- |
| `ht ask '看下 LAB 的价格'` | 6.62s，正确返回 `LAB-USDT-SWAP` 价格、24h 变化和精确来源 | 精确只读能力可用 |
| `ht ask '看下我最好的实盘策略是哪个？'` | 8.23s，识别到缺少可比收益，拒绝编造排名 | 数据缺口处理正确 |
| `ht ask '主网满仓买入 ETH'` | 2.97s，在工具前阻断且未创建订单 | 主网安全入口有效 |
| 连续输入“比较 momentum... 和 mean_reversion...”→“后者最大回撤多少？” | 第二轮错误回答 `momentum_breakout_v1` | CLI 未提交服务端 Thread，出现目标漂移 |

定向 Agent/Mission/worker/context/supervisor/tool 测试共 71 条通过。这证明组件本身有测试覆盖，不能抵消
上述真实协议断裂。

### 1.5 成熟度判断

| 能力 | 当前成熟度 | 目标 |
| --- | --- | --- |
| 交易数据与研究证据治理 | 可用，仍需统一 Evidence 语义 | 生产级 |
| 单轮只读 Mission | 对已知路径可用 | 生产级 |
| 多轮会话连续性 | 不合格 | 生产级 Thread/Turn |
| 可重放事件模型 | 不成立；部分状态直接改 projection | 完整 event + reducer |
| 工具权限/批准 | 有预检骨架，无 Mission 批准闭环 | 参数级 allow/ask/deny |
| 多 Agent | 合同和测试存在，默认执行使用演示 worker | 有界真实 delegation |
| 故障恢复/副作用一致性 | 只读路径较安全，写路径协议不完整 | outbox + reconciliation |
| 专业完成验证 | 规则字段检查，缺少独立 verifier | Evidence-backed verifier |
| 真实端到端评测 | 固定集较强，跨端/故障弱 | surface + fault matrix |

### 1.6 第一件应替换的东西

第一件事不是添加更多策略角色，也不是换更强模型，而是用**服务端持久化的 Thread/Turn/Item 协议**替换
自然语言入口对 `/api/agent/runs`、客户端 `prior_turns` 和旧 AgentKernel fallback 的依赖。没有这个基础，
上下文、批准、恢复、多 Agent 和评测都只能继续打补丁。

---

## 2. Real current request execution map

### 2.1 默认 API 路径

~~~mermaid
sequenceDiagram
  participant C as Web/CLI/Desktop
  participant A as FastAPI /api/agent/runs[/stream]
  participant R as Canary Router
  participant M as MissionRuntime
  participant W as SQL Worker
  participant X as GovernedToolExecutor
  participant L as Legacy AgentKernel/AgentTask

  C->>A: prompt + optional client prior_turns
  A->>R: is_mission_canary(...)
  alt Mission cohort
    R->>M: mission_request_for_prompt(...)
    M->>M: create Mission + plan
    alt worker enabled
      A->>W: poll until terminal
      W->>M: lease and run
    else in-process
      A->>M: run(mission_id)
    end
    M->>X: sequential capability calls
    X-->>M: bounded observations
    M-->>A: mission_run_projection
  else legacy cohort/fallback
    R->>L: AgentTaskService + AgentTaskExecutor + AgentKernel
    L-->>A: legacy CompletedAgentRun
  end
  A-->>C: legacy run-shaped JSON or SSE projection
~~~

关键证据：

- `backend/src/hypertrade/main.py:1481-1650`：同一 `/api/agent/runs` 与 `/stream` 中保留 Mission 和
  `AgentKernel` 两条写路径。
- `backend/src/hypertrade/main.py:1786-1838`：列表合并 Mission 与 legacy run，详情再按 ID 猜测来源。
- `backend/src/hypertrade/runtime/application/entrypoint.py`：将 prompt 和可选 `prior_turns` 转为 Mission 请求。
- `backend/src/hypertrade/runtime/application/service.py`：`MissionRuntime` 负责计划、逐步执行和终态投影。
- `backend/src/hypertrade/worker.py:91`：worker 通过 lease 调用同一运行时。

### 2.2 客户端差异

| Surface | 当前自然语言入口 | 历史来源 | 风险 |
| --- | --- | --- | --- |
| Remote CLI | `/api/agent/runs`/`stream` | 不提交 `prior_turns` | 多轮代词和目标丢失 |
| Local CLI | 自行组合 MissionRuntime，canary 外回退 AgentKernel | 本地进程状态 | 与服务端构造和治理漂移 |
| Web | legacy run-shaped API | 未建立 canonical Thread | 刷新/重连只能恢复 run 投影 |
| Desktop | `/api/agent/runs/stream` | 最近 8 条用户文本 | 无 assistant/tool 事实，客户端成为上下文真相源 |
| Textual TUI | 方法存在时显示 Mission，否则 Task fallback | Mission/Task 两种模型 | UI 行为由 adapter 方法形状决定 |

### 2.3 Mission 内部实际循环

当前循环可概括为：

`ingress safety → regex/窄语义路由 → versioned plan → compile ContextPack → sequential ready step →
capability preflight → tool handler → validate bounded observation → simple criteria check → project response`

它与专业目标循环的差距：

| 专业阶段 | 当前实现 | 缺口 |
| --- | --- | --- |
| Intake / Safety | 已有并且主网阻断有效 | 尚未绑定 Thread/Turn 与统一 policy snapshot |
| Context | 会编译 ContextPack | executor/推理并不消费该 pack |
| Planning | 大量确定性关键词路由，窄场景调用模型提取意图 | 不是通用、可验证的 Plan proposal |
| Capability resolution | Catalog + schema/hash 较完整 | 权限维度不足，发现/审核/运行版本未形成完整 snapshot |
| Approval | capability 字段和 preflight 骨架 | 无 Mission Approval 聚合、单次消费、过期和恢复 |
| Dispatch | 顺序 Step/Attempt，可由 worker lease | 无 write-ahead dispatch/outbox 和 unknown-effect reconciliation |
| Validation | 检查来源、字段、Artifact | 没有 claim-level entailment 和独立 verifier |
| Reducer | store 直接写 projection 并追加部分事件 | 事件不足以重建状态 |
| Completion | `_criteria_satisfied` 做简单字段/来源/Artifact 判断 | 没有 false-completed 防线和独立完成证明 |
| Replan | 有界 plan diff | 触发和证据仍绑在同一 runtime 逻辑中 |
| Response | `OperatorResponseV1` 有界且诚实 | 经过多轮关键词补丁，协议仍是 legacy run projection |
| Learning | Memory/研究证据存在 | 缺少 reviewed outcome → lesson → promotion 流程 |

### 2.4 当前事件不可完整重放

`AgentMissionEvent` 记录部分转移和原因，但 `update_usage`、`set_current_step` 等更新 projection 时不产生
足够事件；事件也没有每次变更的完整 payload、aggregate version、causation/correlation 和 reducer version。
因此现有 Mission projection **不能仅从 event log 确定性重建**。在完成新事件协议前，文档和代码注释都
不得继续声称它是 rebuildable read model。

### 2.5 当前多 Agent 和批准的真实状态

- `BoundedSupervisor` 有 assignment、reservation、handoff、conflict 合同和单元测试，是可保留资产。
- 默认 `MissionRuntime.run` 不调用 Supervisor。
- `/api/agent/missions/{id}/team/run` 当前使用 `deterministic_worker()`；它返回固定角色完成声明，不是调用
  模型、工具和证据验证的生产 worker。
- `ToolRequestV2.approval_ref` 和 capability `approval_required` 存在，但默认 Mission 请求不创建/消费
  Approval；当前 Catalog 又以只读能力为主，所以批准流程没有被真实闭环验证。

### 2.6 当前评测盲区

`scripts/run_operator_task_completion_eval.py` 的价值在于固定任务、硬断言和 P0/P1 分类；其局限是：

1. runner 将人工编写的 `prior_turns` 直接注入每个请求，不经过真实 Thread 历史；
2. Desktop 正文在 runner 中被等价合成，不是完整 Tauri→SSE→React 路径；
3. context 断言只要求存在 `context_ref`，不验证最终实体是否等于用户指代；
4. 数据和提示词固定，无法覆盖新 ticker、字段长度变化、乱序、断连、租约丢失和外部副作用未知状态。

---

## 3. Keep / Rewrite / Delete

### 3.1 Keep

| 资产 | 保留理由 | 必要加固 |
| --- | --- | --- |
| BitPro MCP/API 边界 | 交易事实和业务规则所有权正确 | capability/version/freshness 契约化 |
| Mission/PlanVersion/Step/Attempt 概念 | 适合长任务和审计 | 重写状态与事件持久化 |
| Capability schema/hash/review | 防止模型动态扩大能力 | 加 permission snapshot 与参数策略 |
| bounded Observation/source refs | 有利于可追溯回答 | 提升为 claim-level Evidence |
| SQL lease/heartbeat | 可支持分布式 worker | 加 fencing token、outbox、orphan recovery |
| OperatorResponse 有界投影 | 默认不泄漏原始工具载荷/私有推理 | 从 canonical Turn 生成 |
| Evidence/Experiment/StrategyCard/robustness/portfolio | 交易研究的专业领域资产 | 统一 source time、as-of、data lineage |
| 隔离策略 sandbox | 代码研究安全边界正确 | 保持无网络、digest、资源上限 |
| 主网禁用 | 现阶段正确的产品边界 | live-write capability 不编译/不部署 |

### 3.2 Rewrite

1. 以 Thread/Turn/Item 为交互协议，以 Mission 为长任务聚合；两者显式关联，不再相互伪装。
2. 以 append-only domain event + reducer 构建 projection；所有状态变更必须事件化。
3. 将 MissionRuntime 拆为 Coordinator、Planner、Policy Engine、Dispatcher、Validator、Verifier、Reducer、
   Completion Engine 和 Response Projector。
4. Context Engine 输出必须成为 planner/model/tool request 的实际输入，并记录选入/压缩/丢弃决策。
5. Permission/Approval 改为参数级、环境级、账户级确定性策略，Approval 一次性、可过期、可撤销。
6. Supervisor 作为 Delegation DAG 接入 Coordinator；专业角色执行真实受限子 Mission，而非 canned worker。
7. CLI/Web/TUI/Desktop 全部只做同一协议投影；历史和恢复由服务器拥有。
8. 评测从“提示词是否得到预期文本”升级为协议、状态、证据、故障、权限、交易时间一致性联合门禁。

### 3.3 Delete or archive

按垂直切换逐项删除，不做一次性大爆炸：

- 对已迁移 surface 删除 `AgentKernel`/`AgentTask`/`AgentRun` 新写入 fallback；旧表仅保留限时只读归档。
- 删除 `/api/agent/runs` 作为 canonical 自然语言协议；迁移期只作为旧客户端兼容适配器。
- 删除客户端 `prior_turns` 参数和“客户端拼历史”的责任。
- 删除生产 team endpoint 对 `deterministic_worker()` 的依赖；保留它仅作为测试 fixture。
- 删除“Mission event log 可重建”的不实声明，直到 reducer 重放门禁通过。
- 删除永久 canary 双运行分支；每个 vertical slice 完成后必须有 deletion date。
- 删除以关键词补丁作为主要意图/完成引擎的模式；只保留输入归一化和 fail-closed 安全分类规则。
- 删除 Local CLI 隐式构造第二套 production runtime 的行为；本地开发模式必须显式并使用同一协议实现。

---

## 4. Comparison matrix

比较只借鉴公开架构思想，不复制代码，也不把通用编码 Agent 的权限模型直接套到交易系统。

| 维度 | HyperTrade 当前 | Hermes Agent | OpenCode | Codex app-server | TradingAgents | HyperTrade 目标选择 |
| --- | --- | --- | --- | --- | --- | --- |
| 交互聚合 | Run/Task/Mission 混合 | 统一 AIAgent + session/gateway | session + primary/subagents | Thread/Turn/Item | 单次 ticker/date graph | 采用 canonical Thread/Turn/Item，Mission 独立 |
| 多端一致性 | 客户端差异大 | CLI/gateway/ACP 共享核心 | TUI/CLI/desktop 围绕 session | rich clients 共享双向协议 | 主要 CLI/graph | 服务器拥有历史和状态，surface 纯投影 |
| 工具循环 | 受审核但顺序、规则化 | 集中 registry、回调、可中断 | 工具权限 + agent 配置 | item lifecycle + approvals | LangGraph ToolNode | 保留 Catalog，补齐 Item/ToolCall 生命周期 |
| Context | pack 未真正消费 | stable/context/volatile + compression | session/compaction agents | persisted items + compaction | graph state + memory log | stable/task/retrieved/volatile 四层并实际输入 |
| 权限 | 只读/非只读粗粒度 | dangerous command approval | allow/ask/deny + pattern | sandbox/permission/approval request | 无交易执行治理 | 参数/标的/账户/环境/path/role 的确定性 ABAC |
| 多 Agent | Supervisor 未接默认循环 | subagent delegation | primary/subagent + task permission | child threads/collab items | 固定分析/辩论/风险角色 | bounded Delegation DAG + 独立证据/风险 verifier |
| 恢复 | lease 有，事件不完整 | session persistence | event/session projector 思路 | lifecycle events、resume/fork/interrupt | LangGraph SQLite checkpoint | event reducer + checkpoint + outbox + reconciliation |
| 学习 | Memory/证据多，晋级协议弱 | skills/memory/trajectory 闭环 | summary/compaction | memory/skills | realized return reflection | 只从已结算结果产生 reviewed lesson，不自改权限 |
| 交易专业性 | 领域最强 | 通用 | 编码 | 编码 | 角色研究强、执行安全弱 | 保留 HyperTrade/BitPro 安全边界，引入角色辩论 |
| 完成判断 | 简单 criteria + projection | 模型循环/verification stop | 模型完成 + tool state | turn/item terminal lifecycle | graph terminal node | 独立 verifier + objective/evidence/side-effect reconciliation |

借鉴边界：

- **Hermes Agent**：借鉴统一核心、会话连续性、context 分层、工具可见性、interrupt；不采用无限通用自治。
- **OpenCode**：借鉴 primary/subagent、Plan 只读模式、细粒度 `allow/ask/deny` 和最后匹配规则；交易策略必须
  使用结构化字段而非字符串 shell pattern。
- **Codex app-server**：借鉴 Thread/Turn/Item、start/resume/fork/interrupt、`item/started → delta →
  item/completed`、inline approval；不引入编码 Agent 的任意 shell/file 权限。
- **TradingAgents**：借鉴 analyst/bull/bear/risk/portfolio 分工、有限辩论、checkpoint、用已实现收益反思；
  不让 LLM 投票直接成为下单授权，也不把 markdown memory 当审计账本。

公开资料：

- [Hermes Agent repository](https://github.com/NousResearch/hermes-agent) 与
  [architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- [OpenCode repository](https://github.com/anomalyco/opencode)、
  [agents](https://opencode.ai/docs/agents)、[permissions](https://opencode.ai/docs/permissions)
- [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [TradingAgents repository](https://github.com/TauricResearch/TradingAgents)

---

## 5. Target architecture diagram

~~~mermaid
flowchart TB
  subgraph Surfaces["Operator Surfaces — no workflow truth"]
    CLI["CLI / TUI"]
    WEB["Web"]
    DESK["Desktop"]
    APIUSER["External Agent API"]
  end

  subgraph Gateway["Agent Gateway"]
    AUTH["Identity · tenant · role"]
    PROTOCOL["Thread / Turn / Item API\ncommands + cursor event stream"]
    IDEM["Idempotency · rate limit · admission"]
  end

  subgraph Control["Durable Agent Control Plane"]
    CMD["Command Handler"]
    ES[("Append-only Event Store")]
    RED["Deterministic Reducers"]
    PROJ[("Thread · Mission · audit projections")]
    OUTBOX[("Transactional Outbox")]
    COORD["Runtime Coordinator"]
    CHECK["Checkpoint · lease · fencing"]
    FACTS[("Evidence · Artifact · Memory · Budget")]
  end

  subgraph Loop["Professional Agent Loop"]
    INTAKE["Intake + safety intent"]
    CTX["Context Compiler\nstable · task · retrieved · volatile"]
    PLAN["Planner → immutable PlanVersion"]
    RESOLVE["Capability Resolver"]
    POLICY["Policy / Risk / Approval"]
    DISPATCH["Attempt + ToolCall Dispatcher"]
    VALIDATE["Schema + provenance Validator"]
    LEDGER["Observation / Evidence Ledger"]
    VERIFY["Independent Completion Verifier"]
    REPLAN["Bounded Replan"]
    RESPONSE["OperatorResponse Projector"]
  end

  subgraph Team["Bounded Multi-Agent Research Team"]
    LEAD["Lead researcher"]
    SPECIALISTS["Market · strategy · data · portfolio specialists"]
    EVERIFY["Independent evidence verifier"]
    RVERIFY["Independent risk verifier"]
    CONFLICT["Conflict-preserving merge"]
  end

  subgraph Execution["Isolated Execution/Data Plane"]
    WORKERS["Stateless workers"]
    CATALOG["Reviewed Capability Catalog"]
    TOOLGW["Governed Tool Gateway"]
    SANDBOX["Strategy sandbox\nnon-root · no network"]
    RECON["Side-effect reconciliation"]
  end

  subgraph Ports["Trading Ports — separate credentials and deployments"]
    MARKET["Market data read"]
    BITPRO["BitPro strategy/backtest/paper facts"]
    TESTNET["Testnet intent/write — approval gated"]
    LIVEREAD["Live account read"]
    LIVEWRITE["Live write — not deployed"]
  end

  OBS["Metrics · traces · audit · eval replay"]

  CLI --> AUTH
  WEB --> AUTH
  DESK --> AUTH
  APIUSER --> AUTH
  AUTH --> PROTOCOL --> IDEM --> CMD
  CMD --> ES --> RED --> PROJ
  CMD --> OUTBOX
  OUTBOX --> COORD
  COORD --> CHECK
  COORD --> INTAKE --> CTX --> PLAN --> RESOLVE --> POLICY --> DISPATCH
  DISPATCH --> WORKERS --> CATALOG --> TOOLGW
  TOOLGW --> MARKET
  TOOLGW --> BITPRO
  TOOLGW --> TESTNET
  TOOLGW --> LIVEREAD
  TOOLGW -. physically absent .-> LIVEWRITE
  TOOLGW --> SANDBOX
  TOOLGW --> RECON
  WORKERS --> VALIDATE --> LEDGER --> VERIFY
  LEDGER --> FACTS
  FACTS --> CTX
  VERIFY -->|criteria met| RESPONSE
  VERIFY -->|repairable| REPLAN --> PLAN
  VERIFY -->|input/approval| COORD
  PLAN --> LEAD --> SPECIALISTS --> EVERIFY --> RVERIFY --> CONFLICT --> VALIDATE
  RESPONSE --> ES
  PROJ --> PROTOCOL
  ES --> OBS
  WORKERS --> OBS
~~~

### 5.1 关键架构决定

1. **Thread 不是 Mission 的别名。** Thread 表示人机对话；Turn 表示一次用户输入到可审计终态；Mission 表示
   可跨 Turn 持续的目标。一个 Turn 可创建、推进、查询或取消 Mission；一个 Mission 可由多个 Turn steering。
2. **命令与事件分离。** API 接受 command，领域校验后原子追加 event/outbox；projection 只能由 reducer 更新。
3. **外部调用不在数据库事务内。** `ToolCallDispatched` 前持久化 dispatch intent；完成后以幂等键确认。写调用
   超时进入 `unknown`，必须 reconcile，不能直接 retry。
4. **模型只做 proposal。** Plan、tool args、response draft 可由模型提出；权限、风险、状态转移、证据有效性、
   预算和终态由确定性组件决定。
5. **所有 surface 使用同一协议。** 无 surface-specific 历史拼接、完成判断或 fallback runtime。
6. **部署即权限。** live-write adapter、凭证和网络路由在当前部署中物理不存在；配置开关不能绕过。

### 5.2 专业 Agent Loop

每个 Turn/Mission 的显式循环固定为以下阶段；阶段可以因确定性规则跳过，但不能由客户端或模型重排：

| Phase | 输入 | 结构化输出 | 失败/暂停行为 |
| --- | --- | --- | --- |
| 1. Intake | user Item、Thread facts | normalized subject、instrument、time range、environment、intent | 歧义进入 waiting_input |
| 2. Safety preflight | normalized request、identity | risk class、hard deny、permission profile | unsafe 在 provider/tool 前终止 |
| 3. Context compile | Thread、Mission、Plan、Evidence、health、budget | immutable ContextPack + inclusion ledger | 超预算按裁剪顺序；缺关键事实等待输入 |
| 4. Structured planning | objective、criteria、ContextPack | proposed immutable PlanVersion | schema/能力不可解析则失败或澄清 |
| 5. Capability resolution | proposed capability ids | reviewed version/hash snapshots | pending/unhealthy capability 不可用 |
| 6. Policy evaluation | tool args + subject/account/env/role | allow/ask/deny PolicyDecision | ask 创建 Approval，deny 不可覆盖 |
| 7. Approval | scoped Approval request | approved/denied/expired fact | 批准前零 dispatch |
| 8. Dispatch | Attempt、ToolCall、budget、fencing | durable dispatch intent + external operation id | 断连的写调用进入 unknown |
| 9. Observation validation | bounded result | schema-valid Observation or classified failure | 不合法结果不进入 Evidence |
| 10. Evidence binding | Observation/Artifact | claims、support/opposition/unknown refs | 来源/时间缺失则 evidence invalid |
| 11. State reduction | domain events | rebuilt projections | version gap quarantine aggregate |
| 12. Completion verification | success criteria、Evidence、in-flight effects | pass/fail/gaps verifier result | 模型文字不能触发 completed |
| 13. Bounded replanning | rejected hypothesis/gaps | PlanVersion diff | 超 replan budget 则失败/等待输入 |
| 14. Response projection | verified claims/unknowns/risks | OperatorResponse + public Items | factual claim 无 Evidence 则拒绝 |
| 15. Reviewed learning | settled outcome + review | candidate Memory/Skill lesson | 未结算/未审核内容不晋级 |

每个 Mission 在创建时冻结 `max_steps`、`max_attempts_per_step`、`max_tool_calls`、`max_model_calls`、
`max_tokens`、`max_wall_seconds`、`max_replans`、`max_delegations` 和 `max_parallelism`。Budget 必须先 reserve
再消费，模型和 child Agent 只能获得更小切片。

失败分类至少包括：`transient`（退避重试）、`contract`（schema/version，不盲重试）、`permission`（等待批准
或 deny）、`source`（显式 unknown/health）、`unsafe`（立即终止）、`budget`（停止或请求扩展）、`effect_unknown`
（对账，不重试）。Provider 不可用不能降级为虚假成功或无来源回答。

Coordinator 必须支持 cancel propagation、timeout、heartbeat、fencing lease、持久 circuit breaker、
checkpoint 和 bounded queue。Gateway 使用有界 ingress/outbound queue；过载返回可重试错误和 retry-after，
不得无限缓存。SSE/WebSocket 断线不取消服务器 Turn；客户端用 cursor replay 恢复，显式 interrupt 才传播取消。

### 5.3 Context、Memory 与 Skills

ContextPack 是 planner/model/verifier 的真实输入合同，而不是旁路审计产物：

| Layer | 内容 | 稳定性与裁剪 |
| --- | --- | --- |
| Stable | 身份、安全不变量、permission profile、工具协议、output schema | 版本固定；不能被 Memory/Skill 覆盖 |
| Task | objective、success criteria、active Plan/Step、已解决实体、operator constraints | 当前 Turn/Mission 必需，优先保留 |
| Retrieved | 带 source/time 的 Evidence、reviewed Memory、RAG、Artifact summaries | 按相关性、freshness、独立来源和 token 预算选择 |
| Volatile | 当前时间、source/circuit health、剩余 Budget、lease/environment | 每个 Attempt 刷新，不跨 Turn 缓存为事实 |

裁剪顺序固定为：重复/低相关 retrieved → 过期 retrieved → 可重取的 tool detail → 较旧非关键 Items →
结构化摘要；Stable、安全、当前 Task、Approval scope、未解决冲突和关键 Evidence refs 不得丢失。压缩只保存
事实摘要、决策 reason code、实体引用和来源，不保存 private reasoning。

Memory 是候选经验而非事实。写入必须绑定 settled Evidence/outcome、confidence method、validity window、
review status、producer 和 lineage；`pending_review` Memory 不能支持公开 claim。冲突 Memory 并存，由检索结果
明确显示 stance 和适用 regime。过期/被反证 Memory 不删除审计记录，只退出 active retrieval。

Skill 只能提供 prompt template、workflow proposal 或已审核 capability 组合；它不能扩大 permission、注册未
审核代码、绕过 Catalog/Policy 或直接写 Memory。Skill version 更新必须经过 schema、security、regression
和 domain eval，并使用 content hash/签名进入 allowlist。

### 5.4 当前控制能力的证据等级

| 能力 | 代码/测试证据 | 真实运行证据 | 审计结论 |
| --- | --- | --- | --- |
| cancel/pause/resume/steer | Mission control API、runtime methods 和相关测试存在 | 本轮未执行生产状态变更 | 组件存在，不宣称跨 surface/崩溃恢复已验证 |
| lease/heartbeat | worker/store 路径与 worker tests | 本轮只观察终态 worker，不注入生产崩溃 | 可保留，但需 fencing/outbox fault gate |
| ghost/duplicate run | idempotency/worker 单测存在 | 代表性只读请求未见重复输出 | 未覆盖所有 crash boundary |
| completion | criteria 与 OperatorResponse tests | 曾出现 worker completed 但 SSE 无 final 的 Sprint 119 故障 | 完成语义需独立 verifier 和协议终态 |
| payload/reasoning exposure | bounded OperatorResponse 投影和测试 | 代表性输出未泄漏 Plan/原始 payload/private reasoning | 默认回答边界可保留 |
| duplicate side effect | 当前 Mission Catalog 主要只读 | 没有在生产触发写请求 | 不能据此证明未来写路径 exactly-once |

---

## 6. Full state machines and illegal transitions

### 6.1 通用状态机规则

- Command 是意图；只有通过 guard 才能产生 event。
- 每个 event 包含 `event_id`、`aggregate_id`、`aggregate_version`、`schema_version`、`causation_id`、
  `correlation_id`、`idempotency_key`、actor、policy snapshot、timestamps 和 payload hash。
- reducer 只接受 `aggregate_version = current + 1`；重复 event_id/idempotency_key 为 no-op，版本跳跃拒绝。
- side effect 只能由已提交 outbox record 触发；事件重放永不再次执行外部副作用。
- `completed` 只代表所有完成条件已有有效 Evidence 且没有未对账写副作用，不代表策略将盈利。

### 6.2 Mission 状态机

必需状态：`draft → queued → planning → ready → running → verifying → completed`，以及
`waiting_input`、`waiting_approval`、`paused`、`replanning`、`retrying`、`cancelling`、`cancelled`、`failed`、
`expired`。

| From → To | Command | Guard | Event | Deterministic side effect |
| --- | --- | --- | --- | --- |
| ∅ → draft | `CreateMission` | objective/schema/idempotency valid | `MissionCreated` | create budget and owner projection |
| draft → queued | `QueueMission` | success criteria, permission profile and deadline present | `MissionQueued` | enqueue planning outbox |
| queued → planning | `ClaimPlanning` | valid lease/fencing token; not expired | `MissionPlanningStarted` | reserve planning budget |
| planning → ready | `AcceptPlan` | immutable plan validates; capabilities resolvable; risk class known | `PlanVersionActivated`, `MissionReady` | materialize step dependencies |
| planning → waiting_input | `RequestInput` | required ambiguity cannot be resolved safely | `InputRequested` | create OperatorRequest item |
| planning → waiting_approval | `RequestApproval` | proposed scope resolves to ask | `ApprovalRequested` | publish approval item; release lease |
| planning → failed | `FailPlanning` | non-recoverable schema/policy/provider error | `MissionFailed` | release reservations |
| ready → running | `StartMission` | active plan; budget; no pending approval; worker lease | `MissionStarted` | schedule first ready steps |
| running → verifying | `BeginVerification` | no runnable steps; no in-flight/unknown ToolCall | `MissionVerificationStarted` | dispatch independent verifier |
| running → waiting_input | `RequestInput` | progress requires missing operator fact | `InputRequested` | checkpoint and release lease |
| running → waiting_approval | `RequestApproval` | next ToolCall is ask and approval absent | `ApprovalRequested` | checkpoint; no dispatch |
| running → replanning | `RequestReplan` | hypothesis invalidated; replan budget remains | `MissionReplanningStarted` | freeze old plan, enqueue planner |
| replanning → ready | `AcceptPlanDiff` | new immutable version valid; completed evidence retained | `PlanVersionActivated`, `MissionReady` | materialize delta only |
| replanning → waiting_input | `RequestInput` | safe replan needs operator choice | `InputRequested` | publish request |
| replanning → failed | `FailReplan` | no valid plan or budget exhausted | `MissionFailed` | release reservations |
| running → retrying | `ScheduleRetry` | classified recoverable; retry budget/backoff available; no unknown write | `MissionRetryScheduled` | durable delayed outbox |
| retrying → running | `RetryDue` | backoff elapsed; fresh lease; dependency still valid | `MissionRetryStarted` | create new Attempt, never reuse old |
| retrying → failed | `ExhaustRetries` | attempts or deadline exhausted | `MissionFailed` | release reservations |
| verifying → completed | `AcceptCompletion` | independent verifier pass; evidence fresh; all write effects reconciled; response validates | `MissionCompleted` | persist response, close budget |
| verifying → replanning | `RejectCompletionRepairable` | gaps repairable within budget | `CompletionRejected`, `MissionReplanningStarted` | enqueue bounded replan |
| verifying → waiting_input | `RejectCompletionNeedsInput` | only operator can resolve gap | `InputRequested` | publish exact missing fact |
| verifying → failed | `RejectCompletionFatal` | false/unsafe/unrecoverable result | `MissionFailed` | record verifier reasons |
| waiting_input → queued | `ProvideInput` | request id open; schema valid; actor authorized | `InputProvided`, `MissionQueued` | resume from checkpoint |
| waiting_approval → ready | `Approve` | approval open, unexpired, scope/hash exact | `ApprovalGranted`, `MissionReady` | mark approval consumable once |
| waiting_approval → failed | `DenyApproval` | decision authorized | `ApprovalDenied`, `MissionFailed` | no tool dispatch |
| ready/running/replanning/retrying → paused | `PauseMission` | actor authorized; no irreversible dispatch boundary crossed | `MissionPaused` | stop new dispatch; checkpoint |
| paused → queued | `ResumeMission` | deadline/budget/policy still valid | `MissionResumed`, `MissionQueued` | fresh context/freshness check |
| nonterminal → cancelling | `CancelMission` | actor authorized | `MissionCancellationRequested` | cancel model calls, unleased work, child delegations |
| cancelling → cancelled | `ConfirmCancellation` | all cancellable work stopped; unknown writes reconciled or quarantined | `MissionCancelled` | close budget and response |
| nonterminal → expired | `ExpireMission` | deadline reached and no protected reconciliation pending | `MissionExpired` | cancel queued work, preserve audit |
| any active → failed | `FailMission` | classified fatal invariant/permission/data error | `MissionFailed` | stop dispatch, preserve evidence |

`cancelled` 是 canonical spelling。迁移适配器只在读取旧数据时接受 `canceled`，新事件不得产生该拼写。

### 6.3 Turn 状态机

状态：`accepted`、`contextualizing`、`running`、`waiting_input`、`waiting_approval`、`streaming`、
`completed`、`failed`、`cancelled`、`expired`。

| Transition | Command | Guard | Event | Side effect |
| --- | --- | --- | --- | --- |
| ∅ → accepted | `StartTurn` | thread active; client idempotency unique | `TurnAccepted` | persist user Item |
| accepted → contextualizing | `CompileTurnContext` | admission and safety pass | `TurnContextualizationStarted` | compile server-owned history |
| contextualizing → running | `StartTurnWork` | ContextPack valid and target resolved | `TurnStarted` | link/create Mission |
| contextualizing → waiting_input | `RequestTurnInput` | referent/constraint unsafe to infer | `TurnInputRequested` | publish request Item |
| running → streaming | `PublishResponseDelta` | first validated public delta exists | `ResponseStreamingStarted` | publish ordered deltas |
| running/streaming → waiting_approval | `RequestTurnApproval` | linked ToolCall/Mission policy is ask | `TurnApprovalRequested` | inline approval Item |
| running/streaming → waiting_input | `RequestTurnInput` | required clarification cannot be inferred | `TurnInputRequested` | checkpoint linked work |
| waiting_input → contextualizing | `ProvideTurnInput` | request open; input schema and actor valid | `TurnInputProvided` | recompile context |
| waiting_approval → running | `ResolveTurnApproval` | exact Approval approved and unexpired | `TurnApprovalResolved` | resume linked Mission |
| running/streaming → completed | `CompleteTurn` | linked action has verified public terminal result | `TurnCompleted` | persist final response Item |
| active → failed | `FailTurn` | fatal runtime/protocol error classified | `TurnFailed` | persist bounded error Item |
| active → cancelled | `InterruptTurn` | cancellation confirmed; unknown effects quarantined | `TurnCancelled` | stop streaming; keep completed Items |
| accepted/waiting → expired | `ExpireTurn` | TTL exceeded | `TurnExpired` | resolve pending requests as expired |

### 6.4 Step 状态机

状态：`proposed`、`ready`、`blocked`、`running`、`verifying`、`succeeded`、`failed`、`skipped`、`cancelled`。

| Transition | Command | Guard | Event | Side effect |
| --- | --- | --- | --- | --- |
| proposed → ready | `ReadyStep` | plan active; dependencies succeeded; capability reviewed | `StepReadied` | enqueue Attempt intent |
| proposed/ready → blocked | `BlockStep` | dependency/input/approval/freshness/budget unmet | `StepBlocked` | record structured blocker |
| blocked → ready | `UnblockStep` | exact blocker resolved; dependencies revalidated | `StepUnblocked` | enqueue Attempt intent |
| ready → running | `StartStep` | Attempt lease and reservation acquired | `StepStarted` | mark one active Attempt |
| running → verifying | `VerifyStep` | Attempt produced bounded Observation/Artifact | `StepVerificationStarted` | dispatch validator/verifier |
| verifying → succeeded | `AcceptStepResult` | schema, provenance and criteria pass | `StepSucceeded` | release unused reservation; unlock dependents |
| verifying → failed | `RejectStepResult` | fatal validation failure or attempts exhausted | `StepFailed` | record structured failure |
| proposed/ready/blocked → skipped | `SkipStep` | newer PlanVersion supersedes; explicit reason | `StepSkipped` | release reservations; do not dispatch |
| nonterminal → cancelled | `CancelStep` | Mission cancellation/plan removal; effects safe | `StepCancelled` | cancel pending attempts |

### 6.5 Attempt 状态机

状态：`created`、`leased`、`dispatching`、`awaiting_tool`、`validating`、`succeeded`、`failed`、`timed_out`、
`cancelled`、`orphaned`。

| Transition | Command | Guard | Event | Side effect |
| --- | --- | --- | --- | --- |
| created → leased | `ClaimAttempt` | atomic claim; fencing token monotonic | `AttemptLeased` | heartbeat starts |
| leased → dispatching | `DispatchAttempt` | context/capability/policy snapshots fixed | `AttemptDispatching` | persist outbox intent |
| dispatching → awaiting_tool | `AcknowledgeAttemptDispatch` | ToolCall/model invocation opened | `AttemptAwaitingTool` | supervise calls and timeout |
| awaiting_tool → validating | `ValidateAttempt` | required ToolCalls terminal/reconciled | `AttemptValidationStarted` | dispatch validator |
| validating → succeeded | `AcceptAttempt` | Step validator passes | `AttemptSucceeded` | notify Step reducer |
| validating → failed | `RejectAttempt` | validator failure classified | `AttemptFailed` | schedule retry or fail Step |
| active → timed_out | `ExpireAttempt` | wall/idle deadline exceeded; effect safe/quarantined | `AttemptTimedOut` | stop work; classify retry |
| active → orphaned | `OrphanAttempt` | lease heartbeat lost/fencing superseded | `AttemptOrphaned` | prohibit old worker writes |
| created/leased/awaiting_tool → cancelled | `CancelAttempt` | cancellation accepted; no unknown side effect | `AttemptCancelled` | cancel child calls |

### 6.6 ToolCall 状态机

状态：`proposed`、`policy_evaluating`、`waiting_approval`、`approved`、`denied`、`dispatched`、`acknowledged`、
`succeeded`、`failed`、`unknown`、`reconciling`、`cancelled`。

| Transition | Command | Guard | Event | Side effect |
| --- | --- | --- | --- | --- |
| ∅ → proposed | `ProposeToolCall` | tool id/args schema/context refs present | `ToolCallProposed` | none |
| proposed → policy_evaluating | `EvaluateToolPolicy` | catalog version/hash reviewed and healthy | `ToolPolicyEvaluationStarted` | run deterministic policy |
| policy_evaluating → approved | `AllowToolCall` | PolicyDecision is allow | `ToolCallApproved` | reserve policy snapshot |
| policy_evaluating → waiting_approval | `AskToolApproval` | PolicyDecision is ask | `ToolApprovalRequested` | create Approval and public Item |
| policy_evaluating/waiting_approval → denied | `DenyToolCall` | deny rule or human denial | `ToolCallDenied` | no outbox dispatch |
| waiting_approval → approved | `ConsumeToolApproval` | exact scope/hash approved and unexpired | `ToolApprovalConsumed`, `ToolCallApproved` | single-use consumption |
| approved → dispatched | `DispatchToolCall` | budget reserved; idempotency ledger/outbox committed | `ToolCallDispatched` | adapter receives request |
| dispatched → acknowledged | `AcknowledgeToolCall` | adapter returns external operation id | `ToolCallAcknowledged` | persist operation id |
| dispatched/acknowledged → succeeded | `CompleteToolCall` | response schema/provenance pass; effect confirmed | `ToolCallSucceeded` | create Observation |
| dispatched/acknowledged → failed | `FailToolCall` | definitive non-effect or safe failure | `ToolCallFailed` | release/reclassify budget |
| dispatched/acknowledged → unknown | `MarkToolEffectUnknown` | timeout/disconnect leaves effect uncertain | `ToolCallEffectUnknown` | block retry/completion |
| unknown → reconciling | `ReconcileToolCall` | reconciliation adapter available | `ToolCallReconciliationStarted` | query by external/idempotency id |
| reconciling → succeeded | `ConfirmToolEffect` | external system confirms effect/result | `ToolCallSucceeded` | create reconciled Observation |
| reconciling → failed | `ConfirmToolNonEffect` | external system confirms no effect | `ToolCallFailed` | allow classified retry |
| proposed/approved → cancelled | `CancelToolCall` | not dispatched | `ToolCallCancelled` | release reservation |

### 6.7 Approval 状态机

状态：`requested`、`pending`、`approved`、`denied`、`expired`、`revoked`、`consumed`。

| Transition | Command | Guard | Event | Side effect |
| --- | --- | --- | --- | --- |
| ∅ → requested | `RequestApproval` | policy is ask; complete immutable scope | `ApprovalRequested` | persist args/scope/policy hash and TTL |
| requested → pending | `PublishApproval` | request Item durably visible | `ApprovalPending` | notify authorized reviewers |
| pending → approved | `ApproveRequest` | reviewer authorized; request open/unexpired | `ApprovalApproved` | make exact scope consumable |
| pending → denied | `DenyRequest` | reviewer authorized | `ApprovalDenied` | unblock ToolCall as denied |
| pending → expired | `ExpireApproval` | TTL elapsed | `ApprovalExpired` | resolve UI request; deny dispatch |
| approved → consumed | `ConsumeApproval` | ToolCall policy/catalog/args hash exact; unused | `ApprovalConsumed` | atomically bind one ToolCall |
| approved → revoked | `RevokeApproval` | not consumed; reviewer/policy authorized | `ApprovalRevoked` | deny future consumption |

任何终态不可重新打开；重试必须创建新 Approval。

### 6.8 Delegation 状态机

状态：`proposed`、`accepted`、`running`、`handed_off`、`verifying`、`completed`、`rejected`、`failed`、
`cancelled`。

| Transition | Command | Guard | Event | Side effect |
| --- | --- | --- | --- | --- |
| ∅ → proposed | `ProposeDelegation` | typed role/objective/inputs/output/budget | `DelegationProposed` | none |
| proposed → accepted | `AcceptDelegation` | permission subset; depth/concurrency/budget/deadline valid | `DelegationAccepted` | reserve parent budget |
| accepted → running | `StartDelegation` | child Mission/Turn created and leased | `DelegationStarted` | dispatch child |
| running → handed_off | `SubmitHandoff` | structured Handoff schema valid | `DelegationHandedOff` | persist claims/evidence/conflicts |
| handed_off → verifying | `VerifyHandoff` | independent verifier available | `DelegationVerificationStarted` | dispatch evidence/risk verification |
| verifying → completed | `AcceptHandoff` | output contract and verifier gates pass | `DelegationCompleted` | append result to parent merge |
| proposed → rejected | `RejectDelegation` | scope/duplicate/depth/concurrency/budget invalid | `DelegationRejected` | no child dispatch |
| active → failed | `FailDelegation` | child fatal/timeout/retries exhausted | `DelegationFailed` | release budget; expose gap |
| active → cancelled | `CancelDelegation` | parent cancel/plan superseded; effects safe | `DelegationCancelled` | propagate cancel to child |

### 6.9 明确非法转移

| 非法转移 | 原因 | 系统响应 |
| --- | --- | --- |
| Mission `draft → running` | 跳过 success criteria、plan、policy | 409 + invariant event |
| Mission `running → completed` | 跳过独立 verification | 409；P0 评测失败 |
| Mission terminal → active | 破坏审计终态 | 新建 Mission/Turn，不复活 |
| Mission `paused → running` | 未重新检查 deadline/freshness/policy | 必须先 queued/ready |
| Step `proposed → succeeded` | 无 Attempt/Evidence | 拒绝 |
| Attempt `orphaned → succeeded` | 旧 worker fencing 已失效 | 丢弃写入并告警 |
| ToolCall `proposed → dispatched` | 绕过 catalog/policy/approval | 安全事件；零分 |
| ToolCall `unknown → dispatched` | 可能重复副作用 | 只能 reconcile |
| Approval `approved → approved` with wider scope | 批准不可扩权 | 新建 Approval |
| Approval `consumed → reused` | 防 replay | 原子唯一约束拒绝 |
| Delegation `handed_off → completed` without verifier | 自我声明完成 | 拒绝 |
| Turn `completed → streaming` | 终态后事件泄漏 | 断开流并报协议错误 |
| reducer version gap/duplicate conflicting idempotency | 状态不确定 | quarantine aggregate，禁止执行 |

---

## 7. Core schema draft

### 7.1 通用字段与 ID

- ID 使用不可预测、时间可排序的 ULID/UUIDv7，并带前缀：`thr_`、`turn_`、`mis_`、`plan_`、`stp_`、
  `att_`、`tcall_`、`obs_`、`evi_`、`art_`、`apr_`、`bud_`、`chk_`、`dlg_`、`rsp_`、`evt_`。
- 所有实体包含：`schema_version`、`status`、`tenant_id`、`created_at`、`updated_at`、`created_by`、
  `idempotency_key`（或不可变 `creation_command_id`）、`correlation_id`、`retention_class`、
  `redaction_class`、`metadata`（有大小/schema 上限）。
- 可变 projection 包含 `aggregate_version`；immutable record 包含 `content_hash`。
- 所有时间为 UTC RFC3339 + 数据源原始 event/as-of time；禁止只存“今天”“最新”。
- 不持久化 secret、provider credential、完整 private reasoning、无限原始 tool payload 或未脱敏 prompt。

### 7.2 Event envelope

```json
{
  "event_id": "evt_...",
  "event_type": "ToolCallSucceeded",
  "schema_version": 1,
  "aggregate_type": "tool_call",
  "aggregate_id": "tcall_...",
  "aggregate_version": 8,
  "thread_id": "thr_...",
  "turn_id": "turn_...",
  "mission_id": "mis_...",
  "causation_id": "cmd_...",
  "correlation_id": "corr_...",
  "idempotency_key": "tenant-scoped opaque key",
  "actor": {"type": "worker", "id": "worker_...", "role": "dispatcher"},
  "policy_snapshot_hash": "sha256:...",
  "payload": {},
  "payload_hash": "sha256:...",
  "occurred_at": "2026-07-16T00:00:00Z",
  "recorded_at": "2026-07-16T00:00:00Z"
}
```

### 7.3 核心实体

| Entity | 核心字段 | 关系与不变量 | 默认保留 |
| --- | --- | --- | --- |
| Thread | `thread_id`, owner, title, status, active_turn_id, context_epoch, summary_artifact_refs | has many Turn; 同一时刻最多一个普通 active Turn | 审计 7 年；可按租户政策归档 |
| Turn | `turn_id`, thread_id, status, input_item_ids, mission_links, context_pack_ref, response_id, client_message_id | belongs Thread；client_message_id 租户内幂等 | 7 年 |
| Mission | `mission_id`, objective, success_criteria, risk_class, permission_profile_id, deadline, active_plan_id, budget_id | 可跨 Turn；terminal 不复活 | 7 年 |
| PlanVersion | `plan_id`, mission_id, version, parent_plan_id, rationale_evidence_refs, steps, content_hash | immutable；每 Mission 仅一个 active version | 7 年 |
| Step | `step_id`, plan_id, type, objective, dependencies, output_contract, status, attempt_limit | DAG 无环；不能引用未来 Plan | 7 年 |
| Attempt | `attempt_id`, step_id, ordinal, status, worker_id, lease_token, fencing_token, started/ended, failure_class | 每次 retry 新建；旧 fencing token 无写权 | 2 年明细，摘要 7 年 |
| ToolCall | `tool_call_id`, attempt_id, capability_id/version/hash, args_hash, policy_decision_id, approval_id, idempotency_key, environment, side_effect_class, external_operation_id, status | dispatch 唯一；write unknown 阻断完成 | 7 年 |
| Observation | `observation_id`, tool_call_id, source_ref, source_type, observed_at, as_of, ingested_at, freshness_ttl, schema_ref, bounded_payload_ref, quality | 事实陈述必须带时间/来源；不可被 response 直接改写 | 按数据许可；摘要 7 年 |
| Evidence | `evidence_id`, claim_id, observation/artifact refs, stance, scope, confidence_method, verifier_id, valid_from/to | 支持/反对/不确定并存；不能只存总分 | 7 年 |
| Artifact | `artifact_id`, media_type, size, content_hash, storage_uri, producer, lineage, redaction | 内容寻址；数据库只存 bounded metadata/ref | 元数据 7 年；blob 按类别 30d–7y |
| Approval | `approval_id`, subject_type/id, requested_scope, args_hash, policy_hash, requester, reviewer, decision, expires_at, consumed_by | single-use；scope 不可扩大 | 7 年 |
| Budget | `budget_id`, limits, reserved, consumed, currency/token/tool/model/time/delegation dimensions | reserve-before-use；模型不能增加 | 7 年摘要；明细 2 年 |
| Checkpoint | `checkpoint_id`, aggregate cursor/version, reducer_version, context refs, inflight ids, reconciliation refs, content_hash | 不含 secret/private reasoning；恢复先校验 hash | 活动期 + 180d，审计摘要 7 年 |
| Delegation | `delegation_id`, parent_mission/step, child_mission, role, objective, input_refs, output_schema, capability_subset, budget_slice, deadline, status | 深度/并发/预算有上限；child 不继承额外权限 | 7 年 |
| OperatorResponse | `response_id`, turn_id, outcome, decision, claims, evidence_refs, unknowns, risk_disclosures, safe_next_actions, locale, content_hash | 每个事实 claim 必须有 Evidence 或标记 unknown | 7 年 |

### 7.4 重要辅助对象

- `Item`：`user_message`、`agent_message`、`plan_update`、`tool_call`、`approval_request`、`input_request`、
  `evidence_ready`、`warning` 等 tagged union；生命周期统一为 started/delta/completed。
- `Claim`：响应中最小可验证陈述，含 claim type、subject、predicate、object/value、unit、time scope、
  environment/account/symbol scope 和 Evidence refs。
- `PolicyDecision`：输入 snapshot、匹配规则、最终 allow/ask/deny、reason code、engine version；immutable。
- `IdempotencyLedger`：tenant + operation scope + key + request hash 唯一；相同 key 不同 hash 为 conflict。
- `OutboxRecord`：command/event 事务内写入；dispatch worker 使用 fencing 和 delivery attempts，不删除历史。

### 7.5 存储与隐私

1. PostgreSQL 保存事件、projection、索引和 bounded metadata；大 Artifact 使用对象存储/content hash。
2. 原始市场序列、交易明细和 BitPro 实体继续由事实源拥有；HyperTrade 存引用、时间、hash 和必要摘要。
3. 用户文本按租户 retention 分类；敏感账户/订单字段 tokenization，日志默认掩码。
4. private reasoning 不进入 event；只记录可公开的 plan rationale、decision reason code 和 verifier summary。
5. reducer 每次发布带版本；迁移通过离线 replay + hash compare，再切换读 projection。

---

## 8. Tool / permission / approval

### 8.1 Capability descriptor

每个工具版本必须是审核产物，而不是运行时从 MCP 自动发现后直接可用：

```yaml
capability_id: bitpro.backtest.read
version: 3
schema_hash: sha256:...
side_effect: read
data_class: trading_research
environments: [research, staging]
allowed_roles: [lead_researcher, strategy_analyst, evidence_verifier]
required_permission: strategy.backtest.read
input_schema_ref: schema://...
output_schema_ref: schema://...
timeouts: {connect_ms: 2000, total_ms: 15000}
retry_policy: {max_attempts: 2, classes: [transient]}
freshness: {max_age_seconds: 300}
idempotency: required
approval_mode: policy
result_limit: {rows: 200, bytes: 262144}
redaction_policy: trading_metadata_v1
source_contract: {requires_as_of: true, requires_source_id: true}
evidence_mapping: schema://evidence/backtest-summary-v1
health: {status: healthy, checked_at: "...", circuit: closed}
owner: {provider: bitpro, adapter: bitpro_mcp_v2, team: trading-platform}
```

### 8.2 确定性权限模型

Policy Engine 返回唯一的 `allow | ask | deny`，并记录所有匹配规则。建议使用结构化 ABAC/Rego 或等价
确定性引擎，输入至少包括：

| 维度 | 示例 |
| --- | --- |
| tool | `bitpro.paper.pause`, version/hash, side-effect class |
| args | amount, leverage, order type, time range, output size |
| symbol | `ETH-USDT-SWAP`, asset class, whitelist, liquidity tier |
| account | tenant/account id, ownership, risk tier, daily limits |
| environment | research/backtest/paper/testnet/live |
| path/resource | Artifact URI、sandbox path、外部 URL/MCP server |
| role | operator、lead、specialist、evidence verifier、risk verifier、service |
| context | Thread/Mission risk class、deadline、freshness、market status |

求值顺序：硬 deny（部署/主网/租户隔离）→ capability existence/review → schema → environment/account/symbol →
role/delegation subset → budget/rate → ask rules → allow。**deny 永远不能被 approval 覆盖**。

### 8.3 默认权限矩阵

| Capability class | Research | Backtest | Paper | Testnet | Live |
| --- | --- | --- | --- | --- | --- |
| market/reference read | allow | allow | allow | allow | allow（只读） |
| strategy metadata/read | allow | allow | allow | allow | allow（只读） |
| generate/validate strategy code | allow in sandbox | allow | deny | deny | deny |
| start deterministic backtest | ask/allow by budget | allow | deny | deny | deny |
| paper create/pause/close/reset | deny | deny | ask + operator | deny | deny |
| testnet order intent | deny | deny | deny | ask + risk + operator | deny |
| live account/position read | deny by default | deny | deny | deny | explicit read profile only |
| live order/capital write | deny | deny | deny | deny | **not deployed / hard deny** |

### 8.4 Approval contract

批准 UI 必须展示：动作、工具版本、标的、账户、环境、数量/杠杆、预期副作用、最大风险、数据时间、理由、
有效期、是否单次。批准者只能批准原请求，不能在批准时修改为更大 scope。

- `once`：默认，绑定一个 ToolCall args hash。
- `mission`：只允许低风险重复读或 paper 控制，并受时间/次数/参数 pattern 上限。
- 禁止“永久允许 live write”。
- 批准后 capability/policy/args/context 任何 hash 改变，都必须重新求值和批准。
- Approval 的 UI response 与 ToolCall dispatch 必须通过数据库原子消费关联，防止双击/重放。

### 8.5 Tool safety

- read 工具也要限制 symbol、time window、rows、payload bytes、URL/domain 和 freshness。
- 所有网络 adapter 使用 egress allowlist；MCP capability discovery 只进入 `pending_review`。
- Tool output 先做 schema、大小、secret/HTML/指令注入隔离，再形成 Observation；原始文本不能变成 system prompt。
- circuit breaker 状态必须持久化/共享，不以单进程内存作为生产真相。
- 写工具必须提供外部 idempotency key 或 reconciliation query；否则不得进入生产 Catalog。

---

## 9. Multi-agent protocol

### 9.1 目标

多 Agent 用于减少认知偏差和并行收集证据，不用于扩大权限或通过“多数投票”绕过风险。默认单 Agent；只有
任务可分解、并行收益大于协调成本且预算充足时才 delegation。

### 9.2 角色

| Role | 职责 | 明确禁止 |
| --- | --- | --- |
| Lead researcher | 分解目标、分配预算、合并可验证结果 | 自批工具、覆盖冲突证据 |
| Market data analyst | 行情、instrument identity、source health、freshness | 生成交易授权 |
| Technical analyst | 结构、指标、regime 与假设边界 | 把指标相关性写成因果事实 |
| News/sentiment analyst | 带发布时间/可得时间的事件与情绪证据 | 使用未来发布或无来源摘要 |
| Strategy researcher | 假设、实现约束、回测设计 | 使用未来数据、选择性删除失败 |
| Bull challenger | 有界提出支持论据和可证伪条件 | 无限争论或忽略反证 |
| Bear challenger | 有界寻找失败模式、反例和 regime 限制 | 以否定意见直接阻断 policy |
| Portfolio specialist | 相关性、暴露、组合稳健性 | 以单策略收益替代组合风险 |
| Evidence verifier | 独立检查 claim/source/time/entailment | 与生产者共享“通过”目标 |
| Risk verifier | 检查权限、风险、数据泄漏、执行边界 | 被 Lead 的多数意见覆盖 |

### 9.3 Delegation request

```json
{
  "delegation_id": "dlg_...",
  "parent_mission_id": "mis_...",
  "role": "strategy_specialist",
  "objective": "验证突破假设在三个市场阶段的稳健性",
  "input_refs": ["art_...", "evi_..."],
  "capability_subset": ["bitpro.backtest.read@3"],
  "permission_profile_id": "research_readonly_v1",
  "budget_slice": {"tokens": 30000, "tool_calls": 12, "wall_seconds": 180},
  "deadline": "...",
  "output_schema": "schema://handoff/strategy-evidence-v1",
  "acceptance_criteria": ["three_regimes", "no_lookahead_check", "source_refs"]
}
```

### 9.4 Structured handoff

Handoff 必须包含：`claims[]`、`supporting_evidence[]`、`opposing_evidence[]`、`unknowns[]`、`assumptions[]`、
`artifacts[]`、`methods[]`、`data_windows[]`、`freshness`、`budget_usage`、`recommended_next_action` 和
`confidence_method`。禁止只有“已完成/建议买入”的自由文本。

### 9.5 并发和故障边界

- 默认最大深度 2、每 parent 并发 4、总 child 8；由 Budget 配置而非模型修改。
- child 只能获得 parent 权限的交集和更小预算；不得继承 Approval。
- parent 取消时递归请求取消；已经 dispatch 的 write ToolCall 仍需 reconciliation。
- child 超时/失败不自动伪装为 unknown-free success；merge 中保留缺口。
- 同一事实源/方法的结果不算独立证据；verifier 必须检查来源相关性。

### 9.6 冲突保留

merge 不做简单多数票。对每个 claim 保存：支持 Evidence、反对 Evidence、来源独立性、时间范围、方法差异、
适用 regime 和 verifier decision。重大冲突只能：补充实验、缩小结论范围、标记 unknown 或请求人工复核；
不得由 Lead 静默覆盖。

---

## 10. Trading safety

### 10.1 数据时间与 no-lookahead

每个市场/策略 Observation 必须携带：`source_id`、`instrument_id`、`event_time`、`available_at`、`as_of`、
`ingested_at`、`timezone`、`revision_id`、`freshness_ttl`。训练/回测只能使用 `available_at <= decision_time` 的
数据。宏观、财务、指数成分和修订数据使用 point-in-time 版本；不能用最终修订值回填历史。

硬门禁：

- train/validation/test 时间窗口不重叠，walk-forward/embargo/purge 配置进入 Experiment Manifest；
- 特征、标签、归一化和 universe selection 都做 temporal leakage 测试；
- 手续费、滑点、资金费率、成交限制、停牌/缺失、延迟和容量进入确定性配置；
- dataset、strategy code、engine、container、seed、参数、calendar、source revision 全部 content hash；
- 相同 manifest 重跑必须在数值容差内相同，否则实验不可晋级。

### 10.2 研究晋级流水线

`hypothesis → data-quality gate → deterministic backtest → robustness/OOS → portfolio impact → human review →
paper observation → paper review → optional testnet approval`

任何阶段失败都保留负面 Evidence，不允许 winner-only memory。策略晋级不是 Mission `completed` 的同义词；
Mission 可以完成并得出“策略不通过”。

### 10.3 Backtest、paper 和风险门禁

| 阶段 | 必须满足 |
| --- | --- |
| Backtest | deterministic manifest、no-lookahead、成本/滑点、基准、OOS、样本量、失败实验留档 |
| Robustness | walk-forward、参数邻域、不同 regime、bootstrap/扰动、容量与流动性 |
| Portfolio | 相关性、边际风险、集中度、尾部、共同因子、已有组合冲突 |
| Paper | 固定版本 StrategyCard、实时 freshness、状态重启一致性、成交/滑点偏差、观察期 |
| Testnet | 独立 operator approval、账户/环境硬绑定、限额、kill switch、幂等与对账 |

### 10.4 执行权限物理分离

- Research/backtest worker 没有 paper/testnet/live 凭证。
- Paper mutation adapter 运行在独立 service identity，仅接受已批准的 structured command。
- Testnet adapter 使用独立账户和网络路由；不能通过 symbol 或 base URL 切换到 mainnet。
- Live read 与 live write 是不同 capability、service、credential 和部署单元。
- 当前版本不构建、不注入、不路由 live-write credential；Policy 的 deny 是第二道防线，不是唯一防线。

### 10.5 紧急控制

kill switch 是确定性控制面命令，不依赖模型：停止新 dispatch、撤销未消费 Approval、取消可取消工作、隔离
unknown writes、触发 account reconciliation，并生成 operator incident response。恢复需要新 policy snapshot
和人工授权。

---

## 11. Evaluation matrix and quantitative gates

### 11.1 评测层级

| 层级 | 评测对象 | 示例 |
| --- | --- | --- |
| Schema/property | 状态机、ID、幂等、reducer | 随机命令序列不能产生非法终态 |
| Component | planner/policy/context/verifier/tool adapter | denied args 永不 dispatch |
| Protocol contract | Thread/Turn/Item/API/SSE | start/resume/replay/interrupt/approval |
| Integration | worker/store/outbox/lease/reconciliation | crash at every boundary |
| Surface E2E | CLI/Web/TUI/Desktop | 同一 Thread 得到同一 target/evidence/terminal |
| Trading eval | temporal data/backtest/paper | leakage、freshness、determinism、risk |
| Adversarial | prompt/tool injection、scope confusion | 不扩权、不把工具文本当指令 |
| Production canary | 只读代表性请求 | latency、truthfulness、no legacy writes |

### 11.2 可观测性指标

每个指标按 protocol version、surface、intent、capability、provider、environment 和 risk class 分组；禁止把
prompt、private reasoning、secret 或完整原始 tool payload 写入 label/log。

| Metric | 定义 |
| --- | --- |
| `task_success_rate` | verifier 通过且 OperatorResponse 满足目标的 Turn/Mission 比例 |
| `grounded_claim_rate` | 有有效 Evidence 的公开 factual claim / 全部公开 factual claim |
| `correct_tool_selection_rate` | gold/contract 允许集合内的必要 capability 选择比例 |
| `false_completed_count` | completed 后被 verifier/eval 证明目标未满足的数量 |
| `unsafe_dispatch_count` | hard deny、scope 越界或缺批准仍 dispatch 的数量 |
| `duplicate_side_effect_count` | 同一逻辑 operation 出现多次外部 effect 的数量 |
| `recovery_success_rate` | 故障后在 RTO 内恢复且无丢失/重复副作用的比例 |
| `approval_bypass_count` | 缺失、过期、扩大或重复消费 Approval 的 dispatch 数量 |
| `stale_data_claim_count` | 使用超过 freshness/available-time 边界的公开 claim 数量 |
| `first_useful_event_latency` | TurnAccepted 到首个进度/证据/回答 Item 的时间，而非心跳 |
| `mission_completion_latency` | MissionQueued 到 verified terminal 的分位延迟 |
| `budget_adherence_rate` | 未超过 token/tool/cost/time/retry/delegation 上限的比例 |

同时记录 queue depth、backpressure reject、lease loss、orphan Attempt、ToolCall unknown/reconciliation、
source health/circuit、context inclusion/drop reason、SSE reconnect/replay gap 和 child conflict count。trace 只使用
稳定 ID 和 bounded summaries，支持从 OperatorResponse → Evidence → Observation → ToolCall → Attempt → Step →
Mission → Turn 的双向追踪。

### 11.3 故障注入矩阵

至少覆盖：provider 在首 token/中途/末尾断开；SSE 断开和 cursor replay；worker 在 lease 前、dispatch intent 后、
external ack 前后、event commit 前后崩溃；lease 丢失；DB deadlock；outbox 重投；MCP timeout/乱序/重复；
Approval 双击/过期/撤销；context compaction；stale market data；symbol/account/environment 混淆；write effect
unknown；child Agent 超时/冲突；sandbox OOM/CPU/wall limit；BitPro schema/version 漂移。

### 11.4 硬零分条件

一次出现即本次发布失败：

- false `completed`；
- unsafe dispatch；
- approval bypass/reuse/scope widening；
- duplicate external side effect；
- ungrounded visible factual claim；
- 错误 symbol/account/environment 上的操作；
- lookahead/temporal leakage；
- 主网 live write 路径可达。

### 11.5 量化门禁

| Metric | 发布门槛 |
| --- | --- |
| false completed | 0 / ≥500 completion and fault cases |
| unsafe/approval bypass/duplicate side effects | 0 / 全部故障注入 |
| ungrounded visible claims | 0；每个 factual claim 有有效 Evidence 或明确 unknown |
| critical entity resolution（symbol/account/env/action） | 100% |
| 一般多轮 referent accuracy | ≥99.5% |
| state-machine invariant violations | 0 / property test ≥100k command sequences |
| event replay projection equality | 100%，hash 与 online projection 一致 |
| SSE terminal/replay correctness | ≥99.9% fault runs，CI contract cases 100% |
| worker recovery | RTO p95 <60s；0 committed event loss |
| boundedness | 100% 遵守 token/tool/time/retry/delegation 上限 |
| backtest temporal leakage | 0 |
| deterministic rerun | 100% 在预声明数值容差内 |
| source time/freshness contract | 100% trading observations |
| single-tool read latency | 当前基线 2.97–8.23s；目标 p95 <20s，首个 ack p95 <500ms |
| legacy write delta on migrated slice | 0 |

### 11.6 真实任务集改造

- 保留现有 100 题作为 regression cohort，但不再手工注入 context 作为唯一多轮测试。
- 每个任务必须通过实际 surface 创建 Thread，再按 Turn 发送；断言 resolved subject/symbol/account/env。
- response 断言从 substring 升为 claim/evidence entailment 和 source freshness。
- 每次生产故障都加入 held-out case；开发者不能通过只修改期望文本使其通过。
- evaluator、fixtures 和 runtime 分离版本；发布报告注明覆盖范围，不再把 100/100 写成整体 production grade。

---

## 12. Vertical cutover

### 12.1 原则

不做 big bang，也不允许永久双写。每个 slice 选择一个**完整用户路径**，从 surface、协议、状态、worker、
事件、projection 到评测全部切换；旧路径只读兼容并设置删除日期。

### 12.2 切换顺序

| Slice | 范围 | 进入条件 | 退出/删除条件 |
| --- | --- | --- | --- |
| A | Remote CLI `ht ask/chat`：Thread/Turn/Item + read-only Mission | 新 event/reducer/schema 完成 | CLI 不写 Run/Task、不传 prior_turns；双轮/SSE/fault gates 通过 |
| B | Web natural-language workspace | A 稳定；Web contract test | 删除 Web 对 run projection 的完成判断 |
| C | Desktop | B 稳定；Tauri protocol versioning | 删除最近 8 条用户文本和 legacy SSE adapter |
| D | Textual TUI | canonical list/detail/control ready | 删除 Task fallback view/model |
| E | Mission runtime loop | surface 统一 | Context 真消费、Verifier/Completion、Checkpoint/Approval 接入；删除旧 runtime branch |
| F | Multi-Agent research | 单 Agent invariant/eval 稳定 | 真实 child Mission/Handoff/Verifier；删除 production canned worker |
| G | Paper/Testnet controlled writes | reconciliation/approval/risk 100% | 只开放合同明确的操作；live write 继续缺席 |

### 12.3 单 slice 写入规则

1. 新 API 写新 aggregate/event/projection。
2. legacy adapter 可从新 projection **读取并降级展示**，但不得反向写旧 Run/Task。
3. 不对同一用户命令同时写新旧模型；迁移审计通过 `legacy row delta = 0` 证明。
4. backfill 仅迁移只读历史索引，不伪造缺失 event。
5. slice 通过后在下一 Sprint 删除兼容代码；canary 仅用于短期流量切换，有明确截止日。

### 12.4 回滚

回滚是把该 surface 暂时标记 unavailable/read-only，或回到上一协议版本的只读客户端；不是恢复 legacy
写路径。已提交的新 event 永不删除。schema 采用 expand → switch → contract，projection 可由 event 重建。

---

## 13. First minimal sprint contract

第一个 Sprint 只解决一个基础问题：让 Remote CLI 的两轮自然语言会话由服务端 Thread/Turn 真相驱动，并
证明事件可重放、SSE 可恢复、Mission 可关联、旧表没有新写入。详细可执行合同见
[Sprint 121 — Canonical Thread/Turn Protocol](../contracts/sprint-121-canonical-thread-turn-protocol.md)。

### 13.1 In scope

- 最小 `Thread`、`Turn`、`Item`、event envelope、reducer 和 projection 表/领域模型。
- `POST /api/agent/v1/threads`、`POST /threads/{id}/turns`、read/list 与 cursor event stream。
- Remote `ht ask/chat` 使用新协议；`chat` 在一个 Thread 内连续 Turn，`ask` 可使用 ephemeral/单 Turn Thread。
- Turn 在服务器从 persisted Items 编译 context，不接受 `prior_turns`。
- Turn 可创建/关联现有 read-only Mission，并把 Mission delivery 转成 canonical Items。
- 断连 replay、interrupt、idempotency、event reducer hash、worker crash 基础测试。
- migrated CLI 路径的 `AgentRun`/`AgentTask` 写入计数必须为零。

### 13.2 Out of scope

- Web/TUI/Desktop 迁移；
- 通用多 Agent；
- paper/Testnet/live 写能力；
- 完整参数级 Approval UI；
- 旧历史事件伪造/backfill；
- 自动学习或策略自主晋级。

### 13.3 Acceptance gates

1. 真实 CLI 连续问“比较 A 和 B”→“后者最大回撤？”时，resolved entity 精确为 B，并在 Turn projection
   和 Evidence 中可验证。
2. 同一 client message/idempotency key 重发只创建一个 Turn；不同 payload 冲突返回 409。
3. 任意 event cursor 断开后重连不丢、不重复 terminal Item；没有 `final` 的 EOF 视为失败。
4. event log 离线 reducer 结果与 online Thread/Turn projection hash 完全一致。
5. worker 在 dispatch 前后崩溃不会产生重复 tool call；本 Sprint 只允许 read-only capability。
6. migrated CLI 的 legacy Run/Task row delta = 0；删除/禁用 remote CLI legacy fallback。
7. false completed、unsafe dispatch、ungrounded factual claim 均为 0。
8. `./scripts/check.sh`、focused protocol/property/fault tests 和真实 CLI E2E 全部通过。

### 13.4 Sprint 完成后才能开始的下一步

只有上述门禁通过，才迁移 Web。不能在 Sprint 121 同时添加更多 Agent 角色、更多交易工具或策略研究功能，
否则会继续扩大不一致协议的表面积。

---

## Architecture trade-offs

1. **事件协议增加初期复杂度，换取可恢复和可证明的一致性。** 对交易 Agent 来说，这比继续在 projection
   上补状态字段更便宜。
2. **确定性 policy/verifier 限制模型自由，换取权限和完成语义可审计。** 模型仍可提出假设与计划，但不能
   自证完成或自授权限。
3. **vertical cutover 会暂时让不同 surface 处于不同协议版本，换取无永久双写的低风险迁移。** 每个 slice
   都必须设置兼容删除日期。
4. **多 Agent 默认为按需而非全开，牺牲“看起来更自主”的演示效果，换取成本、冲突和风险可控。**
5. **当前不部署 live write，牺牲端到端实盘自治，换取在研究和模拟阶段建立可信基础。**
