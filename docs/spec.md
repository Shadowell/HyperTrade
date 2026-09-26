独立paper_provenance.v1核验冻结来源代码/成本，窗口读取失败仍保留来源缺口；来源verified不表示窗口完整、归因成立或允许晋级。研究预算来源改用target/strategy/session三元键，旧无target记录仍归BitPro且总预算不重置。

来源核验中的固定历史成本、源码、执行/审核绑定缺口独立产生操作告警；14天时间条件或近期采样正常不能遮盖这些缺口。告警投影不改研究准入条件，恢复须有新鲜的来源核验结果。

全部运行中BitPro Paper均为自主调优接入目标：逐策略核验可调范围、周期、资金和不可变来源，缺口保持显式阻塞；不得把扩大扫描范围或列出阻塞视为完成调优闭环。原实例持续保留，候选仍经同窗回测与逐版本Paper审核。

BitPro连接器现分别暴露当前来源只读描述、参数授权政策和幂等停止态变体创建接口，回测任务可传入已封存行情ID/manifest并在任务回读中取得安全摘要。连接器核对策略ID、来源manifest和候选停止态回执，不把静态来源描述、行情封存或工具映射视为已完成Agent提案、可比回测或Paper审核。

Paper清单周期仅取显式配置和身份匹配的仪表盘字段，缺失/冲突保持unknown；1m/5m/15m/1h策略的市场基准使用独立标注的完整1h闭合K线网格，三处边界用上一根已收盘价格，缺口回退绝对口径并显式标注，不改原策略研究周期。

进化告警（2026-09-21）：业务成功回执才记送达；未解决未确认每日提醒、失败6小时节流，中文原因和下一步可查，旧sent显示未核验。点数上限/成本缺失分类明确；原Paper和政策不变。

同一策略告警的阻塞条件变化即开启新投递事件；成功回执只证明绑定的当前条件和消息已发送。旧无绑定回执、已变更但尚未重发的消息均显示未核验，不能借旧业务码0证明新文案送达。

升级前留下的open、已送达但未绑定内容的回执应尽快对当前告警重新投递；旧回执仅留作历史接受观察，失败重投按六小时节流，不沿用旧24小时成功提醒时间阻塞新内容。确认过的告警不自动重投。

# HyperTrade Product Spec

AVO 与通用 Agent 使用 compaction.v1 对注入完成的消息、工具定义及模型身份执行统一输入预算检查。原始业务事件保留，模型视图只压缩已识别数值序列；首目标、system、最近工具组、来源与未决事实保留。私有脱敏恢复快照限制 2MiB、30 天读取期限，公开活动只提供哈希清单；证据无法安全容纳时阻断，不改变模型推理预算。

ResearchMemory v1 统一 AVO 与 MemoryService 的 ARC 开发回执投影，保留来源、标的/周期/窗口/资金、代码/配置/成本身份、假设方向及正反例。历史未知身份不回填，只能作为带 unknown 的观察，不能支持可比性、审批或晋级；成本目标不匹配、最终窗口污染和持久失效记录阻止召回。

隔离配对评测冻结相同研究控制，只切换长期记忆输入；保留原评审模式，但不执行 Paper 评审或交易。每臂使用独立操作来源和持久预算，恢复以 journal 为准；差异及用量/成本/数据身份未知项均保存，不把一次配对实验作为盈利、因果或记忆有效性证明。

自主进化持久保存按来源会话的资格条件、检查时间与证据游标；worker 重新读取真实证据并受预算/冷却控制续跑。验收账本引用各阶段 ARC 事件，区分完整回执、缺口终态与未知副作用；旧 Paper 缺回执不回填，配置审计失败阻断后续启动。

自主进化附加paper_attribution.v1只读报告，并通过API与ht research diagnostics读取。执行流水证据不足时，入场/退出/成本/regime等维度保持unknown；假设须引用诊断字段和反证条件，不改变研究门槛或Paper审批。

自主进化经验保存开发回执的已核验成本策略哈希；跨成本或缺成本身份不能形成可比方向结论。历史记录保留，召回时明确unknown，仍不作为因果或样本外有效性结论。

受阻策略的自主进化诊断同时显示原阻塞与最近6小时采样状态。近期正常不替代14天历史门槛，读取失败不直接判为采样故障；旧Paper缺正式会话只提示核对，不重建或重置。

进化诊断与告警统一遵守当前配置的策略范围。清单返回不可用行或会话快照尚未读取时，只报告固定的读取不可用与重试行动；只有确实返回的快照缺少身份或起点，才将其归为会话字段缺口。范围外的历史告警按原恢复生命周期解决，不改原Paper或研究门槛。

清单行缺少或包含非法策略ID时只记录不可归属的覆盖缺口，不映射到其它策略，也不阻断有效策略。上游已返回会话快照但身份或格式校验失败时报告固定契约错误，由操作员核对；它不同于传输失败，亦不能证明原Paper历史已丢失。

自主进化开发结果记录引用实验的同窗指标方向评估，并进入后续有界记忆；不可比为unknown，不改变最终验证或Paper审核门槛。

新Paper人审通过后采用paper_review_binding.v1专用配置/启动接口，将代码、参数、资金和会话绑定在BitPro事务中；启动与重启验证冻结版本，旧服务不降级。真实闭环完成仍需合格候选、人审和真实观察期。

Paper启动交接区分数字策略ID与paper_...会话ID；配置前核对候选源码和已有运行历史，配置/启动回执分别验证实际成功标志、版本与身份。证据未确认时不宣称运行成功，不重配原模拟会话。

操作者继续研究会形成幂等恢复消息，旧停止回执不能被当作当前结束指令。模型仅回复文字而没有工具动作时最多自动重试两次，每次正常计入预算；持续无动作、预算不足或最终验证未达标仍明确停止。

组合指标研究支持EMA交叉+MACD+KDJ确认，指定周期先忠实实现；开发失败在预算内继续修订，能力/数据/预算不足须明确说明。progress提供最近100条白名单详细活动日志，BitPro工作流置顶且只为实际运行阶段播放动画。

默认研究 Provider 为 Codex / GPT-6 Astra。新生成策略按净值比例约束目标保证金，订单回执与实际持仓一致性进入执行逻辑；资金策略绑定人工审核包。

新研究默认启用 Paper 7+7 反馈：完成 UTC 日、同会话小时权益采样、任一指标退化 10 个百分点触发独立参数研究；同窗新旧复验后再次人审，原 Paper 连续运行。数据与去重边界见统一闭环合同切片 4。

AVO 每轮请求提供包含历史动作及本次请求的预算总数、服务端计算的剩余额度与已计数候选 ID；模型不负责重复计算消耗。

AVO 任务支持显式 Provider 与任务模型选择并持久化；改选仅允许在未生成候选的停止任务上进行，不自动变更全局默认或购买模型额度。

AVO 主线：新建研究默认交给持久 worker；模型在预算内选择检查、候选变异、开发实验和最终提交，最终验证后仍等待人审。开发/隔离/最终窗口固定为 119/1/60 天，最终结果不反馈给同轮模型调参。已有 ARC 任务保持原模式，不因升级重跑。当前变异由受约束策略族与参数编译实现，不开放任意运行时代码自修改；详见当前实施合同切片 3。

新研究任务现使用 `paper_review.v1`：回测候选提交人工审核后才配置/启动 Paper，批准绑定代码、回测引用和配置哈希。CLI `ht research` 与 BitPro 代理操作同一 ARC mission。历史任务保持兼容；新协议不自动转入 Live。

实施入口：[统一研究闭环实施合同](contracts/user-directed-research-loop-consolidation.md)。
产品所有者已批准架构收敛及无用代码直接删除；第一切片移除四个孤立 ARC 实验模块，
保留仍被真实路径调用的研究和治理能力，后续迁移按该合同推进。

## Product-owner clarification — 2026-09-09

产品所有者进一步要求引入 AVO（Agentic Variation Operators）式自主研究与进化：
在 ARC 领域主线内，Agent 根据版本谱系、领域知识和真实实验反馈自主调查、变异、修复和验证。
它不是单次模板生成，也不新增一套独立业务状态机；原策略保留、每版本 Paper 人审和独立验证
边界不变。当前只修订设计，参数之外的结构演化仍需后续实施范围定义，详见架构 61 第 5.1 节。

当前第一阶段验收目标收敛为：生成策略、真实回测、逐版本人工 Review 后启动 BitPro Paper；
按同一策略最近 7 天与前 7 天的 Paper 表现比较，收益率下降或最大回撤扩大达到默认
10 个百分点（可配置），任意一项即启动自动参数调优与重新回测。新版本再次经人工
Review 后另开 Paper，与原版本并行；原策略和历史不修改、不重置。同一原策略已有
调优任务或候选待 Review 时不重复触发。系统提供可配置、每轮冻结的验证默认值。

第一阶段要求真实可恢复闭环，不以找到有效策略为完成条件。该产品边界取代下文早期
“预授权自动启动 Paper → Live 审批”的当前交付优先级，不表示代码已经切换，也不激活 Live。
架构现状、保留/合并/删除候选和建议迁移顺序见
[61 策略研究闭环架构梳理与删减建议](architecture/61-research-loop-architecture-rationalization.md)。
该文档的实现取舍仍待审阅；当前只交付分析文档，不执行代码删除。

## Product Summary

HyperTrade is a crypto trading agent for market research and execution. V1 focuses on stable agent capabilities: provider configuration, tool calls, RAG, memory, trace, market ingestion, connector capability discovery, risk gates, testnet execution, BitPro strategy lifecycle orchestration, and operator-facing harnesses.

HyperTrade 是一个面向行情研究与执行的加密交易 Agent。V1 重点是稳定 Agent 能力：Provider 配置、Tool Call、RAG、Memory、Trace、行情采集、Connector 能力发现、风控门禁、Testnet 执行、BitPro 策略生命周期编排和面向操作员的 Harness。

> Maturity correction (updated 2026-07-21): the reviewed trading-research capabilities and selected read-only
> Mission paths are usable, but the system is not yet a complete professional general Agent runtime.
> Sprint 121–123 have replaced Remote CLI/Web client-owned history with canonical Thread/Turn/Item and made
> new Mission state replayable from V2 events with independent completion proofs. Desktop/TUI/local compatibility,
> legacy records, Supervisor and Approval remain incomplete or separate paths. The target is defined in
> [architecture/34](architecture/34-next-generation-agent-runtime-audit-and-target-design.md); fixed-suite
> 100/100 results are bounded regression evidence, not an overall production-grade certification.

BitPro is treated as the base trading-system platform: it owns market/reference data, strategy storage, backtest execution, metrics, paper/simulation runtime, and future live execution. HyperTrade is the Agent control and research layer: it discovers BitPro capabilities, reads/writes through MCP tools only, generates and validates `BaseStrategy` code, starts BitPro-owned backtests, inspects real evidence, and promotes only passing candidates into paper simulation. HyperTrade must not copy BitPro business logic or bypass BitPro risk boundaries.

BitPro 作为基础交易系统平台：负责行情/基础数据、策略存储、回测执行、指标、模拟盘运行和未来实盘执行。HyperTrade 作为 Agent 控制与研发层：通过 MCP 发现 BitPro 能力，只经由 MCP 工具读写，生成并校验 `BaseStrategy` 策略，启动 BitPro 负责的回测，基于真实证据迭代，并且只把通过门禁的候选策略推进到模拟盘。HyperTrade 不复制 BitPro 业务逻辑，也不绕过 BitPro 风险边界。

## Long-Term North Star

