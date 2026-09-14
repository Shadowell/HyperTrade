# 33 HyperTrade 系统架构

> 状态：当前实现快照（2026-09-14），不是下一代架构完成声明。本次刷新覆盖自上一版（2026-07-21）以来上线的
> 自主研究循环（AVO）、默认开启的自主进化引擎、可插拔市场目标与组合（篮子）研究支持。Remote CLI 与 Web 已实现
> canonical Thread/Turn/Item 垂直切片；目标架构与切换计划见
> [34 下一代专业 Agent Runtime](34-next-generation-agent-runtime-audit-and-target-design.md)，历史路线图见
> [30 Professional Agent Runtime V2 路线图](30-professional-agent-runtime-v2-roadmap.md) 与
> [31 Professional Agent Runtime V2 技术设计](31-professional-agent-runtime-v2-technical-design.md)。

## 1. 系统定位

HyperTrade 是一个自托管、受治理的量化策略研究 Agent Runtime。它把开放式研究目标转为可恢复的
Mission，在明确的权限、预算、证据和复核边界内，驱动自主研究循环产出候选策略，经隔离沙箱自测、同窗基线
对比与对抗审查后进入 BitPro 模拟盘孵化；并在生产上持续运行默认开启的自主进化引擎，对孵化中的策略做退化
扫描与再研究。

它不承诺盈利、不提供投资建议。策略研究结论必须保留证据、数据缺口和适用条件；主网下单不在当前范围内，
唯一的外部写路径是 BitPro 模拟盘。

| 系统 | 拥有的事实与职责 | 明确不拥有的职责 |
| --- | --- | --- |
| HyperTrade | Agent Mission、计划、工具治理、证据投影、自主研究与进化编排、审计、复核与交付 | 复制交易平台业务规则、绕过外部风险控制、自动分配资本 |
| BitPro | 市场/参考数据、策略存储、回测、模拟盘与交易系统状态 | HyperTrade 的 Agent 状态、模型规划或证据账本 |
| 市场目标适配层 | `market_target.v1` 档案与 `market-evolution.v1` MCP 契约；BitPro 是第一个目标 | 平台业务逻辑；适配层只做契约翻译与能力声明 |
| OKX 与其他外部数据源 | 行情、交易所状态及其原始时间戳 | HyperTrade 内部的研究结论或权限决策 |
| 人类操作员 | 目标、约束、批准、复核、风险承担 | 将权限或证据判断完全委托给模型 |

HyperTrade 只能通过稳定的 MCP/API 合同使用 BitPro。它不直接读取 BitPro 数据库，也不把 BitPro
的策略、回测或执行业务逻辑复制进自身代码库。

## 2. 架构原则

1. **Mission 是研究任务的目标真相源，Thread 是 Remote CLI/Web 的交互真相源。** Remote `ht ask/chat` 与 Web 由
   server-owned Thread/Turn/Item、versioned event 和 deterministic reducer 驱动，并显式关联只读 Mission；
   Desktop、TUI、Local CLI 仍保留 AgentTask/AgentRun/AgentKernel 兼容分支。
2. **模型不能扩大权限。** 模型只可提出受 schema 限制的计划或输入；Capability Catalog、Tool Policy、
   Approval 与风险门禁在调用前后独立验证。
3. **结论必须可追溯。** 默认操作员答案只显示结论、置信度、证据、未知项和安全下一步。模型文字、
   工具原始输出或"我已完成"的声明本身不能完成 Mission。
4. **数据不足时显式失败。** stale、不可用、冲突、超预算或未审批状态会成为 `waiting_input`、
   `waiting_approval`、`needs_review` 或受分类的失败，绝不由模型补造事实。退化判定、效果账本与
   基线对比同理：回退口径与无效对比必须标注并单独计数。
5. **自主进化默认开启，但始终受治理。** 进化引擎在预算（`research_budget.v1` 准入）、证据（预检与
   延续记录）与评审（human/agent 政策）门禁内行动；它不能扩大自身权限、不能绕过审批发起模拟盘写操作。
