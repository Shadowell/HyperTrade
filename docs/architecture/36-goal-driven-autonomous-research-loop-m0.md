# 36 目标驱动的自主策略研究闭环 M0

> 文档性质：开发设计、接口参考与迁移说明。
>
> 状态：Approved for implementation by owner request，2026-07-24。
>
> 本文定义 HyperTrade 当前最高优先级的产品路径：用户只提交研究目标，系统自主生成候选、调用 BitPro
> 校验与回测、根据证据迭代，并在明确预授权内把达标候选送入模拟盘。本文不授权任何 Testnet、Live、订单或
> 资金动作。

## 1. 目标

M0 必须让下面这类请求成为一条真实、可恢复、可审计的端到端任务，而不是一组需要操作员手工拼接的 API：

> 帮我研究一个收益稳定、最大回撤不超过 15% 的 BTC 策略。你自己生成和测试策略；满足要求后上模拟盘，
> 没有满足要求的策略就告诉我证据并询问是否继续。

用户提交目标后，HyperTrade 负责：

1. 将自然语言编译为有边界的研究章程。
2. 生成至少两个实质不同、可证伪的候选假设和 BitPro `BaseStrategy` 代码。
3. 调用真实 BitPro 能力完成代码校验、策略创建和回测。
4. 使用确定性验证策略判断候选是否通过，不让模型评价自己的结果。
5. 对失败候选提取结构化失败原因，在预算内生成下一候选。
6. 对通过候选，在用户任务开始时授予的 Paper 边界内自动配置并启动模拟盘。
7. 预算耗尽后进入 `needs_operator`，展示完整失败证据并提供“继续”动作。
8. 服务重启、超时或外部状态不明时安全恢复，不重复创建策略、回测或模拟盘实例。

M0 的成功不是“找到盈利策略”。M0 的成功是：系统能真实完成研究闭环，并对通过、失败、未知和需要人工
处理的状态给出可验证证明。

## 2. 当前实现审计

HyperTrade 已经具备多数底层资产，但它们不是同一条默认执行路径。

| 当前资产 | 已有能力 | M0 缺口 | 处理方式 |
| --- | --- | --- | --- |
| `Thread → Turn → Mission` | 服务端任务真相源、事件、重放、预算、完成证明 | 当前默认 Planner 只允许受审查的只读能力 | 保留；新增 research mission profile |
| `ProviderRuntime` / `ChatProvider` | OpenAI-compatible、Codex、DeepSeek、OpenRouter、Qwen 等路由 | 没有面向候选生成的统一结构化调用端口 | 保留；新增 `CandidateGenerator` |
| `ResearchProgramService` | ResearchMandate、Job、幂等和状态迁移 | draft 只是确定性骨架，任务需要人工 draft/queue/run | 降为内部持久化兼容层 |
| `ResearchOrchestrator` | BitPro 健康预检、代码校验、策略创建、回测矩阵、证据落库 | `_compile_strategy()` 固定生成均线策略；一次 Job 只处理一个候选 | 拆成单候选 `CandidateExperimentExecutor` |
| `StrategyDiscoveryService` | 假设冻结、新颖性、预算、BitPro validate/create | 调用方必须预先提供完整 Proposal 和代码 | 改为候选登记与新颖性裁判 |
| `UnifiedStrategyValidationService` | OOS、walk-forward、成本、稳定性、选择偏差、风险门禁 | 尚未由统一研究循环自动调用 | 保留为唯一晋级裁判 |
| `AutonomousPaperIncubationService` | Paper configure/start/observe/pause、Approval、幂等和对账 | 需要候选产生后再创建人类 Paper mandate | 接入预授权派生流程 |
| 固定 ResearchGraph | 多角色、有界预算、研究证据 | 固定角色图不负责端到端策略结果 | 从默认路径移除，保留为可选工具 |
| `/research-program` 等 CLI/API | 可以逐步操作每个子系统 | 用户必须理解内部工作流并手工串联 | 保留为诊断接口；新增单入口 |

当前最重要的工程事实是：

