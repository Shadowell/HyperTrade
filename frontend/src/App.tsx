import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Cable,
  CheckCircle2,
  Clock3,
  Languages,
  Layers3,
  LineChart,
  Lock,
  MemoryStick,
  Radio,
  RefreshCw,
  Send,
  Sparkles,
  TerminalSquare
} from "lucide-react";
import { CSSProperties, FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type Language = "zh" | "en";

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
};

const copy = {
  zh: {
    product: "HyperTrade",
    harness: "Harness",
    market: "行情摘要",
    providers: "Provider",
    tools: "Tool Call Trace",
    memory: "Memory",
    rag: "RAG",
    risk: "非投资建议",
    login: "登录",
    run: "发起归纳",
    prompt: "请做 OKX 全市场 SWAP 行情归纳",
    okx: "OKX SWAP",
    live: "实时 Tickers",
    report: "Agent Run",
    fallback: "最近更新",
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
    operator: "Operator",
    password: "Password",
    providerMesh: "Provider Mesh",
    dataPlane: "Data Plane",
    agentPlane: "Agent Plane",
    lastSync: "Last Sync",
    overviewLoading: "正在同步运行态"
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
    overviewLoading: "Syncing runtime state"
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
  }
};

function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [prompt, setPrompt] = useState(copy.zh.prompt);
  const [run, setRun] = useState<AgentRun>(seedRun);
  const [overview, setOverview] = useState<HarnessOverview | null>(null);
  const [loginState, setLoginState] = useState<"idle" | "ok" | "error">("idle");
  const [harnessError, setHarnessError] = useState("");
  const [feishuState, setFeishuState] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const t = copy[language];
  const activeOverview = overview ?? previewOverview;
  const defaultProvider =
    activeOverview.providers.find((provider) => provider.default) ?? activeOverview.providers[0];
  const traceEvents =
    run.id !== seedRun.id ? run.trace_events : activeOverview.trace.recent_events.slice(0, 6);

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
        value: activeOverview.tools.some((tool) => tool.requires_approval) ? "Gate" : "Open",
        icon: Lock,
        tone: "danger"
      }
    ],
    [activeOverview, t]
  );

  const refreshOverview = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await fetch("/api/harness/overview", { credentials: "include" });
      if (response.ok) {
        setOverview((await response.json()) as HarnessOverview);
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
  }, []);

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
  }, []);

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
    try {
      const response = await fetch("/api/agent/runs", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt })
      });
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
              <div className="text-xs text-paper/55">Agent Trading Console</div>
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
            <a className="nav-item nav-item-active" href="/harness">
              <TerminalSquare size={16} />
              {t.harness}
            </a>
            <a className="nav-item" href="#market">
              <LineChart size={16} />
              {t.market}
            </a>
            <a className="nav-item" href="#memory">
              <MemoryStick size={16} />
              {t.memory}
            </a>
            <a className="nav-item" href="#rag">
              <Brain size={16} />
              {t.rag}
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
            {language === "zh" ? "EN" : "中文"}
          </button>
        </aside>

        <main className="mx-auto w-full max-w-[1480px] px-8 py-7 max-lg:px-4">
          <header className="grid grid-cols-[1fr_auto] items-start gap-4 border-b border-ink/15 pb-5 max-md:grid-cols-1">
            <div>
              <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase text-brass">
                <span>{t.risk}</span>
                <span className="h-1 w-1 rounded-full bg-brass/45" />
                <span>{overview ? t.lastSync : t.preview}</span>
              </div>
              <h1 className="mt-2 text-4xl font-semibold tracking-tight max-sm:text-3xl">
                Harness
              </h1>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-ink/55">
                <span>{overview ? activeOverview.generated_at : t.preview}</span>
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
                <span>{t.dataPlane}</span>
                <strong>{t.okx}</strong>
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
                  <h2 className="section-title">{t.tools}</h2>
                  <p className="mt-1 text-sm text-ink/50">{t.agentPlane}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button className="icon-button" onClick={refreshOverview} type="button">
                    <RefreshCw className={refreshing ? "animate-spin" : ""} size={16} />
                    <span>{t.refresh}</span>
                  </button>
                  <Cable size={18} className="text-brass" />
                </div>
              </div>
              <div className="mt-5 trace-list">
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
                      {event.status}
                    </span>
                  </div>
                ))}
              </div>

              <div className="mt-6 grid grid-cols-[1.2fr_0.9fr_0.9fr] gap-3 max-md:grid-cols-1">
                <div className="mini-block">
                  <span>{t.providers}</span>
                  <strong>{providerLabel(defaultProvider, t)}</strong>
                </div>
                <div className="mini-block" id="rag">
                  <span>{t.rag}</span>
                  <strong>
                    {activeOverview.rag.document_count} docs / {activeOverview.rag.chunk_count}{" "}
                    chunks
                  </strong>
                </div>
                <div className="mini-block" id="memory">
                  <span>{t.memory}</span>
                  <strong>
                    {activeOverview.memory.active_count} active /{" "}
                    {activeOverview.memory.total_count} total
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
            </div>

            <div className="panel" id="market">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="section-title">{t.market}</h2>
                  <p className="mt-1 text-sm text-ink/50">{t.prompt}</p>
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
              <pre className="report-block">{busy ? `${t.overviewLoading}...` : run.report_markdown}</pre>
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
                        {recentRun.status}
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
              <span>PostgreSQL</span>
              <strong>pgvector / jobs</strong>
            </div>
            <div className="wide-strip">
              <Radio size={16} className="text-signal" />
              <span>Deploy</span>
              <strong>3333 / 3334</strong>
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

function StatusDot({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={`status-dot ${enabled ? "status-dot-on" : "status-dot-off"}`}
      aria-label={enabled ? "configured" : "missing"}
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
    return "n/a";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m`;
  }
  return `${Math.floor(seconds / 3600)}h`;
}

export default App;
