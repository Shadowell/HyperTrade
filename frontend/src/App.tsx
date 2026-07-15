import {
  Activity,
  AlertTriangle,
  Archive,
  BarChart3,
  Bot,
  Brain,
  Cable,
  CheckCircle2,
  Clock3,
  FileText,
  Languages,
  Layers3,
  LineChart,
  MemoryStick,
  Radio,
  RefreshCw,
  Sparkles,
  TerminalSquare
} from "lucide-react";
import {
  CSSProperties,
  MouseEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState
} from "react";
import {
  AgentFlightRecorder,
  RunObservability
} from "./components/observability/AgentFlightRecorder";

type Language = "zh" | "en";
type NavSection =
  | "harness"
  | "strategy"
  | "portfolio"
  | "alerts"
  | "runs"
  | "quality"
  | "memory"
  | "rag";

type TraceEvent = {
  id?: string;
  tool_name: string;
  status: string;
  created_at?: string;
  input_json?: Record<string, unknown>;
  output_json?: Record<string, unknown>;
};

type AgentRun = {
  id: string;
  status: string;
  report_markdown: string;
  report_json?: Record<string, unknown>;
  run_state_json?: {
    current_node?: string;
  };
  trace_events: TraceEvent[];
};

type RunSummary = {
  id: string;
  prompt: string;
  status: string;
  created_at: string;
  updated_at: string;
  error: string;
};

type ProviderStatus = {
  name: string;
  display_name: string;
  model: string;
  enabled: boolean;
  default: boolean;
  key_status: string;
};

type ToolStatus = {
  name: string;
  description: string;
  category: string;
  requires_approval: boolean;
};

type TickerSummary = {
  inst_id: string;
  last: string;
  volume_ccy_24h: string;
  change_utc0_pct: string;
};

type PaperPosition = {
  inst_id: string;
  side: string;
  quantity: string;
  entry_price: string;
  mark_price: string;
  notional: string;
  unrealized_pnl: string;
};

type PaperFill = {
  inst_id: string;
  side: string;
  quantity: string;
  price: string;
  fee: string;
  created_at?: string;
};

type StrategyResearchSummary = {
  id: string;
  prompt: string;
  strategy_key: string;
  title: string;
  report_markdown: string;
  spec_json: Record<string, unknown>;
  created_at: string;
};

type BacktestSummary = {
  id: string;
  research_id: string;
  strategy_key: string;
  status: string;
  metrics: {
    start_cash: string;
    end_value: string;
    total_return_pct: string;
    max_drawdown_pct: string;
    trade_count: number;
  };
  report_markdown: string;
  report_json: Record<string, unknown>;
  created_at: string;
};

type StrategyExperimentSummary = {
  id: string;
  prompt: string;
  status: string;
  research_id: string;
  backtest_id: string;
  report_markdown: string;
  report_json: Record<string, unknown>;
  created_at: string;
};

type LiveOrderIntent = {
  id: string;
  environment: string;
  status: string;
  inst_id: string;
  side: string;
  order_type: string;
  size: string;
  price: string | null;
  reason: string;
  decision_reason: string;
  risk_status?: string;
  exchange_order_id?: string;
  created_at: string;
};

type MemoryItem = {
  id: string;
  kind: string;
  content: string;
  source_run_id: string;
  source_tool: string;
  tags?: string[];
  usage_count?: number;
  importance?: string;
  confidence?: string;
  last_used_at?: string | null;
  created_at: string;
};

type MemoryAssertion = {
  id: string;
  claim: string;
  status: string;
  usable: boolean;
  source_evidence_ids?: string[];
  confidence?: string;
};

type SkillProposal = {
  id: string;
  skill_key: string;
  status: string;
  definition_hash: string;
  diff?: string;
};

type SkillRelease = {
  id: string;
  skill_key: string;
  version: number;
  status: string;
};

type PortfolioRecommendation = {
  recommendation_id: string;
  action: string;
  strategy_card_id: string;
  reason: string;
  requires_human_review: boolean;
  allocation_change_allowed: boolean;
  trading_mutation_allowed: boolean;
};

type PortfolioAssessment = {
  id: string;
  status: string;
  policy_version: string;
  valid_until: string;
  strategies: Array<Record<string, unknown>>;
  pairwise: Array<Record<string, unknown>>;
  unknowns: string[];
  recommendations: PortfolioRecommendation[];
};

type RagHit = {
  source_path: string;
  title: string;
  chunk_index: number;
  score: number;
  content_preview: string;
};

type EvalStatus = {
  status: string;
  case_count: number;
  cases: Array<{ name: string; status: string; expectation?: string }>;
  mode: string;
  research_os?: {
    status?: string;
    suite_version?: string;
    case_count?: number;
  };
  quality?: {
    metric_contract?: string;
    status?: string;
    suite_version?: string;
    provider_baseline?: string;
    cohorts?: Record<string, number>;
    failure_categories?: Record<string, number>;
  };
};

type StrategyEvidence = {
  memory_id?: string;
  experiment_id?: string;
  research_id?: string;
  backtest_id?: string;
  bitpro_result_id?: string;
  variant_id?: string;
  passed?: boolean;
  total_return_pct?: string;
  max_drawdown_pct?: string;
  trade_count?: number;
  score?: string;
  data?: Record<string, unknown>;
  gate_results?: Record<string, unknown>;
  failure_reasons?: string[];
  next_experiment?: string;
  created_at?: string;
};

type StrategyLibraryItem = {
  strategy_key: string;
  evidence_count: number;
  passed_count: number;
  failed_count: number;
  best?: StrategyEvidence;
  latest?: StrategyEvidence;
  variants?: Array<{ variant_id: string; evidence_count: number; passed_count: number }>;
  failure_reasons?: string[];
  next_experiments?: string[];
  source_memory_ids?: string[];
};

type StrategyLibraryPayload = {
  source: string;
  memory_count: number;
  items: StrategyLibraryItem[];
};

type MonitorAlert = {
  id?: string;
  severity?: string;
  code?: string;
  title?: string;
  message?: string;
  source_id?: string;
  created_at?: string;
  threshold?: string;
  source_refs?: string[];
};

type EvidenceSelection = {
  title: string;
  rows: Array<{ label: string; value: string }>;
};

type RouteMetric = {
  label: string;
  value: string;
  tone: "signal" | "brass" | "violet" | "danger";
};

type ReportBlock = {
  block_type?: string;
  title?: string;
  severity?: string;
  notes?: unknown;
  metrics?: unknown;
  rows?: unknown;
  missing?: unknown;
  source_refs?: unknown;
};

type HarnessOverview = {
  generated_at: string;
  providers: ProviderStatus[];
  tools: ToolStatus[];
  market: {
    ticker_count: number;
    latest_ticker_at: string | null;
    latest_update_age_seconds: number | null;
    top_movers: TickerSummary[];
  };
  agent_runs: {
    total_count: number;
    recent: RunSummary[];
  };
  rag: {
    document_count: number;
    chunk_count: number;
  };
  memory: {
    active_count: number;
    total_count: number;
    latest_created_at: string | null;
  };
  trace: {
    total_count: number;
    recent_events: TraceEvent[];
  };
  observability?: {
    window_size: number;
    completed_runs: number;
    success_rate: number;
    model_requests: number;
    total_tokens: number;
    usage_reported_runs: number;
    p50_duration_ms: number;
    p95_duration_ms: number;
    private_reasoning_stored: boolean;
  };
  paper: {
    session: {
      id: string;
      status: string;
      cash: string;
      equity: string;
      realized_pnl: string;
    };
    positions: PaperPosition[];
    recent_fills: PaperFill[];
    recent_events: Array<Record<string, unknown>>;
  };
  strategy_lab: {
    latest_research: StrategyResearchSummary | null;
    latest_backtest: BacktestSummary | null;
    latest_experiment: StrategyExperimentSummary | null;
  };
  live_orders: {
    total_count: number;
    pending_approval_count: number;
    recent: LiveOrderIntent[];
  };
  bitpro?: {
    adapter: string;
    configured: boolean;
    api_base: string;
    auth_header: string;
    token_configured: boolean;
    token_source?: string;
    remote_mcp?: {
      transport?: string;
      path_default?: string;
      auth_header_default?: string;
      token_env?: string;
      token_status_path?: string;
      token_generate_path?: string;
    };
    agent_auth?: {
      auth_header_default?: string;
      static_token_env?: string;
      token_management?: {
        settings_routes?: Record<string, string>;
        plaintext_returned_once?: boolean;
        default_tool_groups?: string[];
      };
      scope_classes?: Record<
        string,
        {
          label?: string;
          tool_group?: string;
          description?: string;
        }
      >;
      idempotency?: {
        required_tools?: string[];
      };
    };
    tool_groups?: Record<string, string[]>;
    live_write_enabled: boolean;
    live_write_scope?: string;
    live_write_note?: string;
    tools: string[];
  };
  evals: EvalStatus;
};