- `ResearchOrchestrator.run()` 可以执行一个已给定的策略，但不会自己产生下一候选。
- `ResearchProgramService.draft_strategy_spec()` 只根据第一个 symbol、timeframe 和 category 生成通用骨架。
- `StrategyDiscoveryService.discover()` 消费已经生成好的 `request.proposals`，不负责调用 LLM 发现策略。
- `ProviderBackedResearchPlanner` 把模型约束在固定的只读 Capability envelope 中，不适合作为写策略和
  Paper 生命周期控制器。
- `AutonomousPaperIncubationService.create_mandate()` 要求当前认证人就是审批人，不能让 Agent 在候选通过后
  冒充操作员补授权。

因此 M0 不重写通用 Runtime。它新增一个专用的、持久化的策略研究控制器，把现有能力组合为产品闭环。

## 3. 设计原则

### 3.1 一个产品入口

面向用户只有一个默认入口：创建自主策略研究任务。Draft、Job、Discovery、Validation 和 Paper Action 是
内部步骤，不再要求用户依次调用。

### 3.2 动态工具循环，不使用固定 LangGraph 作为主路径

控制器根据当前状态、真实证据、失败原因和剩余预算决定下一动作。策略类别、候选数量和重试次数不编码成
固定节点图。

LangGraph 依赖可以暂时保留给旧路径，但新的 M0 控制器只依赖领域状态机和端口接口。删除 LangGraph 依赖
属于新路径稳定后的单独清理，不进入 M0。

### 3.3 模型提案，确定性系统裁决

模型可以：

- 解释用户目标；
- 提出市场现象和 Alpha 假设；
- 生成策略代码、参数范围和实验计划；
- 根据失败证据提出下一候选；
- 生成面向用户的阶段说明。

模型不能：

- 授予 Paper 或 Live 权限；
- 宣布自己的候选通过验证；
- 修改验证门槛；
- 隐藏失败实验；
- 把缺失数据解释为通过；
- 在外部副作用状态未知时要求盲目重试；
- 直接创建订单或操作资金。

### 3.4 外部平台保留交易真相

BitPro 继续拥有策略存储、行情、回测、模拟盘和执行真相。HyperTrade 只通过稳定 MCP/API Adapter 工作，
保存任务状态、结构化摘要、hash、lineage 和外部引用，不复制 BitPro 业务逻辑。

未来 StockPro 必须实现相同的 `StrategyResearchPlatform` 端口，不能在控制器中增加 StockPro 条件分支。

### 3.5 通过验证不等于稳定盈利

候选通过验证后的状态是 `validated`。进入模拟盘后的任务状态是 `paper_observing`。只有达到预设观察期和
样本要求后，系统才可以输出模拟盘阶段结论；任何阶段都不得承诺未来收益。

## 4. 目标架构

```text
Thread / Turn
    |
    v
GoalCompiler ---------------------- ProviderRuntime / ChatProvider
    |                                          |
    v                                          v
ResearchGoalV1                    CandidateGenerator / FailureAnalyzer
    |                                          |
    +-------------------+----------------------+
                        v
             AutonomousResearchController
                        |
          +-------------+--------------+
          |                            |
          v                            v
CandidateRegistry            Research Mission Event Store
          |
          v
CandidateExperimentExecutor
          |
          v
StrategyResearchPlatform (M0: BitPro)
validate code -> create strategy -> backtest -> read artifacts
          |
          v
UnifiedStrategyValidationService
          |
    +-----+--------------------------+
    |                                |
validated                    rejected / needs_data
    |                                |
    v                                v
PaperAuthorizationResolver      FailureAnalyzer
    |                                |
    v                                +--> next candidate, while budget remains
AutonomousPaperIncubationService
    |
    v
paper_observing
```

### 4.1 组件责任

#### `GoalCompiler`

把自然语言目标编译成 `ResearchGoalV1`。它可以调用 LLM，但输出必须经过严格 schema、默认值和政策校验。
无法安全推断的高风险字段保持关闭；M0 中 `live_allowed` 永远为 `false`。