6. **市场目标可插拔。** 进化核心不绑定交易平台；新市场通过实现 `market-evolution.v1` MCP 契约接入，
   账本、告警、元学习与效果评估自动继承。
7. **组合是一等公民。** 篮子策略从扫描、研究、自测、基准到模拟盘全程保持声明标的集合的完整，
   进化过程不允许把组合静默缩成单标的。
8. **副作用最小化。** 当前 Mission Catalog 只暴露受治理的读取能力；模拟盘写能力经由独立的预授权、
   审批、幂等与产品合同，主网写能力仍被产品边界禁用。

## 3. 系统上下文

~~~mermaid
flowchart LR
  Operator["操作员 / 外部 Agent"]
  Surfaces["Web · Remote CLI · Textual TUI · Desktop<br/>REST / SSE"]
  API["FastAPI Mission Control API<br/>Mission · Thread/Turn · ARC · Evolution"]
  Worker["SQL-leased Worker Loops<br/>Mission · AVO 研究 · 进化 · 自动评审 · 元学习"]

  subgraph Runtime["HyperTrade Agent Runtime"]
    Mission["Mission / Plan / Step / Event"]
    Loop["Adaptive Loop<br/>plan → context → execute → validate"]
    Research["ARC 自主研究循环（AVO）<br/>假设 → 候选 → 自测 → 基线 → 对抗 → Paper 评审"]
    Evolution["自主进化引擎<br/>退化扫描 → 预算准入 → 再研究 → 账本 → 告警"]
    Catalog["Reviewed Capability Catalog<br/>Governed Tool Executor"]
    Context["Context Pack + Artifact Index"]
  end

  Targets["市场目标适配层<br/>market_target.v1 · market-evolution.v1"]
  DB[("PostgreSQL + pgvector<br/>canonical projections & ledgers")]
  BitPro["BitPro（首个市场目标）<br/>回测 · 模拟盘 · 策略存储"]
  External["OKX · RAG · Memory · 本地只读模型"]
  Sandbox["Digest-bound 策略沙箱<br/>UDS · non-root · no network"]
  Eval["物理隔离的评测目标"]

  Operator --> Surfaces --> API
  API --> Mission
  API --> DB
  Worker --> DB
  Worker --> Loop
  Worker --> Research
  Worker --> Evolution
  Mission --> Loop
  Loop --> Context
  Loop --> Catalog
  Catalog --> External
  Research --> Sandbox
  Research --> Targets
  Evolution --> Targets
  Targets --> BitPro
  Context --> DB
  Loop --> DB
  Eval -. 独立网络、数据库与合成事实 .-> API
~~~

上述图是控制面，不是交易执行拓扑。外部数据与 BitPro 仍是各自领域的事实源；HyperTrade 只保存
受界限的引用、摘要、哈希、指标和审计投影，而非秘密、完整原始序列、完整 prompt 或私有推理。

## 4. 运行时分层

| 层 | 主要组件 | 职责 |
| --- | --- | --- |
| Operator surfaces | React `/harness/missions`、`ht` CLI、Textual TUI、Tauri desktop、REST/SSE | 创建与查看 Mission，发送带理由和幂等键的控制动作，投影公开交付与审计事件 |
| Control plane | FastAPI、认证与作用域令牌、Mission/Thread REST/SSE、Idempotency | 验证身份和请求，提供 cursor replay；不在浏览器或 CLI 中保存工作流真相 |
| Domain | `runtime/domain`、`arc/contracts.py` | Mission、Plan、Step、预算、Capability、Context、Artifact、ARC Goal/Candidate 的严格 Pydantic 合同和状态机 |
| Application | `runtime/application`、`arc/`（research / evolution / review） | ingress 安全分类、Mission loop、AVO 研究循环、进化扫描、自动评审、元学习、效果账本、告警 |
| Ports | `runtime/ports.py`、`targets/ports.py` | Mission store、planner、context、catalog、executor、sandbox，以及市场目标读/回测/模拟盘能力的稳定 protocol |
| Adapters | `runtime/adapters`、`bitpro/`、`targets/` | PostgreSQL/内存存储、受治理工具执行、上下文/产物、UDS sandbox、BitPro MCP/API 适配、`market_target.v1` 注册表与 `market-evolution.v1` 契约客户端 |
| Data & integrations | PostgreSQL/pgvector、OKX、RAG、Memory（46 个 Alembic 迁移） | 保存 canonical Mission projection 与研究/进化账本；以有健康度、schema 和来源信息的合同接入外部事实 |
| Operations | Docker Compose、Nginx、GitHub Actions、`deploy/`、隔离评测、`./scripts/check.sh` | 部署、健康检查、迁移、监控与可重复的安全/质量验证 |

