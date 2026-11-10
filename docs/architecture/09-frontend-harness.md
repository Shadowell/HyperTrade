# 09 Frontend Harness / 前端 Harness

## English

The frontend is an operational workbench, not a marketing page. `/harness` is intentionally a core console for Agent runs, report reading, tool trace, RAG, Memory, OKX market snapshot, recent runs, strategy-library evidence, monitor alerts, and approval/risk status.

Runtime data comes from public workbench read endpoints, primarily `GET /api/harness/overview`. That endpoint keeps the page focused on a small operator surface: default provider status, OKX ticker freshness, recent Agent runs, recent trace events, RAG document/chunk counts, and Memory audit counts. The page no longer renders a login form for observability or research workflows. Advanced controls such as provider selection, paper lifecycle controls, live order approval/execution, strategy/backtest forms, eval panels, Memory disable, and Feishu send are intentionally not first-class UI controls; privileged mutations still require admin session auth at the API layer where they are exposed.

Sprint 52 expands the console with source-backed operator review surfaces:

- Strategy evidence reads `GET /api/strategy/library` and displays best/latest evidence, pass/fail counts, failure reasons, next experiment candidates, and source ids for Memory, experiment, backtest, and BitPro result records.
- Report reading can render structured blocks from `report_json.report_blocks` or `report_json.blocks` while preserving Markdown fallback for older reports.
- Recent run rows can load `GET /api/agent/runs/{run_id}` so operators can inspect trace and report details without switching to the CLI.
- Monitor alerts read the Sprint 51-style `/api/alerts` path when available; empty alert lists render an explicit operational empty state.
- Approval/risk status is read-only in the console and surfaces pending live/testnet intents and risk status without adding live execution controls.

Sprint 76 adds the componentized `AgentFlightRecorder`. It reads
`GET /api/agent/runs/{run_id}/observability` and renders an ordered Graph /
Model / Tool / Policy / Memory tape, provider-reported Token composition,
per-call and tool latency, linked Memory ids, and an explicit redaction boundary.
Unknown provider usage is displayed as unavailable rather than estimated.

Sprint 88 expands the routed Memory page into a read-only Memory observability
dashboard. It uses the existing `GET /api/memory` payload only: active-item
composition by `kind`, creation-date activity, and the audited importance,
confidence, and reuse fields. “Capacity” means the proportion of active loaded
items, not a fabricated storage quota. Search retains a full inventory snapshot
for the dashboard while rendering filtered rows for the operator.

Sprint 89 adds a shared route-context metric strip. It is not a second data
dashboard: each page projects only already loaded, source-bound state. The
workbench uses global telemetry; strategy projects evidence totals; alerts
project monitor and approval state; runs project run/trace/provider counts;
Memory projects its active inventory; and RAG projects document/chunk/search
counts. No route creates a new API request just for visual statistics.

Sprint 90 gives the operator's evidence and state rows a shared card system.
Strategy evidence, monitor alerts, approval intents, Memory rows, and RAG hits
all use one compact dark container and an explicit semantic rail. The rail is
a presentation of the source state (signal, brass, violet, or danger), never a
new risk calculation or permission decision.

Sprint 91 completes the strategy evidence hierarchy. Summary, performance,
provenance, guidance, and drilldown blocks reuse a lower-contrast compact card
variant inside the selected strategy card. This preserves a visual distinction
between the primary evidence selection and its audited subfacts while keeping
one consistent source-state language.

The `/harness` Agent workbench is composed from focused components in
`frontend/src/components/agent/`: `HarnessHeader`, `TelemetryGrid`, `RunControls`,
`AgentProgress`, `ThreadDetails`, `ReportReader`, `RuntimeMonitor` (with `BitProCard`) and the
existing `AgentFlightRecorder`, assembled by `HarnessPage`. Each region sits in its own
`ErrorBoundary`, so one crashing region does not blank the console. Shared pieces moved out of
`App.tsx` into `types/`, `i18n/`, `lib/` (format, time, errors, markdown, report),
`api/client.ts` (typed fetch with `ApiError`) and `components/ui/`. The other pages are untouched:
the split is incremental by design (`docs/optimization/03-frontend-component-refactor.md`).

The page states what it does not know. Before the first response the overview is `null`: the
header says it is connecting, telemetry shows placeholders and the tool heading keeps a skeleton
body. If the API cannot be reached the page says "overview unavailable" and offers Retry. It never
falls back to sample data (a preview fixture with an example report, a paper account and a BitPro
configuration was removed); `EMPTY_OVERVIEW` is all zeros. With no run, the report area is an
explicit empty state.

Access detection stays passive. The console never probes the session and renders no login form
(see `docs/spec.md`). Only when a privileged call (run, new thread, archive thread) is refused with
401/403 does the page switch to read-only: an explanatory note (an admin session is required; sign
in from a terminal with `ht /login`), a "Read-only" badge, and the three actions disabled. Errors
are mapped to actionable localized sentences (`describeError`) instead of raw status text. After the
overview, the other sections load in parallel (`Promise.allSettled`), so one failing endpoint no
longer stops the rest and the header stops spinning once the overview is in.

Design direction:

- dense dark observability console with deep green-black surfaces and a restrained grid texture
- light operational text, cyan runtime state, amber audit emphasis, and red risk state
- 8px-or-less radius
- lucide icons for controls and state
- Chinese UI by default, English toggle available

## 中文

