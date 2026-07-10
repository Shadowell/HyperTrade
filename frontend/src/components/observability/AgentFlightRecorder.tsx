import {
  Activity,
  BrainCircuit,
  Cpu,
  Database,
  EyeOff,
  GitBranch,
  ShieldCheck,
  TimerReset,
  Wrench
} from "lucide-react";
import { CSSProperties, useMemo, useState } from "react";

export type TokenUsage = {
  input_tokens?: number;
  output_tokens?: number;
  cached_input_tokens?: number;
  reasoning_tokens?: number;
  total_tokens?: number;
  request_count?: number;
  reported_requests?: number;
  unreported_requests?: number;
  reported?: boolean;
};

export type FlightRecorderEvent = {
  id: string;
  sequence: number;
  category: "graph" | "model" | "tool" | "memory" | "policy";
  name: string;
  status: string;
  created_at: string;
  offset_ms: number;
  duration_ms: number;
  summary: string;
  usage?: TokenUsage;
  memory_ids?: string[];
};

type MemoryTraceItem = {
  id: string;
  kind: string;
  content_preview: string;
  source_run_id: string;
  source_tool: string;
  importance: string;
  confidence: string;
  usage_count: number;
  created_at: string;
};

export type RunObservability = {
  schema_version: string;
  run: {
    id: string;
    status: string;
    provider: string;
    model: string;
    duration_ms: number;
    started_at: string;
    completed_at: string;
  };
  usage: TokenUsage;
  models: {
    request_count: number;
    calls: Array<Record<string, unknown>>;
  };
  tools: {
    call_count?: number;
    error_count?: number;
    total_execution_ms?: number;
    slowest?: { tool_name?: string; execution_ms?: number } | null;
  };
  memory: {
    read_count?: number;
    write_count?: number;
    read_ids?: string[];
    write_ids?: string[];
    items?: MemoryTraceItem[];
  };
  timeline: FlightRecorderEvent[];
  categories: Record<string, number>;
  safety: {
    private_reasoning_stored: boolean;
    secrets_redacted: boolean;
    payload_mode: string;
  };
};

type Props = {
  data: RunObservability | null;
  language: "zh" | "en";
  loading?: boolean;
};

const labels = {
  zh: {
    eyebrow: "Agent Flight Recorder",
    title: "运行黑匣子",
    subtitle: "按真实顺序检查模型、工具、治理与 Memory 事件",
    empty: "运行或打开一条 Agent 记录后，这里会显示完整飞行数据。",
    provider: "模型路由",
    elapsed: "总耗时",
    tokens: "Token",
    requests: "模型请求",
    tools: "工具时间",
    memory: "Memory",
    input: "Input",
    output: "Output",
    cached: "Cached input",
    reasoning: "Reasoning",
    usageMissing: "Provider 未返回 usage，不做估算",
    tokenHint: "Cached 属于 Input 子集，Reasoning 属于 Output 子集",
    timeline: "执行时间带",
    evidence: "事件检查",
    select: "选择时间带中的事件查看安全摘要",
    offset: "偏移",
    duration: "耗时",
    memoryLinks: "关联 Memory",
    noMemory: "此事件没有 Memory 关联",
    privateSafe: "未存储私有思维链",
    redacted: "密钥已脱敏",
    summaryOnly: "摘要投影",
    reads: "读",
    writes: "写"
  },
  en: {
    eyebrow: "Agent Flight Recorder",
    title: "Run flight recorder",
    subtitle: "Inspect model, tool, policy, and Memory events in execution order",
    empty: "Run or open an Agent record to inspect its flight data.",
    provider: "Model route",
    elapsed: "Elapsed",
    tokens: "Tokens",
    requests: "Model calls",
    tools: "Tool time",
    memory: "Memory",
    input: "Input",
    output: "Output",
    cached: "Cached input",
    reasoning: "Reasoning",
    usageMissing: "Provider did not report usage; no estimate shown",
    tokenHint: "Cached is a subset of Input; Reasoning is a subset of Output",
    timeline: "Execution tape",
    evidence: "Event inspector",
    select: "Select an event from the tape to inspect its safe summary",
    offset: "Offset",
    duration: "Duration",
    memoryLinks: "Linked Memory",
    noMemory: "No Memory is linked to this event",
    privateSafe: "Private reasoning not stored",
    redacted: "Secrets redacted",
    summaryOnly: "Summary projection",
    reads: "read",
    writes: "write"
  }
} as const;