#### `AutonomousResearchController`

研究闭环的唯一协调者。它：

- 读取 Mission projection 和下一步合法动作；
- 预留预算；
- 调用候选生成、实验、验证、失败分析和 Paper 派生授权；
- 追加领域事件；
- 计算任务状态；
- 触发独立完成证明；
- 不包含具体 Provider、BitPro 或验证算法。

#### `CandidateGenerator`

根据研究目标、可用市场证据、已尝试候选、失败诊断和剩余预算生成结构化候选。它通过 `ChatProvider` 调用
当前模型，不依赖厂商 SDK。

#### `CandidateRegistry`

复用并收敛 `StrategyDiscoveryService` 的不可变假设、重复检测、新颖性和预算记录能力。所有候选，包括
schema 失败、代码失败和重复候选，都必须留下终态。

#### `CandidateExperimentExecutor`

从 `ResearchOrchestrator` 抽取的单候选执行器。只负责：

- BitPro capability/health/data preflight；
- `strategy_validate_code`；
- `strategy_create`；
- 回测窗口和参数矩阵；
- 外部 ID、artifact 和指标摘要；
- 幂等和明确错误分类。

它不生成候选，不决定是否通过，不决定是否继续研究，也不启动 Paper。

#### `EvidenceVerifier`

M0 由 `UnifiedStrategyValidationService` 实现。它独立读取候选、trial family、真实结果、成本和数据引用，
输出 `validated | rejected | needs_data | needs_review`。

#### `FailureAnalyzer`

把验证 Gate、代码错误、数据问题和实验异常转换为结构化 `FailureDiagnosisV1`。LLM 可以据此提出下一
候选，但 reason code、失败指标和 source refs 由确定性代码冻结。

#### `PaperAuthorizationResolver`

根据任务开始时由用户创建的不可变预授权，确定候选是否可自动进入 Paper。它只能收窄权限，并把通过验证的
候选 fingerprint 绑定到派生 Paper 授权。

#### `StrategyResearchPlatform`

交易平台端口。M0 只实现 BitPro。未来 StockPro 通过新 Adapter 接入，不改变控制器、候选、验证或任务状态。

## 5. 核心领域合同

以下是目标合同，不代表当前代码已经存在。实现时使用 Pydantic `extra="forbid"`、版本字段和 canonical
payload hash。

### 5.1 `ResearchGoalV1`

```python
class ResearchGoalV1:
    schema_version: Literal["research_goal.v1"]
    objective: str
    platform: Literal["bitpro"]
    market_type: str
    symbols: list[str]
    timeframes: list[str]
    strategy_families: list[str]
    success_criteria: ResearchSuccessCriteriaV1
    budget: ResearchBudgetV1
    paper_authorization: PaperPreauthorizationV1 | None
    live_allowed: Literal[False]
```

最低成功标准字段：

| 字段 | 类型 | M0 规则 |
| --- | --- | --- |
| `min_oos_net_return` | decimal | 必须声明单位和观察窗口 |
| `min_oos_sharpe` | decimal | 由验证策略计算，不能采用模型自报值 |
| `max_drawdown` | decimal | 范围 `[0, 1]` |
| `min_trades` | integer | 必须大于零 |
| `required_validation_policy` | string | 绑定版本和 policy hash |
| `paper_required` | boolean | 仅在有效预授权存在时可以为 true |

自然语言没有提供阈值时，`GoalCompiler` 使用版本化的 M0 默认 Profile，并把采用的默认值写入任务摘要。

### 5.2 `ResearchBudgetV1`

```python
class ResearchBudgetV1:
    max_candidates: int
    max_model_calls: int
    max_tool_calls: int
    max_backtests: int
    max_wall_seconds: int
```

所有预算必须在服务端设置上限。用户执行“继续”时创建新的 `BudgetExtensionV1`，保留原预算和已消费记录，
不能改写历史 usage。

### 5.3 `CandidateProposalV1`