HyperTrade 的最终产品目标是成为一个在操作员预先定义的资本、风险、市场和授权期限内，能够持续自主研究、
验证、组合、执行、复盘和迭代的量化交易员。它根据已经结算的回测、模拟盘和实盘结果识别策略适用状态与
衰减，同时从新的市场现象和未覆盖 regime 提出全新可证伪 Alpha 假设，而不只优化已有策略；系统生成并验证
新旧候选，根据当前市场状态配置多策略组合，并让合格策略在授权内进入实盘、让失效或越过风险条件的策略退出。

该目标及分阶段 Gate 定义在 [Autonomous Quant Trader North Star](architecture/35-autonomous-quant-trader-north-star.md)。
这是长期目标，不改变当前 mainnet 禁用、人工批准、只读 Mission Catalog 或 Sprint 121 的范围；任何自动
资金配置和实盘生命周期能力都必须通过新的合同、Risk Engine、LiveTradingMandate、Canary、对账和回滚门禁。

依赖有序的 Proposed 交付合同现为 Sprint 121–134：先完成 canonical 协议、Mission event、Approval、Outcome
和 BitPro 证据合同，再分别交付已有策略进化、全新策略发现、统一验证、自动 Paper、regime Shadow、
LiveTradingMandate、Live Canary 和有限自主组合 Pilot。详细链接见北极星文档的“交付合同序列”。

## Active Product Priority — Goal-Driven Research Loop M0

2026-07-24 产品所有者明确调整当前开发优先级：暂停 Sprint 132–134 的实盘扩张，先把已经交付但分散的
Provider、Mission、BitPro 策略/回测、统一验证和 Paper Incubation 能力收敛为一个最小自主研究闭环。

当前最高优先级用户结果是：

> 用户只提交一次自然语言策略目标；HyperTrade 自主生成多个候选、编写策略、调用真实 BitPro 校验和回测、
> 根据确定性证据淘汰并继续研究；达标候选在用户预先批准的 Paper 边界内自动进入模拟盘；预算耗尽仍无候选
> 达标时，系统交付完整失败证据并询问是否继续。

这次调整不改变长期北极星，也不授权任何 Live 能力。它修正的是交付顺序和产品主路径：

- 新增专用、持久化的 `AutonomousResearchController`，而不是继续扩大固定 ResearchGraph。
- 新路径采用动态、有预算的工具循环，不以 LangGraph 固定节点图作为核心编排。
- 模型负责目标解释、候选和失败后的下一假设；确定性服务负责权限、验证、状态迁移和完成证明。
- 复用 `ChatProvider` 保持 Provider 可切换，但 M0 生产验收只要求一个真实 Provider。
- BitPro 继续拥有策略、回测和 Paper 真相；未来 StockPro 通过相同平台端口接入。
- Sprint 132–134 保持未激活，直至 M0 和后续现有策略优化闭环完成并再次获得产品所有者明确批准。

开发设计见
[Goal-Driven Autonomous Research Loop M0](architecture/36-goal-driven-autonomous-research-loop-m0.md)，
M0 合同见
[User-Directed Autonomous Strategy Research Loop M0](contracts/user-directed-autonomous-strategy-research-loop-m0.md)。

2026-08-19 产品所有者确认第一档目标，激活
[User-Directed ARC 真身闭环与 Provider 假设层](contracts/user-directed-arc-real-closure.md)
为当前最高优先执行合同。它填充 M0 的两个未达成项：Provider 产生的候选（M0 Done Means #2）
与生产正路的真身验证（Done Means #14）。ARC 仍是唯一产品入口；Live 边界、Sprint 132–134
未激活状态与 M0 的其余安全边界不变。

## Current Product Path — ARC Research, Paper Observe, One Live Approval

产品入口是 `POST /api/v1/arc/missions`，不是第三条控制器。Agent 自己生成候选、本地预筛、再走
BitPro `strategy_validate_code` / create / `backtest_start_job`；`ARCGoalV1.success_criteria`
必须参与第二级判定。过检后自动上模拟盘并进入 `paper_observing`，不立刻 `mission_completed`。
观察窗（最短小时数 + 最少成交 + BitPro 对账）结束后生成 `LiveApprovalPackageV1`。缺 backtest
ref、paper instance、观察窗或对账时包状态为 `incomplete`，`POST .../live-approval/decide`
拒绝批准。操作员批准后才走审批绑定的 `authorized_live_promote`；`call_tool("live_promote")`
和现货/合约下单、划转仍然拦截。Mission 投影落在 `arc_missions`，重启可恢复。

证据窗口带来源合同（2026-08-23）：preflight 与每个 attempt 的证据记录携带
`source_origin`（`okx_swap` / `alternative_exchange` / `archive_unknown`）、`window_as_of`
与 `window_source_hash`。归档文件自身无溯源，来源由部署通过 `ARC_EVIDENCE_ARCHIVE_ORIGIN`
声明。窗口来源不可证明为 OKX 时，mission 必须在创建参数中显式
`alternative_source_confirmed=true` 才允许消耗候选预算，否则停在
`needs_operator(evidence_window_unavailable)`，且替代来源在进度视图与证据视图中可见——
替代数据是显式事实，不是静默降级。

Provider 假设通道（2026-08-23，真身已验证）：`ARC_PROVIDER_HYPOTHESES_ENABLED=true` 时，
配置的 ChatProvider 以"假设提出者"身份参与蓝队——只能产出 `research_strategy_spec.v1`
形状的 spec 并经同一确定性 codegen 与静态门禁编译，候选携带 `origin=provider_hypothesis`
与模型/request-hash 溯源；预算、验证门槛、Paper 授权不在模型词表内，非法回复记显式
`provider_status` 且确定性路径不受影响。BitPro 写链路（validate → create → backtest →
result）已于生产真身验证；成功指标按 BitPro 实际键名与 `*_pct` 单位翻译后由
`success_criteria` 裁决。

`api` 与 `worker` 是两个进程，同时推进同一个 mission：前者跑研究循环并服务审批，后者推进模拟盘
观察。`arc_missions.revision` 区分缓存投影与已提交投影：读命中缓存时先比对 revision，落后就重载；
写在 mission 行上串行，发现行已前进就把控制器 rebase 到已提交投影再重放该事件。任何一方都不会
用自己的整份快照覆盖对方已提交的事实。

外部控制台（BitPro）通过服务令牌调用同一组 ARC 路由：`arc:read` 可读任务列表、进度视图、证据视图
和候选下钻，`arc:start` 可创建任务和追加预算。令牌结构上没有审批能力。实盘审批只接受 HyperTrade
管理员会话，或 BitPro 对 `mission_id + decision + operator_id + idempotency_key + issued_at`
签名的 `X-Operator-Assertion`。记录的操作人带 `identity_source`，区分 `hypertrade_session`
与 `bitpro_signed`。证据视图是投影的只读渲染，列表响应不含策略源码。

`GET .../missions/{id}/progress` 是给轮询控制台的流水线投影：七个阶段（目标编译、候选探索、红队
对抗、BitPro 验证、模拟盘观察、实盘审批、实盘灰度）各带状态、计数和本阶段进度；后续阶段有证据即
认定前面阶段已走过——但 `incomplete` 的审批包是缺口清单，不算走到过审批阶段，预算耗尽的任务不会
因为末尾那份包而把模拟盘观察判成已完成。`needs_operator` / `failed` 把停住的那个阶段标为 blocked 并附最后一条
`operator_needed` 的原因，进度条不再给该阶段部分分数。活动流只投影事件类型与白名单标量字段，
不转发事件载荷，策略源码仍然只在候选下钻里。

## Canonical Agent Runtime Target

The next runtime uses a server-owned `Thread → Turn → Item` interaction protocol and links long-running
`Mission → PlanVersion → Step → Attempt → ToolCall` work explicitly. Commands append versioned domain
events; deterministic reducers build projections; clients never submit synthesized prior turns or maintain
a second completion state machine.

The professional loop is: intake and safety classification → context compilation → plan proposal → reviewed
capability resolution → deterministic policy and approval → dispatch → schema/provenance validation →
Evidence ledger → independent completion verification → bounded replan or response. Models may propose plans,
arguments and prose; they cannot grant permissions, validate their own evidence, reconcile unknown side effects,
or declare terminal completion.

Tool policy resolves `allow | ask | deny` using capability/version, structured arguments, symbol, account,
environment, path/resource, role, budget and context. Deny cannot be overridden by approval. Research,
backtest, paper, Testnet, live-read and live-write permissions use distinct identities and deployments; live-write
capabilities and credentials remain physically absent.

Multi-agent execution is an optional bounded Delegation DAG, not a default conversation group. Delegations carry
typed objectives, evidence/artifact inputs, a capability subset, budget, deadline and output schema. Independent
evidence and risk verifiers validate handoffs, and conflicting claims remain visible instead of being removed by a
majority vote.

Delivery follows vertical cutover with no permanent dual writes. Sprint 121 migrated Remote CLI ask/chat to
the canonical protocol and requires correct real two-turn entity resolution, deterministic event replay, SSE
recovery, zero false completion and zero legacy Run/Task writes. Sprint 122 migrates the Web natural-language
workspace to the same server projection; Desktop and TUI remain later slices.

Sprint 121 provides the Remote CLI vertical slice: authenticated Thread/Turn/Item REST/SSE,
content-bound client idempotency, deterministic in-memory/SQL replay, worker fencing, server-owned follow-up
resolution and explicit read-only Mission links. Sprint 122 now adds Web Thread restore/archive, cursor reconnect,
canonical Item/Evidence/unknown rendering and explicit legacy-history separation without Web Run/Task writes.
Desktop/TUI/Local CLI and legacy historical reads remain unchanged pending later slices.

Sprint 123 makes newly created Missions canonical event aggregates. Mission, Plan, Attempt, usage, current step,
steer and terminal state are reduced from schema/reducer-versioned events with payload hashes, correlation,
policy snapshots and worker fencing. Online SQL/in-memory projections must equal offline replay hashes. A separate
`CompletionProofV1` checks criteria, Evidence/Artifact binding, pending/unknown attempts and budget before Mission
or linked Turn completion. Pre-V2 Missions are labeled `legacy_non_replayable` and are not backfilled with invented
events. Approval and external-effect reconciliation remain Sprint 124 scope.

Sprint 124 adds the governance contract required before any external mutation: `PolicyDecisionV1` binds the exact
capability version, arguments, subject/account/environment, role, budget and policy snapshot; an `ask` decision
requires a separately granted, expiring, one-time Approval. Every accepted write first persists a content-bound
`DispatchIntentV1` and `ToolCallV1`. A timeout or ambiguous adapter result becomes `effect_unknown`, is never
blindly redispatched, and blocks `CompletionProofV1` until reconciliation establishes a definite outcome. Circuit
state, recovery and operator override are durable and audited. The implementation defaults to isolated adapters
only and adds no production paper, Testnet, live, order or capital capability. Sprint 125 will consume these
canonical outcomes to build the Strategy Outcome/Lesson Ledger.

Sprint 125 implements that immutable learning boundary. `StrategyOutcomeV1` binds a settled research rejection,
validated backtest or paper observation to the exact strategy lineage/version/Card, manifest/code identity,
parameters, data/cost window, regime, metrics, Evidence/Artifact, Mission CompletionProof and any Approval/ToolCall
or observation-window facts. Corrections append new hash-bound records. `LessonCandidateV1` keeps support,
opposition, unknowns, scope, regime, confidence method and validity visible; only an independently reviewed active
Lesson is context-eligible. The ledger does not auto-approve Memory, Skill, strategy or portfolio policy and does
not run research or mutate trading state. Sprint 126 extends BitPro's stable read contract with versioned,
cost-aware and bounded return series, fixed-denominator aligned matrices and execution-quality evidence.
HyperTrade validates versions, hashes, UTC ordering, future/duplicate points, cost completeness and comparability
before persisting summaries and source references only; it never copies raw series or BitPro business logic.

