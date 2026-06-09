import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Cable,
  CheckCircle2,
  Clock3,
  CirclePause,
  CirclePlay,
  CopyCheck,
  Languages,
  Layers3,
  LineChart,
  Lock,
  MemoryStick,
  Radio,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  TestTube2,
  TerminalSquare,
  XCircle
} from "lucide-react";
import {
  CSSProperties,
  FormEvent,
  MouseEvent,
  ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState
} from "react";

type Language = "zh" | "en";
type NavSection = "harness" | "market" | "memory" | "rag";

type TraceEvent = {
  id?: string;
  tool_name: string;
  status: string;
  created_at?: string;
};

type AgentRun = {
  id: string;
  status: string;
  report_markdown: string;
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
  created_at: string;
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
    live_write_enabled: boolean;
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
    noIntents: "暂无订单意图",
    agentProgress: "智能体进度",
    reportReader: "报告阅读",
    rawMarkdown: "原始 Markdown",
    memoryManager: "记忆管理",
    source: "来源",
    disable: "禁用",
    noMemoryItems: "暂无记忆",
    selectedMemory: "选中记忆",
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
    auditBoundary: "审计边界"
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
    noIntents: "No order intents",
    agentProgress: "Agent Progress",
    reportReader: "Report Reader",
    rawMarkdown: "Raw Markdown",
    memoryManager: "Memory Manager",
    source: "Source",
    disable: "Disable",
    noMemoryItems: "No memory items",
    selectedMemory: "Selected Memory",
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
    auditBoundary: "Audit Boundary"
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
    live_write_enabled: false,
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

const bitproMcpToolGroups = [
  {
    label: "行情数据",
    tools: "market_symbols / market_klines / market_indicators",
    note: "读取 symbol、K 线、指标与数据新鲜度"
  },
  {
    label: "回测数据",
    tools: "backtest_start_job / backtest_get_job / backtest_get_result",
    note: "启动或读取 BitPro 拥有的回测任务与报告"
  },
  {
    label: "策略生命周期",
    tools: "strategy_generate / strategy_create / strategy_search",
    note: "生成和保存策略草案，供回测与模拟盘验证"
  },
  {
    label: "模拟盘",
    tools: "paper_configure / paper_start / paper_dashboard / paper_events",
    note: "配置、启动和读取模拟盘实例，仍不触发实盘写"
  },
  {
    label: "实盘只读",
    tools: "trading_balance / trading_positions / trading_open_orders",
    note: "默认只做诊断读取，写工具必须独立审批"
  }
] as const;

function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [activeSection, setActiveSection] = useState<NavSection>(() => activeSectionFromHash());
  const [prompt, setPrompt] = useState(copy.zh.prompt);
  const [run, setRun] = useState<AgentRun>(seedRun);
  const [overview, setOverview] = useState<HarnessOverview | null>(null);
  const [loginState, setLoginState] = useState<"idle" | "ok" | "error">("idle");
  const [harnessError, setHarnessError] = useState("");
  const [feishuState, setFeishuState] = useState("");
  const [busy, setBusy] = useState(false);
  const [strategyPrompt, setStrategyPrompt] = useState("研究一个趋势突破策略");
  const [strategyBusy, setStrategyBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [agentProgress, setAgentProgress] = useState<string[]>([]);
  const [marketSymbol, setMarketSymbol] = useState("ETH");
  const [marketCompare, setMarketCompare] = useState("ETH SOL");
  const [marketBar, setMarketBar] = useState("1H");
  const [marketLimit, setMarketLimit] = useState("100");
  const [marketResult, setMarketResult] = useState("");
  const [intentSymbol, setIntentSymbol] = useState("ETH");
  const [intentSide, setIntentSide] = useState<"buy" | "sell">("buy");
  const [intentSize, setIntentSize] = useState("0.01");
  const [intentReason, setIntentReason] = useState("手动审批测试");
  const [liveBusy, setLiveBusy] = useState(false);
  const [memoryItems, setMemoryItems] = useState<MemoryItem[]>([]);
  const [selectedMemoryId, setSelectedMemoryId] = useState("");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [ragQuery, setRagQuery] = useState("risk");
  const [ragHits, setRagHits] = useState<RagHit[]>([]);
  const [providerBusy, setProviderBusy] = useState(false);
  const [showRawMarkdown, setShowRawMarkdown] = useState(false);
  const [backtestSymbol, setBacktestSymbol] = useState("BTC");
  const [backtestBar, setBacktestBar] = useState("1H");
  const [backtestLimit, setBacktestLimit] = useState("100");
  const [backtestSource, setBacktestSource] = useState("sample");
  const [backtestCash, setBacktestCash] = useState("100000");
  const [backtestStrategy, setBacktestStrategy] = useState("momentum_breakout_v1");
  const t = copy[language];
  const activeOverview = overview ?? previewOverview;
  const bitproStatus = activeOverview.bitpro ?? previewOverview.bitpro;
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
        label: t.approval,
        value:
          activeOverview.live_orders.pending_approval_count > 0
            ? String(activeOverview.live_orders.pending_approval_count)
            : activeOverview.tools.some((tool) => tool.requires_approval)
              ? "需审批"
              : "开放",
        icon: Lock,
        tone: "danger"
      }
    ],
    [activeOverview, t]
  );

  const refreshMemoryItems = useCallback(async (query = "") => {
    const path = query ? `/api/memory?query=${encodeURIComponent(query)}` : "/api/memory";
    const response = await fetch(path, { credentials: "include" });
    if (response.ok) {
      const payload = (await response.json()) as { items: MemoryItem[] };
      setMemoryItems(payload.items);
      setSelectedMemoryId((current) => current || payload.items[0]?.id || "");
    }
  }, []);

  const refreshOverview = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await fetch("/api/harness/overview", { credentials: "include" });
      if (response.ok) {
        setOverview((await response.json()) as HarnessOverview);
        await refreshMemoryItems();
        setHarnessError("");
        setLoginState("ok");
        return;
      }
      if (response.status !== 401) {
        setHarnessError(`${response.status}`);
      }
    } finally {
      setRefreshing(false);
    }
  }, [refreshMemoryItems]);

  useEffect(() => {
    let cancelled = false;

    async function hydrateSession() {
      const response = await fetch("/api/auth/me", { credentials: "include" });
      if (!response.ok || cancelled) {
        return;
      }
      setLoginState("ok");
      setRefreshing(true);
      try {
        const overviewResponse = await fetch("/api/harness/overview", {
          credentials: "include"
        });
        if (overviewResponse.ok && !cancelled) {
          setOverview((await overviewResponse.json()) as HarnessOverview);
          await refreshMemoryItems();
          setHarnessError("");
        }
      } finally {
        if (!cancelled) {
          setRefreshing(false);
        }
      }
    }

    void hydrateSession();
    return () => {
      cancelled = true;
    };
  }, [refreshMemoryItems]);

  useEffect(() => {
    function syncActiveSection() {
      setActiveSection(activeSectionFromHash());
    }

    window.addEventListener("hashchange", syncActiveSection);
    return () => window.removeEventListener("hashchange", syncActiveSection);
  }, []);

  function handleNavClick(section: NavSection, event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    setActiveSection(section);
    const target = document.getElementById(section);
    if (target) {
      target.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const username = String(form.get("username") ?? "");
    const password = String(form.get("password") ?? "");
    const response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    if (response.ok) {
      setLoginState("ok");
      await refreshOverview();
      return;
    }
    setLoginState("error");
  }

  async function handleRun() {
    setBusy(true);
    setAgentProgress([]);
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
        }
        await refreshOverview();
        return;
      }
      if (response.ok) {
        setRun((await response.json()) as AgentRun);
        await refreshOverview();
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleSendFeishu() {
    if (run.id === seedRun.id) {
      return;
    }
    const response = await fetch(`/api/reports/${run.id}/send-feishu`, {
      method: "POST",
      credentials: "include"
    });
    if (response.ok) {
      const payload = (await response.json()) as { status: string };
      setFeishuState(payload.status);
    }
  }

  async function handlePaperControl(action: "pause" | "resume" | "close" | "reset") {
    const response = await fetch("/api/paper/control", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    if (response.ok) {
      await refreshOverview();
    }
  }

  async function handleStrategyResearch() {
    setStrategyBusy(true);
    try {
      const response = await fetch("/api/strategy/research", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: strategyPrompt })
      });
      if (response.ok) {
        await refreshOverview();
      }
    } finally {
      setStrategyBusy(false);
    }
  }

  async function handleBacktest() {
    setStrategyBusy(true);
    try {
      const response = await fetch("/api/backtests", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          research_id: activeOverview.strategy_lab.latest_research?.id ?? "",
          strategy_key: backtestStrategy,
          initial_cash: backtestCash,
          symbol: backtestSymbol,
          bar: backtestBar,
          candle_limit: Number.parseInt(backtestLimit, 10) || 100,
          candle_source: backtestSource,
          use_live_candles: backtestSource === "okx"
        })
      });
      if (response.ok) {
        await refreshOverview();
      }
    } finally {
      setStrategyBusy(false);
    }
  }

  async function handleStrategyExperiment() {
    setStrategyBusy(true);
    try {
      const response = await fetch("/api/strategy/experiments", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: strategyPrompt })
      });
      if (response.ok) {
        await refreshOverview();
      }
    } finally {
      setStrategyBusy(false);
    }
  }

  async function handleProviderSwitch(provider: string) {
    setProviderBusy(true);
    try {
      const response = await fetch("/api/harness/provider-selection", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider })
      });
      if (response.ok) {
        await refreshOverview();
      }
    } finally {
      setProviderBusy(false);
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

  async function handleMarketTool(kind: "price" | "candles" | "compare") {
    setMarketResult(`${t.overviewLoading}...`);
    const limit = Number.parseInt(marketLimit, 10) || 100;
    let response: Response;
    if (kind === "price") {
      response = await fetch(`/api/market/ticker/${encodeURIComponent(marketSymbol)}`, {
        credentials: "include"
      });
    } else if (kind === "candles") {
      response = await fetch(
        `/api/market/candles/${encodeURIComponent(marketSymbol)}?bar=${encodeURIComponent(
          marketBar
        )}&limit=${limit}`,
        { credentials: "include" }
      );
    } else {
      response = await fetch("/api/market/compare", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbols: marketCompare.split(/\s+/).filter(Boolean),
          bar: marketBar,
          limit
        })
      });
    }
    if (response.ok) {
      setMarketResult(JSON.stringify(await response.json(), null, 2));
    } else {
      setMarketResult(`API ${response.status}`);
    }
  }

  async function handleCreateIntent() {
    setLiveBusy(true);
    try {
      const response = await fetch("/api/live/order-intents", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: intentSymbol,
          side: intentSide,
          size: intentSize,
          reason: intentReason
        })
      });
      if (response.ok) {
        await refreshOverview();
      }
    } finally {
      setLiveBusy(false);
    }
  }

  async function handleIntentDecision(intentId: string, decision: "approve" | "reject") {
    setLiveBusy(true);
    try {
      const response = await fetch(`/api/live/order-intents/${intentId}/${decision}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: `harness ${decision}` })
      });
      if (response.ok) {
        await refreshOverview();
      }
    } finally {
      setLiveBusy(false);
    }
  }

  async function handleIntentExecute(intentId: string) {
    setLiveBusy(true);
    try {
      const response = await fetch(`/api/live/order-intents/${intentId}/execute`, {
        method: "POST",
        credentials: "include"
      });
      if (response.ok) {
        await refreshOverview();
      }
    } finally {
      setLiveBusy(false);
    }
  }

  async function handleDisableMemory(memoryId: string) {
    const response = await fetch(`/api/memory/${memoryId}`, {
      method: "DELETE",
      credentials: "include"
    });
    if (response.ok) {
      await refreshOverview();
    }
  }

  return (
    <div className="min-h-[100dvh] bg-paper text-ink">
      <div className="fixed inset-0 pointer-events-none bg-[radial-gradient(circle_at_20%_10%,rgba(184,137,59,0.10),transparent_28%),linear-gradient(rgba(17,21,19,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(17,21,19,0.035)_1px,transparent_1px)] bg-[size:auto,28px_28px,28px_28px]" />
      <div className="relative grid min-h-[100dvh] grid-cols-[260px_1fr] max-lg:grid-cols-1">
        <aside className="border-r border-ink/15 bg-ink px-5 py-6 text-paper shadow-[inset_-1px_0_0_rgba(255,255,255,0.04)]">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-md border border-paper/20 bg-paper text-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.55)]">
              <Activity size={19} />
            </div>
            <div>
              <div className="text-base font-semibold tracking-normal">{t.product}</div>
              <div className="text-xs text-paper/55">生产级交易智能体</div>
            </div>
          </div>

          <div className="mt-7 rounded-md border border-paper/10 bg-paper/[0.04] px-3 py-3">
            <div className="flex items-center justify-between text-xs text-paper/55">
              <span>{t.providerMesh}</span>
              <StatusDot enabled={Boolean(defaultProvider?.enabled)} />
            </div>
            <div className="mt-2 truncate font-mono text-xs text-paper/85">
              {providerLabel(defaultProvider, t)}
            </div>
          </div>

          <nav className="mt-8 space-y-2 text-sm">
            <a
              className={navItemClass("harness")}
              href="#harness"
              onClick={(event) => handleNavClick("harness", event)}
            >
              <TerminalSquare size={16} />
              {t.harness}
            </a>
            <a
              className={navItemClass("market")}
              href="#market"
              onClick={(event) => handleNavClick("market", event)}
            >
              <LineChart size={16} />
              {t.market}
            </a>
            <a
              className={navItemClass("memory")}
              href="#memory"
              onClick={(event) => handleNavClick("memory", event)}
            >
              <MemoryStick size={16} />
              {t.routeMemory}
            </a>
            <a
              className={navItemClass("rag")}
              href="#rag"
              onClick={(event) => handleNavClick("rag", event)}
            >
              <Brain size={16} />
              {t.routeRag}
            </a>
          </nav>

          <form className="mt-8 space-y-3" onSubmit={handleLogin}>
            <div className="text-xs uppercase text-paper/45">{t.login}</div>
            <label className="field-group-dark">
              <span>{t.operator}</span>
              <input
                autoComplete="username"
                className="field-dark"
                name="username"
                placeholder="admin"
              />
            </label>
            <label className="field-group-dark">
              <span>{t.password}</span>
              <input
                autoComplete="current-password"
                className="field-dark"
                name="password"
                placeholder="password"
                type="password"
              />
            </label>
            <button className="button-dark" type="submit">
              <Lock size={15} />
              {loginState === "ok" ? "OK" : t.login}
            </button>
            {loginState === "error" ? <div className="text-xs text-red-300">401</div> : null}
          </form>

          <button
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-md border border-paper/15 px-3 py-2 text-sm text-paper/80"
            onClick={() => setLanguage(language === "zh" ? "en" : "zh")}
            type="button"
          >
            <Languages size={16} />
            {language === "zh" ? "英文界面" : "中文界面"}
          </button>
        </aside>

        <main className="mx-auto w-full max-w-[1480px] px-8 py-7 max-lg:px-4">
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
                <strong>{loginState === "ok" ? t.healthy : t.preview}</strong>
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

          <section className="mt-5 grid grid-cols-[1.1fr_0.9fr] gap-5 max-xl:grid-cols-1">
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
                  <div
                    className="trace-row"
                    key={`${event.tool_name}-${event.id ?? index}`}
                    style={cascadeStyle(index)}
                  >
                    <span className="font-mono text-xs text-ink/45">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span className="font-medium">{event.tool_name}</span>
                    <span className="ml-auto rounded border border-signal/30 px-2 py-1 text-xs text-signal">
                      {statusLabel(event.status)}
                    </span>
                  </div>
                ))}
              </div>

              <div className="mt-6 grid grid-cols-[1.2fr_0.9fr_0.9fr] gap-3 max-md:grid-cols-1">
                <div className="mini-block">
                  <span>{t.providers}</span>
                  <strong>{providerLabel(defaultProvider, t)}</strong>
                  <label className="mt-3 grid gap-1.5">
                    <span className="text-[11px] uppercase text-ink/45">
                      {t.switchProvider}
                    </span>
                    <select
                      className="field-light"
                      disabled={providerBusy}
                      onChange={(event) => void handleProviderSwitch(event.target.value)}
                      value={defaultProvider?.name ?? "deepseek"}
                    >
                      {activeOverview.providers.map((provider) => (
                        <option key={provider.name} value={provider.name}>
                          {provider.name} / {statusLabel(provider.key_status)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="mini-block" id="rag">
                  <span>{t.rag}</span>
                  <strong>
                    {activeOverview.rag.document_count} 文档 / {activeOverview.rag.chunk_count} 分片
                  </strong>
                </div>
                <div className="mini-block" id="memory">
                  <span>{t.memory}</span>
                  <strong>
                    {activeOverview.memory.active_count} 可用 /{" "}
                    {activeOverview.memory.total_count} 总数
                  </strong>
                </div>
              </div>

              <div className="mt-6 grid grid-cols-2 gap-3 max-md:grid-cols-1">
                {activeOverview.providers.slice(0, 4).map((provider) => (
                  <div className="status-row" key={provider.name}>
                    <span>{provider.display_name}</span>
                    <span className={provider.enabled ? "text-signal" : "text-danger"}>
                      {provider.enabled ? t.configured : t.missing}
                    </span>
                  </div>
                ))}
              </div>

              <div className="mt-6 rounded-md border border-ink/10 bg-white/70 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <h3 className="section-title">{t.bitproMcp}</h3>
                    <p className="mt-1 text-sm leading-6 text-ink/55">{t.bitproMcpHint}</p>
                  </div>
                  <Cable size={18} className="text-brass" />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-2 max-md:grid-cols-1">
                  <div className="status-row">
                    <span>{t.mcpAdapter}</span>
                    <strong className="font-mono text-xs">
                      {bitproStatus?.adapter ?? "mcp_non_live_lifecycle"}
                    </strong>
                  </div>
                  <div className="status-row">
                    <span>{bitproStatus?.auth_header ?? "X-BitPro-MCP-Token"}</span>
                    <strong
                      className={
                        bitproStatus?.token_configured ? "text-signal" : "text-danger"
                      }
                    >
                      {bitproStatus?.token_configured ? t.mcpTokenReady : t.mcpTokenMissing}
                    </strong>
                  </div>
                  <div className="status-row">
                    <span>{t.mcpApiBase}</span>
                    <strong className="truncate font-mono text-xs">
                      {bitproStatus?.api_base ?? "http://127.0.0.1:8889/api/v2"}
                    </strong>
                  </div>
                  <div className="status-row">
                    <span>{t.auditBoundary}</span>
                    <strong
                      className={
                        bitproStatus?.live_write_enabled ? "text-danger" : "text-signal"
                      }
                    >
                      {bitproStatus?.live_write_enabled
                        ? t.mcpLiveWriteOn
                        : t.mcpLiveWriteOff}
                    </strong>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-2 gap-2 max-sm:grid-cols-1">
                  {[
                    t.mcpCapabilities,
                    t.mcpHealth,
                    t.mcpSelectTool,
                    t.mcpAudit
                  ].map((step) => (
                    <div className="mini-block" key={step}>
                      <span>{t.mcpCallOrder}</span>
                      <strong className="break-words font-mono text-[11px] leading-5">
                        {step}
                      </strong>
                    </div>
                  ))}
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 max-md:grid-cols-1">
                  {bitproMcpToolGroups.map((group) => (
                    <div className="status-row items-start" key={group.label}>
                      <div className="min-w-0">
                        <div className="font-semibold">{group.label}</div>
                        <div className="mt-1 truncate font-mono text-xs text-ink/45">
                          {group.tools}
                        </div>
                        <div className="mt-1 text-xs text-ink/55">{group.note}</div>
                      </div>
                      <span className="shrink-0 rounded border border-brass/25 px-2 py-1 text-xs text-brass">
                        {group.label === t.liveReadOnly ? t.writeBlocked : t.readOnlyDefault}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-6 rounded-md border border-ink/10 bg-paper/60 p-3">
                <div className="grid grid-cols-[1fr_auto] gap-2">
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
                <div className="mt-3 space-y-2">
                  {ragHits.length === 0 ? (
                    <div className="empty-row">{t.rag}</div>
                  ) : (
                    ragHits.slice(0, 4).map((hit) => (
                      <div className="status-row items-start" key={`${hit.source_path}-${hit.chunk_index}`}>
                        <div className="min-w-0">
                          <div className="font-semibold">{hit.title}</div>
                          <div className="truncate font-mono text-xs text-ink/45">
                            {hit.source_path}#{hit.chunk_index}
                          </div>
                          <p className="mt-1 max-h-9 overflow-hidden text-xs text-ink/55">
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

            <div className="panel" id="market">
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
                <button
                  className="button-secondary"
                  disabled={run.id === seedRun.id}
                  onClick={handleSendFeishu}
                  type="button"
                >
                  <Send size={16} />
                  {feishuState || t.sendFeishu}
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
              ) : (
                <div className="markdown-report">
                  {busy ? t.overviewLoading : renderMarkdown(run.report_markdown)}
                </div>
              )}
            </div>
          </section>

          <section className="mt-5 grid grid-cols-[0.9fr_1.1fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-center justify-between gap-4">
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
                      className={`memory-row ${
                        selectedMemory?.id === item.id ? "memory-row-active" : ""
                      }`}
                      key={item.id}
                      onClick={() => setSelectedMemoryId(item.id)}
                      type="button"
                    >
                      <span className="font-mono text-xs text-ink/45">{item.id}</span>
                      <span className="min-w-0 truncate text-left text-sm">{item.content}</span>
                      <span className="rounded border border-ink/10 px-2 py-1 text-xs">
                        {item.kind}
                      </span>
                      {item.usage_count ? (
                        <span className="rounded border border-brass/25 px-2 py-1 text-xs text-brass">
                          {item.usage_count}
                        </span>
                      ) : null}
                    </button>
                  ))
                )}
              </div>
            </div>

            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.selectedMemory}</h2>
                {selectedMemory ? (
                  <button
                    className="icon-button"
                    onClick={() => handleDisableMemory(selectedMemory.id)}
                    type="button"
                  >
                    <XCircle size={14} />
                    {t.disable}
                  </button>
                ) : null}
              </div>
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
          </section>

          <section className="mt-5 grid grid-cols-[0.9fr_1.1fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.paperRuntime}</h2>
                  <p className="mt-1 font-mono text-xs text-ink/45">
                    {activeOverview.paper.session.id}
                  </p>
                </div>
                <span className="rounded border border-signal/25 px-2 py-1 text-xs text-signal">
                  {statusLabel(activeOverview.paper.session.status)}
                </span>
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3 max-sm:grid-cols-1">
                <div className="mini-block">
                  <span>{t.equity}</span>
                  <strong className="font-mono">{activeOverview.paper.session.equity}</strong>
                </div>
                <div className="mini-block">
                  <span>{t.cash}</span>
                  <strong className="font-mono">{activeOverview.paper.session.cash}</strong>
                </div>
                <div className="mini-block">
                  <span>{t.realizedPnl}</span>
                  <strong className="font-mono">
                    {activeOverview.paper.session.realized_pnl}
                  </strong>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  className="button-secondary"
                  onClick={() => handlePaperControl("pause")}
                  type="button"
                >
                  <CirclePause size={16} />
                  {t.pause}
                </button>
                <button
                  className="button-primary"
                  onClick={() => handlePaperControl("resume")}
                  type="button"
                >
                  <CirclePlay size={16} />
                  {t.resume}
                </button>
                <button
                  className="button-secondary"
                  onClick={() => handlePaperControl("close")}
                  type="button"
                >
                  <CopyCheck size={16} />
                  {t.closeAll}
                </button>
                <button
                  className="button-secondary"
                  onClick={() => handlePaperControl("reset")}
                  type="button"
                >
                  <RefreshCw size={16} />
                  {t.reset}
                </button>
              </div>
            </div>

            <div className="panel">
              <div className="grid grid-cols-2 gap-5 max-md:grid-cols-1">
                <div>
                  <h3 className="section-title">{t.positions}</h3>
                  <div className="mt-3 rounded-md border border-ink/10 bg-paper/60 px-3">
                    {activeOverview.paper.positions.length === 0 ? (
                      <div className="empty-row my-3">{t.noPositions}</div>
                    ) : (
                      activeOverview.paper.positions.slice(0, 6).map((position) => (
                        <div className="paper-row" key={position.inst_id}>
                          <span className="font-mono text-xs">{position.inst_id}</span>
                          <span>{sideLabel(position.side)}</span>
                          <span className="font-mono">{position.unrealized_pnl}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
                <div>
                  <h3 className="section-title">{t.fills}</h3>
                  <div className="mt-3 rounded-md border border-ink/10 bg-paper/60 px-3">
                    {activeOverview.paper.recent_fills.length === 0 ? (
                      <div className="empty-row my-3">{t.noFills}</div>
                    ) : (
                      activeOverview.paper.recent_fills.slice(0, 6).map((fill, index) => (
                        <div className="paper-row" key={`${fill.inst_id}-${index}`}>
                          <span className="font-mono text-xs">{fill.inst_id}</span>
                          <span>{sideLabel(fill.side)}</span>
                          <span className="font-mono">{fill.price}</span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section className="mt-5 grid grid-cols-[0.95fr_1.05fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.marketTools}</h2>
                  <p className="mt-1 text-sm text-ink/50">OKX SWAP 确定性行情工具</p>
                </div>
                <Radio size={18} className="text-signal" />
              </div>
              <div className="mt-4 grid grid-cols-[1fr_0.7fr_0.55fr] gap-3 max-md:grid-cols-1">
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.symbol}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setMarketSymbol(event.target.value)}
                    value={marketSymbol}
                  />
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.bar}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setMarketBar(event.target.value)}
                    value={marketBar}
                  />
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.limit}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setMarketLimit(event.target.value)}
                    value={marketLimit}
                  />
                </label>
              </div>
              <label className="mt-3 grid gap-1.5">
                <span className="text-[11px] uppercase text-ink/45">{t.compare}</span>
                <input
                  className="field-light"
                  onChange={(event) => setMarketCompare(event.target.value)}
                  value={marketCompare}
                />
              </label>
              <div className="mt-3 flex flex-wrap gap-2">
                <button className="button-primary" onClick={() => handleMarketTool("price")} type="button">
                  <LineChart size={16} />
                  {t.price}
                </button>
                <button className="button-secondary" onClick={() => handleMarketTool("candles")} type="button">
                  <Activity size={16} />
                  {t.candles}
                </button>
                <button className="button-secondary" onClick={() => handleMarketTool("compare")} type="button">
                  <Layers3 size={16} />
                  {t.compare}
                </button>
              </div>
            </div>

            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.query}</h2>
                <TerminalSquare size={18} className="text-brass" />
              </div>
              <pre className="report-block">{marketResult || "{}"}</pre>
            </div>
          </section>

          <section className="mt-5 grid grid-cols-[0.95fr_1.05fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.liveApproval}</h2>
                  <p className="mt-1 text-sm text-ink/50">
                    {activeOverview.live_orders.pending_approval_count} {t.pending}
                  </p>
                </div>
                <ShieldCheck size={18} className="text-danger" />
              </div>
              <div className="mt-4 grid grid-cols-[1fr_0.7fr_0.8fr] gap-3 max-md:grid-cols-1">
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.symbol}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setIntentSymbol(event.target.value)}
                    value={intentSymbol}
                  />
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.side}</span>
                  <select
                    className="field-light"
                    onChange={(event) => setIntentSide(event.target.value as "buy" | "sell")}
                    value={intentSide}
                  >
                    <option value="buy">买入</option>
                    <option value="sell">卖出</option>
                  </select>
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.size}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setIntentSize(event.target.value)}
                    value={intentSize}
                  />
                </label>
              </div>
              <label className="mt-3 grid gap-1.5">
                <span className="text-[11px] uppercase text-ink/45">{t.reason}</span>
                <input
                  className="field-light"
                  onChange={(event) => setIntentReason(event.target.value)}
                  value={intentReason}
                />
              </label>
              <button
                className="button-primary mt-3"
                disabled={liveBusy}
                onClick={handleCreateIntent}
                type="button"
              >
                {liveBusy ? <RefreshCw className="animate-spin" size={16} /> : <Lock size={16} />}
                {t.createIntent}
              </button>
            </div>

            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.orderIntent}</h2>
                <span className="font-mono text-xs text-ink/45">
                  {activeOverview.live_orders.total_count}
                </span>
              </div>
              <div className="mt-4 space-y-2">
                {activeOverview.live_orders.recent.length === 0 ? (
                  <div className="empty-row">{t.noIntents}</div>
                ) : (
                  activeOverview.live_orders.recent.map((intent) => (
                    <div className="status-row items-start" key={intent.id}>
                      <div className="min-w-0">
                        <div className="font-mono text-xs text-ink/55">{intent.id}</div>
                        <div className="mt-1 text-sm font-semibold">
                          {intent.inst_id} {sideLabel(intent.side)} {intent.size}
                        </div>
                        <div className="mt-1 text-xs text-ink/45">
                          {intent.environment} / {statusLabel(intent.status)}
                        </div>
                        <div className="mt-1 text-xs text-ink/45">
                          风控：{statusLabel(intent.risk_status ?? "pending")}
                          {intent.exchange_order_id ? ` / 订单 ${intent.exchange_order_id}` : ""}
                        </div>
                      </div>
                      {intent.status === "pending_approval" ? (
                        <div className="flex shrink-0 gap-2">
                          <button
                            className="icon-button"
                            disabled={liveBusy}
                            onClick={() => handleIntentDecision(intent.id, "approve")}
                            type="button"
                          >
                            <ShieldCheck size={14} />
                            {t.approve}
                          </button>
                          <button
                            className="icon-button"
                            disabled={liveBusy}
                            onClick={() => handleIntentDecision(intent.id, "reject")}
                            type="button"
                          >
                            <XCircle size={14} />
                            {t.reject}
                          </button>
                        </div>
                      ) : intent.status === "approved" ? (
                        <button
                          className="icon-button"
                          disabled={liveBusy}
                          onClick={() => handleIntentExecute(intent.id)}
                          type="button"
                        >
                          <Send size={14} />
                          {t.execute}
                        </button>
                      ) : (
                        <span className="rounded border border-ink/15 px-2 py-1 text-xs">
                          {statusLabel(intent.status)}
                        </span>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <section className="mt-5 grid grid-cols-[0.9fr_1.1fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.strategyLab}</h2>
                  <p className="mt-1 text-sm text-ink/50">{t.researchPrompt}</p>
                </div>
                <TestTube2 size={18} className="text-brass" />
              </div>
              <textarea
                className="prompt-box"
                onChange={(event) => setStrategyPrompt(event.target.value)}
                value={strategyPrompt}
              />
              <div className="mt-4 grid grid-cols-[1fr_0.75fr_0.75fr] gap-3 max-md:grid-cols-1">
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.strategyKey}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setBacktestStrategy(event.target.value)}
                    value={backtestStrategy}
                  />
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.candleSource}</span>
                  <select
                    className="field-light"
                    onChange={(event) => setBacktestSource(event.target.value)}
                    value={backtestSource}
                  >
                    <option value="sample">样本</option>
                    <option value="okx">OKX</option>
                    <option value="bitpro">BitPro</option>
                  </select>
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.initialCash}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setBacktestCash(event.target.value)}
                    value={backtestCash}
                  />
                </label>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-3 max-md:grid-cols-1">
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.symbol}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setBacktestSymbol(event.target.value)}
                    value={backtestSymbol}
                  />
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.bar}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setBacktestBar(event.target.value)}
                    value={backtestBar}
                  />
                </label>
                <label className="grid gap-1.5">
                  <span className="text-[11px] uppercase text-ink/45">{t.limit}</span>
                  <input
                    className="field-light"
                    onChange={(event) => setBacktestLimit(event.target.value)}
                    value={backtestLimit}
                  />
                </label>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  className="button-primary"
                  disabled={strategyBusy}
                  onClick={handleStrategyResearch}
                  type="button"
                >
                  {strategyBusy ? (
                    <RefreshCw className="animate-spin" size={16} />
                  ) : (
                    <Sparkles size={16} />
                  )}
                  {t.runResearch}
                </button>
                <button
                  className="button-secondary"
                  disabled={strategyBusy}
                  onClick={handleBacktest}
                  type="button"
                >
                  <LineChart size={16} />
                  {t.fullBacktest}
                </button>
                <button
                  className="button-secondary"
                  disabled={strategyBusy}
                  onClick={handleStrategyExperiment}
                  type="button"
                >
                  <TestTube2 size={16} />
                  {t.experiment}
                </button>
              </div>
            </div>

            <div className="panel">
              <div className="grid grid-cols-3 gap-5 max-xl:grid-cols-2 max-md:grid-cols-1">
                <div>
                  <h3 className="section-title">{t.latestResearch}</h3>
                  {activeOverview.strategy_lab.latest_research ? (
                    <div className="mt-3 strategy-card">
                      <span className="font-mono text-xs text-ink/45">
                        {activeOverview.strategy_lab.latest_research.id}
                      </span>
                      <strong>{activeOverview.strategy_lab.latest_research.title}</strong>
                      <p>{activeOverview.strategy_lab.latest_research.prompt}</p>
                      <span className="font-mono text-xs text-brass">
                        {activeOverview.strategy_lab.latest_research.strategy_key}
                      </span>
                    </div>
                  ) : (
                    <div className="empty-row mt-3">{t.noResearch}</div>
                  )}
                </div>
                <div>
                  <h3 className="section-title">{t.latestBacktest}</h3>
                  {activeOverview.strategy_lab.latest_backtest ? (
                    <div className="mt-3 grid gap-3">
                      <div className="status-row">
                        <span className="font-mono text-xs">
                          {activeOverview.strategy_lab.latest_backtest.id}
                        </span>
                        <span className="rounded border border-signal/25 px-2 py-1 text-xs text-signal">
                          {statusLabel(activeOverview.strategy_lab.latest_backtest.status)}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-1">
                        <div className="mini-block">
                          <span>{t.returnPct}</span>
                          <strong className="font-mono">
                            {
                              activeOverview.strategy_lab.latest_backtest.metrics
                                .total_return_pct
                            }
                            %
                          </strong>
                        </div>
                        <div className="mini-block">
                          <span>{t.maxDrawdown}</span>
                          <strong className="font-mono">
                            {
                              activeOverview.strategy_lab.latest_backtest.metrics
                                .max_drawdown_pct
                            }
                            %
                          </strong>
                        </div>
                        <div className="mini-block">
                          <span>{t.trades}</span>
                          <strong className="font-mono">
                            {activeOverview.strategy_lab.latest_backtest.metrics.trade_count}
                          </strong>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="empty-row mt-3">{t.noBacktest}</div>
                  )}
                </div>
                <div>
                  <h3 className="section-title">{t.latestExperiment}</h3>
                  {activeOverview.strategy_lab.latest_experiment ? (
                    <div className="mt-3 strategy-card">
                      <span className="font-mono text-xs text-ink/45">
                        {activeOverview.strategy_lab.latest_experiment.id}
                      </span>
                      <strong>{statusLabel(activeOverview.strategy_lab.latest_experiment.status)}</strong>
                      <p>{activeOverview.strategy_lab.latest_experiment.prompt}</p>
                      <span className="font-mono text-xs text-brass">
                        {activeOverview.strategy_lab.latest_experiment.backtest_id}
                      </span>
                    </div>
                  ) : (
                    <div className="empty-row mt-3">{t.latestExperiment}</div>
                  )}
                </div>
              </div>
            </div>
          </section>

          <section className="mt-5 grid grid-cols-[0.95fr_1.05fr] gap-5 max-xl:grid-cols-1">
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
                    <div className="run-row" key={recentRun.id} style={cascadeStyle(index)}>
                      <span className="font-mono text-xs text-ink/55">{recentRun.id}</span>
                      <span className="min-w-0 truncate text-sm">{recentRun.prompt}</span>
                      <span className="rounded border border-signal/25 px-2 py-1 text-xs text-signal">
                        {statusLabel(recentRun.status)}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <section className="mt-5 grid grid-cols-[1.5fr_1fr_0.8fr] gap-5 max-xl:grid-cols-1">
            <div className="wide-strip">
              <AlertTriangle size={16} className="text-danger" />
              <span>{t.severe}</span>
              <strong>Feishu Webhook</strong>
            </div>
            <div className="wide-strip">
              <Brain size={16} className="text-brass" />
              <span>{t.evals}</span>
              <strong>
                {statusLabel(activeOverview.evals.status)} / {activeOverview.evals.case_count}
              </strong>
            </div>
            <div className="wide-strip">
              <Radio size={16} className="text-signal" />
              <span>部署端口</span>
              <strong>3333 / 3334</strong>
            </div>
          </section>
          <section className="mt-5 panel">
            <div className="flex items-center justify-between gap-4">
              <h2 className="section-title">{t.evals}</h2>
              <span className="font-mono text-xs text-ink/45">{statusLabel(activeOverview.evals.mode)}</span>
            </div>
            <div className="mt-4 grid grid-cols-5 gap-2 max-xl:grid-cols-2 max-sm:grid-cols-1">
              {activeOverview.evals.cases.map((item) => (
                <div className="mini-block" key={item.name}>
                  <span>{item.name}</span>
                  <strong className={item.status === "passed" ? "text-signal" : "text-danger"}>
                    {statusLabel(item.status)}
                  </strong>
                </div>
              ))}
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

function sideLabel(side: string | undefined): string {
  const normalized = (side ?? "").toLowerCase();
  const labels: Record<string, string> = {
    buy: "买入",
    long: "多头",
    sell: "卖出",
    short: "空头"
  };
  return labels[normalized] ?? side ?? "未知";
}

function activeSectionFromHash(): NavSection {
  if (typeof window === "undefined") {
    return "harness";
  }
  const section = window.location.hash.replace("#", "");
  if (section === "market" || section === "memory" || section === "rag") {
    return section;
  }
  return "harness";
}

function StatusDot({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={`status-dot ${enabled ? "status-dot-on" : "status-dot-off"}`}
      aria-label={enabled ? "已配置" : "未配置"}
    />
  );
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