```python
class CandidateProposalV1:
    candidate_key: str
    hypothesis: str
    economic_rationale: str
    strategy_family: str
    distinguishing_dimensions: list[str]
    expected_regimes: list[str]
    failure_conditions: list[str]
    required_data: list[str]
    strategy_spec: StrategySpecDraft
    strategy_code: str
    parameter_space: dict[str, ParameterBoundV1]
    model_provenance: ModelProvenanceV1
```

`model_provenance` 至少冻结 provider、model、prompt hash、response hash、tool registry hash 和 policy hash。
不保存模型私有思维过程。

### 5.4 `CandidateAttemptV1`

每次候选执行产生一个不可变 Attempt：

```python
class CandidateAttemptV1:
    attempt_id: str
    candidate_id: str
    state: CandidateAttemptState
    bitpro_strategy_id: str | None
    validation_id: str | None
    experiment_fingerprint: str
    external_refs: dict[str, str]
    usage: ResearchUsageV1
    error: ResearchErrorV1 | None
```

候选 Attempt 状态：

```text
proposed
  -> duplicate | generation_rejected
  -> code_validating
  -> code_rejected | strategy_creating
  -> effect_unknown | backtesting
  -> experiment_failed | evaluating
  -> validated | rejected | needs_data | needs_review
```

`effect_unknown` 不能自动回到 `strategy_creating` 或 `backtesting`。必须先读取 BitPro 外部状态完成对账。

### 5.5 `FailureDiagnosisV1`

```python
class FailureDiagnosisV1:
    candidate_id: str
    failure_class: Literal[
        "hypothesis",
        "code",
        "data",
        "backtest",
        "validation",
        "platform",
        "budget",
    ]
    reason_codes: list[str]
    failed_gates: list[str]
    observed_metrics: dict[str, Decimal]
    source_refs: list[str]
    retryable: bool
    next_candidate_constraints: list[str]
```

模型只能消费该结构并提出下一候选。它不能删除 `failed_gates` 或覆盖 `retryable`。

### 5.6 `PaperPreauthorizationV1`

```python
class PaperPreauthorizationV1:
    schema_version: Literal["paper_preauthorization.v1"]
    approved_by: str
    platform: Literal["bitpro"]
    symbols: list[str]
    max_instances: int
    max_capital_per_instance: Decimal
    allowed_actions: list[Literal["configure", "start", "observe", "pause", "retire"]]
    required_validation_policy_hash: str
    valid_from: datetime
    valid_until: datetime
    policy_hash: str
```

派生 Paper mandate 时必须满足：

- 候选为 `validated`；
- validation policy hash 精确匹配；
- strategy、candidate、validation 和 manifest fingerprint 完整；
- symbol、capital、instance count、action 和 validity 不超过父授权；
- 当前认证用户在任务创建时就是 `approved_by`；
- 派生过程由确定性服务完成，不能填写伪造的 Agent 审批人；
- `effect_unknown`、kill switch、过期或撤销时禁止 `configure/start`。

### 5.7 `ResearchMissionSummaryV1`

对用户的任务摘要至少包含：

- 原始目标与结构化目标；
- 使用的默认值；
- 当前状态和下一合法动作；
- 候选总数及各终态；
- 最佳候选，但不得隐藏未通过 Gate；
- BitPro strategy/backtest/result refs；
- validation decision 和失败证据；
- Paper member 和观察状态；
- 模型与工具预算使用；
- 是否需要操作员以及可执行选项；
- `not_investment_advice` 和 `no_profit_guarantee`。

## 6. Research Mission 状态机

```text
created
  -> compiling_goal
  -> awaiting_goal_confirmation
  -> generating_candidate
  -> registering_candidate
  -> validating_code
  -> backtesting
  -> evaluating
  -> diagnosing_failure
  -> generating_candidate
  -> paper_authorizing
  -> paper_starting
  -> paper_observing
  -> needs_operator
  -> completed
  -> canceled
  -> failed
```

### 6.1 关键转移

