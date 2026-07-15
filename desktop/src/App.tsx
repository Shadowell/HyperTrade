import {
  AlertCircle,
  ChevronDown,
  Database,
  Grip,
  Minus,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Wifi,
  WifiOff,
  X
} from "lucide-react";
import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  checkConnection,
  DEFAULT_API_BASE,
  hideWindow,
  runAgent,
  setPanelOpen,
  startDragging,
  type AgentStreamEvent
} from "./bridge";
import { applyAgentEvent, eventActivity, type ChatMessage } from "./conversation";

type RuntimeStatus = "connecting" | "online" | "offline" | "running" | "error";

const welcomeMessage: ChatMessage = {
  id: "welcome",
  role: "assistant",
  text: "告诉我你想验证的市场、策略或风险问题。我会通过 HyperTrade Mission Runtime 返回有证据边界的结论。",
  state: "complete"
};

function App() {
  const browserPreview = !window.__TAURI_INTERNALS__;
  const [panelOpen, setPanelOpenState] = useState(browserPreview);
  const [status, setStatus] = useState<RuntimeStatus>("connecting");
  const [apiBase, setApiBase] = useState(
    () => window.localStorage?.getItem("hypertrade.bot.apiBase") || DEFAULT_API_BASE
  );
  const [draftBase, setDraftBase] = useState(apiBase);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [activity, setActivity] = useState("正在连接 HyperTrade");
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeMessage]);
  const messageListRef = useRef<HTMLDivElement>(null);

  const statusLabel = useMemo(() => {
    if (status === "running") return "Mission 运行中";
    if (status === "online") return "服务已连接";
    if (status === "connecting") return "正在连接";
    if (status === "error") return "运行异常";
    return "服务离线";
  }, [status]);

  useEffect(() => {
    void refreshConnection(apiBase);
  }, [apiBase]);

  useEffect(() => {
    const node = messageListRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages, activity]);

  async function refreshConnection(base: string) {
    setStatus("connecting");
    setActivity("正在连接 HyperTrade");
    try {
      await checkConnection(base);
      setStatus("online");
      setActivity("Mission Runtime 就绪");
    } catch {
      setStatus("offline");
      setActivity("无法连接服务，请检查地址");
    }
  }

  async function togglePanel() {
    const next = !panelOpen;
    setPanelOpenState(next);
    await setPanelOpen(next);
  }

  async function closePanel() {
    setSettingsOpen(false);
    setPanelOpenState(false);
    await setPanelOpen(false);
  }

  function saveEndpoint() {
    const normalized = draftBase.trim().replace(/\/$/, "");
    if (!normalized) return;
    window.localStorage?.setItem("hypertrade.bot.apiBase", normalized);
    setApiBase(normalized);
    setSettingsOpen(false);
  }

  async function sendPrompt() {
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt || status === "running") return;

    const messageSeed = createId("message");
    const assistantId = `${messageSeed}_assistant`;
    setMessages((items) => [
      ...items,
      { id: `${messageSeed}_user`, role: "user", text: cleanPrompt, state: "complete" },
      { id: assistantId, role: "assistant", text: "", state: "streaming" }
    ]);
    setPrompt("");
    setStatus("running");
    setActivity("正在建立 Mission");

    try {
      await runAgent(apiBase, cleanPrompt, createId("desktop_run"), (event) => {
        handleAgentEvent(assistantId, event);
      });
      setStatus("online");
      setActivity("研究完成");
    } catch (error) {
      const text = error instanceof Error ? error.message : String(error);
      handleAgentEvent(assistantId, { event: "error", error: text });
      setStatus("error");
      setActivity("运行失败，请检查服务连接");
    }
  }

  function handleAgentEvent(assistantId: string, event: AgentStreamEvent) {
    setActivity(eventActivity(event));
    setMessages((items) =>
      items.map((message) =>
        message.id === assistantId ? applyAgentEvent(message, event) : message
      )
    );
    if (event.event === "error") {
      setStatus("error");
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendPrompt();
    }
  }

  if (!panelOpen) {
    return (
      <main className="collapsed-shell" aria-label="HyperTrade 悬浮助手">
        <button
          className="bot-orb"
          data-status={status}
          aria-label="打开 HyperTrade Bot"
          onClick={() => void togglePanel()}
        >
          <span className="signal-orbit" aria-hidden="true" />
          <img src="/hypertrade-orb.png" alt="" />
          <span className="orb-status" aria-hidden="true" />
        </button>
        <button
          className="orb-drag"
          aria-label="拖动悬浮助手"
          onMouseDown={(event) => {
            event.preventDefault();
            void startDragging();
          }}
        >
          <Grip size={10} strokeWidth={1.8} />
        </button>
      </main>
    );
  }

  return (
    <main className="desktop-stage">
      <section className="bot-panel" aria-label="HyperTrade Mission 助手">
        <div
          className="drag-rail"
          onMouseDown={(event) => {
            if (event.button === 0) void startDragging();
          }}
        >
          <span />
        </div>

        <header className="panel-header">
          <div className="identity">
            <div className="avatar-mini" data-status={status}>
              <img src="/hypertrade-orb.png" alt="HyperTrade 产品图标" />
            </div>
            <div>
              <div className="eyebrow">HYPERTRADE · MISSION</div>
              <h1>研究助手</h1>
            </div>
          </div>
          <div className="window-actions">
            <button
              className="icon-action"
              aria-label="连接设置"
              aria-pressed={settingsOpen}
              onClick={() => setSettingsOpen((open) => !open)}
            >
              <Settings size={16} />
            </button>
            <button className="icon-action" aria-label="收起" onClick={() => void closePanel()}>
              <Minus size={17} />
            </button>
            <button className="icon-action" aria-label="隐藏" onClick={() => void hideWindow()}>
              <X size={17} />
            </button>
          </div>
        </header>

        <div className="runtime-strip" data-status={status}>
          <span className="runtime-dot" />
          <span>{statusLabel}</span>
          <span className="runtime-activity">{activity}</span>
        </div>

        {settingsOpen && (
          <section className="settings-card" aria-label="服务连接设置">
            <div className="settings-title">
              <div>
                <span>服务连接</span>
                <strong>HyperTrade API</strong>
              </div>
              {status === "online" ? <Wifi size={17} /> : <WifiOff size={17} />}
            </div>
            <label htmlFor="api-base">服务器地址</label>
            <input
              id="api-base"
              value={draftBase}
              onChange={(event) => setDraftBase(event.target.value)}
              placeholder="http://127.0.0.1:3334"
              spellCheck={false}
            />
            <div className="settings-actions">
              <button onClick={() => setSettingsOpen(false)}>取消</button>
              <button className="save-endpoint" onClick={saveEndpoint}>保存并连接</button>
            </div>
            {!draftBase.startsWith("https://") && (
              <p className="transport-warning">
                <AlertCircle size={13} /> 当前连接未使用 HTTPS，仅建议在可信网络中使用。
              </p>
            )}
          </section>
        )}

        <div className="message-list" ref={messageListRef} aria-live="polite">
          <div className="session-marker">
            <span>受治理的研究会话</span>
            <ShieldCheck size={14} />
          </div>
          {messages.map((message) => (
            <article
              className={`message message-${message.role}`}
              data-state={message.state}
              key={message.id}
            >
              <div className="message-label">
                {message.role === "user" ? "你的问题" : "HT 结论"}
                {message.state === "streaming" && <span className="typing-mark">分析中</span>}
              </div>
              <div className="message-copy">
                {message.text || <span className="thinking-placeholder">正在读取可验证证据…</span>}
              </div>
              {typeof message.evidenceCount === "number" && (
                <div className="evidence-chip">
                  <Database size={13} /> 已验证证据 {message.evidenceCount}
                </div>
              )}
              {message.unknowns && message.unknowns.length > 0 && (
                <div className="unknown-block">
                  <span>尚未确认</span>
                  {message.unknowns.map((unknown) => <p key={unknown}>{unknown}</p>)}
                </div>
              )}
            </article>
          ))}
        </div>

        <footer className="composer-wrap">
          <div className="composer">
            <textarea
              aria-label="研究问题"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="问市场、策略或风险…"
              rows={2}
              disabled={status === "running"}
            />
            <button
              className="send-button"
              aria-label="发送研究问题"
              disabled={!prompt.trim() || status === "running"}
              onClick={() => void sendPrompt()}
            >
              {status === "running" ? <Sparkles size={18} /> : <Send size={18} />}
            </button>
          </div>
          <div className="safety-note">
            <ShieldCheck size={12} /> 仅发起受治理研究，交易密钥与执行权限不进入桌面端
            <ChevronDown size={12} aria-hidden="true" />
          </div>
        </footer>
      </section>
    </main>
  );
}

function createId(prefix: string) {
  const random = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
  return `${prefix}_${random}`;
}

export default App;