代码组织遵循模块化单体与 ports-and-adapters：`runtime/domain` 与 `arc/contracts.py` 不依赖 FastAPI、
SQLAlchemy、LLM provider、MCP 或交易平台。外部实现只能位于 adapter 边界，从而能在不改变领域规则的前提下
替换 provider、存储、数据源或市场目标。

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

## 6. 自主研究循环（AVO）

`POST /api/v1/arc/missions` 创建研究 Mission 后，由 worker 运行自主研究循环
（`arc/router.py::run_autonomous_arc_loop` 与 `arc/avo.py`）：

1. **证据预检**：窗口不可用、来源不是可证明的 OKX（且未被操作员确认替代来源）时，Mission 停在
   `operator_needed`，不消耗候选预算。
2. **候选生成**：LLM provider 假设通道（未配置 provider 时记录原因）提出假设，与确定性策略族
   （`research/codegen.py`）的边界化参数组合编译为候选代码与 `strategy_spec`。
3. **对抗审查与变异**：蓝队提出候选，`ARCAdversarialEngine`（带历史证据门禁）产出攻击发现，
   遗传变异器（`ARCGeneticMutator`）在参数边界内做变体。
4. **隔离沙箱自测**：`ARCSelfTestService` 经 BitPro 适配器执行 validate → create → backtest，
   沙箱以 digest 绑定、UDS 隔离、非 root、无网络运行；硬指标（OOS 收益、Sharpe、回撤、交易数）不达标即失败。
5. **同窗基线对比**：候选与基线在完全相同的时间窗上比较；`comparison_evidence_invalid`
   单独计数，不静默算负。
6. **反思与技能**：失败原因归类为 reason code，经 `ARCReflexionLedger` 转为否定约束注入后续轮次
   上下文；过检策略的子函数可蒸馏进技能库（`ARCSkillLibrary`）。
7. **Paper 评审**：`request_paper_review` 组装版本、成本、回测与风险门禁证据；评审模式 human 模式下
   等待人工批准，agent 模式按系统政策自动评审。
8. **模拟盘孵化**：批准后从操作员预授权派生候选绑定的模拟盘授权，在 BitPro 配置并启动独立模拟盘实例；
   观察策略（最少小时数/交易数）由观察循环跟踪，证据经 `paper_evidence.v1` 等合同读回。

研究模式 `avo` 支持单标的与组合（`symbols`，2–20 个），`arc` 模式保留单标的并行 MCTS 路径。
组合的声明标的集合由 `enforce_source_scope` 保证在候选生成、边界化与记忆整编全链路不被缩窄。

## 7. 自主进化引擎（默认开启）

生产 worker 小时级扫描全部孵化中的模拟盘策略（`arc/evolution.py::EvolutionService`），四个账本
支撑"有没有用、有没有卡住、判断得对不对"：

### 7.1 退化扫描与判定口径

- **窗口**：两周观察窗拆为前后各 7 天，比较策略自身的变化与其标的同期买入持有的变化（相对口径）。
  组合策略取成员等权合成基准（各自归一基 100 后按共享 K 线网格平均）。