| 当前状态 | 条件 | 下一状态 |
| --- | --- | --- |
| `compiling_goal` | schema 和 policy 通过 | `generating_candidate` |
| `compiling_goal` | 关键范围不能安全推断 | `awaiting_goal_confirmation` |
| `generating_candidate` | 合法且非重复候选 | `registering_candidate` |
| `generating_candidate` | 模型失败且预算可用 | `generating_candidate`，新 attempt |
| `evaluating` | `validated` 且 Paper 预授权有效 | `paper_authorizing` |
| `evaluating` | 未通过且预算仍可用 | `diagnosing_failure` |
| `evaluating` | 未通过且预算耗尽 | `needs_operator` |
| `paper_starting` | BitPro 确认运行 | `paper_observing` |
| `paper_starting` | 外部状态不确定 | `needs_operator`，reason=`effect_unknown` |
| `needs_operator` | 用户批准 BudgetExtension | `generating_candidate` |
| `paper_observing` | M0 最小观察启动证明完成 | `completed`，Paper 观察继续作为子生命周期 |

### 6.2 非法转移

- `rejected -> validated`：必须创建新的验证版本。
- `needs_data -> validated`：必须补齐来源并创建新的验证版本。
- `effect_unknown -> retry_write`：必须先 reconciliation。
- `generating_candidate -> paper_starting`：不得绕过 BitPro 实验和统一验证。
- `validated -> live_*`：M0 不存在任何 Live 状态。
- `needs_operator -> completed`：没有完成证明时不得把“停止工作”标记为完成。

## 7. 运行循环

控制器每次只执行一个可恢复步骤：

```python
async def advance(mission_id: str) -> ResearchMissionProjection:
    mission = store.load_for_update(mission_id)
    action = transition_policy.next_action(mission)
    reservation = budget.reserve(mission, action)
    result = await dispatch(action, mission)
    event = event_factory.from_result(mission, action, result, reservation)
    return store.append_and_reduce(event)
```

要求：

- `next_action()` 是确定性的。
- 外部调用前写入 intent 和幂等键。
- 同一 Mission 同时只能有一个有效 worker fencing token。
- 每个步骤完成后持久化事件和 projection。
- 失败必须分类为 definite failure、retryable failure 或 unknown effect。
- LLM 调用和 BitPro 调用都计入预算。
- 控制器不使用进程内无限 `while`；Worker 通过新的可领取状态继续任务。

## 8. Provider 与模型切换

M0 复用 `ChatProvider`，新增结构化调用封装：

```python
class StructuredModelPort(Protocol):
    async def generate(
        self,
        *,
        messages: Sequence[Message],
        output_schema: type[BaseModel],
        context: ModelCallContextV1,
    ) -> StructuredModelResult: ...
```

Provider 规则：

- provider/model 由 Mission 创建时冻结，单个候选内不能静默切换；
- Provider 故障可以根据任务 policy 显式 failover，但必须追加 `provider_changed` 事件；
- prompt、response、schema 和 policy 使用 hash 记录；
- 只保存结构化输出和公开解释，不保存私有 reasoning；
- Provider 输出在进入数据库和工具调用前必须再次经过本地 schema 和 policy 校验；
- M0 生产验收只要求一个真实 Provider 跑通；
- Anthropic、Gemini 等后续实现 `ChatProvider` 即可接入，不得修改控制器。

## 9. Platform Adapter

目标端口：

```python
class StrategyResearchPlatform(Protocol):
    async def capabilities(self) -> PlatformCapabilitiesV1: ...
    async def health(self) -> PlatformHealthV1: ...
    async def fetch_research_data(self, request: ResearchDataRequestV1) -> ResearchDataRefV1: ...
    async def validate_strategy_code(
        self, request: StrategyCodeValidationRequestV1
    ) -> StrategyCodeValidationResultV1: ...
    async def create_strategy(
        self, request: StrategyCreateRequestV1
    ) -> ExternalOperationResultV1: ...
    async def start_backtest(
        self, request: BacktestRequestV1
    ) -> ExternalOperationResultV1: ...
    async def get_backtest_result(self, ref: ExternalRefV1) -> BacktestResultRefV1: ...
```

