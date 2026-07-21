# 33 HyperTrade 系统架构

> 状态：当前实现快照（2026-07-21），不是下一代架构完成声明。Remote CLI 与 Web natural-language workspace
> 已实现 canonical Thread/Turn/Item 垂直切片；其他 surface 仍有 Run/Task/Mission 双路径和客户端上下文差异。目标架构与切换计划见
> [34 下一代专业 Agent Runtime](34-next-generation-agent-runtime-audit-and-target-design.md)。历史路线图与
> 逐 Sprint 设计见 [30 Professional Agent Runtime V2 路线图](30-professional-agent-runtime-v2-roadmap.md)
> 和 [31 Professional Agent Runtime V2 技术设计](31-professional-agent-runtime-v2-technical-design.md)。

## 1. 系统定位

HyperTrade 是一个自托管、受治理的加密市场研究 Agent Runtime。它把开放式研究目标转为可恢复的
Mission，并在明确的权限、预算、证据和人工复核边界内，调用市场、知识、策略、回测、模拟盘和
Testnet 状态的受控能力。

它不是“自动赚钱机器”，也不承诺稳定盈利或提供投资建议。策略研究结论必须保持证据、数据缺口和
适用条件；主网下单不在当前范围内。

| 系统 | 拥有的事实与职责 | 明确不拥有的职责 |
| --- | --- | --- |
| HyperTrade | Agent Mission、计划、工具治理、证据投影、研究编排、审计、人工复核与交付 | 复制交易平台业务规则、绕过外部风险控制、自动分配资本 |
| BitPro | 市场/参考数据、策略存储、回测、模拟盘与交易系统状态 | HyperTrade 的 Agent 状态、模型规划或证据账本 |
| OKX 与其他外部数据源 | 行情、交易所状态及其原始时间戳 | HyperTrade 内部的研究结论或权限决策 |
| 人类操作员 | 目标、约束、批准、复核、风险承担 | 将权限或证据判断完全委托给模型 |

HyperTrade 只能通过稳定的 MCP/API 合同使用 BitPro。它不直接读取 BitPro 数据库，也不把 BitPro
的策略、回测或执行业务逻辑复制进自身代码库。

## 2. 架构原则

1. **Mission 是研究任务的目标真相源，Thread 是 Remote CLI/Web 的交互真相源。** Remote `ht ask/chat` 与 Web 由
   server-owned Thread/Turn/Item、versioned event 和 deterministic reducer 驱动，并显式关联只读 Mission；
   Desktop、TUI、Local CLI 仍保留 AgentTask/AgentRun/AgentKernel 兼容分支，Web 仅保留 legacy history 读取。
2. **模型不能扩大权限。** 模型只可提出受 schema 限制的计划或输入；Capability Catalog、Tool Policy、
   Approval 与风险门禁在调用前后独立验证。
3. **结论必须可追溯。** 默认操作员答案只显示结论、置信度、证据、未知项和安全下一步。模型文字、
   工具原始输出或“我已完成”的声明本身不能完成 Mission。
4. **数据不足时显式失败。** stale、不可用、冲突、超预算或未审批状态会成为 `waiting_input`、
   `waiting_approval`、`needs_review` 或受分类的失败，绝不由模型补造事实。
5. **Remote CLI 与 Web 只投影服务端状态，其他 surface 尚未完成切换。** 两者只提交
   `thread_id + input + client_message_id`，使用 cursor SSE 恢复；Desktop 仍提交最近用户文本，
   Local CLI/TUI 仍有本地/legacy fallback。统一 surface 投影属于 architecture 34 的后续 vertical cutover。
6. **副作用最小化。** 当前 Mission Catalog 只暴露受治理的读取能力；任何后续 paper、Testnet 或
   live 写能力仍须独立的审批、幂等、风险和产品合同。

## 3. 系统上下文