- **基准状态标注**：observed / unavailable / misaligned / insufficient_coverage / unsupported_timeframe；
  任一非 observed 状态回退绝对口径并在 window 载荷中标注，绝不静默。
- **基准相对为默认**（`EvolutionConfig.degradation_basis=benchmark_relative`），操作员可切回绝对口径；
  触发原因码为 `relative_return_drop` / `relative_drawdown_increase`（绝对口径下为旧 reason 码）。
- **组合保持**：扫描发现的组合退化以完整篮子开启再研究（goal.symbols = 声明标的集合），
  研究记忆按标的交集限定作用域。

### 7.2 预算准入与延续记录

- 进化发起的研究经 `research_budget.v1` 准入（候选/模型/回测预算与冷却），准入回执并入效果账本。
- 每个策略的延续记录（continuation ledger）跟踪阻塞、`next_eligible_at` 与
  `attention_required`；阻塞分为 `resolution=time`（等待窗口滚动、成交累积、预算冷却）与
  `resolution=operator`（session 身份/启动、运行状态、读取与成本元数据采样失败）。
- 陈旧延续记录（>3 小时未刷新，即策略已暂停/移除）不参与告警，暂停策略的未解决告警自动 resolved。

### 7.3 自动评审、元学习与孵化治理

- 评审模式：human（等待明确批准）/ agent（系统政策自动评审并启动独立模拟盘后孵化），
  经 `configured_review_mode` 冻结进 goal。
- 元学习（`arc/meta_tuning.py`）：按 p90 规则评估退化阈值并做有界步进（≤3pp，边界 [5,20]pp，
  最少样本 12）；默认只记录建议（`meta_tuning_auto_apply=False`），每日幂等、带回执。
- 晋升与实盘审批：`live_promote` / `live_approval` 记录受治理的晋升审批事实；主网执行本身仍被
  `live_allowed=false` 禁用。

### 7.4 效果账本与告警

- **效果账本**（`evolution_effectiveness.v1`，`arc/effectiveness.py`）：只统计进化循环发起的任务，
  按周期状态、任务、证据（候选/开发运行/最终运行/基线对比与胜出）、Paper 决策、已结算 Outcome、
  成本与逐来源聚合；`baseline_win_rate` 仅在有有效对比时给出，`causal_conclusion=not_established`，
  样本不足时报告自述不足以支撑结论。面：`GET /api/v1/arc/evolution/effectiveness`。
- **告警**（`arc/evolution_alerts.py`，表 `arc_evolution_alerts`）：三条规则——
  `evolution_blocked_needs_operator`（任一 operator 阻塞，warning，立即）、
  `evolution_evidence_stalled`（证据停滞且无法预计恢复时间，先跟踪，
  >72h 升级告警）、`evolution_cycles_erroring`（最近 3 个扫描周期全部 error，critical）。
  确定性 ID 去重；条件消失自动 resolved；`POST /alerts/{id}/ack` 确认后同一条件不再打扰，
  再次出现视为新事件。投递复用 `FEISHU_WEBHOOK_URL`（未配置只记台账；失败 6 小时节流、7 天放弃），
  投递失败永不阻塞扫描。面：`GET /api/v1/arc/evolution/alerts`。
- **元学习面**：`GET /api/v1/arc/evolution/tuning`。

## 8. 可插拔市场目标

`targets/` 包把"市场"抽象为可插拔目标（[62](62-pluggable-market-targets.md)）：

- **`market_target.v1` 档案**：标识、标的宇宙、周期集合、日历/时区、能力声明与环境配置；
  `registry` 以 `MARKET_TARGET` 设置（默认 `bitpro`）解析当前目标，提供
  `adapter_for_target` / `get_active_market_target`。
- **`market-evolution.v1` MCP 契约**：7 个标准工具（模拟盘快照读取、行情读取、回测、
  策略校验、策略创建、模拟盘配置、模拟盘启停），`McpContractClient` 带预检（preflight）；
  契约档案供外部控制面（如 BitPro 控制台）发现能力。