const copy = {
  zh: {
    product: "HyperTrade",
    harness: "工作台",
    market: "行情摘要",
    providers: "模型提供方",
    tools: "工具调用链路",
    memory: "记忆",
    rag: "知识检索",
    risk: "研究辅助",
    login: "登录",
    run: "发起归纳",
    prompt: "请做 OKX 全市场 SWAP 行情归纳",
    okx: "OKX SWAP",
    live: "行情覆盖",
    report: "运行记录",
    fallback: "数据延迟",
    approval: "实盘审批",
    severe: "严重异常",
    sendFeishu: "转发飞书",
    refresh: "刷新",
    recentRuns: "最近运行",
    topMovers: "异动榜",
    preview: "预览数据",
    configured: "已配置",
    missing: "未配置",
    noRuns: "暂无运行记录",
    noMarket: "暂无行情快照",
    operator: "管理员",
    password: "密码",
    providerMesh: "模型路由",
    dataPlane: "数据平面",
    agentPlane: "智能体平面",
    lastSync: "最近同步",
    overviewLoading: "正在同步运行态",
    paperRuntime: "模拟盘运行",
    pause: "暂停",
    resume: "恢复",
    equity: "权益",
    cash: "现金",
    realizedPnl: "已实现 PnL",
    positions: "持仓",
    fills: "成交",
    noPositions: "暂无模拟持仓",
    noFills: "暂无模拟成交",
    strategyLab: "策略实验室",
    researchPrompt: "策略研究主题",
    runResearch: "生成研究",
    runBacktest: "运行回测",
    latestResearch: "最新研究",
    latestBacktest: "最新回测",
    noResearch: "暂无策略研究",
    noBacktest: "暂无回测记录",
    returnPct: "收益率",
    maxDrawdown: "最大回撤",
    trades: "成交数",
    closeAll: "全部平仓",
    reset: "重置",
    marketTools: "行情工具",
    price: "价格",
    candles: "K线",
    compare: "强弱对比",
    symbol: "标的",
    bar: "周期",
    limit: "数量",
    query: "查询",
    liveApproval: "实盘审批",
    createIntent: "创建意图",
    approve: "批准",
    reject: "拒绝",
    orderIntent: "订单意图",
    size: "数量",
    side: "方向",
    reason: "理由",
    pending: "待审批",
    approvalQueue: "审批待办",
    noIntents: "暂无订单意图",
    agentProgress: "智能体进度",
    reportReader: "报告阅读",
    rawMarkdown: "原始 Markdown",
    memoryManager: "记忆管理",
    source: "来源",
    disable: "禁用",
    noMemoryItems: "暂无记忆",
    selectedMemory: "选中记忆",
    memoryObservatory: "记忆态势",
    memoryObservatoryHint: "审计活跃条目的构成、写入节奏与可用信号。",
    memoryLoaded: "已加载 / 活跃",
    memoryCapacity: "容量构成",
    memoryCapacityHint: "以当前加载的活跃条目为 100%，不代表存储配额。",
    memoryActivity: "写入节奏",
    memoryActivityHint: "按最近有写入的日期聚合。",
    memoryConfidence: "平均可信度",
    memoryImportance: "平均重要性",
    memoryReuse: "累计复用",
    memoryReuseCount: "复用次数",
    memorySources: "来源工具",
    memoryKinds: "记忆类型",
    memoryEntries: "条",
    memoryNoActivity: "暂无可用创建日期",
    governanceReview: "记忆与技能治理",
    governanceReviewHint: "只有来源有效的 Assertion 与通过隔离评测、人工批准的无代码 Skill 才能进入 Agent。",
    memoryAssertions: "Memory Assertions",
    skillProposals: "Skill 提案",
    skillReleases: "不可变发布",
    governanceReason: "必填：人工复核理由",
    dispute: "标记争议",
    noAssertions: "暂无 Assertion",
    noSkillProposals: "暂无 Skill 提案",
    noSkillReleases: "暂无 Skill 发布",
    portfolioLifecycle: "组合生命周期",
    portfolioLifecycleHint: "基于有界证据查看状态适配、共同暴露与相关性；这里只记录研究或人工复核决定。",
    runPortfolioAssessment: "生成组合评估",
    portfolioAssessments: "历史评估",
    portfolioUnknowns: "未知项",
    portfolioPairs: "策略对",
    hold: "暂缓",
    noPortfolioAssessments: "暂无组合评估",
    initialCash: "初始资金",
    candleSource: "数据源",
    strategyKey: "策略",
    fullBacktest: "完整回测",
    switchProvider: "切换模型",
    currentStage: "当前阶段",
    searchRag: "搜索知识库",
    searchMemory: "搜索记忆",
    execute: "执行",
    experiment: "实验工作流",
    latestExperiment: "最新实验",
    evals: "智能体评测",
    workbenchTitle: "智能体工作台",
    workbenchSubtitle: "面向生产运行的智能体控制台，集中呈现模型、工具、行情、风控与外部数据接入状态。",
    runtimeMonitor: "运行监控",
    runtimeMonitorHint: "查看模型路由、工具调用、评测和数据新鲜度。",
    runConsole: "运行控制",
    runConsoleHint: "发起行情归纳，观察节点状态，并阅读结构化报告。",
    marketKnowledge: "行情与知识",
    executionResearch: "执行与实验",
    bitproMcp: "BitPro MCP 接入",
    bitproMcpHint: "HyperTrade 只通过稳定 MCP/API 合同接入 BitPro 数据与非实盘策略生命周期，不复制 BitPro 业务逻辑。",
    mcpCallOrder: "调用顺序",
    mcpCapabilities: "1. bitpro_capabilities",
    mcpHealth: "2. bitpro_health",
    mcpSelectTool: "3. 选择读/非实盘工具",
    mcpAudit: "4. 记录 trace 与审计字段",
    marketData: "行情数据",
    backtestData: "回测数据",
    paperState: "模拟盘",
    liveReadOnly: "实盘只读",
    readOnlyDefault: "默认只读",
    writeBlocked: "写工具需审批",
    mcpAdapter: "适配器",
    mcpApiBase: "API Base",
    mcpAuthHeader: "认证 Header",
    mcpTokenSource: "Token 来源",
    mcpTokenSourceSettings: "BitPro 设置 / 服务器环境",
    mcpScopes: "Scope 分组",
    mcpTools: "工具数量",
    mcpTokenReady: "Token 已配置",
    mcpTokenMissing: "Token 未配置",
    mcpLiveWriteOff: "实盘写关闭",
    mcpLiveWriteOn: "实盘写开启",
    toolCatalog: "工具目录",
    providerStatus: "模型状态",
    systemStatus: "系统状态",
    healthy: "健康",
    stale: "待同步",
    routeMemory: "记忆检索",
    routeRag: "知识库",
    dataContract: "数据合同",
    latestResult: "最新结果",
    auditBoundary: "审计边界",
    strategyLibrary: "策略库",
    strategyEvidence: "策略证据",
    strategyLibraryHint: "从 Memory 中聚合本地策略实验、回测和 BitPro 结果证据。",
    noStrategyEvidence: "暂无策略证据",
    bestEvidence: "最佳证据",
    sourceMemories: "来源 Memory",
    failureReasons: "失败原因",
    nextExperiment: "下一步实验",
    evidenceDrilldown: "证据详情",
    selectEvidence: "选择一条策略或 trace 证据",
    monitorAlerts: "监控告警",
    alertStatus: "告警状态",
    alertStatusHint: "展示只读监控告警、审批等待和风险状态。",
    noMonitorAlerts: "暂无监控告警",
    approvalRisk: "审批与风险",
    reportBlocks: "结构化报告",
    markdownFallback: "Markdown 回退",
    loadRun: "查看运行",
    traceEvidence: "Trace 证据",
    sourceRefs: "来源",
    missingData: "缺失数据",
    evidenceCount: "证据数",
    pageMetrics: "页面指标",
    strategyCount: "策略条目",
    evidenceTotal: "累计证据",
    passedEvidence: "通过证据",
    failedEvidence: "失败证据",
    currentAlerts: "当前告警",
    highPriority: "高优先级",
    runTotal: "运行总数",
    recentCompleted: "最近完成",
    traceTotal: "Trace 事件",
    modelRequests: "模型请求",
    activeMemory: "活跃记忆",
    loadedMemory: "已加载记忆",
    ragDocuments: "知识文档",
    ragChunks: "知识分片",
    ragMatches: "命中结果",
    ragSearchTerm: "检索词",
    passFail: "通过 / 失败",
    variants: "变体",
    score: "评分",
    noSourceIds: "暂无来源 ID",
    tokenUsage: "Token 使用量"
  },
  en: {
    product: "HyperTrade",
    harness: "Harness",
    market: "Market Summary",
    providers: "Provider",
    tools: "Tool Call Trace",
    memory: "Memory",
    rag: "RAG",
    risk: "Not Investment Advice",
    login: "Login",
    run: "Run Summary",
    prompt: "Summarize OKX SWAP market",
    okx: "OKX SWAP",
    live: "Live Tickers",
    report: "Agent Runs",
    fallback: "Last Update",
    approval: "Live Approval",
    severe: "Severe Alerts",
    sendFeishu: "Send Feishu",
    refresh: "Refresh",
    recentRuns: "Recent Runs",
    topMovers: "Top Movers",
    preview: "Preview",
    configured: "Configured",
    missing: "Missing",
    noRuns: "No runs yet",
    noMarket: "No market snapshot",
    operator: "Operator",
    password: "Password",
    providerMesh: "Provider Mesh",
    dataPlane: "Data Plane",
    agentPlane: "Agent Plane",
    lastSync: "Last Sync",
    overviewLoading: "Syncing runtime state",
    paperRuntime: "Paper Runtime",
    pause: "Pause",
    resume: "Resume",
    equity: "Equity",
    cash: "Cash",
    realizedPnl: "Realized PnL",
    positions: "Positions",
    fills: "Fills",
    noPositions: "No paper positions",
    noFills: "No paper fills",
    strategyLab: "Strategy Lab",
    researchPrompt: "Research Prompt",
    runResearch: "Create Research",
    runBacktest: "Run Backtest",
    latestResearch: "Latest Research",
    latestBacktest: "Latest Backtest",
    noResearch: "No strategy research",
    noBacktest: "No backtest yet",
    returnPct: "Return",
    maxDrawdown: "Max Drawdown",
    trades: "Trades",
    closeAll: "Close All",
    reset: "Reset",
    marketTools: "Market Tools",
    price: "Price",
    candles: "Candles",
    compare: "Compare",
    symbol: "Symbol",
    bar: "Bar",
    limit: "Limit",
    query: "Query",
    liveApproval: "Live Approval",
    createIntent: "Create Intent",
    approve: "Approve",
    reject: "Reject",
    orderIntent: "Order Intent",
    size: "Size",
    side: "Side",
    reason: "Reason",
    pending: "Pending",
    approvalQueue: "Approvals queued",
    noIntents: "No order intents",
    agentProgress: "Agent Progress",
    reportReader: "Report Reader",
    rawMarkdown: "Raw Markdown",
    memoryManager: "Memory Manager",
    source: "Source",
    disable: "Disable",
    noMemoryItems: "No memory items",
    selectedMemory: "Selected Memory",
    memoryObservatory: "Memory observatory",
    memoryObservatoryHint: "Audit active-item composition, creation cadence, and reuse signals.",
    memoryLoaded: "Loaded / active",
    memoryCapacity: "Capacity composition",
    memoryCapacityHint: "100% represents loaded active items, not a storage quota.",
    memoryActivity: "Creation cadence",
    memoryActivityHint: "Grouped by the latest dates with recorded writes.",
    memoryConfidence: "Mean confidence",
    memoryImportance: "Mean importance",
    memoryReuse: "Total reuse",
    memoryReuseCount: "Reuse count",
    memorySources: "Source tools",
    memoryKinds: "Memory kinds",
    memoryEntries: "items",
    memoryNoActivity: "No usable creation dates",
    governanceReview: "Memory and Skill Governance",
    governanceReviewHint:
      "Only source-valid Assertions and code-free Skills with isolated evaluation plus human approval can enter the Agent.",
    memoryAssertions: "Memory Assertions",
    skillProposals: "Skill Proposals",
    skillReleases: "Immutable Releases",
    governanceReason: "Required operator review reason",
    dispute: "Dispute",
    noAssertions: "No assertions",
    noSkillProposals: "No skill proposals",
    noSkillReleases: "No skill releases",
    portfolioLifecycle: "Portfolio Lifecycle",
    portfolioLifecycleHint:
      "Review regime fit, shared exposure, and bounded correlation evidence; this surface records research or human review decisions only.",
    runPortfolioAssessment: "Create Assessment",
    portfolioAssessments: "Assessment History",
    portfolioUnknowns: "Unknowns",
    portfolioPairs: "Strategy Pairs",
    hold: "Hold",
    noPortfolioAssessments: "No portfolio assessments",
    initialCash: "Initial Cash",
    candleSource: "Source",
    strategyKey: "Strategy",
    fullBacktest: "Full Backtest",
    switchProvider: "Switch Provider",
    currentStage: "Current Stage",
    searchRag: "Search RAG",
    searchMemory: "Search Memory",
    execute: "Execute",
    experiment: "Experiment Workflow",
    latestExperiment: "Latest Experiment",
    evals: "Agent Evals",
    workbenchTitle: "Agent Workbench",
    workbenchSubtitle:
      "Production operator console for models, tools, market data, risk, and external data access.",
    runtimeMonitor: "Runtime Monitor",
    runtimeMonitorHint: "Review provider routing, tool calls, evals, and data freshness.",
    runConsole: "Run Console",
    runConsoleHint: "Start a market summary, inspect nodes, and read structured reports.",
    marketKnowledge: "Market and Knowledge",
    executionResearch: "Execution and Research",
    bitproMcp: "BitPro MCP Access",
    bitproMcpHint:
      "HyperTrade uses stable MCP/API contracts for BitPro data and non-live strategy lifecycle workflows without copying BitPro business logic.",
    mcpCallOrder: "Call Order",
    mcpCapabilities: "1. bitpro_capabilities",
    mcpHealth: "2. bitpro_health",
    mcpSelectTool: "3. Select read/non-live tools",
    mcpAudit: "4. Record trace and audit fields",
    marketData: "Market Data",
    backtestData: "Backtest Data",
    paperState: "Paper",
    liveReadOnly: "Live Read Only",
    readOnlyDefault: "Read-only default",
    writeBlocked: "Writes require approval",
    mcpAdapter: "Adapter",
    mcpApiBase: "API Base",
    mcpAuthHeader: "Auth Header",
    mcpTokenSource: "Token Source",
    mcpTokenSourceSettings: "BitPro Settings / server env",
    mcpScopes: "Scope Groups",
    mcpTools: "Tool Count",
    mcpTokenReady: "Token configured",
    mcpTokenMissing: "Token missing",
    mcpLiveWriteOff: "Live writes off",
    mcpLiveWriteOn: "Live writes on",
    toolCatalog: "Tool Catalog",
    providerStatus: "Provider Status",
    systemStatus: "System Status",
    healthy: "Healthy",
    stale: "Stale",
    routeMemory: "Memory Search",
    routeRag: "Knowledge Base",
    dataContract: "Data Contract",
    latestResult: "Latest Result",
    auditBoundary: "Audit Boundary",
    strategyLibrary: "Strategy Library",
    strategyEvidence: "Strategy Evidence",
    strategyLibraryHint: "Aggregate local experiment, backtest, and BitPro result evidence from Memory.",
    noStrategyEvidence: "No strategy evidence",
    bestEvidence: "Best Evidence",
    sourceMemories: "Source Memories",
    failureReasons: "Failure Reasons",
    nextExperiment: "Next Experiment",
    evidenceDrilldown: "Evidence Detail",
    selectEvidence: "Select strategy or trace evidence",
    monitorAlerts: "Monitor Alerts",
    alertStatus: "Alert Status",
    alertStatusHint: "Read-only monitor alerts, pending approvals, and risk state.",
    noMonitorAlerts: "No monitor alerts",
    approvalRisk: "Approval and Risk",
    reportBlocks: "Structured Report",
    markdownFallback: "Markdown Fallback",
    loadRun: "Open Run",
    traceEvidence: "Trace Evidence",
    sourceRefs: "Sources",
    missingData: "Missing Data",
    evidenceCount: "Evidence",
    pageMetrics: "Page metrics",
    strategyCount: "Strategies",
    evidenceTotal: "Evidence total",
    passedEvidence: "Passed evidence",
    failedEvidence: "Failed evidence",
    currentAlerts: "Current alerts",
    highPriority: "High priority",
    runTotal: "Runs total",
    recentCompleted: "Recently completed",
    traceTotal: "Trace events",
    modelRequests: "Model requests",
    activeMemory: "Active memories",
    loadedMemory: "Loaded memories",
    ragDocuments: "Knowledge documents",
    ragChunks: "Knowledge chunks",
    ragMatches: "Matched results",
    ragSearchTerm: "Search term",
    passFail: "Pass / Fail",
    variants: "Variants",
    score: "Score",
    noSourceIds: "No source ids",
    tokenUsage: "Token usage"
  }
} satisfies Record<Language, Record<string, string>>;