~~~mermaid
flowchart LR
  Operator["操作员 / 外部 Agent"]
  Surfaces["Web · CLI · Textual TUI · Desktop<br/>REST / SSE"]
  API["FastAPI Mission Control API"]
  Worker["SQL-leased Mission Worker"]

  subgraph Runtime["HyperTrade Professional Agent Runtime"]
    Mission["Mission / Plan / Step / Event"]
    Loop["Adaptive Loop<br/>plan → context → execute → validate"]
    Catalog["Reviewed Capability Catalog<br/>Governed Tool Executor"]
    Context["Context Pack + Artifact Index"]
    Team["Bounded Multi-Agent Supervisor"]
  end

  DB[("PostgreSQL + pgvector<br/>canonical projections & audit")]
  External["OKX · RAG · Memory<br/>BitPro MCP/API · local read models"]
  Sandbox["Digest-bound strategy sandbox<br/>UDS · non-root · no network"]
  Eval["Physically isolated evaluation target"]
  Observability["Domain events · metrics · safe telemetry"]

  Operator --> Surfaces --> API
  API --> Mission
  API --> DB
  Worker --> DB
  Worker --> Loop
  Mission --> Loop
  Loop --> Context
  Loop --> Catalog
  Loop --> Team
  Catalog --> External
  Context --> DB
  Team --> Catalog
  Loop --> DB
  API --> Sandbox
  Sandbox --> DB
  Loop --> Observability
  Eval -. separate network, database and facts .-> API
~~~

上述图是控制面，不是交易执行拓扑。外部数据与 BitPro 仍是各自领域的事实源；HyperTrade 只保存
受界限的引用、摘要、哈希、指标和审计投影，而非秘密、完整原始序列、完整 prompt 或私有推理。

## 4. 运行时分层

| 层 | 主要组件 | 职责 |
| --- | --- | --- |
| Operator surfaces | React `/harness/missions`、`ht`、Textual、Tauri desktop、REST/SSE | 创建与查看 Mission，发送带理由和幂等键的控制动作，投影公开交付与审计事件 |
| Control plane | FastAPI、认证、Mission REST/SSE、Idempotency | 验证身份和请求，提供 cursor replay；不在浏览器或 CLI 中保存工作流真相 |
| Domain | `runtime/domain` | Mission、Plan、Step、预算、Capability、Context、Artifact、Supervisor 与 Sandbox 的严格 Pydantic 合同和状态机 |
| Application | `runtime/application` | ingress 安全分类、Mission loop、OperatorResponse、服务组合与评测隔离入口 |
| Ports | `runtime/ports.py` | Mission store、planner、context、catalog、executor、sandbox 等依赖的稳定 protocol |
| Adapters | `runtime/adapters` | PostgreSQL/内存存储、Capability Catalog、受治理工具执行、上下文/产物、Supervisor、UDS sandbox 与 provider/connector 适配 |
| Data & integrations | PostgreSQL/pgvector、OKX、RAG、Memory、BitPro MCP/API | 保存 canonical Mission projection；以有健康度、schema 和来源信息的合同接入外部事实 |
| Operations | Docker Compose、Nginx、GitHub Actions、`deploy/`、隔离评测 | 部署、健康检查、迁移、监控与可重复的安全/质量验证 |

代码组织遵循模块化单体与 ports-and-adapters：`runtime/domain` 不依赖 FastAPI、SQLAlchemy、LLM
provider、MCP 或交易平台。外部实现只能位于 adapter 边界，从而能在不改变 Mission 领域规则的前提下
替换 provider、存储或数据源。

## 5. Mission 生命周期与一致性

~~~mermaid
sequenceDiagram
  participant O as 操作员
  participant C as Control API
  participant S as Mission Store
  participant W as Mission Worker
  participant R as Runtime
  participant X as Capability Adapter

  O->>C: 创建 / steer / control（认证、理由、Idempotency-Key）
  C->>S: 原子写入 Mission projection + append-only event
  W->>S: SQL lease claim + heartbeat
  W->>R: 加载 Mission 与活动 Plan
  R->>R: ingress / budget / permission / dependency check
  R->>R: 编译可复现 Context Pack
  R->>R: 生成参数绑定的 PolicyDecision，必要时等待一次性 Approval
  R->>S: 外部写前原子提交 DispatchIntent + ToolCall
  R->>X: 数据库事务外执行 adapter
  X-->>R: bounded ToolObservation + provenance
  R->>S: 写 ack/terminal；歧义结果写 effect_unknown 并对账
  R->>S: 验证 observation，写 attempt/event/artifact refs
  alt 假设被否定且仍有预算
    R->>S: 写不可变 Plan diff 并激活新版本
  else 需要人工或输入
    R->>S: waiting_approval / waiting_input 事件
  else 完成条件已验证
    R->>S: CompletionProofV1(pass) + completed + OperatorResponse
  end
  S-->>C: cursor event stream
  C-->>O: 公共答案或审计事件