Sprint 127 consumes only settled Strategy Outcomes and fresh Sprint 126 evidence to evolve an existing immutable
strategy version. A bounded `EvolutionMandateV1` constrains parameters, declared rule slots, scope, trials,
candidates, model/tool calls, wall time and deterministic seed. Actionable decay requires multiple settled facts;
single losses, stale evidence, unknown effects and data gaps remain review-only. Accepted candidates clone the
parent ExperimentManifest into a distinct queued experiment and same-lineage StrategyVersion, while rejected,
duplicate and budget-exhausted proposals remain auditable. The engine has no BitPro, paper, live, order or capital
adapter, and its API/CLI surfaces are read-only.

Sprint 128 discovers new strategy families without a parent strategy. A bounded `DiscoveryMandateV1` admits only
fresh, source-bound market facts and freezes observable phenomena plus falsifiable Alpha hypotheses before locked
OOS results are visible. Hypothesis versions are immutable; novelty is deterministic across existing rule/code
signatures, return/signal similarity and regime exposure, with missing comparison evidence remaining unknown.
Only novel candidates may pass static isolation and BitPro `strategy_validate_code` before reviewed dynamic-DB
`strategy_create`; the resulting immutable ExperimentManifest/StrategyVersion remains a research candidate with
paper, live, order and capital permissions disabled. Rejections, duplicates, data gaps, sandbox failures and budget
termination remain append-only terminal facts exposed through authenticated read-only queue APIs.

Sprint 129 places both evolution and discovery candidates in one Research Quarantine. An immutable
`ValidationPolicyV2` and `TrialFamilyV1` bind candidate freeze time, first locked-OOS access, every successful or
failed attempt, real-data/cost/artifact references and the full required gate set. A deterministic verifier—not an
LLM—derives `validated`, `rejected`, `needs_data` or `needs_review` from OOS, walk-forward, purge/embargo, funding,
capacity, drawdown, tail risk, probabilistic/deflated Sharpe, selection bias, parameter stability, cost stress and
regime evidence. Discovery adds novelty falsification but cannot remove common gates. Decisions are immutable and
versioned by candidate, policy, trial family and source hash; StrategyCard receives a new research projection only,
while Paper, Live, order and capital state remain unchanged.

Sprint 130 admits only an exact fixed denominator of Sprint 129 `validated` candidates into an operator-created
`PaperResearchMandateV1`. The authenticated creator must be the named human approver; candidate, validation
fingerprint, symbol, capital, action, cost, risk, horizon and validity bounds are immutable and content-hashed.
Configure, start, pause and retire use Sprint 124 one-time Approval plus write-ahead DispatchIntent/ToolCall;
ambiguous effects remain `effect_unknown` until read-state reconciliation and are never blindly retried. Paper
observations can automatically issue the same governed pause when drawdown, errors, abnormal trades, stale data or
BitPro health cross the mandate boundary. Immutable 30/60/90-day PortfolioObservationWindows and PaperCohorts keep
incomplete horizons and single-member groups from producing a Champion. API, CLI and Harness expose server-owned
mandate/member/action/kill-switch state; the controller protocol contains no Testnet, live-order, capital-transfer
or credential surface, and every projection explicitly reports `live_authorized=false`.

Sprint 131 adds immutable, point-in-time `MarketRegimeSnapshotV2`, per-version `StrategyEligibilityV1`, and
`RegimeShadowTargetV2`. Regime probabilities remain source/as-of/availability bound, missing values stay unknown,
and ex-post labels never enter decisions. Eligibility is calculated before weights over the fixed Paper cohort
denominator. Four deterministic allocation templates enforce strategy, symbol, capacity, liquidity, correlation,
turnover, transaction-cost and weight-delta constraints; missing required inputs or infeasible bounds suppress the
target instead of applying defaults. Entry/exit hysteresis, confirmation windows, minimum dwell and cooldown prevent
churn. Historical replay uses only then-visible source versions. API, CLI and Harness are read-only projections and
all outputs keep execution, capital, paper lifecycle and live authorization false.

## Users

- Operator running audited agent research and execution workflows.
- Quant trader researching OKX perpetual swap market structure.
- Engineer integrating stable external data and execution-state providers.

## Core User Journeys

1. Operator opens `/harness` and reviews the core workbench: Agent run creation, report reading, recent runs, Flight Recorder trace/Token/Memory telemetry, RAG, Memory, and OKX market snapshot without a login wall.
2. Worker continuously ingests OKX SWAP ticker snapshots.
3. User asks for a market summary in free-form chat.
4. Agent calls market, RAG, and memory tools, then stores trace and report.
5. User reviews the report from `/harness`; privileged sharing or mutation actions stay outside the primary workbench and require admin-authenticated API/CLI paths.
6. User creates auditable strategy research records and Backtrader backtests through API/CLI workflows.
7. Developer runs `hypertrade` for a standalone terminal Agent, or `hypertrade --remote <url>` to connect to a deployed API.
8. Operator can open the optional macOS floating bot for a short governed research question. User
   messages appear on the right and HT conclusions on the left; the desktop client projects public
   Mission events only and keeps credentials and execution authority on the server.

## Post-Sprint-44 Capability Roadmap

The next development phase is split into parallel contracts under
`docs/contracts/sprint-45-*` through `docs/contracts/sprint-54-*`. The governing
design document is `docs/architecture/18-hypertrade-capability-roadmap.md`.

The roadmap keeps BitPro as the trading-system platform while HyperTrade grows
its own Agent capabilities:

- Agent runtime reliability and tool policy
- structured strategy evidence
- evidence-driven strategy iteration
- multi-source market intelligence
- risk and governance policy
- report provenance
- monitoring and alerts
- frontend operator console
- Agent evaluation suite
- connector framework

## Approved Post-Sprint-80 Research Institution Roadmap

The next proposed strategy-research phase is governed by
`docs/architecture/23-autonomous-strategy-research-institution.md` and the
Sprint 81–84 contracts. It develops an operator-controlled, evidence-bound
research institution on top of the existing BitPro lifecycle integration:

- Sprint 81: research mandates and durable jobs define what an Agent may
  research and keep work state outside chat history.
- Sprint 82: a bounded BitPro backtest matrix validates dynamic DB strategies
  against real data and locked out-of-sample windows.
- Sprint 83: passing candidates require a human-approved, idempotent BitPro
  paper-promotion action and remain under read-only observation.
- Sprint 84: WorldState/portfolio review combines strategy lifecycle evidence
  with market-state and monitoring evidence to recommend research or review
  actions.

This roadmap does not promise stable profitability and does not add automatic
live trading, automatic live promotion, direct BitPro database access, or
BitPro business logic to HyperTrade.

## Approved Post-Sprint-95 Agent Research OS Roadmap

The approved Sprint 96–105 phase is documented in
`docs/architecture/27-agent-research-os-roadmap.md`, with implementation-level
contracts in `docs/contracts/sprint-96-*` through `docs/contracts/sprint-105-*`
and the cross-sprint technical design in
`docs/architecture/28-agent-research-os-technical-design.md`.

It keeps the Sprint 81–94 research, BitPro, paper-observation, governance, and
isolated-evaluation boundaries intact while adding:

- durable Agent sessions, tasks, checkpoints, control actions, and resumable events;
- a role-scoped multi-Agent research graph whose outputs use a structured evidence contract;
- immutable experiment fingerprints and bounded robustness validation;
- Research OS recovery, evidence, budget, and tool-safety evaluation;
- an optional TUI over the same API/event contracts as CLI and Web;
- bounded background research triggers, governed Memory/Skill changes, and
  read-only portfolio lifecycle review.

This phase entered implementation with Sprint 96 on 2026-07-14. It does not enable automatic paper
promotion, automatic live trading, automatic capital allocation, arbitrary
Agent code execution, or any bypass of BitPro MCP and existing approval gates.

Sprint 97 entered implementation on 2026-07-14 after Sprint 96 production
acceptance. Its active boundary is the append-only Research Evidence V2 contract;
the multi-Agent role graph remains deferred to Sprint 98.

Sprint 98 completed implementation and production acceptance on 2026-07-14.
The fixed 13-role LangGraph DAG uses durable Task/Node/Event/Checkpoint state,
Evidence V2-only outputs, read-only role-policy intersections, atomic budgets,
bounded provider/BitPro concurrency, safe-point controls, failed-node replay,
and a trusted StrategySpec handoff to the existing ResearchOrchestrator queue.
Invalid provider JSON receives one repair attempt and then becomes an explicit
data gap; it is never stored as evidence. No role can invoke paper/live writes,
and the graph cannot promote a candidate or allocate capital.

Sprint 99 completed implementation and production acceptance on 2026-07-14.
Every orchestrated experiment now receives a canonical `ExperimentManifestV1`
fingerprint before BitPro strategy/backtest writes. Immutable manifests are separated
from append-only executions and evidence links; same-fingerprint requests reuse one
physical execution, failed/forced attempts retain an audit reason, and bounded BitPro
refs, metrics, artifact hashes and usage remain queryable through API and `/ledger`.
Raw data, secrets, full prompts and private reasoning are excluded. Robustness selection
remains deferred to Sprint 100, and no paper/live permission changed.

Sprint 100 completed implementation and production acceptance on 2026-07-15.
Bounded locked-OOS, walk-forward, parameter-neighborhood, cost/slippage and optional
regime scenarios produce explicit passed/failed/unknown/not-applicable gates and a
persisted validated/rejected/needs_data/needs_review result. Every scenario is tied to
the immutable experiment ledger and BitPro job/result refs. Strategy code must pass
BitPro's sandbox plus deterministic runtime smoke before creation; failed or incomplete
backtests fail closed. Paper promotion now requires a validated result but remains an
explicit human action. Unbounded optimization, profitability claims, raw-result
persistence, automatic paper/live promotion and capital allocation remain excluded.

Sprint 101 completed implementation and isolated acceptance on 2026-07-15 after
Sprint 100 production acceptance. It extends the required offline evaluation gate across Task recovery,
multi-Agent role ordering, Evidence V2 integrity, experiment reproducibility,
robustness decisions, budgets, privacy and pre-dispatch tool safety. Authored golden
cases and deterministic fault injection run locally; provider-backed Promptfoo/Ragas
baselines remain restricted to the explicit Sprint 94 isolated target. Evaluation
scores cannot authorize paper/live actions or use profitability as a quality score.
The required suite now passes 38 cases, including 24 versioned Research OS cases;
Promptfoo passes six attacks with zero dispatch, and two complete provider-backed
baselines expose the generic Agent's low Research Graph alignment without hiding it.
All optional evaluation dependencies execute in a separate locked Docker target and
final artifacts contain no prompts, reports, tool arguments, raw outputs or credentials.

Sprint 102 completed implementation and production acceptance on 2026-07-15. It adds an optional Textual TUI
that projects the durable Session/Task/Event/Evidence/Experiment/Validation contracts
and reconnects from a cursor after SSE loss. The client contains no trading, approval,
budget or state-transition business logic: every mutation remains an authenticated API
request with reason and idempotency, and dangerous actions require an explicit modal.
The existing chat CLI, plain renderer and Web Harness remain supported.
Textual is pinned at 8.2.8 in a separate optional/client image. REST-first snapshots,
cursor SSE replay/deduplication, gap-triggered reconciliation, responsive 80/120/160
column layouts and reason-required control modals are covered by headless and client
tests. Production API/Worker images do not contain the UI dependency.