M0 BitPro Adapter 包装现有能力：

- `capabilities`
- `health`
- `market_klines`
- `strategy_validate_code`
- `strategy_create`
- `backtest_start_job`
- `backtest_get_result`

Paper 仍由窄化的 `PaperIncubationAdapter` 处理，不把 Paper、Live、订单和资金方法放进研究 Adapter。

## 10. API 与 CLI 目标

这些是 M0 要实现的新产品接口。现有细粒度接口保留用于兼容和诊断，但 Web/CLI 默认入口不再要求操作员使用。

### 10.1 API

```text
POST /api/autonomous-research/missions
GET  /api/autonomous-research/missions
GET  /api/autonomous-research/missions/{mission_id}
GET  /api/autonomous-research/missions/{mission_id}/events
POST /api/autonomous-research/missions/{mission_id}/continue
POST /api/autonomous-research/missions/{mission_id}/cancel
GET  /api/autonomous-research/missions/{mission_id}/stream
```

创建请求：

```json
{
  "objective": "研究一个收益稳定、最大回撤不超过15%的BTC策略，满足后上模拟盘",
  "provider": "openai",
  "model": "configured-model",
  "profile": "crypto_single_symbol_m0",
  "paper_preauthorization": {
    "enabled": true,
    "max_instances": 1,
    "max_capital_per_instance": "10000"
  },
  "idempotency_key": "operator-generated-key"
}
```

`provider` 和 `model` 是标识符，不是密钥。API 不接受 Provider key、交易所凭证或 BitPro 内部数据库连接。

### 10.2 CLI

```text
/research <自然语言目标>
/research status <mission_id>
/research continue <mission_id> [追加预算 JSON]
/research cancel <mission_id> <reason>
```

创建命令成功后立即返回 Mission ID 和已采用的研究边界。长任务通过事件流持续显示：

```text
目标已编译
候选 1/10 已生成
BitPro 代码校验通过
回测 3/3 已完成
候选 1 未通过：locked_oos_sharpe、drawdown
候选 2/10 正在生成
```

CLI 只能投影服务端状态，不能在本地维护第二套研究循环。

## 11. 持久化与事件

优先扩展 canonical Mission event，而不是创建独立且不可重放的任务状态机。

建议新增领域事件：

```text
research_goal_compiled
research_goal_confirmation_requested
candidate_generation_requested
candidate_generated
candidate_rejected
candidate_registered
candidate_experiment_started
candidate_experiment_completed
candidate_validation_recorded
candidate_failure_diagnosed
research_budget_exhausted
research_budget_extended
paper_authorization_derived
paper_start_requested
paper_start_reconciled
research_operator_needed
research_completion_proved
```

需要新增或收敛的持久化对象：

- `AutonomousResearchMission`
- `ResearchGoal`
- `ResearchCandidateAttempt`
- `ResearchFailureDiagnosis`
- `ResearchBudgetExtension`
- `DerivedPaperAuthorization`

已有 `ResearchMandate`、`ResearchJob` 和 `ResearchExperimentEvidence` 在 M0 可以由兼容 Adapter 继续写入。
新控制器上线后再决定是否迁移或归档旧表，M0 不做破坏性删除。

## 12. 安全与故障边界

### 12.1 策略代码

- 代码必须先通过 BitPro `strategy_validate_code`。
- 禁止文件系统、网络、子进程、环境变量、动态安装和凭证访问。
- 只允许 BitPro 审查过的 `BaseStrategy` 接口。
- 代码 digest 必须绑定候选、manifest、回测和验证。
- 失败代码保留 hash、错误和生成来源，但不进入 Paper。

### 12.2 提示注入和不可信数据

- 市场、RAG、Memory、BitPro 文本和策略描述全部是不可信输入。
- 外部文本不能改变 tool policy、预算、Provider、验证门槛或 Paper 授权。
- 候选生成 Prompt 明确区分指令和引用材料。
- Provider 输出中的工具名和参数不能直接 dispatch，必须映射到受审查端口。

### 12.3 外部副作用