~~~

新建 Mission 的 V2 domain event 和 projection 在同一个数据库事务中更新。Worker 以 PostgreSQL
lease/heartbeat 和 fencing token 领取可执行 Mission，默认硬上限由服务端 schema 强制。Mission、Plan、
Attempt、usage、current step、steer 和 terminal delivery 都由同一 reducer 投影；离线重放 hash 必须与线上
projection hash 一致。版本 gap、冲突重复、未知 schema/reducer 或 stale fencing event 会使 aggregate
quarantine。旧 Mission 明确标记为 `legacy_non_replayable`，不会以伪造事件补齐历史。

## 6. 研究与数据流

1. 操作员描述研究目标、成功条件和约束，或由受配额的已提交事实触发研究。
2. ingress 分类器先阻断主网执行、未批准/高杠杆 Testnet 请求和明确陈旧数据；这些请求在模型或工具
   调用之前结束或等待人工处理。
3. Planner 只能从已审核的 Capability Catalog 选择 capability id；发现的 MCP/OpenAPI 能力先成为
   `pending_review`，不会自动进入生产 allowlist。
4. Context Engine 按固定优先级编译目标、权限、Plan/Step 合同、依赖 observation、Evidence、Memory、
   RAG 与 Artifact 引用。它记录保留、压缩、丢弃和原因，且不会把完整对话或原始交易序列拼入 prompt。
5. Governed Tool Executor 以 schema、policy hash、side-effect 分类、健康度、超时、circuit 与幂等约束
   调用 adapter；返回值再次验证并截断/脱敏。
6. Validator 只接受带 source 或 Artifact ref 的 observation。可恢复故障、未知项、证据冲突和过期输入
   保留在账本中；重要假设失效时再产生有上限的 Plan diff，而不是无限重试。
7. Mission 完成后，`OperatorResponseV1` 输出有证据约束的结论和安全下一步。深入的 Plan、步骤、预算、
   工具和审批信息在授权审计视图中查看，不混入默认答案。
8. 已结算研究事实可以追加为 `StrategyOutcomeV1`；它引用策略版本、数据/成本窗口、Evidence、当前完成证明和
   已确定 effect，不复制原始行情/订单。多个 Outcome 只能生成待审核 Lesson，冲突与反对证据必须保留。
9. 只有 reviewed active Lesson 可作为有界 Context source；它不能替代当前市场/BitPro Evidence，也不会自动
   修改 Memory、Skill、Strategy、PortfolioPolicy 或任何执行权限。

策略研究复用既有的 Evidence、Experiment Manifest、StrategyCard、robustness 和 Portfolio
projections。它们是研究事实和复核材料，不是自动执行授权；BitPro 负责策略和回测系统事实，
HyperTrade 不持久化 BitPro 的完整蜡烛、权益、交易、订单或持仓序列。

## 7. 安全与治理边界