Sprint 103 completed implementation and production acceptance on 2026-07-15. It adds persistent background
research triggers for bounded schedules and already-committed regime, drift, data
quality and evaluation facts. Production and isolated runtimes remain disabled by
default. A trigger can create only a budgeted `triggered_research` Task after feature
flag, kill switch, mandate, lease, fingerprint dedupe, cooldown and quota checks; it
cannot call any BitPro, paper, order, approval or capital-allocation adapter. Trigger
decisions are immutable, event projections are schema-bounded, scheduled claims use
PostgreSQL row locks/leases, and API/CLI/TUI controls require administrator authority
and operator reasons. Production migration `0016_research_triggers` is active while
the worker feature remains explicitly disabled.

Sprint 104 completed production acceptance on 2026-07-15. Governed Memory assertions require active Evidence V2 sources and explicit
review; conflicts, supersession and expiry remain queryable while ordinary Memory reads
fail closed. Code-free Skill definitions pass schema/static policy, a HMAC-authenticated
isolated regression attestation and independent administrator approval before an
immutable version can become active. The role loader rechecks release hash, schema,
role and tool-policy intersection and injects template metadata only. It cannot execute
Python/shell, register endpoints/tools or widen paper/live permission. API, CLI, TUI and
Web review surfaces contain no alternate state transition logic.

Sprint 105 completed implementation and production acceptance on 2026-07-15.
`portfolio_assessment.v2` persists canonical request/policy/content hashes, bounded source
refs, per-strategy lifecycle projections, pairwise aligned-return summaries, explicit
unknowns and six fixed research/review recommendations. Request and review idempotency keys
are bound to their canonical payloads. Human accept/reject/hold writes only a review ledger;
the portfolio module imports no BitPro/paper/live mutation adapter. API, CLI, Textual and
Web are thin projections of the same service. It cannot allocate capital, rebalance,
pause/start strategies, promote to live, place orders, or overwrite historical facts.
Production intentionally returned `needs_data` with an explicit unknown when no StrategyCard
was available; it emitted no recommendation and no human review rather than inventing inputs.

## Approved Post-Sprint-105 Research Operations Roadmap

The approved planning sequence is documented in
`docs/architecture/29-research-operations-shadow-portfolio-roadmap.md`. Sprint 106
completed production acceptance on 2026-07-15. Two isolated 26-case runs passed
`agent_research_quality.v2` route/source/citation/Task/Graph/safety gates with zero unsafe
dispatch, bounded candidate tools and a single fail-closed repair. Sprint 107 moved StrategyCard creation from the
PaperPromotion boundary to the StrategySpec/ExperimentManifest lifecycle and adds stable
lineage/version/incomplete projections; Gate F passed production acceptance. Sprints 108–110 add bounded portfolio evidence
windows, human-reviewed Champion–Challenger paper cohorts and execution-isolated Shadow
Portfolio proposals. None of these phases promises profitability or enables automatic
paper/live promotion, capital allocation, rebalance or orders.

Sprint 108 completed production acceptance under
`docs/contracts/sprint-108-portfolio-evidence-data-plane.md`.
Observation windows use only bounded BitPro MCP reads and persist source-bound statistical/quality
summaries, never complete equity/return/position/trade/order series. Missing or unhealthy sources
remain explicit unknowns and cannot trigger paper, live, order or capital actions.
The production three-Card denominator retained two no-window candidates and one available bounded
window; raw-series key audit and execution-side count comparisons passed.

Sprint 109 completed production acceptance under
`docs/contracts/sprint-109-champion-challenger-paper-incubation.md`. Cohorts consume committed
Card/Manifest/Observation summaries only, require exact comparison keys, retain every rejected or
unknown candidate in the denominator, and make all expiring labels human-review facts with no
paper/live/order/capital authority. Production retained three Cards but returned 0 comparable
members and 0 proposals, with idempotent replay and unchanged execution-side counts. Gate G is
closed; Sprint 110 adds only execution-isolated Shadow Portfolio proposals and review facts.

Sprint 110 completed production acceptance under
`docs/contracts/sprint-110-shadow-portfolio-capital-governance.md`. It consumes only immutable,
accepted and unexpired cohort evidence; compares a fixed set of bounded templates; preserves all
excluded members and unknowns; and makes every scenario/order impact explicitly hypothetical.
Neither proposal build nor human review has paper, live, order or capital authority. Production
retained three intake members but returned 0 eligible/0 scenarios because no accepted comparable
cohort exists; repeated build was idempotent, persisted no execution payload keys and changed no
paper/live counts. Gate H and the Sprint 106–110 research-operations route are closed.

## Active Professional Agent Runtime V2 Roadmap

Sprint 111 completed production acceptance on 2026-07-15. The new `hypertrade.runtime` Mission core is an
independent source of truth and does not dual-write legacy Task/Run state. Execution remains behind
`MISSION_RUNTIME_ENABLED`, off by default, and the initial capability is read-only. The implemented
technical boundary is documented in
`docs/architecture/31-professional-agent-runtime-v2-technical-design.md`.

The active Sprints 111–116 sequence is documented in
`docs/architecture/30-professional-agent-runtime-v2-roadmap.md`. Existing AgentKernel, Task OS and
fixed Research Graph internals are not compatibility constraints: proven domain facts, external
contracts and safety policies remain, while weak orchestration/state/UI code may be replaced and
deleted. The new runtime adds a durable Mission aggregate, immutable Plan versions,
validated Step observations, bounded adaptive replanning, reviewed capability discovery, compiled
Context Packs, a Mission Artifact Index, bounded multi-Agent supervision, sandboxed strategy
development and long-horizon readiness evaluation. Sprint 116 also defines a compact public
`OperatorResponseV1` and an isolated output-evaluation catalog: user-facing answers carry only
conclusion, confidence, provenance-bound evidence, explicit gaps and a safe next action. Internal
Mission/Plan/tool telemetry remains an audited drill-down, not default chat content; model prompts,
answers, tool arguments and raw results are never retained in output-evaluation artifacts.

The reviewed Mission read catalog includes market, RAG/Memory, local strategy/backtest performance,
BitPro live-strategy inventory, paper portfolio and pending Testnet intent summaries. BitPro inventory
queries follow the MCP capabilities/health/live-strategies read chain and return a bounded, source-bound
operator list; they cannot create/approve/execute an order or change paper state. Isolated evaluator
facts are synthetic, post-migration and explicitly environment-gated; they are never seeded in production.

Sprint 118 replaces contract-only public-answer readiness claims with a 100-task operator-completion
gate. The gate tests the actual user-visible answer, source category, context resolution, safety and
final desktop delivery in a physically separate evaluation target. A declared unsupported multi-turn
task, an empty generic conclusion or an ungrounded data gap is a failed task, not a passing safety result.
For tasks that declare a target decision fact, the fact must appear in `OperatorResponseV1.decision`
itself; evidence-body keywords cannot satisfy a conclusion-relevance assertion.
The runtime receives at most eight prior *user* turns through the Agent API and resolves references only
when an unambiguous bounded context is available; it records a hash-only conversation reference and never
treats prior assistant output as evidence. Deterministic capability handlers project only the exact operator
facts needed for the request (for example return, drawdown and trade count for a backtest, or status and
PnL for a live strategy). Missing records, unavailable sources and unavailable order detail remain explicit
data gaps with a next action, rather than a generic “completed” result. These response projections stay
read-only and preserve the catalog’s source provenance and execution isolation.

Sprint 119 adds a production delivery hardening gate after a real `ht` Mission completed in the worker
but lost its terminal response during public projection. Every `/api/agent/runs/stream` path must emit a
bounded, renderable `final` event even when a terminal projection or legacy execution fails; it must not
expose the underlying exception. If a CLI receives an unexpected EOF after a durable Mission/Run/Task id,
it reads the server-owned final projection before reporting a typed, traceable failure. Live-strategy
requests using “best/worst/ranking/performance” require numeric, comparable `return_pct` values for every
candidate; a strategy inventory without those values is an explicit data gap, never a list-order ranking.
The visible `OperatorResponseV1.decision` remains bounded independently from longer evidence, so a valid
inventory cannot break the public delivery contract.

Sprint 120 adds a hybrid semantic-ingress boundary for free-form Mission requests. The configured model
first returns a small structured intent with any explicitly named market symbol; the server then verifies
that symbol is present as a full user token, normalizes it to the reviewed OKX swap format, and keeps the
existing catalog-selected read capability, dependency graph and permission profile immutable. Invalid,
unavailable or invented model entities fall back to deterministic parsing. A named symbol must produce
either its own price/provenance or a symbol-specific data gap; a generic market snapshot count is never a
valid substitute.

Migration uses vertical cutover without dual writes; historical runs remain read-only, and every
Sprint includes an explicit legacy deletion budget. The roadmap is planning-only until explicitly approved. The first draft contract is
`docs/contracts/sprint-111-professional-agent-loop-v2.md`; no feature flag is enabled and no current
paper/live/order/capital permission changes. Professional Agent capability means controllable,
recoverable and evidence-backed goal execution, not unrestricted autonomy or profitability.

Sprint 112 replaces direct Mission tool dispatch with a reviewed, versioned Capability Catalog and
`ToolObservationV2` boundary. Definitions bind JSON Schemas, source owner, health/freshness, side
effects, approvals, idempotency, timeout, result bounds and contract/policy hashes. Discovery creates
pending proposals only; authenticated idempotent administrator review is required before activation.
Execution validates schemas and permission scope before and after the adapter call, applies bounded
timeout/circuit recovery and stores only redacted/truncated SQL observations with provenance. The
initial catalog remains read-only and changes no paper, live, order or capital permission.

Sprint 113 compiles a deterministic, hard-budgeted Context Pack for every Mission Step and records
stable include/drop decisions for each source. Objective, constraints, permission, Plan and Step
contracts are mandatory; prior observations enter only as bounded summaries and provenance refs.
The Mission Artifact Index binds content hashes, versions, producers, source relations and stable
external refs or bounded safe previews. Completion rejects forged, cross-Mission, unavailable or
superseded artifact refs. Raw BitPro series, credentials, full transcripts and private reasoning are
forbidden from both stores.

Sprint 114 adds a bounded Multi-Agent Supervisor over four reviewed read-only roles. Independent
assignment DAG nodes may run concurrently only after atomic token/tool/model/duration reservation;
dependencies run in later layers and role/team concurrency is hard-limited. Handoffs are structured,
source-bound and content-hashed. Contradictory claims create an immutable Conflict ledger and remain
explicit unknowns in merge output. Dynamic teams are disabled by default and cannot add write,
paper, live, order or capital permissions.

Sprint 107 implementation uses `ExperimentManifest` as the StrategyCard V2 identity boundary.
Mandate-scoped lineages, Manifest-bound versions, immutable content-hashed snapshots and human
lifecycle decisions are projection facts in `0019`; they cannot edit source facts or authorize
execution. The research funnel denominator is the Manifest candidate set, including incomplete
and rejected candidates rather than only PaperPromotion records.
Production reconciliation proved a fixed three-Manifest denominator, stable one-lineage/three-version
identity and idempotent three-snapshot projection without changing PaperPromotion, paper order or
live-order-intent counts.

## V1 In Scope

- Harness routing: sidebar destinations are independent, refreshable SPA paths
  (`/harness`, `/harness/strategy`, `/harness/portfolio`, `/harness/alerts`,
  `/harness/runs`, `/harness/quality`, `/harness/memory`, `/harness/rag`) rather
  than hash-scroll targets in one
  long workbench view.
- Harness visual system: every routed workbench page uses a dark observability
  console with green-black surfaces, restrained grid texture, cyan runtime
  state, amber audit emphasis, and red risk state. This is display-only and
  does not alter research, approval, paper, or live-execution behavior.
- Harness Memory observability: `/harness/memory` aggregates existing audited
  active Memory items client-side into explicitly labeled composition, creation
  cadence, importance, confidence, and reuse visualizations. It is read-only;
  it does not introduce a storage quota, a second Memory store, or a mutation
  path.