const categoryMeta = {
  graph: { label: "GRAPH", Icon: GitBranch },
  model: { label: "MODEL", Icon: BrainCircuit },
  tool: { label: "TOOL", Icon: Wrench },
  memory: { label: "MEM", Icon: Database },
  policy: { label: "POLICY", Icon: ShieldCheck }
} as const;

export function AgentFlightRecorder({ data, language, loading = false }: Props) {
  const t = labels[language];
  const [selectedEventId, setSelectedEventId] = useState("");

  const selectedEvent =
    data?.timeline.find((event) => event.id === selectedEventId) ??
    data?.timeline.find((event) => event.category === "model") ??
    data?.timeline[0] ??
    null;
  const maxEventDuration = useMemo(
    () => Math.max(1, ...(data?.timeline.map((event) => event.duration_ms) ?? [1])),
    [data?.timeline]
  );
  const memoryById = useMemo(
    () => new Map((data?.memory.items ?? []).map((item) => [item.id, item])),
    [data?.memory.items]
  );

  return (
    <section className="flight-recorder" aria-busy={loading} aria-label={t.eyebrow}>
      <div className="flight-recorder-header">
        <div className="flight-recorder-mark" aria-hidden="true">
          <Activity size={18} />
        </div>
        <div className="min-w-0">
          <div className="flight-recorder-eyebrow">{t.eyebrow}</div>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2>{t.title}</h2>
            <span className="flight-recorder-subtitle">{t.subtitle}</span>
          </div>
        </div>
        <div className="flight-recorder-run-state">
          <span className={`flight-state-dot flight-state-${data?.run.status ?? "idle"}`} />
          <span>{loading ? "streaming" : data?.run.status ?? "idle"}</span>
          <strong>{data?.run.id ?? "no run selected"}</strong>
        </div>
      </div>

      {!data ? (
        <div className="flight-recorder-empty">
          <Cpu size={24} />
          <p>{loading ? "Recording agent events…" : t.empty}</p>
        </div>
      ) : (
        <>
          <div className="flight-metric-grid">
            <FlightMetric
              label={t.provider}
              value={`${data.run.provider || "n/a"}${data.run.model ? ` / ${data.run.model}` : ""}`}
            />
            <FlightMetric label={t.elapsed} value={formatDuration(data.run.duration_ms)} />
            <FlightMetric
              label={t.tokens}
              value={data.usage.reported ? formatNumber(data.usage.total_tokens) : "n/a"}
            />
            <FlightMetric label={t.requests} value={formatNumber(data.models.request_count)} />
            <FlightMetric
              label={t.tools}
              value={formatDuration(data.tools.total_execution_ms ?? 0)}
            />
            <FlightMetric
              label={t.memory}
              value={`${data.memory.read_count ?? 0} ${t.reads} · ${data.memory.write_count ?? 0} ${t.writes}`}
            />
          </div>

          <TokenLedger usage={data.usage} labels={t} />

          <div className="flight-recorder-body">
            <div className="flight-tape">
              <div className="flight-section-label">
                <span>{t.timeline}</span>
                <span>{data.timeline.length} events</span>
              </div>
              <div className="flight-tape-list">
                {data.timeline.map((event, index) => {
                  const meta = categoryMeta[event.category];
                  const durationWidth = Math.max(3, (event.duration_ms / maxEventDuration) * 100);
                  const rowStyle = {
                    "--event-index": index,
                    "--duration-width": `${durationWidth}%`
                  } as CSSProperties;
                  return (
                    <button
                      className={`flight-event flight-event-${event.category} ${
                        selectedEvent?.id === event.id ? "flight-event-selected" : ""
                      }`}
                      key={event.id}
                      onClick={() => setSelectedEventId(event.id)}
                      style={rowStyle}
                      type="button"
                    >
                      <span className="flight-event-sequence">
                        {String(event.sequence).padStart(2, "0")}
                      </span>
                      <span className="flight-event-icon">
                        <meta.Icon size={14} />
                      </span>
                      <span className="flight-event-copy">
                        <span className="flight-event-line">
                          <span className="flight-event-category">{meta.label}</span>
                          <strong>{event.name}</strong>
                        </span>
                        <span>{event.summary}</span>
                        <i aria-hidden="true" />
                      </span>
                      <span className="flight-event-time">
                        <strong>+{formatDuration(event.offset_ms)}</strong>
                        <span>{event.duration_ms ? formatDuration(event.duration_ms) : "—"}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <aside className="flight-inspector" aria-live="polite">
              <div className="flight-section-label">
                <span>{t.evidence}</span>
                <EyeOff size={14} />
              </div>
              {selectedEvent ? (
                <>
                  <div className={`flight-inspector-kind flight-inspector-${selectedEvent.category}`}>
                    {categoryMeta[selectedEvent.category].label}
                  </div>
                  <h3>{selectedEvent.name}</h3>
                  <p>{selectedEvent.summary}</p>
                  <dl className="flight-inspector-facts">
                    <div>
                      <dt>{t.offset}</dt>
                      <dd>+{formatDuration(selectedEvent.offset_ms)}</dd>
                    </div>
                    <div>
                      <dt>{t.duration}</dt>
                      <dd>{selectedEvent.duration_ms ? formatDuration(selectedEvent.duration_ms) : "—"}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>{selectedEvent.status}</dd>
                    </div>
                  </dl>
                  {selectedEvent.category === "model" ? (
                    <div className="flight-inspector-usage">
                      <TokenValue label={t.input} value={selectedEvent.usage?.input_tokens} />
                      <TokenValue label={t.output} value={selectedEvent.usage?.output_tokens} />
                      <TokenValue label={t.cached} value={selectedEvent.usage?.cached_input_tokens} />
                      <TokenValue label={t.reasoning} value={selectedEvent.usage?.reasoning_tokens} />
                    </div>
                  ) : null}
                  <div className="flight-memory-links">
                    <span>{t.memoryLinks}</span>
                    {selectedEvent.memory_ids?.length ? (
                      selectedEvent.memory_ids.map((id) => {
                        const item = memoryById.get(id);
                        return (
                          <div key={id}>
                            <strong>{id}</strong>
                            <small>{item ? `${item.kind} · ${item.content_preview}` : "audited memory"}</small>
                          </div>
                        );
                      })
                    ) : (
                      <p>{t.noMemory}</p>
                    )}
                  </div>
                </>
              ) : (
                <p>{t.select}</p>
              )}
            </aside>
          </div>

          <div className="flight-safety-strip">
            <span><EyeOff size={13} /> {t.privateSafe}</span>
            <span><ShieldCheck size={13} /> {t.redacted}</span>
            <span><TimerReset size={13} /> {t.summaryOnly}</span>
          </div>
        </>
      )}
    </section>
  );
}

function TokenLedger({
  usage,
  labels: t
}: {
  usage: TokenUsage;
  labels: (typeof labels)["zh"] | (typeof labels)["en"];
}) {
  const input = usage.input_tokens ?? 0;
  const output = usage.output_tokens ?? 0;
  const primaryTotal = Math.max(1, input + output);
  const inputWidth = `${(input / primaryTotal) * 100}%`;
  const outputWidth = `${(output / primaryTotal) * 100}%`;
  return (
    <div className="token-ledger">
      <div className="token-ledger-head">
        <span>Token ledger</span>
        <span>{usage.reported ? t.tokenHint : t.usageMissing}</span>
      </div>
      <div className={`token-primary-bar ${usage.reported ? "" : "token-primary-missing"}`}>
        <span className="token-input" style={{ width: inputWidth }} />
        <span className="token-output" style={{ width: outputWidth }} />
      </div>
      <div className="token-ledger-values">
        <TokenValue label={t.input} value={usage.reported ? input : undefined} />
        <TokenValue label={t.output} value={usage.reported ? output : undefined} />
        <TokenValue label={t.cached} value={usage.reported ? usage.cached_input_tokens : undefined} />
        <TokenValue label={t.reasoning} value={usage.reported ? usage.reasoning_tokens : undefined} />
      </div>
    </div>
  );
}

function FlightMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flight-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TokenValue({ label, value }: { label: string; value?: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value === undefined ? "n/a" : formatNumber(value)}</strong>
    </div>
  );
}

function formatDuration(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 ms";
  }
  if (value < 1000) {
    return `${Math.round(value)} ms`;
  }
  return `${(value / 1000).toFixed(value >= 10_000 ? 1 : 2)} s`;
}

function formatNumber(value: number | undefined): string {
  return new Intl.NumberFormat("en-US").format(value ?? 0);
}