const seedRun: AgentRun = {
  id: "run_preview",
  status: "ready",
  report_markdown:
    "# OKX 永续合约行情归纳\n\n**范围**: OKX 全市场 SWAP\n\n- BTC-USDT-SWAP: 最新价 70000, UTC0 涨跌幅 4.2%, 24h 成交额 20000\n- ETH-USDT-SWAP: 最新价 3600, UTC0 涨跌幅 -2.5%, 24h 成交额 14000",
  trace_events: [
    { tool_name: "market.summary", status: "ready" },
    { tool_name: "rag.search", status: "ready" },
    { tool_name: "memory.write", status: "ready" }
  ]
};

const previewOverview: HarnessOverview = {
  generated_at: new Date(0).toISOString(),
  providers: [
    {
      name: "deepseek",
      display_name: "DeepSeek",
      model: "deepseek-v4-flash",
      enabled: false,
      default: true,
      key_status: "missing"
    },
    {
      name: "qwen",
      display_name: "Qwen",
      model: "text-embedding-v4",
      enabled: false,
      default: false,
      key_status: "missing"
    }
  ],
  tools: [
    {
      name: "market.summary",
      description: "Summarize OKX SWAP market state.",
      category: "market",
      requires_approval: false
    },
    {
      name: "rag.search",
      description: "Search project and trading knowledge.",
      category: "rag",
      requires_approval: false
    },
    {
      name: "memory.write",
      description: "Write audited long-term memory.",
      category: "memory",
      requires_approval: false
    },
    {
      name: "live.order_intent",
      description: "Create a live/testnet order intent for human approval.",
      category: "live",
      requires_approval: true
    }
  ],
  market: {
    ticker_count: 0,
    latest_ticker_at: null,
    latest_update_age_seconds: null,
    top_movers: []
  },
  agent_runs: {
    total_count: 0,
    recent: []
  },
  rag: {
    document_count: 0,
    chunk_count: 0
  },
  memory: {
    active_count: 0,
    total_count: 0,
    latest_created_at: null
  },
  trace: {
    total_count: 0,
    recent_events: seedRun.trace_events
  },
  paper: {
    session: {
      id: "paper_preview",
      status: "ready",
      cash: "100000",
      equity: "100000",
      realized_pnl: "0"
    },
    positions: [],
    recent_fills: [],
    recent_events: []
  },
  strategy_lab: {
    latest_research: null,
    latest_backtest: null,
    latest_experiment: null
  },
  live_orders: {
    total_count: 0,
    pending_approval_count: 0,
    recent: []
  },
  bitpro: {
    adapter: "mcp_non_live_lifecycle",
    configured: false,
    api_base: "http://127.0.0.1:8889/api/v2",
    auth_header: "X-BitPro-MCP-Token",
    token_configured: false,
    token_source: "bitpro_settings_agent_token_or_server_env",
    remote_mcp: {
      transport: "streamable-http",
      path_default: "/api/v2/mcp/",
      auth_header_default: "X-BitPro-MCP-Token",
      token_env: "BITPRO_MCP_API_TOKEN",
      token_status_path: "/settings/mcp-token",
      token_generate_path: "/settings/mcp-token/generate"
    },
    agent_auth: {
      auth_header_default: "X-BitPro-MCP-Token",
      static_token_env: "BITPRO_MCP_API_TOKEN",
      token_management: {
        settings_routes: {
          list: "GET /api/v2/settings/mcp-agent-tokens",
          create: "POST /api/v2/settings/mcp-agent-tokens",
          revoke: "DELETE /api/v2/settings/mcp-agent-tokens/{token_id}"
        },
        plaintext_returned_once: true,
        default_tool_groups: ["read", "research_backtest_paper_mutation", "live_diagnostic"]
      },
      scope_classes: {
        R: { label: "read", tool_group: "read" },
        W: { label: "research_backtest_paper_mutation", tool_group: "research_backtest_paper_mutation" },
        L: { label: "live_diagnostic", tool_group: "live_diagnostic" },
        T: { label: "live_mutation", tool_group: "live_mutation" }
      },
      idempotency: { required_tools: ["backtest_start_job", "paper_start"] }
    },
    tool_groups: {
      read: ["bitpro_capabilities", "bitpro_health", "market_klines"],
      research_backtest_paper_mutation: ["strategy_create", "backtest_start_job", "paper_start"],
      live_diagnostic: ["live_preflight", "trading_positions"],
      live_mutation: ["trading_futures_order"]
    },
    live_write_enabled: false,
    live_write_scope: "hypertrade_mcp_live_write_gate",
    tools: [
      "bitpro_capabilities",
      "bitpro_health",
      "market_klines",
      "strategy_generate",
      "strategy_create",
      "backtest_start_job",
      "backtest_get_job",
      "paper_configure",
      "paper_start",
      "paper_dashboard",
      "trading_positions"
    ]
  },
  evals: {
    status: "preview",
    case_count: 0,
    mode: "deterministic",
    cases: []
  }
};