- **Phase 2 Ports**（`targets/ports.py`）：读、回测、模拟盘能力的稳定 protocol，供后续
  目标实现按需满足。
- **BitPro 是第一个目标**：`targets/bitpro.py` 提供 `BITPRO_TARGET_PROFILE` 与懒加载
  适配器工厂；既有行为由测试钉死（byte-identical），抽象不改变 BitPro 路径的实际语义。
  接入新市场（例如 QuantLab 的 A 股/美股）只需实现同一契约并注册档案。

## 9. 研究与数据流

1. 操作员描述研究目标、成功条件和约束，或由进化引擎根据已提交的模拟盘反馈发起再研究。
2. ingress 分类器先阻断主网执行、未批准/高杠杆 Testnet 请求和明确陈旧数据；这些请求在模型或工具
   调用之前结束或等待人工处理。
3. Planner 只能从已审核的 Capability Catalog 选择 capability id；发现的 MCP/OpenAPI 能力先成为
   `pending_review`，不会自动进入生产 allowlist。
4. Context Engine 按固定优先级编译目标、权限、Plan/Step 合同、依赖 observation、Evidence、Memory、
   RAG 与 Artifact 引用；它记录保留、压缩、丢弃和原因，且不会把完整对话或原始交易序列拼入 prompt。
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

策略研究复用既有的 Evidence、Experiment Manifest、StrategyCard、robustness 与 Portfolio
projections。它们是研究事实和复核材料，不是自动执行授权；BitPro 负责策略和回测系统事实，
HyperTrade 不持久化 BitPro 的完整蜡烛、权益、交易、订单或持仓序列。

## 10. 安全与治理边界

| 边界 | 实现方式 | 失败行为 |
| --- | --- | --- |
| 权限 | read-only Mission profile、Capability side-effect 分类、Tool Policy、Approval/Risk gate、ARC 作用域令牌 | 缺少匹配权限或批准时拒绝 dispatch |
| 输入与输出 | Pydantic v2 + JSON Schema、policy/contract hash、来源绑定 | schema 或来源不匹配时记录分类失败 |
| 预算与并发 | 事务性 token/tool/model/duration reservation、`research_budget.v1` 进化准入、AnyIO bounded concurrency | 无剩余预算时停止或形成降级交付 |
| 审计与重放 | V2 Mission events、deterministic reducer、projection hash、idempotency、SSE cursor | gap、冲突、未知版本或 stale fencing 会 quarantine；旧记录为 `legacy_non_replayable` |
| 外部副作用 | 参数/版本/policy 绑定的一次性 Approval、write-ahead DispatchIntent、持久 ToolCall/circuit/reconciliation | deny 不可覆盖；超时进入 `effect_unknown` 且不自动重发，未对账时阻止完成 |
| 策略学习 | 不可变 Outcome、append-only correction、reviewed Lesson、support/opposition/validity | 未结算、过期来源、unknown effect 或未审核 Lesson 不进入学习上下文 |
| 自主进化 | 预算准入 + 证据预检 + 延续记录 + human/agent 评审政策；效果账本只读本地账本；告警投递仅为固定模板文本，不持有审批/交易权限 | 门禁不满足时停在 `time`/`operator` 阻塞并显式记录，不消耗预算、不静默重试 |
| 数据保护 | redaction、结果大小限制、metadata-first artifacts | 不保存凭据、原始工具结果、完整 prompt 或私有推理 |
| 策略代码 | UDS isolated sandbox、非 root、无网络、只读根、无 Docker socket、资源限制、digest 绑定 | socket/digest 不可用时生产返回 503，绝不回退到 API/宿主子进程 |
| 评测 | 独立 API、数据库、网络和合成事实；生产禁用 fixture | 评测产物不进入生产事实，也不授予交易权限 |