- Harness route context metrics: every routed page shows a compact, read-only
  metric-card strip derived from the data already loaded for that surface. The
  workbench retains global telemetry; strategy, alerts, runs, Memory, and RAG
  show their own scoped evidence, state, or inventory counts.
- Harness operator cards: strategy evidence, monitor alerts, approval intents,
  Memory entries, and RAG hits use one shared dark card treatment with explicit
  semantic rails. Passing/normal state is signal, evidence or pending review is
  brass, and high-risk or final failed state is danger; the UI does not infer a
  new risk decision from the visual tone.
- Harness strategy card hierarchy: strategy summary, performance metrics,
  provenance references, failure reasons, next-experiment guidance, and evidence
  drilldown rows all use the compact operator-card variant. Nested cards remain
  visually quieter than their selected evidence card, with source-bound tone
  only and no backend or validation behavior change.

- FastAPI backend with public workbench observability/read endpoints and admin session auth for privileged mutations.
- LangGraph-style AgentKernel with explicit traceable tool calls.
- DeepSeek default provider configuration.
- Qwen embedding configuration path and pgvector schema.
- PostgreSQL job table and worker process.
- OKX SWAP market ingestion: WS tickers + REST fallback/supplements.
- RAG scanner over `docs/knowledge`.
- Audited memory writes with disable/delete support.
- React `/harness` and market summary UI.
- Docker Compose and host Nginx deployment on ports `3333/3334`.
- Sprint 03 strategy research and Backtrader backtest workflow with persisted Markdown/JSON reports.
- Sprint 05 standalone hybrid CLI runtime with local AgentKernel mode and remote API mode.
- Sprint 06 CLI slash commands for status, tools, runs, memory, strategy research, and backtests.
- Sprint 07 CLI shortcuts `/research` and `/backtest` for strategy workflow triggers.
- Sprint 08 LLM-driven `AgentPlanner` using DeepSeek function calling; when no
  chat provider is configured, free-form Agent runs return a provider-unavailable
  report instead of guessing a tool route.
- Sprint 09 exact `market_ticker` tool for any listed OKX USDT SWAP symbol or instrument id.
- Sprint 10 `market_candles` tool for recent OKX candles and deterministic trend features.
- Sprint 11 `market_compare` tool for multi-symbol relative strength ranking.
- Sprint 12 CLI/API run streaming with run and tool progress events.
- Sprint 13 live OKX candle input for Backtrader backtests.
- Sprint 14 Agent acceptance tests for tool selection, traceability, RAG, Memory, strategy research, backtesting, and output quality.
- Sprint 15 deterministic CLI market shortcuts and clearer Agent run status display.
- User-directed Operator Console: CLI welcome output prioritizes selected
  provider/model, explicit Mainnet blocking, natural-language research tasks,
  and status/review/approval controls instead of a catalog of tool shortcuts or
  paper mutations. The production deployment can select Codex using a
  server-local read-only OAuth secret without changing the project-level local
  default or committing credentials.
- Sprint 16 structured CLI report rendering that prefers JSON/trace payloads over raw Markdown when possible.
- Sprint 17 Rich CLI renderer for terminal panels/tables with plain text fallback.
- Sprint 77 CLI Flight Recorder: `HYPERTRADE_TRACE=summary|full` renders
  redacted provider/model, Token, latency, tool, Memory, and trace evidence;
  `/run <run_id>` reopens a persisted local or remote Agent run.
- Sprint 78 CLI market-answer quality: generic market prompts prefer
  `market_summary`, WorldState defaults to a compact conclusion, and the host
  wrapper selects Rich output for interactive terminals. Known read-only
  global-market calls are not policy-denied, interactive CLI output prioritizes
  the Agent conclusion, and WorldState audit blocks remain opt-in.
- Sprint 80 paper strategy performance matrix: simulated-strategy ranking uses
  one bounded read-only tool, accepts only strategy-id-matched dashboard
  evidence, ranks reported paper returns, and exposes complete/partial coverage
  instead of inferring a winner from incomplete data.
- Sprint 81 research control plane: operator-authenticated mandates persist
  scope, budgets, validation windows, manual paper promotion, and disabled live
  mode. The Agent can read a mandate and generate only a schema-valid draft;
  durable idempotent jobs have auditable transitions but no scheduler, BitPro
  write, paper action, or live action.
- Sprint 82 BitPro backtest matrix: an admin-triggered, resumable worker
  preflights BitPro, requires real chronological K-line coverage and validated
  dynamic DB strategy code, then records a bounded in-sample/validation/locked
  out-of-sample matrix. Missing results or metrics fail closed; passing evidence
  remains `evidence_recorded` and cannot configure or start paper/live trading.
- Sprint 83 paper promotion and observation: one passing
  `ResearchExperimentEvidence` can create a `pending_paper_approval` record.
  Only an authenticated administrator providing a reason and unique idempotency
  key may configure/start its linked BitPro strategy. The resulting paper
  session is observed through dashboard, events, equity, monitor snapshots,
  and identity-scoped performance evidence. Data gaps become
  `paper_degraded`; alerts become `paper_review_required`; neither condition
  auto-pauses, retires, or reaches a live path. Agent-originated paper
  lifecycle writes are blocked by governance.
- Sprint 84 regime-aware portfolio review: a read-only `StrategyCard` projection
  joins mandate, validation, paper-promotion, and monitor evidence into the
  WorldState portfolio view. It returns only source-bound review actions and
  explicit unknown/data-gap states; it never mutates paper sessions, risk
  budgets, allocations, or live execution.
- Sprint 85 uses BitPro's immutable read-only `paper_snapshot` as the primary
  strategy-scoped paper-evidence source; no Agent or portfolio path may turn
  that evidence into a lifecycle write.
- Sprint 79 CLI unified report rendering: completed Agent answers take
  precedence over report-block/audit dumps in default output, while explicit
  tool/audit modes preserve the structured evidence. Simulated-strategy
  rankings must disclose when BitPro lacks per-strategy PnL/drawdown evidence.
- Sprint 18 paper-trading CLI controls for status, pause, and resume.
- Sprint 19 BitPro archived SQLite K-line source for Backtrader backtests.
- Sprint 20 paper close/reset lifecycle controls.
- Sprint 21 live/testnet order intent approval gate.
- Sprint 22 frontend harness parity for market tools, paper controls, and live approval.
- Sprint 23 Markdown report, Memory details, and complete backtest form UX.
- Sprint 24 graph-style Agent runtime with observable graph nodes and run state.
- Sprint 25 provider router and session model switching.
- Sprint 26 RAG v2 citation-ready search through pgvector-compatible storage.
- Sprint 27 Memory v2 with policy fields, dedupe, search, tags, and audit metadata.
- Sprint 28 RiskEngine for live/testnet order intents.
- Sprint 29 OKX Testnet signed order execution after approval and risk check.
- Sprint 30 multi-step strategy experiment workflow.
- Sprint 31 deterministic Agent eval suite and operations runbooks.
- Sprint 32 production-oriented project positioning and BitPro API tool-surface contract.
- Sprint 33 initial BitPro MCP adapter: capability/health preflight, K-line data direct access, paper dashboard reads, live-position diagnostics, API endpoints, Agent tool schemas, and `bitpro_mcp` backtest candle source.
- Sprint 34 BitPro strategy lifecycle Agent tools: strategy search/generation/creation/update, BitPro-owned backtest job start/status reads, and paper/simulation configure/start/pause/resume/stop with live-write tools still blocked.
- Sprint 35 strategy evidence loop: `/experiment <prompt>` now compares baseline, fast, and conservative variants, persists each backtest as evidence, selects a winner through explicit gates, and proposes the next adjacent experiment.
- Sprint 36 BitPro backtest detail artifacts: `bitpro_backtest_get_result` reads one BitPro-owned result, normalizes metrics and bounded equity/trade/order/fill/drawdown samples, and reports missing artifacts as unavailable.
- Sprint 37 BitPro paper monitor summary: `bitpro_paper_dashboard` produces current dashboard metrics, running strategy coverage, alerts, data gaps, and read-only recommended actions.
- Sprint 38 CLI command history: real TTY `hypertrade` chat sessions use readline-backed history so arrow keys recall previous prompts instead of printing escape sequences.
- Sprint 39 CLI semantic colors: real TTY output colors commands, tools, categories, approvals, status, success, warning, and error text while scripts and `NO_COLOR=1` remain plain.
- Sprint 40 strategy knowledge memory: completed local strategy experiments now persist a source-bound `strategy_knowledge` memory item with winner, parameters, metrics, gates, data selection, and next-experiment guidance.
- Sprint 41 documentation refresh: README, docs index, knowledge guides, architecture notes, testing plan, and runbooks describe the current Agent, BitPro MCP, strategy knowledge, and deployment validation paths.
- Sprint 42 BitPro paper evidence layer: `bitpro_paper_events` and `bitpro_paper_equity_curve` read bounded event/error and equity/drawdown evidence for paper monitoring, with structured Agent/CLI reports.
- Sprint 43 BitPro paper monitor snapshots: `bitpro_paper_monitor_snapshot` persists read-only paper dashboard/event/equity summaries, compares each capture with the previous snapshot for the same scope, and reports drift alerts/data gaps.
- Sprint 44 strategy library memory: `strategy_knowledge` Memory cards are aggregated into strategy-level evidence summaries through `StrategyLibraryService`, `GET /api/strategy/library`, CLI `/strategy library`, Agent tool `strategy_library_search`, and ToolRegistry entry `strategy.library_search`.
- Sprint 51 monitoring and alerts: monitor definitions, monitor runs, and alert events persist read-only BitPro paper, strategy-library freshness, and connector-health checks; API/CLI surfaces list monitors, run one monitor manually, and inspect recent alerts without calling paper/live write tools.
- Sprint 48 multi-source market intelligence: Agent tool `market_intelligence`
  reads OKX public funding/open-interest evidence plus deterministic curated
  market context, normalizes provenance/freshness/missing-field fields, and
  renders a compact `市场情报` report section as context rather than advice.
- Sprint 49 risk governance policy: `RiskGovernancePolicy` enforces
  ToolRegistry scope/approval/idempotency metadata before Agent tool execution,
  denies write-like external actions without `idempotency_key`, records
  `policy_decision` trace payloads, and renders clear governance denial reasons.
- Sprint 53 Agent evaluation suite: deterministic eval cases now guard
  strategy-library source use, BitPro page-parity result metrics, missing
  artifact disclosure, paper-monitor read-only behavior, and compact/default
  report rendering in addition to the original tool/RAG/Memory/risk checks.
- Sprint 54 connector framework: trusted in-repo connectors expose redacted
  capability/auth/tool metadata through `ConnectorRegistry`,
  `GET /api/connectors/capabilities`, `/api/harness/overview.connectors`, CLI
  `/connectors`, and ToolRegistry connector-origin rows; BitPro is represented
  through a compatibility connector and fixture connectors support
  deterministic tests.
- Sprint 46 strategy evidence schema: new `strategy_knowledge` cards store versioned `StrategyEvidence` JSON payloads while `StrategyLibraryService` remains backward compatible with legacy text cards.
- Strategy iteration planning can read prior strategy-library evidence through `strategy_experiment_plan`, `/api/strategy/experiments/iterate`, and CLI `/experiment iterate <prompt>` without triggering paper, live, or BitPro write tools.
- Sprint 55 CLI slash command candidates: incomplete slash prefixes such as `/st` or `/me` render filtered candidates with purpose descriptions, and readline Tab completion can display the same described candidate list.
- Sprint 56 market heat summary: broad market heat/sentiment/breadth prompts route to `market_summary`, compute OKX SWAP breadth metrics, and render a conclusion before raw ticker details.
- Sprint 58 Codex provider runtime: `codex`/`openai-codex` routes chat/planner
  calls through the Codex Responses API while HyperTrade keeps tool execution,
  policy, trace, RAG, and Memory inside its own Agent runtime.