function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [activeSection, setActiveSection] = useState<NavSection>(() => activeSectionFromPath());
  const [prompt, setPrompt] = useState(copy.zh.prompt);
  const [run, setRun] = useState<AgentRun>(seedRun);
  const [overview, setOverview] = useState<HarnessOverview | null>(null);
  const [harnessError, setHarnessError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [agentProgress, setAgentProgress] = useState<string[]>([]);
  const [memoryItems, setMemoryItems] = useState<MemoryItem[]>([]);
  const [memoryInventoryItems, setMemoryInventoryItems] = useState<MemoryItem[]>([]);
  const [selectedMemoryId, setSelectedMemoryId] = useState("");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryAssertions, setMemoryAssertions] = useState<MemoryAssertion[]>([]);
  const [skillProposals, setSkillProposals] = useState<SkillProposal[]>([]);
  const [skillReleases, setSkillReleases] = useState<SkillRelease[]>([]);
  const [governanceReason, setGovernanceReason] = useState("");
  const [portfolioAssessments, setPortfolioAssessments] = useState<PortfolioAssessment[]>([]);
  const [portfolioReason, setPortfolioReason] = useState("");
  const [ragQuery, setRagQuery] = useState("risk");
  const [ragHits, setRagHits] = useState<RagHit[]>([]);
  const [showRawMarkdown, setShowRawMarkdown] = useState(false);
  const [strategyLibrary, setStrategyLibrary] = useState<StrategyLibraryPayload>({
    source: "memory.strategy_knowledge",
    memory_count: 0,
    items: []
  });
  const [strategyQuery, setStrategyQuery] = useState("");
  const [monitorAlerts, setMonitorAlerts] = useState<MonitorAlert[]>([]);
  const [evidenceSelection, setEvidenceSelection] = useState<EvidenceSelection | null>(null);
  const [runObservability, setRunObservability] = useState<RunObservability | null>(null);
  const [observabilityLoading, setObservabilityLoading] = useState(false);
  const t = copy[language];
  const activeOverview = overview ?? previewOverview;
  const reportBlocks = useMemo(() => reportBlocksFromRun(run), [run]);
  const defaultProvider =
    activeOverview.providers.find((provider) => provider.default) ?? activeOverview.providers[0];
  const traceEvents =
    run.id !== seedRun.id ? run.trace_events : activeOverview.trace.recent_events.slice(0, 6);
  const selectedMemory =
    memoryItems.find((item) => item.id === selectedMemoryId) ?? memoryItems[0] ?? null;
  const navItemClass = useCallback(
    (section: NavSection) =>
      section === activeSection ? "nav-item nav-item-active" : "nav-item",
    [activeSection]
  );

  const metrics = useMemo(
    () => [
      {
        label: t.live,
        value: formatMetricNumber(activeOverview.market.ticker_count),
        icon: Radio,
        tone: "signal"
      },
      {
        label: t.report,
        value: formatMetricNumber(activeOverview.agent_runs.total_count),
        icon: Bot,
        tone: "brass"
      },
      {
        label: t.fallback,
        value: formatAge(activeOverview.market.latest_update_age_seconds),
        icon: Clock3,
        tone: "night"
      },
      {
        label: t.memory,
        value: formatMetricNumber(activeOverview.memory.active_count),
        icon: MemoryStick,
        tone: "signal"
      },
      {
        label: t.tokenUsage,
        value: formatMetricNumber(activeOverview.observability?.total_tokens ?? 0),
        icon: Activity,
        tone: "brass"
      }
    ],
    [activeOverview, t]
  );

  const strategyRouteMetrics = useMemo<RouteMetric[]>(() => {
    const evidence = strategyLibrary.items.reduce((total, item) => total + item.evidence_count, 0);
    const passed = strategyLibrary.items.reduce((total, item) => total + item.passed_count, 0);
    const failed = strategyLibrary.items.reduce((total, item) => total + item.failed_count, 0);
    return [
      { label: t.strategyCount, value: formatMetricNumber(strategyLibrary.items.length), tone: "signal" },
      { label: t.evidenceTotal, value: formatMetricNumber(evidence), tone: "brass" },
      { label: t.passedEvidence, value: formatMetricNumber(passed), tone: "signal" },
      { label: t.failedEvidence, value: formatMetricNumber(failed), tone: "danger" }
    ];
  }, [strategyLibrary, t]);

  const alertRouteMetrics = useMemo<RouteMetric[]>(() => {
    const priorityAlerts = monitorAlerts.filter((alert) =>
      ["critical", "high", "severe"].includes((alert.severity ?? "").toLowerCase())
    ).length;
    return [
      { label: t.currentAlerts, value: formatMetricNumber(monitorAlerts.length), tone: "danger" },
      { label: t.highPriority, value: formatMetricNumber(priorityAlerts), tone: "brass" },
      {
        label: t.approvalQueue,
        value: formatMetricNumber(activeOverview.live_orders.pending_approval_count),
        tone: "brass"
      },
      {
        label: t.orderIntent,
        value: formatMetricNumber(activeOverview.live_orders.total_count),
        tone: "signal"
      }
    ];
  }, [activeOverview.live_orders, monitorAlerts, t]);

  const runRouteMetrics = useMemo<RouteMetric[]>(() => {
    const completed = activeOverview.agent_runs.recent.filter((item) =>
      ["completed", "success"].includes(item.status.toLowerCase())
    ).length;
    return [
      { label: t.runTotal, value: formatMetricNumber(activeOverview.agent_runs.total_count), tone: "signal" },
      { label: t.recentCompleted, value: formatMetricNumber(completed), tone: "signal" },
      { label: t.traceTotal, value: formatMetricNumber(activeOverview.trace.total_count), tone: "brass" },
      {
        label: t.modelRequests,
        value: formatMetricNumber(activeOverview.observability?.model_requests ?? 0),
        tone: "violet"
      }
    ];
  }, [activeOverview.agent_runs, activeOverview.observability, activeOverview.trace, t]);

  const memoryRouteMetrics = useMemo<RouteMetric[]>(() => {
    const kinds = new Set(memoryInventoryItems.map((item) => item.kind).filter(Boolean)).size;
    const usage = memoryInventoryItems.reduce((total, item) => total + (item.usage_count ?? 0), 0);
    return [
      { label: t.activeMemory, value: formatMetricNumber(activeOverview.memory.active_count), tone: "signal" },
      { label: t.loadedMemory, value: formatMetricNumber(memoryInventoryItems.length), tone: "violet" },
      { label: t.memoryKinds, value: formatMetricNumber(kinds), tone: "brass" },
      { label: t.memoryReuseCount, value: formatMetricNumber(usage), tone: "signal" }
    ];
  }, [activeOverview.memory.active_count, memoryInventoryItems, t]);

  const ragRouteMetrics = useMemo<RouteMetric[]>(
    () => [
      { label: t.ragDocuments, value: formatMetricNumber(activeOverview.rag.document_count), tone: "signal" },
      { label: t.ragChunks, value: formatMetricNumber(activeOverview.rag.chunk_count), tone: "violet" },
      { label: t.ragMatches, value: formatMetricNumber(ragHits.length), tone: "brass" },
      { label: t.ragSearchTerm, value: ragQuery || "—", tone: "signal" }
    ],
    [activeOverview.rag, ragHits.length, ragQuery, t]
  );

  const portfolioRouteMetrics = useMemo<RouteMetric[]>(() => {
    const latest = portfolioAssessments[0];
    return [
      {
        label: t.portfolioAssessments,
        value: formatMetricNumber(portfolioAssessments.length),
        tone: "signal"
      },
      {
        label: t.strategyCount,
        value: formatMetricNumber(latest?.strategies.length ?? 0),
        tone: "violet"
      },
      {
        label: t.portfolioPairs,
        value: formatMetricNumber(latest?.pairwise.length ?? 0),
        tone: "brass"
      },
      {
        label: t.portfolioUnknowns,
        value: formatMetricNumber(latest?.unknowns.length ?? 0),
        tone: "danger"
      }
    ];
  }, [portfolioAssessments, t]);

  const refreshMemoryItems = useCallback(async (query = "") => {
    const path = query ? `/api/memory?query=${encodeURIComponent(query)}` : "/api/memory";
    const response = await fetch(path, { credentials: "include" });
    if (response.ok) {
      const payload = (await response.json()) as { items: MemoryItem[] };
      setMemoryItems(payload.items);
      if (query) {
        setMemoryInventoryItems((current) =>
          current.map((item) => payload.items.find((candidate) => candidate.id === item.id) ?? item)
        );
      } else {
        setMemoryInventoryItems(payload.items);
      }
      setSelectedMemoryId((current) => current || payload.items[0]?.id || "");
    }
  }, []);

  const refreshStrategyLibrary = useCallback(async (query = "") => {
    const suffix = query ? `?query=${encodeURIComponent(query)}` : "";
    const response = await fetch(`/api/strategy/library${suffix}`, { credentials: "include" });
    if (response.ok) {
      const payload = (await response.json()) as StrategyLibraryPayload;
      setStrategyLibrary({
        source: payload.source ?? "memory.strategy_knowledge",
        memory_count: payload.memory_count ?? 0,
        items: Array.isArray(payload.items) ? payload.items : []
      });
    }
  }, []);

  const refreshMonitorAlerts = useCallback(async () => {
    const response = await fetch("/api/alerts", { credentials: "include" });
    if (response.ok) {
      const payload = (await response.json()) as { items?: MonitorAlert[] };
      setMonitorAlerts(Array.isArray(payload.items) ? payload.items : []);
      return;
    }
    setMonitorAlerts([]);
  }, []);

  const refreshGovernance = useCallback(async () => {
    const [assertionsResponse, proposalsResponse, releasesResponse] = await Promise.all([
      fetch("/api/memory/assertions", { credentials: "include" }),
      fetch("/api/skills/proposals", { credentials: "include" }),
      fetch("/api/skills/releases", { credentials: "include" })
    ]);
    setMemoryAssertions(
      assertionsResponse.ok
        ? (((await assertionsResponse.json()) as { items?: MemoryAssertion[] }).items ?? [])
        : []
    );
    setSkillProposals(
      proposalsResponse.ok
        ? (((await proposalsResponse.json()) as { items?: SkillProposal[] }).items ?? [])
        : []
    );
    setSkillReleases(
      releasesResponse.ok
        ? (((await releasesResponse.json()) as { items?: SkillRelease[] }).items ?? [])
        : []
    );
  }, []);

  const refreshPortfolioAssessments = useCallback(async () => {
    const response = await fetch("/api/portfolio/assessments", { credentials: "include" });
    if (!response.ok) {
      setPortfolioAssessments([]);
      return;
    }
    const payload = (await response.json()) as { items?: PortfolioAssessment[] };
    setPortfolioAssessments(Array.isArray(payload.items) ? payload.items : []);
  }, []);

  const refreshOverview = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await fetch("/api/harness/overview", { credentials: "include" });
      if (response.ok) {
        setOverview((await response.json()) as HarnessOverview);
        await refreshMemoryItems();
        await refreshStrategyLibrary();
        await refreshMonitorAlerts();
        await refreshGovernance();
        await refreshPortfolioAssessments();
        setHarnessError("");
        return;
      }
      setHarnessError(`${response.status}`);
    } finally {
      setRefreshing(false);
    }
  }, [
    refreshGovernance,
    refreshMemoryItems,
    refreshMonitorAlerts,
    refreshPortfolioAssessments,
    refreshStrategyLibrary
  ]);

  const loadRunObservability = useCallback(async (runId: string) => {
    setObservabilityLoading(true);
    try {
      const response = await fetch(
        `/api/agent/runs/${encodeURIComponent(runId)}/observability`,
        { credentials: "include" }
      );
      if (response.ok) {
        setRunObservability((await response.json()) as RunObservability);
        return;
      }
      setRunObservability(null);
    } finally {
      setObservabilityLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshOverview();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshOverview]);

  useEffect(() => {
    function syncActiveSection() {
      setActiveSection(activeSectionFromPath());
    }

    window.addEventListener("popstate", syncActiveSection);
    return () => window.removeEventListener("popstate", syncActiveSection);
  }, []);

  function handleNavClick(section: NavSection, event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    window.history.pushState({}, "", sectionPath(section));
    setActiveSection(section);
  }

  async function handleRun() {
    setBusy(true);
    setAgentProgress([]);
    setRunObservability(null);
    try {
      const response = await fetch("/api/agent/runs/stream", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
      });
      if (response.ok && response.body) {
        const finalRun = await consumeAgentStream(response.body, (line) =>
          setAgentProgress((items) => [...items.slice(-8), line])
        );
        if (finalRun) {
          setRun(finalRun);
          await loadRunObservability(finalRun.id);
        }
        await refreshOverview();
        return;
      }
      if (response.ok) {
        const completedRun = (await response.json()) as AgentRun;
        setRun(completedRun);
        await loadRunObservability(completedRun.id);
        await refreshOverview();
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleRagSearch() {
    const response = await fetch(`/api/rag/search?query=${encodeURIComponent(ragQuery)}`, {
      credentials: "include"
    });
    if (response.ok) {
      const payload = (await response.json()) as { hits: RagHit[] };
      setRagHits(payload.hits);
    }
  }

  async function handleMemorySearch() {
    await refreshMemoryItems(memoryQuery);
  }

  async function handleStrategySearch() {
    await refreshStrategyLibrary(strategyQuery);
  }

  async function handleGovernanceDecision(
    resource: "assertion" | "skill",
    resourceId: string,
    decision: "approve" | "reject" | "dispute"
  ) {
    const reason = governanceReason.trim();
    if (!reason) {
      return;
    }
    const path =
      resource === "assertion"
        ? `/api/memory/assertions/${encodeURIComponent(resourceId)}/review`
        : `/api/skills/proposals/${encodeURIComponent(resourceId)}/approve`;
    const response = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision,
        reason,
        idempotency_key: `web_${resource}_${Date.now()}_${resourceId}`
      })
    });
    if (response.ok) {
      setGovernanceReason("");
      await refreshGovernance();
    }
  }

  async function handlePortfolioAssessment() {
    const response = await fetch("/api/portfolio/assessments", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `web_portfolio_${Date.now()}` })
    });
    if (response.ok) {
      await refreshPortfolioAssessments();
    }
  }

  async function handlePortfolioReview(
    assessmentId: string,
    recommendationId: string,
    decision: "accept" | "reject" | "hold"
  ) {
    const reason = portfolioReason.trim();
    if (!reason) {
      return;
    }
    const response = await fetch(
      `/api/portfolio/assessments/${encodeURIComponent(assessmentId)}/reviews`,
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recommendation_id: recommendationId,
          decision,
          reason,
          idempotency_key: `web_portfolio_review_${Date.now()}`
        })
      }
    );
    if (response.ok) {
      setPortfolioReason("");
      await refreshPortfolioAssessments();
    }
  }

  async function handleLoadRun(runId: string) {
    const response = await fetch(`/api/agent/runs/${encodeURIComponent(runId)}`, {
      credentials: "include"
    });
    if (response.ok) {
      setRun((await response.json()) as AgentRun);
      await loadRunObservability(runId);
    }
  }

  function handleSelectStrategyEvidence(item: StrategyLibraryItem) {
    setEvidenceSelection(strategyEvidenceSelection(item, t));
  }

  function handleSelectTraceEvidence(event: TraceEvent) {
    setEvidenceSelection(traceEvidenceSelection(event, t));
  }

  return (
    <div className="min-h-[100dvh] bg-paper text-ink">
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(circle_at_82%_0%,rgba(90,214,196,0.10),transparent_28%),radial-gradient(circle_at_20%_10%,rgba(214,162,74,0.06),transparent_24%),linear-gradient(rgba(110,165,150,0.045)_1px,transparent_1px),linear-gradient(90deg,rgba(110,165,150,0.035)_1px,transparent_1px)] bg-[size:auto,auto,28px_28px,28px_28px]" />
      <div className="relative grid min-h-[100dvh] grid-cols-[260px_1fr] max-lg:grid-cols-1">
        <aside className="border-r border-ink/15 bg-night px-5 py-6 text-ink shadow-[inset_-1px_0_0_rgba(90,214,196,0.05)]">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-md border border-signal/35 bg-signal/10 text-signal shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
              <Activity size={19} />
            </div>
            <div>
              <div className="text-base font-semibold tracking-normal">{t.product}</div>
              <div className="text-xs text-ink/55">生产级交易智能体</div>
            </div>
          </div>

          <div className="mt-7 rounded-md border border-ink/10 bg-ink/[0.03] px-3 py-3">
            <div className="flex items-center justify-between text-xs text-ink/55">
              <span>{t.providerMesh}</span>
              <StatusDot enabled={Boolean(defaultProvider?.enabled)} />
            </div>
            <div className="mt-2 truncate font-mono text-xs text-ink/85">
              {providerLabel(defaultProvider, t)}
            </div>
          </div>

          <nav className="mt-8 space-y-2 text-sm">
            <a
              className={navItemClass("harness")}
              href={sectionPath("harness")}
              onClick={(event) => handleNavClick("harness", event)}
            >
              <TerminalSquare size={16} />
              {t.harness}
            </a>
            <a
              className={navItemClass("strategy")}
              href={sectionPath("strategy")}
              onClick={(event) => handleNavClick("strategy", event)}
            >
              <Archive size={16} />
              {t.strategyLibrary}
            </a>
            <a
              className={navItemClass("portfolio")}
              href={sectionPath("portfolio")}
              onClick={(event) => handleNavClick("portfolio", event)}
            >
              <Layers3 size={16} />
              {t.portfolioLifecycle}
            </a>
            <a
              className={navItemClass("alerts")}
              href={sectionPath("alerts")}
              onClick={(event) => handleNavClick("alerts", event)}
            >
              <AlertTriangle size={16} />
              {t.monitorAlerts}
            </a>
            <a
              className={navItemClass("runs")}
              href={sectionPath("runs")}
              onClick={(event) => handleNavClick("runs", event)}
            >
              <Layers3 size={16} />
              {t.recentRuns}
            </a>
            <a
              className={navItemClass("quality")}
              href={sectionPath("quality")}
              onClick={(event) => handleNavClick("quality", event)}
            >
              <CheckCircle2 size={16} />
              {t.evals}
            </a>
            <a
              className={navItemClass("memory")}
              href={sectionPath("memory")}
              onClick={(event) => handleNavClick("memory", event)}
            >
              <MemoryStick size={16} />
              {t.routeMemory}
            </a>
            <a
              className={navItemClass("rag")}
              href={sectionPath("rag")}
              onClick={(event) => handleNavClick("rag", event)}
            >
              <Brain size={16} />
              {t.routeRag}
            </a>
          </nav>

          <button
            className="mt-8 flex w-full items-center justify-center gap-2 rounded-md border border-ink/15 px-3 py-2 text-sm text-ink/80 transition hover:border-signal/35 hover:text-signal"
            onClick={() => setLanguage(language === "zh" ? "en" : "zh")}
            type="button"
          >
            <Languages size={16} />
            {language === "zh" ? "英文界面" : "中文界面"}
          </button>
        </aside>

        <main className="mx-auto min-w-0 w-full max-w-[1480px] px-8 py-7 max-lg:px-4">
          <div className={activeSection === "harness" ? "" : "hidden"}>
          <header
            className="grid grid-cols-[1fr_auto] items-start gap-4 border-b border-ink/15 pb-5 max-md:grid-cols-1"
            id="harness"
          >
            <div>
              <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase text-brass">
                <span>{t.risk}</span>
                <span className="h-1 w-1 rounded-full bg-brass/45" />
                <span>{overview ? t.lastSync : t.preview}</span>
              </div>
              <h1 className="mt-2 text-4xl font-semibold tracking-tight max-sm:text-3xl">
                {t.workbenchTitle}
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-ink/55">
                <span>{t.workbenchSubtitle}</span>
                <span className="font-mono">{overview ? activeOverview.generated_at : t.preview}</span>
                {refreshing ? (
                  <span className="inline-flex items-center gap-2 text-brass">
                    <span className="skeleton-pulse h-1.5 w-1.5 rounded-full bg-brass" />
                    {t.overviewLoading}
                  </span>
                ) : null}
              </div>
            </div>
            <div className="runtime-pill">
              <div>
                <span>{t.systemStatus}</span>
                <strong>{overview ? t.healthy : t.preview}</strong>
                <span className="mt-1 font-mono">{t.okx}</span>
              </div>
              <CheckCircle2 className="text-signal" size={18} />
            </div>
          </header>

          <section className="telemetry-grid mt-6">
            {metrics.map((metric, index) => (
              <div className="telemetry-cell" key={metric.label} style={cascadeStyle(index)}>
                <div className="flex items-start justify-between gap-4">
                  <metric.icon className={`metric-${metric.tone}`} size={18} />
                  <span className="font-mono text-2xl font-semibold tracking-tight text-ink">
                    {metric.value}
                  </span>
                </div>
                <div className="mt-4 text-xs uppercase text-ink/45">{metric.label}</div>
              </div>
            ))}
          </section>

          <section className="mt-5 grid grid-cols-[0.95fr_1.05fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.runConsole}</h2>
                  <p className="mt-1 text-sm text-ink/50">{t.runConsoleHint}</p>
                </div>
                <Sparkles size={18} className="text-brass" />
              </div>
              <textarea
                className="prompt-box"
                onChange={(event) => setPrompt(event.target.value)}
                value={prompt}
              />
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="button-primary" disabled={busy} onClick={handleRun} type="button">
                  {busy ? <RefreshCw className="animate-spin" size={16} /> : <Bot size={16} />}
                  {t.run}
                </button>
              </div>
              <div className="mt-4 trace-list">
                <div className="px-1 py-2 text-xs font-semibold uppercase text-ink/45">
                  {t.agentProgress}
                </div>
                <div className="trace-row">
                  <Bot size={14} className="text-brass" />
                  <span className="text-xs">{t.currentStage}</span>
                  <span className="ml-auto font-mono text-xs text-ink/55">
                    {run.run_state_json?.current_node ?? t.preview}
                  </span>
                </div>
                {agentProgress.length === 0 ? (
                  <div className="empty-row my-3">{t.overviewLoading}</div>
                ) : (
                  agentProgress.map((item, index) => (
                    <div className="trace-row" key={`${item}-${index}`} style={cascadeStyle(index)}>
                      <Clock3 size={14} className="text-brass" />
                      <span className="min-w-0 truncate font-mono text-xs">{item}</span>
                    </div>
                  ))
                )}
              </div>
              <div className="mt-4 flex items-center justify-between gap-3">
                <h3 className="section-title">{t.reportReader}</h3>
                <button
                  className="icon-button"
                  onClick={() => setShowRawMarkdown((value) => !value)}
                  type="button"
                >
                  <TerminalSquare size={14} />
                  {showRawMarkdown ? t.reportReader : t.rawMarkdown}
                </button>
              </div>
              {showRawMarkdown ? (
                <pre className="report-block">
                  {busy ? `${t.overviewLoading}...` : run.report_markdown}
                </pre>
              ) : reportBlocks.length > 0 ? (
                <StructuredReport blocks={reportBlocks} markdown={run.report_markdown} t={t} />
              ) : (
                <div className="markdown-report">
                  {busy ? t.overviewLoading : renderMarkdown(run.report_markdown)}
                </div>
              )}
            </div>

            <div className="panel panel-command">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.runtimeMonitor}</h2>
                  <p className="mt-1 text-sm text-ink/50">{t.runtimeMonitorHint}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button className="icon-button" onClick={refreshOverview} type="button">
                    <RefreshCw className={refreshing ? "animate-spin" : ""} size={16} />
                    <span>{t.refresh}</span>
                  </button>
                  <Cable size={18} className="text-brass" />
                </div>
              </div>
              <div className="mt-5 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">{t.tools}</h3>
                <span className="rounded border border-ink/10 px-2 py-1 text-xs text-ink/45">
                  {activeOverview.trace.total_count}
                </span>
              </div>
              <div className="mt-2 trace-list">
                {traceEvents.map((event, index) => (
                  <button
                    className="trace-row w-full text-left"
                    key={`${event.tool_name}-${event.id ?? index}`}
                    onClick={() => handleSelectTraceEvidence(event)}
                    style={cascadeStyle(index)}
                    type="button"
                  >
                    <span className="font-mono text-xs text-ink/45">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="font-medium">{event.tool_name}</span>
                    <span className="ml-auto rounded border border-signal/30 px-2 py-1 text-xs text-signal">
                      {statusLabel(event.status)}
                    </span>
                  </button>
                ))}
              </div>
              <div className="mt-6 grid grid-cols-3 gap-3 max-md:grid-cols-1">
                <div className="mini-block">
                  <span>{t.providers}</span>
                  <strong>{providerLabel(defaultProvider, t)}</strong>
                </div>
                <div className="mini-block">
                  <span>{t.rag}</span>
                  <strong>
                    {activeOverview.rag.document_count} 文档 / {activeOverview.rag.chunk_count} 分片
                  </strong>
                </div>
                <div className="mini-block">
                  <span>{t.memory}</span>
                  <strong>
                    {activeOverview.memory.active_count} 可用 /{" "}
                    {activeOverview.memory.total_count} 总数
                  </strong>
                </div>
              </div>
              {activeOverview.bitpro ? (
                <div className="mt-6 rounded-md border border-ink/10 bg-paper/70 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold">{t.bitproMcp}</h3>
                      <p className="mt-1 text-xs leading-5 text-ink/50">{t.bitproMcpHint}</p>
                    </div>
                    <span
                      className={`inline-flex items-center gap-2 rounded border px-2 py-1 text-xs font-semibold ${
                        activeOverview.bitpro.token_configured
                          ? "border-signal/25 text-signal"
                          : "border-danger/25 text-danger"
                      }`}
                    >
                      <StatusDot enabled={activeOverview.bitpro.token_configured} />
                      {activeOverview.bitpro.token_configured ? t.mcpTokenReady : t.mcpTokenMissing}
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 max-md:grid-cols-1">
                    <div className="mini-block">
                      <span>{t.mcpApiBase}</span>
                      <strong className="truncate font-mono">{activeOverview.bitpro.api_base}</strong>
                    </div>
                    <div className="mini-block">
                      <span>{t.mcpAuthHeader}</span>
                      <strong className="truncate font-mono">{activeOverview.bitpro.auth_header}</strong>
                    </div>
                    <div className="mini-block">
                      <span>{t.mcpTokenSource}</span>
                      <strong>{formatTokenSource(activeOverview.bitpro.token_source, t)}</strong>
                    </div>
                    <div className="mini-block">
                      <span>{t.mcpScopes}</span>
                      <strong className="font-mono">
                        {Object.keys(activeOverview.bitpro.agent_auth?.scope_classes ?? {}).join(" / ") ||
                          "R / W / L / T"}
                      </strong>
                    </div>
                    <div className="mini-block">
                      <span>{t.mcpAdapter}</span>
                      <strong className="truncate font-mono">{activeOverview.bitpro.adapter}</strong>
                    </div>
                    <div className="mini-block">
                      <span>{t.mcpTools}</span>
                      <strong className="font-mono">
                        {formatMetricNumber(activeOverview.bitpro.tools.length)}
                      </strong>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </section>

          <AgentFlightRecorder
            data={runObservability}
            language={language}
            loading={busy || observabilityLoading}
          />
          </div>

          <section className="mt-5" hidden={activeSection !== "strategy"}>
            <RouteMetricStrip label={t.pageMetrics} metrics={strategyRouteMetrics} />
            <div className="mt-3 grid grid-cols-[1.1fr_0.9fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.strategyEvidence}</h2>
                  <p className="mt-1 text-sm text-ink/50">{t.strategyLibraryHint}</p>
                </div>
                <Archive size={18} className="text-brass" />
              </div>
              <div className="mt-4 grid grid-cols-[1fr_auto] gap-2 max-sm:grid-cols-1">
                <input
                  className="field-light"
                  onChange={(event) => setStrategyQuery(event.target.value)}
                  placeholder={t.strategyKey}
                  value={strategyQuery}
                />
                <button className="icon-button justify-center" onClick={handleStrategySearch} type="button">
                  <Brain size={14} />
                  {t.query}
                </button>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-3 max-md:grid-cols-1">
                <div className="operator-card operator-card-compact strategy-summary-card" data-tone="violet">
                  <span>{t.source}</span>
                  <strong className="truncate font-mono">{strategyLibrary.source}</strong>
                </div>
                <div className="operator-card operator-card-compact strategy-summary-card" data-tone="brass">
                  <span>{t.evidenceCount}</span>
                  <strong className="font-mono">{strategyLibrary.memory_count}</strong>
                </div>
                <div className="operator-card operator-card-compact strategy-summary-card" data-tone="signal">
                  <span>{t.latestResult}</span>
                  <strong className="font-mono">{strategyLibrary.items[0]?.strategy_key ?? "n/a"}</strong>
                </div>
              </div>
              <div className="mt-4 grid gap-3">
                {strategyLibrary.items.length === 0 ? (
                  <div className="empty-row">{t.noStrategyEvidence}</div>
                ) : (
                  strategyLibrary.items.map((item, index) => (
                    <button
                      className="operator-card strategy-card text-left"
                      data-tone={strategyCardTone(item)}
                      key={item.strategy_key}
                      onClick={() => handleSelectStrategyEvidence(item)}
                      style={cascadeStyle(index)}
                      type="button"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <strong className="font-mono">{item.strategy_key}</strong>
                          <div className="mt-1 text-xs text-ink/45">
                            {t.passFail}: {item.passed_count} / {item.failed_count}
                          </div>
                        </div>
                        <span className="rounded border border-brass/25 px-2 py-1 text-xs text-brass">
                          {item.evidence_count} {t.evidenceCount}
                        </span>
                      </div>
                      <div className="evidence-grid">
                        <EvidenceMetric label={t.bestEvidence} tone="brass" value={item.best?.variant_id ?? "n/a"} />
                        <EvidenceMetric
                          label={t.returnPct}
                          tone={metricTone(item.best?.total_return_pct)}
                          value={formatPercentValue(item.best?.total_return_pct)}
                        />
                        <EvidenceMetric
                          label={t.maxDrawdown}
                          tone="brass"
                          value={formatPercentValue(item.best?.max_drawdown_pct)}
                        />
                        <EvidenceMetric label={t.trades} tone="violet" value={String(item.best?.trade_count ?? "n/a")} />
                      </div>
                      <SourceIdStrip
                        evidence={item.best}
                        label={t.source}
                        sourceMemoryIds={item.source_memory_ids ?? []}
                      />
                      {item.failure_reasons?.length ? (
                        <div className="operator-card operator-card-compact evidence-note" data-tone="danger">
                          <span>{t.failureReasons}</span>
                          <strong>{item.failure_reasons.join(", ")}</strong>
                        </div>
                      ) : null}
                      {item.next_experiments?.length ? (
                        <div className="operator-card operator-card-compact evidence-note" data-tone="brass">
                          <span>{t.nextExperiment}</span>
                          <strong>{item.next_experiments[0]}</strong>
                        </div>
                      ) : null}
                    </button>
                  ))
                )}
              </div>
            </div>

            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.evidenceDrilldown}</h2>
                <FileText size={18} className="text-brass" />
              </div>
              {evidenceSelection ? (
                <div className="mt-4 grid gap-2">
                  <div className="text-sm font-semibold">{evidenceSelection.title}</div>
                  {evidenceSelection.rows.map((row) => (
                    <div
                      className="operator-card operator-card-compact evidence-detail-row"
                      data-tone="violet"
                      key={`${row.label}-${row.value}`}
                    >
                      <span>{row.label}</span>
                      <strong>
                        {row.label}: {row.value}
                      </strong>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="empty-row mt-4">{t.selectEvidence}</div>
              )}
            </div>
            </div>
          </section>

          <section className="mt-5" hidden={activeSection !== "alerts"}>
            <RouteMetricStrip label={t.pageMetrics} metrics={alertRouteMetrics} />
            <div className="mt-3 grid grid-cols-[0.95fr_1.05fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.alertStatus}</h2>
                  <p className="mt-1 text-sm text-ink/50">{t.alertStatusHint}</p>
                </div>
                <AlertTriangle size={18} className="text-brass" />
              </div>
              <div className="mt-4 space-y-2">
                {monitorAlerts.length === 0 ? (
                  <div className="empty-row">{t.noMonitorAlerts}</div>
                ) : (
                  monitorAlerts.map((alert, index) => (
                    <div
                      className="operator-card alert-row"
                      data-tone={monitorAlertTone(alert)}
                      key={alert.id ?? `${alert.code}-${index}`}
                    >
                      <span className="font-mono text-xs text-ink/45">
                        {alert.severity ?? "info"}
                      </span>
                      <div className="min-w-0">
                        <div className="font-semibold">{alert.title ?? alert.code ?? "alert"}</div>
                        <div className="truncate text-xs text-ink/50">
                          {alert.message ?? alert.source_id ?? "n/a"}
                        </div>
                      </div>
                      <span className="rounded border border-ink/10 px-2 py-1 text-xs">
                        {alert.source_id ?? alert.id ?? "n/a"}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.approvalRisk}</h2>
                <CheckCircle2 size={18} className="text-signal" />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 max-md:grid-cols-1">
                <div className="mini-block">
                  <span>{t.pending}</span>
                  <strong className="font-mono">{activeOverview.live_orders.pending_approval_count}</strong>
                </div>
                <div className="mini-block">
                  <span>{t.orderIntent}</span>
                  <strong className="font-mono">{activeOverview.live_orders.total_count}</strong>
                </div>
              </div>
              <div className="mt-4 space-y-2">
                {activeOverview.live_orders.recent.length === 0 ? (
                  <div className="empty-row">{t.noIntents}</div>
                ) : (
                  activeOverview.live_orders.recent.slice(0, 5).map((intent) => (
                    <div className="operator-card status-row" data-tone={intentCardTone(intent)} key={intent.id}>
                      <span className="font-mono text-xs text-ink/55">{intent.id}</span>
                      <span className="min-w-0 truncate text-sm">
                        {intent.inst_id} / {intent.side} / {intent.size}
                      </span>
                      <span className="rounded border border-brass/25 px-2 py-1 text-xs text-brass">
                        {intent.risk_status ?? intent.status}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
            </div>
          </section>

          <section className="mt-5" hidden={activeSection !== "portfolio"}>
            <RouteMetricStrip label={t.pageMetrics} metrics={portfolioRouteMetrics} />
            <PortfolioLifecyclePanel
              assessments={portfolioAssessments}
              onAssess={handlePortfolioAssessment}
              onReview={handlePortfolioReview}
              reason={portfolioReason}
              setReason={setPortfolioReason}
              t={t}
            />
          </section>

          <section className="mt-5" hidden={activeSection !== "memory" && activeSection !== "rag"}>
            <div className="min-w-0 space-y-5" hidden={activeSection !== "memory"}>
              <RouteMetricStrip label={t.pageMetrics} metrics={memoryRouteMetrics} />
              <MemoryObservatory
                activeCount={activeOverview.memory.active_count}
                items={memoryInventoryItems}
                t={t}
              />
              <GovernanceReview
                assertions={memoryAssertions}
                onDecision={handleGovernanceDecision}
                proposals={skillProposals}
                reason={governanceReason}
                releases={skillReleases}
                setReason={setGovernanceReason}
                t={t}
              />
              <div className="panel">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.memoryManager}</h2>
                  <p className="mt-1 text-sm text-ink/50">
                    {activeOverview.memory.active_count} 可用 / {activeOverview.memory.total_count} 总数
                  </p>
                </div>
                <MemoryStick size={18} className="text-brass" />
              </div>
              <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
                <input
                  className="field-light"
                  onChange={(event) => setMemoryQuery(event.target.value)}
                  placeholder={t.searchMemory}
                  value={memoryQuery}
                />
                <button className="icon-button" onClick={handleMemorySearch} type="button">
                  <Brain size={14} />
                  {t.query}
                </button>
              </div>
              <div className="mt-4 space-y-2">
                {memoryItems.length === 0 ? (
                  <div className="empty-row">{t.noMemoryItems}</div>
                ) : (
                  memoryItems.slice(0, 8).map((item) => (
                    <button
                      className={`operator-card memory-row ${
                        selectedMemory?.id === item.id ? "memory-row-active" : ""
                      }`}
                      key={item.id}
                      onClick={() => setSelectedMemoryId(item.id)}
                      type="button"
                    >
                      <span className="min-w-0 shrink truncate font-mono text-xs text-ink/45">{item.id}</span>
                      <span className="min-w-0 flex-1 truncate text-left text-sm">{item.content}</span>
                      <span className="shrink-0 rounded border border-ink/10 px-2 py-1 text-xs">
                        {item.kind}
                      </span>
                      {item.usage_count ? (
                        <span className="shrink-0 rounded border border-brass/25 px-2 py-1 text-xs text-brass">
                          {item.usage_count}
                        </span>
                      ) : null}
                    </button>
                  ))
                )}
              </div>
              <div className="mt-5">
                <h3 className="section-title">{t.selectedMemory}</h3>
                {selectedMemory ? (
                  <div className="mt-4 grid gap-3">
                    <div className="grid grid-cols-3 gap-3 max-md:grid-cols-1">
                      <div className="mini-block">
                        <span>ID</span>
                        <strong className="font-mono">{selectedMemory.id}</strong>
                      </div>
                      <div className="mini-block">
                        <span>{t.source}</span>
                        <strong className="font-mono">{selectedMemory.source_tool || "n/a"}</strong>
                      </div>
                      <div className="mini-block">
                        <span>运行</span>
                        <strong className="font-mono">{selectedMemory.source_run_id || "n/a"}</strong>
                      </div>
                    </div>
                    <div className="markdown-report">{renderMarkdown(selectedMemory.content)}</div>
                    {selectedMemory.tags?.length ? (
                      <div className="flex flex-wrap gap-2">
                        {selectedMemory.tags.map((tag) => (
                          <span className="rounded border border-ink/10 px-2 py-1 text-xs" key={tag}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="empty-row mt-4">{t.noMemoryItems}</div>
                )}
              </div>
              </div>
            </div>

            <div className="space-y-3" hidden={activeSection !== "rag"}>
              <RouteMetricStrip label={t.pageMetrics} metrics={ragRouteMetrics} />
              <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.rag}</h2>
                  <p className="mt-1 text-sm text-ink/50">
                    {activeOverview.rag.document_count} 文档 / {activeOverview.rag.chunk_count} 分片
                  </p>
                </div>
                <Brain size={18} className="text-brass" />
              </div>
              <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
                <input
                  className="field-light"
                  onChange={(event) => setRagQuery(event.target.value)}
                  placeholder={t.searchRag}
                  value={ragQuery}
                />
                <button className="icon-button" onClick={handleRagSearch} type="button">
                  <Brain size={14} />
                  {t.query}
                </button>
              </div>
              <div className="mt-4 space-y-2">
                {ragHits.length === 0 ? (
                  <div className="empty-row">{t.rag}</div>
                ) : (
                  ragHits.slice(0, 8).map((hit) => (
                    <div
                      className="operator-card status-row items-start"
                      data-tone="violet"
                      key={`${hit.source_path}-${hit.chunk_index}`}
                    >
                      <div className="min-w-0">
                        <div className="font-semibold">{hit.title}</div>
                        <div className="truncate font-mono text-xs text-ink/45">
                          {hit.source_path}#{hit.chunk_index}
                        </div>
                        <p className="mt-1 max-h-12 overflow-hidden text-xs text-ink/55">
                          {hit.content_preview}
                        </p>
                      </div>
                      <span className="font-mono text-xs text-brass">
                        {hit.score.toFixed(2)}
                      </span>
                    </div>
                  ))
                )}
              </div>
              </div>
            </div>
          </section>

          <section className="mt-5" hidden={activeSection !== "runs"}>
            <RouteMetricStrip label={t.pageMetrics} metrics={runRouteMetrics} />
            <div className="mt-3 grid grid-cols-[0.95fr_1.05fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.topMovers}</h2>
                <LineChart size={18} className="text-signal" />
              </div>
              <div className="mt-4 space-y-2">
                {activeOverview.market.top_movers.length === 0 ? (
                  <div className="empty-row">{t.noMarket}</div>
                ) : (
                  activeOverview.market.top_movers.map((ticker, index) => (
                    <div className="ticker-row" key={ticker.inst_id}>
                      <span className="font-mono text-[11px] text-ink/45">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="font-mono text-xs font-semibold">{ticker.inst_id}</span>
                      <span className="font-mono">{ticker.last}</span>
                      <span className={ticker.change_utc0_pct.startsWith("-") ? "text-danger" : "text-signal"}>
                        {ticker.change_utc0_pct}%
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.recentRuns}</h2>
                <Layers3 size={18} className="text-brass" />
              </div>
              <div className="mt-4 space-y-2">
                {activeOverview.agent_runs.recent.length === 0 ? (
                  <div className="empty-row">{t.noRuns}</div>
                ) : (
                  activeOverview.agent_runs.recent.map((recentRun, index) => (
                    <button
                      className="run-row w-full text-left"
                      key={recentRun.id}
                      onClick={() => handleLoadRun(recentRun.id)}
                      style={cascadeStyle(index)}
                      type="button"
                    >
                      <span className="font-mono text-xs text-ink/55">{recentRun.id}</span>
                      <span className="min-w-0 truncate text-sm">{recentRun.prompt}</span>
                      <span className="rounded border border-signal/25 px-2 py-1 text-xs text-signal">
                        {statusLabel(recentRun.status)}
                      </span>
                    </button>
                  ))
                )}
              </div>
            </div>
            </div>
          </section>

          <section className="mt-5" hidden={activeSection !== "quality"}>
            <RouteMetricStrip
              label={t.pageMetrics}
              metrics={[
                {
                  label: language === "zh" ? "总用例" : "Cases",
                  value: formatMetricNumber(activeOverview.evals.case_count),
                  tone: "signal"
                },
                {
                  label: language === "zh" ? "确定性门禁" : "Deterministic gate",
                  value: statusLabel(activeOverview.evals.research_os?.status),
                  tone: activeOverview.evals.research_os?.status === "passed" ? "signal" : "danger"
                },
                {
                  label: language === "zh" ? "Provider 基线" : "Provider baseline",
                  value: activeOverview.evals.quality?.provider_baseline ?? "not_loaded",
                  tone: "brass"
                },
                {
                  label: language === "zh" ? "质量合约" : "Quality contract",
                  value: activeOverview.evals.quality?.metric_contract ?? "n/a",
                  tone: "violet"
                }
              ]}
            />
            <div className="mt-3 grid grid-cols-[0.9fr_1.1fr] gap-5 max-xl:grid-cols-1">
              <div className="panel">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h2 className="section-title">
                      {language === "zh" ? "Agent 研究质量" : "Agent research quality"}
                    </h2>
                    <p className="mt-1 text-sm text-ink/50">
                      {language === "zh"
                        ? "只读展示 cohort、口径版本和失败分类；评分逻辑由服务端统一执行。"
                        : "Read-only cohorts, metric version, and failure classes scored by the server."}
                    </p>
                  </div>
                  <CheckCircle2 className="text-signal" size={18} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 max-md:grid-cols-1">
                  {Object.entries(activeOverview.evals.quality?.cohorts ?? {}).map(
                    ([cohort, count]) => (
                      <div className="operator-card operator-card-compact" data-tone="signal" key={cohort}>
                        <span>{cohort}</span>
                        <strong className="font-mono">{count}</strong>
                      </div>
                    )
                  )}
                </div>
              </div>
              <div className="panel">
                <div className="flex items-center justify-between gap-4">
                  <h2 className="section-title">
                    {language === "zh" ? "失败分类与边界" : "Failures and boundaries"}
                  </h2>
                  <AlertTriangle size={18} className="text-brass" />
                </div>
                <div className="mt-4 space-y-2">
                  {Object.entries(activeOverview.evals.quality?.failure_categories ?? {}).length ? (
                    Object.entries(activeOverview.evals.quality?.failure_categories ?? {}).map(
                      ([failure, count]) => (
                        <div className="operator-card status-row" data-tone="danger" key={failure}>
                          <span className="font-mono text-xs">{failure}</span>
                          <strong>{count}</strong>
                        </div>
                      )
                    )
                  ) : (
                    <div className="empty-row">
                      {language === "zh" ? "当前确定性门禁没有失败分类" : "No deterministic failures"}
                    </div>
                  )}
                </div>
                <div className="operator-card operator-card-compact mt-4" data-tone="brass">
                  <span>{language === "zh" ? "生产边界" : "Production boundary"}</span>
                  <strong>
                    {language === "zh"
                      ? "后台触发保持禁用；paper/live 权限未变化"
                      : "Background triggers disabled; paper/live permissions unchanged"}
                  </strong>
                </div>
              </div>
            </div>
          </section>
          {harnessError ? <div className="mt-3 text-sm text-danger">API {harnessError}</div> : null}
        </main>
      </div>
    </div>
  );
}

function providerLabel(provider: ProviderStatus | undefined, t: Record<string, string>): string {
  if (!provider) {
    return t.missing;
  }
  const model = provider.model || provider.name;
  return `${provider.display_name} / ${model}`;
}

function formatTokenSource(source: string | undefined, t: Record<string, string>): string {
  if (source === "bitpro_settings_agent_token_or_server_env") {
    return t.mcpTokenSourceSettings;
  }
  return source || "n/a";
}

function statusLabel(status: string | undefined): string {
  const normalized = (status ?? "").toLowerCase();
  const labels: Record<string, string> = {
    allowed: "通过",
    approved: "已批准",
    completed: "已完成",
    configured: "已配置",
    deterministic: "确定性",
    disabled: "已禁用",
    error: "异常",
    failed: "失败",
    missing: "未配置",
    passed: "通过",
    pending: "待处理",
    pending_approval: "待审批",
    preview: "预览",
    ready: "就绪",
    rejected: "已拒绝",
    running: "运行中",
    success: "成功"
  };
  return labels[normalized] ?? status ?? "未知";
}

function activeSectionFromPath(): NavSection {
  if (typeof window === "undefined") {
    return "harness";
  }
  const section = window.location.pathname.split("/").filter(Boolean).at(-1) ?? "harness";
  if (
    section === "strategy" ||
    section === "portfolio" ||
    section === "alerts" ||
    section === "runs" ||
    section === "quality" ||
    section === "memory" ||
    section === "rag"
  ) {
    return section;
  }
  return "harness";
}

function sectionPath(section: NavSection): string {
  return section === "harness" ? "/harness" : `/harness/${section}`;
}

function StatusDot({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={`status-dot ${enabled ? "status-dot-on" : "status-dot-off"}`}
      aria-label={enabled ? "已配置" : "未配置"}
    />
  );
}

function RouteMetricStrip({ metrics, label }: { metrics: RouteMetric[]; label: string }) {
  return (
    <section aria-label={label} className="route-metric-strip">
      {metrics.map((metric) => (
        <div className="route-metric-card" data-tone={metric.tone} key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
        </div>
      ))}
    </section>
  );
}

function strategyCardTone(item: StrategyLibraryItem): RouteMetric["tone"] {
  if (item.failed_count > 0 && item.passed_count > 0) {
    return "brass";
  }
  if (item.failed_count > 0) {
    return "danger";
  }
  if (item.passed_count > 0) {
    return "signal";
  }
  return "brass";
}

function monitorAlertTone(alert: MonitorAlert): RouteMetric["tone"] {
  const severity = (alert.severity ?? "").toLowerCase();
  if (["critical", "high", "severe", "error"].includes(severity)) {
    return "danger";
  }
  if (["warning", "warn", "medium"].includes(severity)) {
    return "brass";
  }
  return "signal";
}

function intentCardTone(intent: LiveOrderIntent): RouteMetric["tone"] {
  const risk = (intent.risk_status ?? "").toLowerCase();
  const status = intent.status.toLowerCase();
  if (status.includes("pending")) {
    return "brass";
  }
  if (["rejected", "failed", "error", "blocked"].includes(risk) || ["rejected", "failed", "error"].includes(status)) {
    return "danger";
  }
  return "signal";
}

type MemoryKindInsight = {
  kind: string;
  count: number;
  share: number;
  color: string;
};

type MemoryActivityInsight = {
  key: string;
  label: string;
  count: number;
};

function PortfolioLifecyclePanel({
  assessments,
  reason,
  setReason,
  onAssess,
  onReview,
  t
}: {
  assessments: PortfolioAssessment[];
  reason: string;
  setReason: (value: string) => void;
  onAssess: () => Promise<void>;
  onReview: (
    assessmentId: string,
    recommendationId: string,
    decision: "accept" | "reject" | "hold"
  ) => Promise<void>;
  t: Record<string, string>;
}) {
  const latest = assessments[0];
  return (
    <div className="mt-3 grid grid-cols-[1.2fr_0.8fr] gap-5 max-xl:grid-cols-1">
      <section className="panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="section-title">{t.portfolioLifecycle}</h2>
            <p className="mt-1 text-sm text-ink/50">{t.portfolioLifecycleHint}</p>
          </div>
          <button className="button-primary" onClick={() => void onAssess()} type="button">
            <Layers3 size={16} />
            {t.runPortfolioAssessment}
          </button>
        </div>
        <input
          aria-label={t.governanceReason}
          className="field-light mt-4 w-full"
          onChange={(event) => setReason(event.target.value)}
          placeholder={t.governanceReason}
          value={reason}
        />
        {!latest ? (
          <div className="empty-row mt-4">{t.noPortfolioAssessments}</div>
        ) : (
          <div className="mt-4 space-y-3">
            {latest.recommendations.map((recommendation) => (
              <div
                className="operator-card block"
                data-tone={recommendation.action === "observe" ? "signal" : "brass"}
                key={recommendation.recommendation_id}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong>{recommendation.action}</strong>
                  <span className="font-mono text-xs text-ink/45">
                    {recommendation.recommendation_id}
                  </span>
                </div>
                <p className="mt-2 text-sm text-ink/65">{recommendation.reason}</p>
                <div className="mt-2 text-xs text-ink/45">
                  card={recommendation.strategy_card_id || "portfolio"} · allocation=false ·
                  trading=false
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(["accept", "hold", "reject"] as const).map((decision) => (
                    <button
                      className="icon-button"
                      disabled={!reason.trim()}
                      key={decision}
                      onClick={() =>
                        void onReview(latest.id, recommendation.recommendation_id, decision)
                      }
                      type="button"
                    >
                      {decision === "accept"
                        ? t.approve
                        : decision === "hold"
                          ? t.hold
                          : t.reject}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="panel">
        <h2 className="section-title">{t.portfolioAssessments}</h2>
        <div className="mt-4 space-y-2">
          {assessments.length === 0 ? (
            <div className="empty-row">{t.noPortfolioAssessments}</div>
          ) : (
            assessments.slice(0, 12).map((assessment) => (
              <div className="operator-card block" data-tone="violet" key={assessment.id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">{assessment.id}</span>
                  <span className="text-xs text-brass">{statusLabel(assessment.status)}</span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-ink/55">
                  <span>{assessment.strategies.length} strategies</span>
                  <span>{assessment.pairwise.length} pairs</span>
                  <span>{assessment.unknowns.length} unknowns</span>
                </div>
                {assessment.pairwise.slice(0, 4).map((pair, index) => (
                  <div className="mt-2 font-mono text-xs text-ink/45" key={index}>
                    {stringifyValue(pair.left_card_id)} ↔ {stringifyValue(pair.right_card_id)} ·
                    corr={stringifyValue(pair.correlation ?? "unknown")} · n=
                    {stringifyValue(pair.sample_count)}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

function GovernanceReview({
  assertions,
  proposals,
  releases,
  reason,
  setReason,
  onDecision,
  t
}: {
  assertions: MemoryAssertion[];
  proposals: SkillProposal[];
  releases: SkillRelease[];
  reason: string;
  setReason: (value: string) => void;
  onDecision: (
    resource: "assertion" | "skill",
    resourceId: string,
    decision: "approve" | "reject" | "dispute"
  ) => Promise<void>;
  t: Record<string, string>;
}) {
  const pendingAssertions = assertions.filter((item) =>
    ["proposed", "disputed"].includes(item.status)
  );
  const pendingSkills = proposals.filter((item) => item.status === "pending_approval");
  return (
    <section className="panel" aria-labelledby="governance-review-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="section-title" id="governance-review-title">
            {t.governanceReview}
          </h2>
          <p className="mt-1 text-sm text-ink/50">{t.governanceReviewHint}</p>
        </div>
        <CheckCircle2 className="text-signal" size={18} />
      </div>
      <input
        aria-label={t.governanceReason}
        className="field-light mt-4 w-full"
        onChange={(event) => setReason(event.target.value)}
        placeholder={t.governanceReason}
        value={reason}
      />
      <div className="mt-4 grid grid-cols-2 gap-4 max-xl:grid-cols-1">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-ink/45">
            {t.memoryAssertions} · {pendingAssertions.length}
          </div>
          <div className="space-y-2">
            {pendingAssertions.length === 0 ? (
              <div className="empty-row">{t.noAssertions}</div>
            ) : (
              pendingAssertions.slice(0, 10).map((item) => (
                <div className="operator-card block" data-tone="brass" key={item.id}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs text-ink/45">{item.id}</span>
                    <span className="text-xs text-brass">{statusLabel(item.status)}</span>
                  </div>
                  <p className="mt-2 text-sm">{item.claim}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className="icon-button"
                      disabled={!reason.trim()}
                      onClick={() => void onDecision("assertion", item.id, "approve")}
                      type="button"
                    >
                      {t.approve}
                    </button>
                    <button
                      className="icon-button"
                      disabled={!reason.trim()}
                      onClick={() => void onDecision("assertion", item.id, "dispute")}
                      type="button"
                    >
                      {t.dispute}
                    </button>
                    <button
                      className="icon-button"
                      disabled={!reason.trim()}
                      onClick={() => void onDecision("assertion", item.id, "reject")}
                      type="button"
                    >
                      {t.reject}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold uppercase text-ink/45">
            {t.skillProposals} · {pendingSkills.length}
          </div>
          <div className="space-y-2">
            {pendingSkills.length === 0 ? (
              <div className="empty-row">{t.noSkillProposals}</div>
            ) : (
              pendingSkills.slice(0, 10).map((item) => (
                <div className="operator-card block" data-tone="violet" key={item.id}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <strong>{item.skill_key}</strong>
                    <span className="font-mono text-xs text-ink/45">
                      {item.definition_hash.slice(0, 12)}
                    </span>
                  </div>
                  <div className="mt-2 font-mono text-xs text-ink/45">{item.id}</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      className="icon-button"
                      disabled={!reason.trim()}
                      onClick={() => void onDecision("skill", item.id, "approve")}
                      type="button"
                    >
                      {t.approve}
                    </button>
                    <button
                      className="icon-button"
                      disabled={!reason.trim()}
                      onClick={() => void onDecision("skill", item.id, "reject")}
                      type="button"
                    >
                      {t.reject}
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="mb-2 mt-4 text-xs font-semibold uppercase text-ink/45">
            {t.skillReleases} · {releases.length}
          </div>
          <div className="flex flex-wrap gap-2">
            {releases.length === 0 ? (
              <div className="empty-row w-full">{t.noSkillReleases}</div>
            ) : (
              releases.slice(0, 10).map((release) => (
                <span className="evidence-chip" key={release.id}>
                  {release.skill_key} v{release.version} · {statusLabel(release.status)}
                </span>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function MemoryObservatory({
  items,
  activeCount,
  t
}: {
  items: MemoryItem[];
  activeCount: number;
  t: Record<string, string>;
}) {
  const insights = useMemo(() => memoryInsights(items), [items]);
  const activityPeak = Math.max(1, ...insights.activity.map((entry) => entry.count));
  const activeLabel = activeCount > 0 ? `${items.length} / ${activeCount}` : formatMetricNumber(items.length);

  return (
    <section className="memory-observatory" aria-labelledby="memory-observatory-title">
      <div className="memory-observatory-head">
        <div>
          <div className="memory-observatory-kicker">Memory telemetry</div>
          <h2 id="memory-observatory-title">{t.memoryObservatory}</h2>
          <p>{t.memoryObservatoryHint}</p>
        </div>
        <div className="memory-observatory-total">
          <span>{t.memoryLoaded}</span>
          <strong>{activeLabel}</strong>
        </div>
      </div>

      {insights.total === 0 ? (
        <div className="memory-observatory-empty">{t.noMemoryItems}</div>
      ) : (
        <div className="memory-observatory-body">
          <div className="memory-capacity-section">
            <div className="memory-visual-heading">
              <div>
                <span>{t.memoryCapacity}</span>
                <strong>
                  {insights.kinds.length} {t.memoryKinds}
                </strong>
              </div>
              <BarChart3 aria-hidden="true" className="text-signal" size={17} />
            </div>

            <div
              className="memory-capacity-rail"
              aria-label={`${t.memoryCapacity}: ${insights.kinds
                .map((item) => `${item.kind} ${item.count}`)
                .join("，")}`}
              role="img"
            >
              {insights.kinds.map((item) => (
                <span
                  key={item.kind}
                  style={{ backgroundColor: item.color, flexGrow: item.count }}
                  title={`${item.kind}: ${item.count} ${t.memoryEntries}`}
                />
              ))}
            </div>

            <div className="memory-kind-list">
              {insights.kinds.map((item) => (
                <div className="memory-kind-row" key={item.kind}>
                  <div className="memory-kind-label">
                    <span aria-hidden="true" style={{ backgroundColor: item.color }} />
                    <strong>{item.kind}</strong>
                  </div>
                  <div aria-hidden="true" className="memory-kind-track">
                    <span style={{ backgroundColor: item.color, width: `${item.share}%` }} />
                  </div>
                  <span className="memory-kind-value">
                    {item.count} <small>{Math.round(item.share)}%</small>
                  </span>
                </div>
              ))}
            </div>
            <p className="memory-visual-note">{t.memoryCapacityHint}</p>
          </div>

          <div className="memory-observatory-side">
            <div className="memory-activity-section">
              <div className="memory-visual-heading">
                <div>
                  <span>{t.memoryActivity}</span>
                  <strong>{t.memoryActivityHint}</strong>
                </div>
                <Activity aria-hidden="true" className="text-brass" size={17} />
              </div>
              {insights.activity.length === 0 ? (
                <div className="memory-activity-empty">{t.memoryNoActivity}</div>
              ) : (
                <div
                  className="memory-activity-bars"
                  aria-label={`${t.memoryActivity}: ${insights.activity
                    .map((item) => `${item.label} ${item.count}`)
                    .join("，")}`}
                  role="img"
                >
                  {insights.activity.map((item) => (
                    <div className="memory-activity-column" key={item.key}>
                      <span
                        aria-hidden="true"
                        className="memory-activity-bar"
                        style={{ height: `${Math.max(2, (item.count / activityPeak) * 100)}%` }}
                        title={`${item.label}: ${item.count} ${t.memoryEntries}`}
                      />
                      <strong>{item.count}</strong>
                      <small>{item.label}</small>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <dl className="memory-quality-grid">
              <div>
                <dt>{t.memoryConfidence}</dt>
                <dd>{formatMemoryRatio(insights.confidence)}</dd>
              </div>
              <div>
                <dt>{t.memoryImportance}</dt>
                <dd>{formatMemoryRatio(insights.importance)}</dd>
              </div>
              <div>
                <dt>{t.memoryReuse}</dt>
                <dd>{formatMetricNumber(insights.usage)}</dd>
              </div>
              <div>
                <dt>{t.memorySources}</dt>
                <dd>{formatMetricNumber(insights.sourceCount)}</dd>
              </div>
            </dl>
          </div>
        </div>
      )}
    </section>
  );
}

function memoryInsights(items: MemoryItem[]): {
  total: number;
  kinds: MemoryKindInsight[];
  activity: MemoryActivityInsight[];
  confidence: number | null;
  importance: number | null;
  usage: number;
  sourceCount: number;
} {
  const kinds = new Map<string, number>();
  const activity = new Map<string, number>();
  const confidence: number[] = [];
  const importance: number[] = [];
  const sources = new Set<string>();
  let usage = 0;

  for (const item of items) {
    kinds.set(item.kind || "unknown", (kinds.get(item.kind || "unknown") ?? 0) + 1);
    const createdAt = new Date(item.created_at);
    if (!Number.isNaN(createdAt.getTime())) {
      const key = createdAt.toISOString().slice(0, 10);
      activity.set(key, (activity.get(key) ?? 0) + 1);
    }
    const confidenceValue = memoryRatioValue(item.confidence);
    const importanceValue = memoryRatioValue(item.importance);
    if (confidenceValue !== null) {
      confidence.push(confidenceValue);
    }
    if (importanceValue !== null) {
      importance.push(importanceValue);
    }
    usage += item.usage_count ?? 0;
    if (item.source_tool) {
      sources.add(item.source_tool);
    }
  }

  const sortedKinds = [...kinds.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([kind, count], index) => ({
      kind,
      count,
      share: items.length ? (count / items.length) * 100 : 0,
      color: memoryChartColor(index)
    }));
  const activityItems = [...activity.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .slice(-7)
    .map(([key, count]) => ({ key, count, label: memoryActivityLabel(key) }));

  return {
    total: items.length,
    kinds: sortedKinds,
    activity: activityItems,
    confidence: averageMemoryRatio(confidence),
    importance: averageMemoryRatio(importance),
    usage,
    sourceCount: sources.size
  };
}

function memoryRatioValue(value: string | undefined): number | null {
  const parsed = Number.parseFloat(value ?? "");
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.max(0, Math.min(1, parsed));
}

function averageMemoryRatio(values: number[]): number | null {
  if (values.length === 0) {
    return null;
  }
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function formatMemoryRatio(value: number | null): string {
  return value === null ? "n/a" : `${Math.round(value * 100)}%`;
}

function memoryActivityLabel(key: string): string {
  const [, month, day] = key.split("-");
  return month && day ? `${Number(month)}/${Number(day)}` : key;
}

function memoryChartColor(index: number): string {
  return ["#5ad6c4", "#d6a24a", "#9d87e8", "#73a7d8", "#e36b4f"][index % 5];
}

function cascadeStyle(index: number): CSSProperties & Record<"--index", number> {
  return { "--index": index };
}

function formatMetricNumber(value: number): string {
  if (value >= 1000) {
    return Intl.NumberFormat("en", { notation: "compact" }).format(value);
  }
  return String(value);
}

function formatAge(seconds: number | null): string {
  if (seconds === null) {
    return "无数据";
  }
  if (seconds < 60) {
    return `${seconds}秒`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}分`;
  }
  return `${Math.floor(seconds / 3600)}时`;
}

function formatPercentValue(value: string | undefined): string {
  if (!value || value === "n/a") {
    return "n/a";
  }
  return value.endsWith("%") ? value : `${value}%`;
}

function metricTone(value: string | undefined): RouteMetric["tone"] {
  const numericValue = Number(value?.replace("%", ""));
  if (Number.isFinite(numericValue) && numericValue < 0) {
    return "danger";
  }
  return "signal";
}

function EvidenceMetric({
  label,
  tone,
  value
}: {
  label: string;
  tone: RouteMetric["tone"];
  value: string;
}) {
  return (
    <div className="operator-card operator-card-compact evidence-metric" data-tone={tone}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SourceIdStrip({
  evidence,
  label,
  sourceMemoryIds
}: {
  evidence: StrategyEvidence | undefined;
  label: string;
  sourceMemoryIds: string[];
}) {
  const ids = [
    evidence?.memory_id ? `memory: ${evidence.memory_id}` : "",
    evidence?.experiment_id ? `experiment: ${evidence.experiment_id}` : "",
    evidence?.backtest_id ? `backtest: ${evidence.backtest_id}` : "",
    evidence?.bitpro_result_id ? `bitpro_result: ${evidence.bitpro_result_id}` : "",
    ...sourceMemoryIds
      .filter((id) => id && id !== evidence?.memory_id)
      .slice(0, 3)
      .map((id) => `memory: ${id}`)
  ].filter(Boolean);
  return (
    <div className="operator-card operator-card-compact evidence-source-card" data-tone="violet">
      <span className="evidence-source-label">{label}</span>
      <div className="evidence-id-strip">
        {ids.length === 0 ? (
          <span>n/a</span>
        ) : (
          ids.map((id) => (
            <span className="evidence-chip" key={id}>
              {id}
            </span>
          ))
        )}
      </div>
    </div>
  );
}

function StructuredReport({
  blocks,
  markdown,
  t
}: {
  blocks: ReportBlock[];
  markdown: string;
  t: Record<string, string>;
}) {
  return (
    <div className="structured-report">
      <div className="flex items-center justify-between gap-3">
        <h4>{t.reportBlocks}</h4>
        <span className="font-mono text-xs text-ink/45">{blocks.length}</span>
      </div>
      <div className="mt-3 grid gap-3">
        {blocks.map((block, index) => (
          <div className="report-card" key={`${block.title ?? block.block_type}-${index}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <span>{block.block_type ?? "block"}</span>
                <strong>{block.title ?? "Report block"}</strong>
              </div>
              {block.severity ? (
                <span className="rounded border border-brass/25 px-2 py-1 text-xs text-brass">
                  {block.severity}
                </span>
              ) : null}
            </div>
            <ReportNotes notes={block.notes} />
            <ReportMetrics metrics={block.metrics} rows={block.rows} />
            <ReportSourceList label={t.sourceRefs} prefix="source" values={block.source_refs} />
            <ReportSourceList label={t.missingData} prefix="missing" values={block.missing} />
          </div>
        ))}
      </div>
      <h4 className="mt-4">{t.markdownFallback}</h4>
      <div className="markdown-report">{renderMarkdown(markdown)}</div>
    </div>
  );
}

function ReportNotes({ notes }: { notes: unknown }) {
  const items = toStringList(notes);
  if (items.length === 0) {
    return null;
  }
  return (
    <ul className="report-note-list">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function ReportMetrics({ metrics, rows }: { metrics: unknown; rows: unknown }) {
  const metricRows = keyValueRows(metrics);
  const dataRows = Array.isArray(rows) ? rows.filter(isRecord).slice(0, 5) : [];
  if (metricRows.length === 0 && dataRows.length === 0) {
    return null;
  }
  return (
    <div className="report-metric-list">
      {metricRows.map((row) => (
        <div key={`${row.label}-${row.value}`}>
          <span>{row.label}</span>
          <strong>{row.value}</strong>
        </div>
      ))}
      {dataRows.map((row, index) => (
        <div key={`row-${index}`}>
          <span>row {index + 1}</span>
          <strong>
            {Object.entries(row)
              .slice(0, 4)
              .map(([key, value]) => `${key}=${stringifyValue(value)}`)
              .join(" / ")}
          </strong>
        </div>
      ))}
    </div>
  );
}

function ReportSourceList({
  label,
  prefix,
  values
}: {
  label: string;
  prefix: string;
  values: unknown;
}) {
  const items = toStringList(values);
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="mt-3">
      <div className="mb-2 text-xs uppercase text-ink/45">{label}</div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span className="evidence-chip" key={item}>
            {prefix}: {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function reportBlocksFromRun(run: AgentRun): ReportBlock[] {
  const reportJson = run.report_json;
  if (!reportJson) {
    return [];
  }
  const blocks = reportJson.report_blocks ?? reportJson.blocks;
  if (!Array.isArray(blocks)) {
    return [];
  }
  return blocks.filter(isRecord).map((block) => ({
    block_type: stringOrUndefined(block.block_type),
    title: stringOrUndefined(block.title),
    severity: stringOrUndefined(block.severity),
    notes: block.notes,
    metrics: block.metrics,
    rows: block.rows,
    missing: block.missing,
    source_refs: block.source_refs
  }));
}

function strategyEvidenceSelection(
  item: StrategyLibraryItem,
  t: Record<string, string>
): EvidenceSelection {
  const best = item.best ?? {};
  const rows = [
    { label: "memory", value: best.memory_id ?? "n/a" },
    { label: "experiment", value: best.experiment_id ?? "n/a" },
    { label: "backtest", value: best.backtest_id ?? "n/a" },
    { label: "bitpro_result", value: best.bitpro_result_id ?? "n/a" },
    { label: t.returnPct, value: formatPercentValue(best.total_return_pct) },
    { label: t.maxDrawdown, value: formatPercentValue(best.max_drawdown_pct) },
    { label: t.score, value: best.score ?? "n/a" },
    { label: t.sourceMemories, value: (item.source_memory_ids ?? []).join(", ") || t.noSourceIds }
  ];
  return {
    title: item.strategy_key,
    rows
  };
}

function traceEvidenceSelection(event: TraceEvent, t: Record<string, string>): EvidenceSelection {
  return {
    title: `${t.traceEvidence}: ${event.tool_name}`,
    rows: [
      { label: "trace", value: event.id ?? "n/a" },
      { label: "tool", value: event.tool_name },
      { label: "status", value: event.status },
      { label: "created_at", value: event.created_at ?? "n/a" },
      { label: "input", value: summarizeRecord(event.input_json) },
      { label: "output", value: summarizeRecord(event.output_json) }
    ]
  };
}

function keyValueRows(value: unknown): Array<{ label: string; value: string }> {
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const label = stringOrUndefined(item.label ?? item.name ?? item.key);
        if (!label) {
          return null;
        }
        return { label, value: stringifyValue(item.value ?? item.amount ?? item.metric ?? "") };
      })
      .filter((item): item is { label: string; value: string } => Boolean(item));
  }
  if (isRecord(value)) {
    return Object.entries(value).map(([label, item]) => ({
      label,
      value: stringifyValue(item)
    }));
  }
  return [];
}

function toStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(stringifyValue).filter((item) => item.length > 0);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function summarizeRecord(value: Record<string, unknown> | undefined): string {
  if (!value) {
    return "n/a";
  }
  const entries = Object.entries(value).slice(0, 4);
  if (entries.length === 0) {
    return "n/a";
  }
  return entries.map(([key, item]) => `${key}=${stringifyValue(item)}`).join(" / ");
}

function stringifyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(stringifyValue).join(", ");
  }
  if (isRecord(value)) {
    return Object.entries(value)
      .slice(0, 4)
      .map(([key, item]) => `${key}=${stringifyValue(item)}`)
      .join(" / ");
  }
  return String(value);
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function renderMarkdown(markdown: string): ReactNode {
  const lines = markdown.split("\n");
  const nodes: ReactNode[] = [];
  let listItems: string[] = [];

  function flushList() {
    if (listItems.length === 0) {
      return;
    }
    const items = listItems;
    listItems = [];
    nodes.push(
      <ul key={`ul-${nodes.length}`}>
        {items.map((item, index) => (
          <li key={`${item}-${index}`}>{renderInlineMarkdown(item)}</li>
        ))}
      </ul>
    );
  }

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      return;
    }
    if (trimmed.startsWith("- ")) {
      listItems.push(trimmed.slice(2));
      return;
    }
    flushList();
    if (trimmed.startsWith("### ")) {
      nodes.push(<h3 key={index}>{renderInlineMarkdown(trimmed.slice(4))}</h3>);
    } else if (trimmed.startsWith("## ")) {
      nodes.push(<h2 key={index}>{renderInlineMarkdown(trimmed.slice(3))}</h2>);
    } else if (trimmed.startsWith("# ")) {
      nodes.push(<h1 key={index}>{renderInlineMarkdown(trimmed.slice(2))}</h1>);
    } else {
      nodes.push(<p key={index}>{renderInlineMarkdown(trimmed)}</p>);
    }
  });
  flushList();
  return nodes.length > 0 ? nodes : <p>n/a</p>;
}

function renderInlineMarkdown(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <span key={index}>{part}</span>;
  });
}

async function consumeAgentStream(
  body: ReadableStream<Uint8Array>,
  onProgress: (message: string) => void
): Promise<AgentRun | null> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalRun: AgentRun | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const dataLine = chunk
        .split("\n")
        .find((line) => line.startsWith("data:"));
      if (!dataLine) {
        continue;
      }
      const payload = JSON.parse(dataLine.slice(5).trim()) as Record<string, unknown>;
      const eventName = String(payload.event ?? "message");
      if (eventName === "final" && isAgentRun(payload.run)) {
        finalRun = payload.run;
      } else if (eventName === "run_completed" && isAgentRun(payload.run)) {
        finalRun = payload.run;
      }
      onProgress(formatAgentEvent(payload));
    }
  }

  return finalRun;
}

function isAgentRun(value: unknown): value is AgentRun {
  return Boolean(
    value &&
      typeof value === "object" &&
      "id" in value &&
      "status" in value &&
      "report_markdown" in value
  );
}

function formatAgentEvent(payload: Record<string, unknown>): string {
  const eventName = String(payload.event ?? "message");
  const toolName = payload.tool_name ? ` ${String(payload.tool_name)}` : "";
  const status = payload.status ? ` ${String(payload.status)}` : "";
  const runId = payload.run_id ? ` ${String(payload.run_id)}` : "";
  return `${eventName}${toolName}${status}${runId}`.trim();
}

export default App;