- `strategy_create`、`backtest_start_job`、Paper configure/start/pause/retire 使用 content-bound
  idempotency key。
- 超时后先读取外部状态，禁止盲目重发。
- `effect_unknown` 阻止 Mission 完成和后续扩大动作。
- kill switch、Paper mandate revoke/expire 优先于模型和普通任务状态。

### 12.4 权限隔离

- 研究 worker 只持有研究和 BitPro 策略/回测能力。
- Paper mutation 使用独立窄权限 Adapter 和治理路径。
- 研究与 Paper worker 都不持有 Live credential。
- M0 Capability Catalog 中不存在 live、order、transfer、account mutation。

## 13. M0 实施顺序

### Slice 1：合同与黄金验收

- 新增领域 schema、状态机和非法转移测试。
- 新增一个端到端黄金场景，先用 Fake Provider 和 Fake BitPro 固定目标行为。
- 验收“一个自然语言请求，不调用细粒度人工 API，也能到 `paper_observing` 或 `needs_operator`”。

### Slice 2：GoalCompiler 与 Provider 结构化输出

- 接入一个真实 `ChatProvider`。
- 实现严格 JSON/schema 输出、模型 provenance 和 M0 默认 Profile。
- 明确 Provider 错误、schema 错误、预算错误和可重试边界。

### Slice 3：候选生成与登记

- 实现至少两个实质不同候选的约束。
- 接入 Discovery 的不可变假设、重复检测和新颖性。
- 删除新路径对 `_compile_strategy()` 的依赖。

### Slice 4：真实 BitPro 实验与验证

- 抽取单候选 `CandidateExperimentExecutor`。
- 接入真实 BitPro health、validate/create/backtest/result。
- 自动调用 `UnifiedStrategyValidationService`。
- 失败候选自动诊断并触发下一候选。

### Slice 5：Paper 预授权派生与启动

- 新增任务创建时的 `PaperPreauthorizationV1`。
- 从通过验证的 candidate/validation fingerprint 派生窄授权。
- 复用 Paper Incubation 的 intent、Approval/effect governance、幂等和 reconciliation。

### Slice 6：单入口、恢复与生产 Canary

- 新增 API、SSE 和 CLI。
- 验证 worker crash、Provider timeout、BitPro timeout、重复请求和 `effect_unknown`。
- 使用真实 Provider 和真实 BitPro 跑一个受限任务。
- 没有候选通过时必须如实交付 `needs_operator`，不得伪造 Paper 启动。

每个 Slice 都必须通过 `./scripts/check.sh`，更新 `docs/progress.md`，独立提交并部署验证。

## 14. M0 测试矩阵

| 类别 | 必测场景 |
| --- | --- |
| Goal | 完整目标、缺省阈值、模糊 symbol、要求 Live、越界 Paper 资金 |
| Provider | 正常结构化输出、非法 JSON、超时、重复候选、恶意工具参数、Provider failover |
| Candidate | 两个不同假设、代码重复、hypothesis hash 冲突、预算终止 |
| BitPro | capability 缺失、health 异常、validate 拒绝、create 超时、backtest 失败、result 缺失 |
| Validation | validated、rejected、needs_data、needs_review、policy hash 不匹配 |
| Loop | 失败后产生下一候选、预算耗尽、continue、cancel、worker 重启 |
| Paper | 无预授权、过期、撤销、资本越界、configure/start 成功、effect_unknown、reconciliation |
| Security | Prompt injection、策略代码逃逸、凭证缺席、无 Live capability |
| Replay | online projection 等于 event replay，重复请求不重复副作用 |
| Delivery | 用户能看到目标、默认值、所有候选终态、证据、下一步和免责声明 |

## 15. M0 完成定义

只有同时满足以下条件，M0 才完成：