- Sprint 60 monitor scheduler worker: default monitor definitions have
  conservative interval schedules, and the worker can run due monitors
  automatically while preserving the same read-only BitPro/tool boundary as
  manual monitor runs.
- Sprint 61 CLI Codex model picker: interactive `/model` renders numbered
  provider choices and, for Codex, a numbered model list backed by
  `CODEX_MODEL_OPTIONS`; API provider selection can carry a validated session
  model override without exposing tokens.
- Sprint 62 live order-history tool coverage: planner guidance and read-only
  BitPro diagnostics let real-account order-history prompts such as
  `我的实盘最近的一笔订单是什么` render `BitPro 实盘订单` evidence instead of
  falling back to all-market reports.
- Sprint 63 CLI selectable candidates: slash command and slash argument
  candidate lists render stable numbers, and interactive chat can dispatch a
  selected candidate directly by number.
- Sprint 64 Codex GPT-5.5 option: the default Codex model allowlist includes
  `gpt-5.5` between `gpt-5.4` and `gpt-5.4-mini`, while `CODEX_MODEL` remains
  the default selected model.
- Sprint 65 live strategy performance tool coverage: planner guidance and
  read-only BitPro diagnostics let real-account strategy performance prompts
  such as `看下实盘收益最高的策略` read BitPro `/live/strategies`, rank by
  `return_pct`, render `BitPro 实盘策略收益`, and avoid OKX all-market fallback.
- Sprint 67 LLM planner routing: free-form natural-language Agent prompts no
  longer use keyword branches or hidden market fallbacks in `AgentKernel`.
  Configured providers own semantic tool selection through `AgentPlanner`; no
  provider means an auditable provider-unavailable report with no business tool
  calls.
- Sprint 68 live BitPro routing evals: `/evals` includes live order-history and
  live strategy-performance guardrails that require the matching BitPro
  diagnostic tools and fail generic market-report fallbacks.
- Sprint 69 README framework guide: the root README is the public framework
  entrypoint, covering architecture, component responsibilities, installation,
  usage recipes, API/CLI examples, configuration, deployment, verification,
  troubleshooting, and development workflow.
- World-model development roadmap: `docs/architecture/22-world-model-development-roadmap.md`
  splits LeCun-style world-model thinking into HyperTrade phases: read-only
  global `WorldState`, scenario decision, defensive automation, and portfolio
  scheduling. The market state is global and cross-asset rather than only
  crypto; early phases remain read-only or human-confirmed.
- Sprint 71 read-only WorldState snapshot: `GET /api/world-model/snapshot`
  and Agent tool `world_model_snapshot` expose a global operator state across
  `global_market`, `crypto_market`, strategy evidence, execution state, tool
  health, deployment state, source references, missing data, and L0/L1
  candidate actions. Cross-asset feeds that are not wired yet are reported as
  `missing_data`; the Agent must not substitute `market_summary` for global
  WorldState prompts.
- Sprint 72 scenario decision layer: `world_model_snapshot` also returns
  deterministic `action_scenarios` and a `decision` record. Scenario scores show
  expected benefit, downside, confidence, data-gap penalty, reversibility,
  execution complexity, policy status/result, review window, and expected
  follow-up evidence for observe/hold/monitor/trace/human-confirmation/pause
  request/risk-reduction request actions. Scenario evaluation is still read-only
  and must not call paper, BitPro lifecycle, Testnet, or live write tools.
- Sprint 73 defensive automation gate: defensive automation is disabled by
  default and can run only explicitly allowlisted actions with idempotency keys.
  `raise_human_confirmation_alert` is the initial safe fixture action; all
  attempts are recorded through trace-backed audit and, when executed, an
  internal monitor alert. Missing idempotency, unsupported actions, offensive
  actions, stale evidence, and non-allowlisted requests are rejected without
  calling adapters or exchange paths.
- Sprint 74 portfolio scheduler: `world_model_snapshot` and
  `GET /api/world-model/portfolio` expose a rule-based portfolio view with
  strategy groups, allocation/risk-budget labels, evidence freshness, recent
  performance labels, drawdown availability, regime fit, correlation/shared
  exposure proxy, active status labels, portfolio recommendations, and
  missing-evidence markers. The scheduler recommends review, observation,
  targeted backtests/experiments, or defensive requests; it does not perform
  live allocation changes or offensive strategy promotion.
- Sprint 76 Agent Flight Recorder: provider-reported input/output/cached/reasoning
  Token usage is normalized across OpenAI-compatible Chat Completions and Codex
  Responses. Each planner model call records trace-safe iteration, route,
  latency, tool-call count, and usage without storing private reasoning text.
  `GET /api/agent/runs/{run_id}/observability` projects an ordered graph/model/
  tool/policy/Memory timeline, `/api/harness/overview.observability` aggregates
  recent-run telemetry, and `/harness` renders the componentized Flight Recorder.
- Sprint 92 Agent evaluation foundation: deterministic `/evals` remains the CI
  gate; an explicit evaluation mode rejects every write-like tool before
  dispatch, self-hosted Langfuse receives metadata-only trace projections when
  opt-in, and Promptfoo/Ragas run only against isolated evaluation targets and
  sanitized trajectories.
- Sprint 93 Agent golden baseline: a committed 24-case, authored and
  privacy-safe task set covers market, knowledge, Memory, strategy, BitPro,
  World Model, and write-attempt safety. An isolated-only runner produces a
  prompt-free diagnostic baseline for tool accuracy/F1, citation coverage,
  denial evidence, latency, and tokens; it does not gate deployment.
- Sprint 94 isolated evaluation deployment: a server-side `hypertrade-eval`
  runtime uses its own API, PostgreSQL container, network, loopback-only port,
  data path, and server-only configuration. It has no production BitPro data
  mount, Nginx route, paper/monitor worker by default, or production database.
- Sprint 95 production-readiness evaluation: attempted isolated provider-backed
  golden baselines, adversarial safety checks, deterministic-gate evidence, and
  a primary-source comparison with representative trading-Agent and
  production-quant systems are documented as diagnostic evidence. Incomplete
  provider or framework runs remain explicit findings; the review does not
  claim comparable trading performance or authorize live trading.
  It is logical isolation on the current host; a separate VM is required for
  physical isolation.
- Sprint 96 Agent Session and Task OS: every new local/API Agent run is backed
  by a durable Session/Task, while `AgentRun` remains one immutable execution
  attempt. PostgreSQL leases, heartbeat, checkpoints, cursor events, bounded
  budgets, idempotent controls, worker recovery, REST/SSE, and CLI inspection
  form one canonical control plane. Provider timeouts become structured
  retryable Task errors; they do not escape as an uncaught HTTP 500. Existing
  paper/live approval and BitPro MCP boundaries are unchanged.
- Sprint 97 Research Evidence V2: append-only facts, inferences,
  counter-evidence, and data gaps use one canonical UTC/Decimal hash contract.
  Facts require available non-Memory sources; inferences require active support;
  conflicts, expiry, rejection, and supersession remain queryable. Existing
  experiment/StrategyEvidence/Memory records are read-only legacy projections,
  and all V2 mutations remain administrator-only trusted-service operations.
- BitPro MCP Agent Token alignment: HyperTrade mirrors BitPro `agent_auth`, `remote_mcp`, scope classes, token-management routes, idempotency requirements, and live-diagnostic grouping while keeping token plaintext server-side only.
- CLI slash command discovery: entering `/` displays the command list, and interactive readline sessions support Tab completion for slash commands and common subcommands.
- BitPro backtest result reads through `bitpro_backtest_list_results`, including total-return threshold filters and page-parity reporting based on BitPro-owned result records.
- BitPro external API adapter contract for backtest data, base market data, paper/simulation state, and live trading state without copying BitPro business logic.

## V1 Out of Scope

- Mainnet live order execution. Mainnet intent creation may be audited, but execution is blocked.
- Automatic investment advice or unattended real-money trading.
- Milvus/Qdrant production vector clusters.
- Large parameter optimization sweeps and live/Testnet order generation from backtest results.
- Direct BitPro database access or copied BitPro trading logic; HyperTrade consumes BitPro capabilities only through explicit API contracts.

## Acceptance

- `./scripts/check.sh` passes.
- `GET /api/health` returns OK.
- `/harness` loads a simplified core workbench without rendering a login form: Agent run creation, report reading, recent runs, trace events, Flight Recorder Token/latency/Memory telemetry, RAG search, Memory search/detail, OKX top movers, and core telemetry.
- Advanced provider switching, paper lifecycle controls, live approval/execution, strategy lab/backtest forms, eval panels, Feishu send, and Memory disable are not first-class `/harness` UI controls.
- Privileged mutations such as provider selection, paper lifecycle control, live order approval/execution, Memory disable, and Feishu send still require admin session auth.
- `/api/harness/tools` shows live order approval gating.
- User can create an Agent market-summary run and inspect trace events.
- User can open `GET /api/agent/runs/{run_id}/observability` or the `/harness`
  Flight Recorder to inspect ordered graph/model/tool/policy/Memory events,
  provider-reported Token usage, tool latency, and linked Memory ids. Missing
  provider usage is marked unavailable rather than estimated, and prompts,
  secrets, and private reasoning text are not copied into the projection.
- User can call `GET /api/world-model/snapshot` or ask `现在全局状态怎么样`;
  the Agent uses `world_model_snapshot`, reports source refs and missing
  cross-asset data, and does not call paper, BitPro lifecycle, Testnet, or live
  write tools from the snapshot path.
- User can ask `现在应该继续持有还是降低风险`; the Agent can compare
  `action_scenarios`, show `decision` and `policy_status`, and prefer
  observation or human-confirmation when cross-asset data gaps are still large.
- Admin can inspect `GET /api/world-model/defensive-actions` and
  `GET /api/world-model/defensive-action-attempts`, and can execute an
  allowlisted defensive action through
  `POST /api/world-model/defensive-actions/execute` only when
  `WORLD_MODEL_DEFENSIVE_ACTIONS_ENABLED=true`,
  `WORLD_MODEL_DEFENSIVE_ACTION_ALLOWLIST` contains the action, and an
  idempotency key is supplied.
- User can ask `当前应该提高还是降低哪些策略权重`; the Agent uses
  `world_model_snapshot` portfolio evidence, reports `recommendation_type`,
  `policy_status`, missing evidence, and `allocation_change_allowed=False`
  unless a later explicit live-risk contract changes that boundary.
- With a chat provider configured, user can ask `看下目前市场的热度怎么样`
  and receive a market heat conclusion with sample count, advancer/decliner
  breadth, average change, strongest/weakest symbols, and top movers rather
  than only ticker tables.
- User can ask for a specific listed OKX SWAP symbol, such as ETH/SOL/DOGE/PEPE, and the Agent can
  call the exact ticker tool instead of returning only the all-market movers list.
- User can ask for a specific symbol's recent trend and the Agent can call the candle research tool
  to return OHLCV-derived features.
- User can compare multiple listed OKX SWAP symbols and the Agent can return relative strength
  rankings.
- User can ask for funding/open-interest context, such as `看 ETH 资金费率和持仓变化`,
  and the Agent can call `market_intelligence`, show source paths, timestamps,
  metrics, missing fields, and curated context without turning it into buy/sell advice.
