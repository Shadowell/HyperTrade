import {
  Activity,
  AlertTriangle,
  Bot,
  Brain,
  Cable,
  CheckCircle2,
  Languages,
  LineChart,
  Lock,
  MemoryStick,
  Radio,
  RefreshCw,
  Send,
  ShieldCheck,
  TerminalSquare
} from "lucide-react";
import { FormEvent, useMemo, useState } from "react";

type Language = "zh" | "en";

type TraceEvent = {
  tool_name: string;
  status: string;
};

type AgentRun = {
  id: string;
  status: string;
  report_markdown: string;
  trace_events: TraceEvent[];
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
    report: "按需报告",
    fallback: "REST 降级",
    approval: "实盘审批",
    severe: "严重异常",
    sendFeishu: "转发飞书"
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
    report: "On Demand",
    fallback: "REST Fallback",
    approval: "Live Approval",
    severe: "Severe Alerts",
    sendFeishu: "Send Feishu"
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

function App() {
  const [language, setLanguage] = useState<Language>("zh");
  const [prompt, setPrompt] = useState(copy.zh.prompt);
  const [run, setRun] = useState<AgentRun>(seedRun);
  const [loginState, setLoginState] = useState<"idle" | "ok" | "error">("idle");
  const [busy, setBusy] = useState(false);
  const t = copy[language];

  const metrics = useMemo(
    () => [
      { label: t.live, value: "WS", icon: Radio, tone: "signal" },
      { label: t.report, value: "Manual", icon: Bot, tone: "brass" },
      { label: t.fallback, value: "Armed", icon: ShieldCheck, tone: "night" },
      { label: t.approval, value: "Gate", icon: Lock, tone: "danger" }
    ],
    [t]
  );

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
    setLoginState(response.ok ? "ok" : "error");
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
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="grid min-h-screen grid-cols-[240px_1fr] max-lg:grid-cols-1">
        <aside className="border-r border-ink/15 bg-ink px-5 py-6 text-paper">
          <div className="flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-md border border-paper/20 bg-paper text-ink">
              <Activity size={19} />
            </div>
            <div>
              <div className="text-base font-semibold tracking-normal">{t.product}</div>
              <div className="text-xs text-paper/55">Agent Trading OS</div>
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

          <form className="mt-8 space-y-2" onSubmit={handleLogin}>
            <div className="text-xs uppercase text-paper/45">{t.login}</div>
            <input
              autoComplete="username"
              className="field-dark"
              name="username"
              placeholder="admin"
            />
            <input
              autoComplete="current-password"
              className="field-dark"
              name="password"
              placeholder="password"
              type="password"
            />
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

        <main className="px-8 py-7 max-lg:px-4">
          <header className="flex items-start justify-between gap-4 border-b border-ink/15 pb-5">
            <div>
              <div className="text-xs font-semibold uppercase text-brass">{t.risk}</div>
              <h1 className="mt-1 text-3xl font-semibold tracking-normal">Harness</h1>
            </div>
            <div className="flex items-center gap-2 rounded-md border border-ink/15 bg-white px-3 py-2 text-sm">
              <CheckCircle2 className="text-signal" size={17} />
              {t.okx}
            </div>
          </header>

          <section className="mt-6 grid grid-cols-4 gap-3 max-xl:grid-cols-2 max-sm:grid-cols-1">
            {metrics.map((metric) => (
              <div className="panel" key={metric.label}>
                <div className="flex items-center justify-between">
                  <metric.icon className={`metric-${metric.tone}`} size={18} />
                  <span className="font-mono text-xs text-ink/45">{metric.value}</span>
                </div>
                <div className="mt-5 text-sm text-ink/60">{metric.label}</div>
              </div>
            ))}
          </section>

          <section className="mt-5 grid grid-cols-[1.1fr_0.9fr] gap-5 max-xl:grid-cols-1">
            <div className="panel">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.tools}</h2>
                <Cable size={18} className="text-brass" />
              </div>
              <div className="mt-5 space-y-3">
                {run.trace_events.map((event, index) => (
                  <div className="trace-row" key={`${event.tool_name}-${index}`}>
                    <span className="font-mono text-xs text-ink/45">0{index + 1}</span>
                    <span className="font-medium">{event.tool_name}</span>
                    <span className="ml-auto rounded border border-signal/30 px-2 py-1 text-xs text-signal">
                      {event.status}
                    </span>
                  </div>
                ))}
              </div>

              <div className="mt-6 grid grid-cols-3 gap-3 max-md:grid-cols-1">
                <div className="mini-block">
                  <span>{t.providers}</span>
                  <strong>DeepSeek V4 Flash</strong>
                </div>
                <div className="mini-block" id="rag">
                  <span>{t.rag}</span>
                  <strong>pgvector / Qwen</strong>
                </div>
                <div className="mini-block" id="memory">
                  <span>{t.memory}</span>
                  <strong>Auto + Audit</strong>
                </div>
              </div>
            </div>

            <div className="panel" id="market">
              <div className="flex items-center justify-between gap-4">
                <h2 className="section-title">{t.market}</h2>
                <AlertTriangle size={18} className="text-danger" />
              </div>
              <textarea
                className="mt-5 min-h-24 w-full resize-none rounded-md border border-ink/15 bg-white p-3 text-sm outline-none focus:border-brass"
                onChange={(event) => setPrompt(event.target.value)}
                value={prompt}
              />
              <div className="mt-3 flex gap-2">
                <button className="button-primary" disabled={busy} onClick={handleRun} type="button">
                  {busy ? <RefreshCw className="animate-spin" size={16} /> : <Bot size={16} />}
                  {t.run}
                </button>
                <button className="button-secondary" type="button">
                  <Send size={16} />
                  {t.sendFeishu}
                </button>
              </div>
              <pre className="report-block">{run.report_markdown}</pre>
            </div>
          </section>

          <section className="mt-5 grid grid-cols-3 gap-5 max-xl:grid-cols-1">
            <div className="wide-strip">
              <span>{t.severe}</span>
              <strong>Feishu Webhook</strong>
            </div>
            <div className="wide-strip">
              <span>PostgreSQL</span>
              <strong>pgvector / jobs</strong>
            </div>
            <div className="wide-strip">
              <span>Deploy</span>
              <strong>3333 / 3334</strong>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}

export default App;