1. 用户只提交一次自然语言目标，不需要手工调用 mandate/draft/queue/run/promote。
2. 真实 Provider 生成至少两个实质不同候选。
3. 候选使用真实 BitPro `strategy_validate_code`、`strategy_create` 和真实回测。
4. 所有候选由统一确定性验证服务裁决。
5. 失败候选在预算内自动触发下一候选。
6. 达标候选在有效 Paper 预授权内自动进入 `paper_observing`。
7. 没有达标候选时进入 `needs_operator`，并提供完整失败证据和“继续”选项。
8. 重启、重复请求和超时不会重复创建外部策略、回测或 Paper 实例。
9. `effect_unknown` 未对账时不继续、不完成、不扩大动作。
10. 没有任何 Testnet、Live、order、transfer 或资本写能力进入研究路径。
11. 端到端黄金测试、故障测试、权限测试和 `./scripts/check.sh` 全部通过。
12. 生产 Canary 使用真实 Provider 与 BitPro；结果可以是失败，但不能是伪造成功。

## 16. 明确不进入 M0

- 第二个真实 Provider 和自动模型择优。
- 已有 BitPro 模拟盘策略优化。
- Champion/Challenger 统计比较。
- StockPro Adapter。
- 多标的、多周期和组合搜索。
- 多 Agent Supervisor 作为默认研究路径。
- RAG、长期 Memory 或自动 Skill 发布。
- Web 工作台重做。
- Testnet、Live、订单、资金、自动组合配置。
- 删除旧表、旧 CLI、旧 API 或 LangGraph 依赖。

这些能力不能阻塞 M0。M0 完成后，下一阶段优先实现现有策略优化与同口径 Challenger 证据，再接
StockPro Adapter。

## 17. 后续阶段接口预留

### 17.1 现有策略优化

后续 `OptimizationMission` 复用同一控制器，但 Goal 增加：

- baseline strategy/version；
- immutable challenger lineage；
- 允许修改的参数和 rule slots；
- 同数据、同窗口、同成本、同 regime、同验证 policy；
- paired comparison、Deflated Sharpe、回撤、尾部风险、参数稳定和 Paper 保持度。

系统只有在 Challenger 的证据在预定义门槛上优于 Baseline 时才能称为“优化成功”。回测收益更高但回撤、
成本、稳定性或样本外证据更差，不能宣称优化。

### 17.2 StockPro

StockPro 只新增：

- `StockProResearchPlatform`；
- 股票市场数据和交易日历 schema；
- 股票特有成本、停牌、涨跌停、复权和容量验证 Profile；
- 对应 Paper Adapter。

GoalCompiler、CandidateGenerator、Controller、Event、FailureDiagnosis、CompletionProof 和用户接口保持不变。

## 18. 取舍

### 选择专用 Research Controller，而不是扩大通用 Planner

通用 Planner 继续适合读取、分析和解释任务。策略生成、回测迭代和 Paper 生命周期包含长时间任务、外部
副作用和专用验证状态，强行塞进只读 Planner 会削弱权限边界，也让完成条件依赖模型。

### 选择显式状态机，而不是固定图

显式状态机增加了领域 schema 和 reducer 工作量，但它能处理动态候选数、预算扩展、重启、对账和未知
副作用。固定图在策略类别、失败类型和循环次数变化时需要不断增加分支。

### 先完成单 Provider、单平台闭环

多 Provider 和多平台只有在一条真实闭环存在后才有复用价值。M0 在端口层保留可替换性，但验收只要求一个
Provider 和 BitPro，避免把“支持很多选项”当成“完成用户目标”。

### 不先删除旧路径

当前细粒度服务包含大量已经验证的安全和证据能力。M0 先通过 Adapter 复用并建立新的唯一产品入口；生产
Canary 稳定后，再用调用量、事件一致性和回归证据决定归档顺序。

## 19. 相关文档

- [自主量化交易员北极星目标](35-autonomous-quant-trader-north-star.md)
- [当前系统架构](33-system-architecture.md)
- [下一代 Agent Runtime 审计与目标设计](34-next-generation-agent-runtime-audit-and-target-design.md)
- [BitPro Tool Adapter](17-bitpro-tool-adapter.md)
- [M0 开发合同](../contracts/user-directed-autonomous-strategy-research-loop-m0.md)
- [当前进度](../progress.md)