前端是操作工作台，不是营销页。`/harness` 刻意收敛为核心控制台，展示 Agent 运行、报告阅读、工具 trace、RAG、Memory、OKX 行情快照、最近运行、策略库证据、监控告警和审批/风控状态。

页面通过公开的工作台读取接口获取运行态，核心入口是 `GET /api/harness/overview`。这个聚合端点让操作路径集中在一个较小界面里：默认 Provider 状态、OKX 行情新鲜度、最近 Agent run、最近 trace、RAG 文档/分片计数、Memory 审计计数。工作台不再为了可观测性和研究流程渲染登录表单；Provider 切换、paper 生命周期控制、实盘审批/执行、策略/回测表单、评测面板、Memory 禁用、发送飞书等高级控制不再作为首屏/主页面功能，仍暴露的特权写操作继续在 API 层要求 admin session auth。

Sprint 52 增加面向操作员的证据审阅能力：

- 策略证据读取 `GET /api/strategy/library`，展示最佳/最新证据、通过/失败计数、失败原因、下一步实验建议，以及 Memory、experiment、backtest、BitPro result 等来源 id。
- 报告阅读优先渲染 `report_json.report_blocks` 或 `report_json.blocks` 中的结构化 block，同时保留旧报告的 Markdown 回退。
- 最近运行可以读取 `GET /api/agent/runs/{run_id}`，让操作员不用切 CLI 就能查看报告和 trace 详情。
- 监控告警读取 Sprint 51 风格的 `/api/alerts` 路径；当告警列表为空时，页面展示明确空状态，而不是报错。
- 审批/风控区域保持只读，只展示待审批 live/testnet intent 与 risk status，不扩展实盘执行 UI。

Sprint 76 新增组件化 `AgentFlightRecorder`。它读取
`GET /api/agent/runs/{run_id}/observability`，按顺序显示 Graph / Model /
Tool / Policy / Memory 时间带、Provider 返回的 Token 构成、模型与工具延迟、
关联 Memory id 和明确的脱敏边界。Provider 没返回 usage 时显示不可用，
不会用字符数估算冒充精确 Token。

Sprint 88 将独立的 Memory 路由扩展为只读可观测面板。它只使用既有
`GET /api/memory` 返回的 active 条目：按 `kind` 的构成、按创建日期的写入
节奏，以及已审计的 importance、confidence、usage_count 字段。界面中的“容量”
指已加载活跃条目的构成比例，不代表虚构的存储配额。搜索结果只过滤操作员列表，
面板仍保留完整库存快照。

Sprint 89 增加共享的路由上下文指标条。它不是第二套数据面板：每个页面只投影
已经加载且有来源的数据。工作台使用全局遥测；策略页投影证据总数；告警页投影
监控与审批状态；运行页投影运行/Trace/Provider 请求数；Memory 页投影活跃库存；
RAG 页投影文档、分片和检索命中数。不会为了视觉统计新增 API 请求。

Sprint 90 为操作员的证据和状态行提供共享的卡片系统。策略证据、监控告警、审批
意图、Memory 条目和 RAG 命中都使用同一个紧凑的深色容器与显式状态轨。状态轨只
展示来源状态（signal、brass、violet、danger），绝不构成新的风险计算或权限决策。

Sprint 91 完成策略证据的卡片层级。摘要、表现指标、来源引用、实验建议和详情行在
选中的策略证据卡内部复用低对比度的紧凑卡片变体。它保留主证据选择与审计子事实的
层级差异，同时维持同一套来源状态语言。

`/harness` Agent 工作台由 `frontend/src/components/agent/` 下职责单一的组件组成：
`HarnessHeader`、`TelemetryGrid`、`RunControls`、`AgentProgress`、`ThreadDetails`、
`ReportReader`、`RuntimeMonitor`（含 `BitProCard`）和既有的 `AgentFlightRecorder`，由
`HarnessPage` 组装。每个区域各有一层 `ErrorBoundary`，单个区域崩溃不会让整个控制台白屏。
公共部分从 `App.tsx` 搬到 `types/`、`i18n/`、`lib/`（格式化、时间、错误、Markdown、报告）、
`api/client.ts`（带 `ApiError` 的类型化请求）和 `components/ui/`。其余页面保持不变：拆分是
有意渐进的（见 `docs/optimization/03-frontend-component-refactor.md`）。

页面如实表达“不知道”。首个响应之前概览为 `null`：头部显示连接中，遥测卡用占位符，工具
标题保留、内容是骨架。API 不可达时页面明确显示“无法获取运行概览”并提供重试，绝不回退到
示例数据（原先带示例报告、模拟账户和 BitPro 配置的预览夹具已删除）；`EMPTY_OVERVIEW` 全部
为零。没有运行记录时，报告区是明确的空状态。

访问状态保持被动判定。控制台不探测会话，也不渲染登录表单（见 `docs/spec.md`）。只有特权
操作（运行、新建会话、归档会话）被服务端以 401/403 拒绝时，页面才进入只读状态：给出说明
（需要管理员会话，请先在终端执行 `ht /login`）、显示“只读”徽标，并禁用这三个操作。错误
经 `describeError` 映射成可操作的本地化句子，而不是原始状态文本。概览之后，其余分区并行加载
（`Promise.allSettled`），一个接口失败不再中断其余分区，概览到达后头部也不再一直转圈。

设计方向：

- 信息密度较高的交易工作台
- 克制的 paper/ink/brass 配色
- 圆角不超过 8px
- 控件和状态使用 lucide 图标
- 默认中文，提供英文切换