| 边界 | 实现方式 | 失败行为 |
| --- | --- | --- |
| 权限 | read-only Mission profile、Capability side-effect 分类、Tool Policy、Approval/Risk gate | 缺少匹配权限或批准时拒绝 dispatch |
| 输入与输出 | Pydantic v2 + JSON Schema、policy/contract hash、来源绑定 | schema 或来源不匹配时记录分类失败 |
| 预算与并发 | 事务性 token/tool/model/duration reservation、AnyIO bounded concurrency | 无剩余预算时停止或形成降级交付 |
| 审计与重放 | V2 Mission events、deterministic reducer、projection hash、idempotency、SSE cursor | gap、冲突、未知版本或 stale fencing 会 quarantine；旧记录为 `legacy_non_replayable` |
| 外部副作用 | 参数/版本/policy 绑定的一次性 Approval、write-ahead DispatchIntent、持久 ToolCall/circuit/reconciliation | deny 不可覆盖；超时进入 `effect_unknown` 且不自动重发，未对账时阻止完成 |
| 策略学习 | 不可变 Outcome、append-only correction、reviewed Lesson、support/opposition/validity | 未结算、过期来源、unknown effect 或未审核 Lesson 不进入学习上下文 |
| 数据保护 | redaction、结果大小限制、metadata-first artifacts | 不保存凭据、原始工具结果、完整 prompt 或私有推理 |
| 策略代码 | UDS isolated sandbox、非 root、无网络、只读根、无 Docker socket、资源限制、digest 绑定 | socket/digest 不可用时生产返回 503，绝不回退到 API/宿主子进程 |
| 评测 | 独立 API、数据库、网络和合成事实；生产禁用 fixture | 评测产物不进入生产事实，也不授予交易权限 |

当前系统不启用 mainnet 订单执行。任何未来的 Paper、Testnet 或 live 写能力必须以新的 capability、
审批、幂等、风险、审计和独立验收合同接入，不能由 Mission Planner、Supervisor 或 UI 自行开放。

## 8. 部署与运行模型

生产使用 Docker Compose、Nginx 与 GitHub Actions 的 `main` 分支部署流程。PostgreSQL 同时保存 Mission
存储/event/lease/projection 和 legacy AgentRun/AgentTask/Session 表；它是单一数据库，不等于单一领域
状态模型。当前没有 Celery、Redis、Kafka 或第二套任务队列。Alembic 迁移在服务启动前执行，
`/api/health`、容器健康检查和部署 smoke 用于确认服务状态。

重要运行约定：

- 新部署默认以 fail-closed feature flags 启动；生产启用必须经过对应 Sprint Gate 和可回滚发布验证。
- Mission worker 使用 SQL lease；当 worker 功能关闭或租约不可领取时，不应由 API 或客户端绕过其控制面。
- Mission API 的控制动作需要认证、理由和幂等键；客户端可通过 `after` 或 `Last-Event-ID` 重放事件。
- 隔离 evaluation target 具有独立网络、数据库和合成事实，不能使用生产 BitPro 数据、凭据或执行路径。
- 部署运行手册、BitPro 接入与故障排查位于 [docs/runbooks](../runbooks/)。

## 9. 面向贡献者的变更准则

在修改系统时，以以下顺序判断：

1. 新行为属于 Mission、研究事实、外部 adapter，还是纯客户端投影？
2. 是否可以由现有的稳定 port/contract 接入，而不是把外部业务逻辑复制进 HyperTrade？
3. 是否有明确的 source/artifact、schema、健康度、预算、权限、超时和幂等语义？
4. 失败时是否保留可审计的 unknown/分类错误，而不是生成看似完整的结论？
5. 是否更新对应的 Product Spec、architecture、Sprint contract、progress、测试和部署验证？

每个有意义的实现改动都应运行 `./scripts/check.sh`。当前 Sprint 状态和已验证的生产证据以
[Progress Log](../progress.md) 与 active contract 为准，不能仅凭 README 或聊天记录判断。

## 10. 相关文档

- [架构总览](00-overview.md)：架构文档入口。
- [可视化架构图](19-hypertrade-architecture-diagram.md)：面向讨论的层次图。
- [Professional Agent Runtime V2 路线图](30-professional-agent-runtime-v2-roadmap.md)：设计动机、Sprint 路线与保留/重构原则。
- [Professional Agent Runtime V2 技术设计](31-professional-agent-runtime-v2-technical-design.md)：Mission、Catalog、Context、Supervisor、Sandbox 和 cutover 的实现细节。
- [产品规格](../spec.md)：产品范围、用户旅程、验收与非目标。
- [开发者指南](../developer-guide.md)：本地开发与扩展入口。
- [部署与运行手册](../runbooks/)：部署、监控、BitPro MCP 与事件响应。