当前系统不启用 mainnet 订单执行。任何未来的 Paper、Testnet 或 live 写能力必须以新的 capability、
审批、幂等、风险、审计和独立验收合同接入，不能由 Mission Planner、Supervisor 或 UI 自行开放。

## 11. 部署与运行模型

生产使用 Docker Compose、Nginx 与 GitHub Actions 的 `main` 分支部署流程。PostgreSQL 同时保存 Mission
存储/event/lease/projection、研究/进化账本和 legacy AgentRun/AgentTask/Session 表；它是单一数据库，不等于单一领域
状态模型。当前没有 Celery、Redis、Kafka 或第二套任务队列。Alembic 迁移（46 个）在服务启动前执行，
`/api/health`、容器健康检查和部署 smoke 用于确认服务状态。

worker 进程内运行的循环包括：mission worker、agent task worker、research trigger、AVO research、
ARC observation、ARC evolution（小时级扫描）、ARC auto review、ARC meta tuning（小时 tick / 每日桶）、
paper trading、market ingestion、market REST supplement、rag scanner、monitor scheduler。

重要运行约定：

- 新部署默认以 fail-closed feature flags 启动；生产启用必须经过对应 Sprint Gate 和可回滚发布验证。
- Mission worker 使用 SQL lease；当 worker 功能关闭或租约不可领取时，不应由 API 或客户端绕过其控制面。
- Mission API 的控制动作需要认证、理由和幂等键；客户端可通过 `after` 或 `Last-Event-ID` 重放事件。
- 隔离 evaluation target 具有独立网络、数据库和合成事实，不能使用生产 BitPro 数据、凭据或执行路径。
- 每个有意义的改动都必须通过 `./scripts/check.sh`（前端 lint/test/构建 + ruff + mypy + pytest）。
- 部署运行手册、BitPro 接入与故障排查位于 [docs/runbooks](../runbooks/)。

## 12. 面向贡献者的变更准则

在修改系统时，以以下顺序判断：

1. 新行为属于 Mission、研究事实、进化账本、外部 adapter，还是纯客户端投影？
2. 是否可以由现有的稳定 port/contract（含 `market-evolution.v1`）接入，而不是把外部业务逻辑复制进 HyperTrade？
3. 是否有明确的 source/artifact、schema、健康度、预算、权限、超时和幂等语义？
4. 失败时是否保留可审计的 unknown/分类错误（含基准回退与阻塞分类），而不是生成看似完整的结论？
5. 是否更新对应的 Product Spec、architecture、Sprint contract、progress、测试和部署验证？

当前 Sprint 状态和已验证的生产证据以 [Progress Log](../progress.md) 与 active contract 为准，
不能仅凭 README 或聊天记录判断。

## 13. 相关文档

- [架构总览](00-overview.md)：架构文档入口。
- [62 可插拔市场目标](62-pluggable-market-targets.md)：`market_target.v1` / `market-evolution.v1` 契约。
- [63 进化加固](63-evolution-effectiveness-alerts-and-benchmark.md)：效果账本、告警与基准相对退化。
- [61 研究闭环架构梳理](61-research-loop-architecture-rationalization.md)：AVO 引入与模块收敛决议。
- [35 North Star](35-autonomous-quant-trader-north-star.md) / [36 M0 研究循环](36-goal-driven-autonomous-research-loop-m0.md)：产品目标与首个闭环合同。
- [可视化架构图](19-hypertrade-architecture-diagram.md)：面向讨论的层次图。
- [Professional Agent Runtime V2 路线图](30-professional-agent-runtime-v2-roadmap.md) / [技术设计](31-professional-agent-runtime-v2-technical-design.md)：Mission、Catalog、Context、Supervisor、Sandbox 和 cutover 的实现细节。
- [产品规格](../spec.md)：产品范围、用户旅程、验收与非目标。
- [开发者指南](../developer-guide.md)：本地开发与扩展入口。
- [部署与运行手册](../runbooks/)：部署、监控、BitPro MCP 与事件响应。