- User can create a strategy research record and run a deterministic Backtrader backtest.
- Developer can run `hypertrade` as a standalone CLI Agent and see run id, tool calls, and report output.
- Developer can use the production host `hypertrade` wrapper as a remote client without attaching to the long-running API service container, so deploy-time API replacement does not terminate the terminal session.
- Developer can run `hypertrade /login` or `ht /login` once on a local machine to save remote API URL, username, and password to `~/.hypertrade/client.env` with local-only permissions; later `ht` commands default to the saved remote API unless `--local` is passed.
- Developer can see run/tool progress while `hypertrade ask` or interactive chat is still running.
- Developer can keep a remote CLI Agent run open through silent long-running tools such as BitPro
  backtests; SSE stream reads do not time out merely because no progress event arrived for a while.
- Developer can see a live `Thought` / `Thinking` animation in interactive terminals while an Agent prompt is waiting for planning or tool results.
- Developer can press the up arrow in an interactive `hypertrade` chat session to recall prior prompts from the current or saved local history.
- Developer can distinguish command help, tool rows, Agent progress, success, warning, and error output by color in interactive terminals.
- Developer can use CLI slash commands such as `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in interactive chat.
- Developer can enter `/` to display slash commands and press Tab after `/` or a partial slash command to complete commands/common subcommands in real TTY sessions.
- Developer can enter a short incomplete slash prefix such as `/st` or `/me` and see filtered candidate commands with descriptions instead of a generic unknown-command page.
- Developer can enter a partial known slash argument such as `/model c` and see matching argument candidates such as `codex` instead of dispatching the incomplete argument.
- Developer can select any displayed slash command or argument candidate by
  number in interactive chat, so `/st` can run `/status` and `/model c` can
  choose `codex` without retyping the candidate.
- Developer can read a purpose description beside every `/help` slash command and every `/tools` Agent tool row.
- Developer can run CLI `/connectors` or `GET /api/connectors/capabilities` to
  inspect connector health/auth status, supported scopes, idempotency
  requirements, source-of-truth notes, and tool descriptors without exposing
  plaintext secrets.
- Developer can run `/research <prompt>` and `/backtest` from interactive CLI chat to create research and backtest records.
- Developer can run Backtrader backtests with recent OKX candles through API or CLI options.
- Developer can run Agent acceptance tests and review a documented test plan for expected tool calls, trace output, and report quality.
- Developer can run deterministic CLI market commands such as `/price`, `/candles`, and `/compare` without waiting for LLM planning.
- Developer can see readable Agent progress statuses while free-form prompts are running.
- Developer can read structured CLI report sections for market runs, and unknown Markdown reports render as terminal headings, lists, and tables in interactive/Rich mode.
- Developer can read compact CLI run output focused on the report body: run metadata and tool trace tables are hidden by default, `HYPERTRADE_TRACE=summary` shows a compact trace, and `HYPERTRADE_TRACE=full` shows the full trace for audits.
- Developer sees only compact run progress by default (`Agent: running/completed`); `HYPERTRADE_PROGRESS=full` restores per-tool progress lines for debugging.
- Developer sees BitPro paper monitoring/equity/event reports as concise conclusions plus core metrics by default; raw paper tool tables require `HYPERTRADE_REPORT_SOURCE=tools`.
- Routine market/RAG/Memory CLI outputs do not repeat a fixed investment-advice disclaimer; strategy, backtest, Testnet, live-order, or recommendation-like prompts still surface the research/risk boundary.
- Developer can enable Rich terminal rendering for structured CLI reports while keeping plain output for scripts.
- Developer can inspect and control the simulated paper runtime from CLI slash commands.
- Developer can run backtests from archived BitPro K-line data without copying BitPro business logic.
- Developer can inspect Agent graph state and graph trace nodes for each run.
- Developer can switch chat providers from CLI/API/frontend without exposing provider keys.
- Developer can run interactive CLI `/model` and select a provider by number
  rather than typing its name; selecting Codex then shows a numbered model list
  from `CODEX_MODEL_OPTIONS`, and the chosen model is used for the current
  local or remote session.
- Developer can select `codex` or Hermes-style `openai-codex` as the active
  chat provider when `CODEX_API_KEY` or `CODEX_AUTH_JSON` provides a Codex
  access token; provider status never exposes the token, and Codex does not
  execute HyperTrade tools or approval decisions directly.
- Developer can search RAG citations and Memory from CLI/API/frontend.
- Developer can create, approve, and execute OKX Testnet order intents after risk checks.
- Developer can run `/experiment <prompt>` to create strategy research, compare multiple backtest variants, inspect the winning evidence, and read the next experiment recommendation.
- Completed local strategy experiments are automatically searchable through Memory as `strategy_knowledge`, with source experiment/backtest ids and evidence metrics rather than unsourced strategy claims.
- Developer can run `/strategy library [query]` or `GET /api/strategy/library` to inspect grouped local strategy evidence: evidence counts, pass/fail counts, best/latest backtest evidence, variants, failure reasons, next experiments, and source Memory ids.
- Agent can use `strategy_library_search` for strategy-library/history/next-experiment questions so prior local strategy experience comes from audited `strategy_knowledge` evidence instead of model recall.
- New strategy evidence cards expose `schema_version=strategy_evidence.v1`, preserve decimal metrics as strings, keep source ids/boundaries visible, and let missing fields surface as `n/a` or empty values instead of inferred data.
- Developer can run `/experiment iterate <prompt>` or call `strategy_experiment_plan` to produce bounded candidate variants from prior strategy-library evidence before any new paper/live promotion path.
- Developer can run `/evals` or open `/harness/quality` and inspect server-scored Agent eval status for
  tool choice, source-of-truth usage, unsupported-claim guardrails,
  missing-data preservation, and compact report rendering.
- `/evals` includes live BitPro routing guardrails for
  `我的实盘最近的一笔订单是什么` and `看下实盘收益最高的策略`; these cases require the
  matching BitPro live diagnostic tools and fail if the Agent substitutes
  generic `market_summary` / `Market Report` evidence.
- Developer can run optional Langfuse, Promptfoo, and Ragas evaluation tooling
  without weakening the deterministic gate: Langfuse is disabled by default and
  receives metadata only; Promptfoo and trajectory collection require an
  isolated target with `evaluation_mode=true`, which denies every non-read
  Agent tool before dispatch.
- Developer can run `./scripts/run_agent_eval_baseline.sh` only against an
  explicitly labelled isolated API to collect the 26-case V2 golden baseline twice. The
  generated report contains aggregate diagnostic metrics only and leaves cost as
  unavailable when no reviewed normalized provider cost is reported. Fixed cohort
  denominators and route/source/graph/task/safety thresholds fail the runner closed.
- Operator can use `docs/knowledge/tool-usage-guide.md` to validate each Agent tool surface and follow related operational source-code comments.
- Operator can review the BitPro tool-surface requirements before wiring external data, backtest, paper/simulation, or live-state APIs into Agent tools.
- Operator can call BitPro read tools through HyperTrade API/Agent paths while every flow starts with `bitpro_capabilities` and `bitpro_health`.
- Operator can verify BitPro MCP Agent Token wiring from `/harness` and `/api/harness/overview`: token values stay hidden, but the auth header, token source, BitPro token-management routes, R/W/L/T scope classes, live-diagnostic group, and idempotency-required tools are visible for Agent authentication debugging.
- Developer can run backtests with `candle_source=bitpro_mcp` or `/backtest --source bitpro_mcp` to use BitPro `market_klines` data without direct database access.
- Agent can use BitPro strategy lifecycle tools to generate/create/update strategy drafts, start/query BitPro-owned backtest jobs, and configure/control paper validation while real-account write tools remain blocked.
- Agent can complete the BitPro strategy R&D loop through MCP only: `bitpro_capabilities` -> `bitpro_health` -> real K-line coverage confirmation -> `strategy_validate_code` -> `strategy_create` with DB-backed `script_content` -> optional `strategy_update` for canonical metadata/renaming -> `backtest_start_job`/result inspection -> gated `paper_configure`/`paper_start`.
- Agent can answer BitPro backtest ranking or threshold questions, such as `回测收益大于100%`, by calling `bitpro_backtest_list_results` and reporting `total_return_pct` from actual BitPro result rows instead of annualized return, strategy descriptions, memory, or inferred data.
- Agent can inspect a specific BitPro backtest result id through `bitpro_backtest_get_result`, reporting real metrics and bounded artifact availability for equity curve, trades, orders, fills, and drawdown series without inventing missing rows.
- Agent can run a named BitPro strategy backtest and return the completed BitPro result metrics from the saved result row or completed job result instead of a raw polling/lifecycle log.
- Default BitPro backtest reports are page-focused: they hide MCP contract/tool-order details, lifecycle polling logs, and RAG citation lists unless the operator explicitly asks for trace/debug evidence.
- Agent can answer BitPro paper/simulation inventory questions without mistaking the current `paper_dashboard` view for the full universe: unfiltered dashboard reads include `strategy_search(status=running)` inventory and reports distinguish current dashboard instance from all running strategies.
- Agent can summarize BitPro paper monitoring state with source-bound alerts and read-only recommended actions, while calling out missing per-strategy PnL/drawdown metrics as data gaps rather than inferred facts.
- Agent can inspect BitPro paper/simulation event streams and equity curves through read-only MCP tools, reporting event counts, error counts, latest event time, equity samples, latest equity, and drawdown evidence without synthesizing missing rows.
- Agent can capture a BitPro paper monitor snapshot through read-only dashboard/events/equity tools, persist it, compare it with the previous snapshot for the same strategy or all-strategy scope, and report PnL/equity/drawdown/error drift without triggering paper or live write tools.
- With a chat provider configured, Agent can answer live-account order-history
  questions, including `我的实盘最近的一笔订单是什么`, by having the planner choose
  read-only BitPro live diagnostics, reporting the latest returned order id,
  symbol, side, status, price/size, timestamp, and strategy attribution when
  BitPro provides it; the Agent must not use `market_summary` for these prompts.
- With a chat provider configured, Agent can answer live strategy performance
  questions, including `看下实盘收益最高的策略`, by having the planner choose
  read-only BitPro live diagnostics, ranking `/live/strategies` rows by
  `return_pct` and reporting `total_pnl` without using `market_summary`.
- Free-form natural-language Agent prompts use the configured chat provider and
  `AgentPlanner` as the semantic source of truth for tool choice. If no chat
  provider is configured, HyperTrade returns an auditable
  `provider_unavailable` result and does not guess a market, BitPro, RAG, or
  Memory route from keywords.
- Operator can run `GET /api/monitors`, `POST /api/monitors/{monitor_id}/run`, `GET /api/alerts`, CLI `/monitors`, `/monitor run <monitor_id>`, and `/alerts` to inspect persisted monitor definitions, runs, thresholds, source tools, alert events, data gaps, and recommended read-only actions.
- Operator can leave `MONITOR_SCHEDULER_ENABLED=true` so the worker persists
  due monitor runs and alert events automatically, or disable the scheduled
  path while keeping manual CLI/API monitor runs available.
- PostgreSQL migration creates business tables and pgvector extension.
- Deployment workflow runs only on `main` with SHA gating.


## 标的范围贯通（2026-09-12）

用户明确标的不限制BTC/ETH。新建API接受symbols（保留显式单symbol兼容），CLI --symbol可重复；省略时读取BitPro当前可用OKX USDT永续列表并冻结为研究范围，列表失败或不支持的标的明确拒绝，不回退默认币种。AVO按目标为候选选择范围内单一标的，在假设中解释依据；研究池不是组合执行。回测、最终审核、Paper仅绑定选中候选标的，反馈子任务继承原Paper标的而非整个研究池。旧任务及运行Paper不迁移。其他市场尚需相应数据和执行适配器，不宣称已支持。


## 流式CLI与终端人工交互（2026-09-12）

research start/continue默认持续跟进服务端持久事件；--detach明确只提交。research watch重新连接已有任务；交互TTY默认显示工作流、逐条活动及可选中展开的日志，E读证据、R逐版本人审、C明确追加预算、F重新连接、Q/Ctrl+C退出观看。--plain用于逐行流式日志。人审必须阅读证据、填写意见并明确点击决定，绑定当前package_hash；未知写入不自动重发。SSE读取复用脱敏事件投影，支持游标重连及完整历史回放，连接定期轮换重新校验身份，断开不取消研究。不把paper_observing任务状态当成实际Paper健康证明。


### 每小时自主进化

BitPro自主进化开关对应HyperTrade持久配置与worker调度。每小时诊断模拟盘7+7退化、当前会话历史成交样本及可追溯开发回测记忆，自主生成改进假设；经过原版本同窗比较和人工审核后，独立运行新Paper。预算、范围、冷却和去重由确定性服务控制。数据不足和不支持复现的组合/策略应显示诊断缺口，不自动替换原策略。默认关闭，立即诊断不会创建研究。（2026-09-14 起 `EvolutionConfig.enabled` 默认开启，仅影响新建配置；见文末「可插拔市场目标与自进化通用化」。）

### 自主进化的证据上下文与提案合同（2026-09-13）

服务端对旧开发回测执行标的/周期/代码指纹/开发时间门禁及有限数值检查；最多扫描200条、选入20条，
保留通过和失败实验，排除原始嵌套指标和最终窗口，记录memory_manifest。无来源的旧数据不补造。
每个自动进化propose包含evolution_hypothesis（证据引用、预期指标和方向、可证伪条件）；归档内相同代码、
标的、周期、开发窗口、资金的重复实验需repeat_reason，仍正常计预算。模型不获改写裁判或审批权限。
论文依据与阶段验收见架构61第11节。经验效用强化学习和生产代码自修改未启用。

开发回测的hypothesis_assessment只核对被引用实验与当前候选的预期指标方向。同标的、周期、资金、
开发窗口且不同回测引用才可比较；百分数与比例按现有指标解析器归一化。结果为observed、not_observed、
mixed或unknown，标明development_metric_direction_only；不验证自然语言因果断言，不影响最终门槛或审批。
缺字段的旧记录不得丢失已结算回测回执，评估摘要可随有界经验进入下一轮。

### 用户授权的全自动Paper评审（2026-09-13）

本次用户明确撤销逐版本人审要求，允许Agent完成模拟盘闭环。EvolutionConfig.paper_review_mode的
agent模式受enabled、策略范围、候选资金上限约束；独立评审器核对版本绑定最终回执、数值和原版比较，
以agent_policy身份记录决策后使用受保护Paper接口。human模式仍可选择，旧决定不改身份。
不允许Live，不重置原Paper；未知效果保持待核对而非重复执行。自动评审不导致SSE/CLI提前结束。

自动评审政策管理需要独立arc:policy权限，arc:start不能改变政策或冒充human审批。Agent评审同时
满足任务门槛与系统paper_criteria，并在approve前读取BitPro新候选成本冻结标识、research_costs.v1
来源/数值/hash与代码身份。新Paper研究strategy_create显式请求_freeze_research_costs=true；
费用解析由BitPro负责，HT不复制费率规则。旧未冻结候选自动否决并保留历史，读取故障暂缓，不盲重试写入。

### 主动探索与全局研究预算（2026-09-13）

`proactive_enabled` 允许 worker 对未退化但证据完整的 Paper 发起可证伪研究；旧配置默认为关闭，原总开关与门槛不迁移。7+7 退化与主动探索及任务自身反馈共用持久 `research_budget.v1` 准入账本，按 UTC 日/可选累计任务限额、全局并发及来源冷却控制。任务与扣额原子提交，重启与配置修订不清账；旧自动任务计入消耗。退化优先，同级按最久未研究来源和策略ID选择。冷却计入诚实终态时间，未知效果继续阻断。GET evolution 和 CLI `research evolution` 展示预算、触发来源、拒绝原因与下一可运行时间；预览不扣额。完整数据门槛不降低，不产生 Live 或原 Paper 修改。

### 不可变组合研究基线（任务 F，2026-09-13）

组合研究通过受管理员保护的 `/api/portfolio/research` 冻结 `portfolio_manifest.v1` 并比较等权持有基线。成员为同层、同窗、同币种、同成本的单资产策略净权益；最多20成员/500点，权重、现金、方向声明、版本/来源哈希、资金与收盘后再平衡均冻结。回放采用自筹费用的 `sleeve_index.v1`，仅代表按比例缩放历史净权益的研究假设，不代表改变资金后策略执行可复现。

成员版本或内容变化、缺样本、不同覆盖/成本均失败关闭。上游未提供逐期间费用和换手时，总值保持未知且状态为 `needs_data`，不能以外层再平衡成本替代内部交易成本。来源序列不落库，组合摘要内容寻址保存、组合曲线当次返回；只生成研究解释，不改变任何运行中Paper或Live。细则见统一研究闭环合同任务 F。

### 可插拔市场目标与自进化通用化（2026-09-14）

自进化核心与平台解耦：`hypertrade/targets` 定义 `market_target.v1` 目标档案（venue/日历/证据契约/成本政策来源/能力开关）与进程级注册表；活跃目标由 `MARKET_TARGET` 设置决定，`EvolutionConfig.target_id` 在配置时校验必须已注册（默认 bitpro，未注册拒绝）。BitPro 为首个内置目标；QuantLab 类平台经 `market-evolution.v1` 通用 MCP 契约（七个规范工具 + `McpContractClient` 按 `tools/list` preflight 校验缺项）注册即插。进化循环客户端经注册表解析，`readiness` 窗口天数与对齐时区由目标日历参数化（continuous/UTC/14 天与旧行为一致）。`EvolutionConfig.enabled` 默认开启，仅影响新建配置；既有持久配置与 revision 不变。

Phase 2 读取切片要求 sessions 日历提供前一交易日收盘基准与之后 14 个已收盘交易日的完整权益证据。第 7 日的收盘权益同时是后 7 日的起点，隔夜跳空进入最近窗收益与回撤；缺基准收盘、明确交易日或时区证据则拒绝退化结论。非 BitPro Paper 写端口、真实市场服务端接入和效果/告警适配仍待后续。

离线元学习：`meta_tuning` 只回放已结算的 7+7 观测（周期账本冻结了当轮配置与窗口值），退化阈值建议定在观测 p90（下限 max(5pp, p50)、上限 20pp、样本 <12 条不调参），单步 ≤3pp、每日至多一次（`tune_YYYYMMDD` 回执幂等）。`meta_tuning_enabled` 默认只产出建议回执；`meta_tuning_auto_apply` 显式授权后经 `EvolutionService.configure` 修订审计应用，操作者记为 `hypertrade:meta-tuner`。`GET /evolution/tuning` 提供只读报告。`paper_criteria`/`min_trades`/冷却/预算上限不在自动调整范围。

归因见证式升级：`costs`/`long_short` 维度仅在上游 `coverage.fields` 两页都标记 `observed` 且台账条目数值齐备时点亮（费用合计、净 PnL、long/short 计数与净 PnL），`side` 仅识别 long/short 词表；`source_field_states` 为 unknown/observed/unverified 三态。当前上游全部字段为 unknown，线上行为不变；语义仍为 `descriptive_execution_coverage_only`、`causal_conclusion=not_established`，不从裸 PnL 推断。细则见架构 62 与《用户指令合同——可插拔市场目标》。

### 组合策略自主进化（2026-09-14）

组合策略（多标的，如 8 标的的 TradFi 半导体篮子）与单标的策略同为自主进化的合法对象：退化诊断与告警同口径（组合基准=成员等权买入持有合成，任一成员构建失败则整体回退并标注）；触发后按完整标的集合发起研究——`ARCGoalV1.symbols` 与基线 spec 均携带全量标的，AVO propose 强制候选保持完整集合（不得静默退化为单标的，单标的来源也不得扩大集合，违反即拒绝并给出明确原因）；候选经同一 self-test 链验证：`strategy_validate_code`/`strategy_create` 传全量标的，回测以 `symbol=None` 让 BitPro 从策略配置的 `trade_symbols` 推导整篮子并输出聚合指标，与基线（原策略模块+配置）同窗比较；Paper 评审包与 reviewed 配置绑定全量 symbols；研究记忆按"与任一成员同源"过滤。命名沿用 BitPro 组合标签约定（前 3 个成员 + 等N）。结构变异（增删标的、改周期）仍不在本阶段范围——组合进化目前只做参数邻域。

### 自进化加固：实效、告警与基准相对退化（2026-09-14）

效果账本：`GET /evolution/effectiveness`（`evolution_effectiveness.v1`）只统计进化循环发起的任务（evolution_context/feedback_parent），给出周期分布、任务进度、候选与基线对比（无效对比单列不充数）、Paper 决策、已结算 Outcome、候选/模型调用/回测成本与逐来源战果；`baseline_win_rate` 仅在存在有效对比时给出，`causal_conclusion=not_established`。

数据缺口告警：`readiness` 每个 blocker 标注 `resolution`（time=等待自愈 / operator=需人工或上游修复），延续记录带 `attention_required`。`arc_evolution_alerts` 账本三规则——operator 阻塞立即告警；证据无法构建且无预计资格时间先跟踪、超 72 小时升级告警；连续 3 个扫描周期 error 告警（critical）。条件消失自动解决，`POST /evolution/alerts/{id}/ack` 确认后同条件不再打扰；投递复用 `FEISHU_WEBHOOK_URL`（未配置只记台账、失败节流重试、投递失败不阻塞扫描）。`GET /evolution/alerts` 可查。

并发名额卡死告警与预算终态（2026-09-26）：最近 6 个扫描周期全部因 `concurrency_limit` 推迟时，开启全局 `evolution_research_slots_blocked` 告警（meta_tuning 行不计入），条件消失自动解决。模型/工具/时间/上下文预算耗尽且无未决动作的研究，在 human 与 agent 模式下都视为本轮结束并释放并发名额，仍受同源冷却约束；`avo_no_candidate` 维持原判定。human 审核只约束候选进入 Paper，不约束发生在审核包之前的预算终态。AVO 首轮只把有界视图交给模型：成交保留最近 30 条并附全量摘要与哈希，窗口回执与超过 12KB 的原策略源码以大小和哈希代替，记忆最多 20 条，均标 `not_full_evidence`；任务目标里的完整上下文仍是假设绑定、候选源码和基线比较的唯一来源。细则见规格 013。规格 014 起 `EvolutionConfig.research_provider`（默认 codex）决定循环研究所用 provider 并在创建时冻结；`avo_provider_unavailable` 与 `avo_no_candidate` 同样视为本轮结束释放名额；模型失败消息附带脱敏后的 HTTP 状态与摘要。规格 015 起来源变体实验身份含父 manifest 与参数，候选回测前以相同幂等键回测同窗基线并引用其封存快照（BitPro v3 固定预热绑定），基线无封存绑定时失败关闭。组合候选审批后以完整标的集合经受审核接口配置并启动 Paper，审核范围必须与候选篮子完全一致。

基准相对退化：默认口径改为基准相对——策略 7+7 变化对比其标的同窗买入持有（`market_klines` 构建，边界容差=周期长度），大盘下跌不再冒充策略退化；组合策略取成员等权买入持有合成作为基准（任一成员构建失败则整体回退并标注）。reasons 为 `relative_return_drop`/`relative_drawdown_increase`。15m 周期超出单页上限、拉取失败、错位均回退绝对口径并在 window 载荷标注 `benchmark.status`，绝不静默。`EvolutionConfig.degradation_basis`（默认 benchmark_relative）可一键回退 `absolute`，绝对口径 reasons 与行为不变。细则见架构 63 与《用户指令合同——自进化加固》。
