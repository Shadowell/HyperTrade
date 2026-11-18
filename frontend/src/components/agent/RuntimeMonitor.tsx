import { Cable, RefreshCw } from "lucide-react";
import { useState } from "react";
import type { Copy } from "../../i18n/messages";
import { cascadeStyle, providerLabel, statusLabel } from "../../lib/format";
import { summarizeRecord } from "../../lib/values";
import type { HarnessOverview, ProviderStatus, RunSummary, TraceEvent } from "../../types";
import { EmptyState } from "../ui/EmptyState";
import { InlineAlert } from "../ui/InlineAlert";
import { BitProCard } from "./BitProCard";
import type { SyncState } from "./HarnessHeader";

/** Model routing, tool calls, recent runs/missions, and the BitPro connection. */
export function RuntimeMonitor({
  t,
  sync,
  overview,
  refreshing,
  onRefresh,
  traceEvents,
  onSelectTraceEvidence,
  defaultProvider,
  recentRuns,
  onSelectRun,
  selectedRunId
}: {
  t: Copy;
  sync: SyncState;
  overview: HarnessOverview | null;
  refreshing: boolean;
  onRefresh: () => void;
  traceEvents: TraceEvent[];
  onSelectTraceEvidence: (event: TraceEvent) => void;
  defaultProvider: ProviderStatus | undefined;
  recentRuns?: RunSummary[];
  onSelectRun?: (runId: string) => void;
  selectedRunId?: string;
}) {
  const [selectedTrace, setSelectedTrace] = useState<TraceEvent | null>(null);
  const runsList = recentRuns ?? overview?.agent_runs.recent ?? [];

  function handleTraceClick(event: TraceEvent) {
    setSelectedTrace(event);
    onSelectTraceEvidence(event);
  }

  return (
    <div className="panel panel-command">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="section-title">{t.runtimeMonitor}</h2>
          <p className="mt-1 text-sm text-ink/55">{t.runtimeMonitorHint}</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="icon-button" disabled={refreshing} onClick={onRefresh} type="button">
            <RefreshCw className={refreshing ? "animate-spin" : ""} size={16} />
            <span>{t.refresh}</span>
          </button>
          <Cable size={18} className="text-accent" />
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{t.tools}</h3>
        <span className="rounded-full border border-ink/15 px-2.5 py-0.5 text-xs text-ink/55">
          {overview ? overview.trace.total_count : "—"}
        </span>
      </div>

      {!overview ? (
        sync === "unavailable" ? (
          <InlineAlert role="alert" title={t.overviewUnavailable} tone="danger">
            {t.overviewUnavailableHint}
            <button className="icon-button mt-3" onClick={onRefresh} type="button">
              <RefreshCw size={14} />
              {t.retry}
            </button>
          </InlineAlert>
        ) : (
          <div aria-busy className="mt-5 space-y-2" role="status">
            <span className="sr-only">{t.overviewConnecting}</span>
            {[0, 1, 2].map((row) => (
              <div className="skeleton-pulse h-9 rounded bg-ink/5" key={row} />
            ))}
          </div>
        )
      ) : (
        <>
          <div className="mt-2 trace-list">
            {traceEvents.length === 0 ? (
              <EmptyState title={t.noToolCalls} />
            ) : (
              traceEvents.map((event, index) => (
                <button
                  className="trace-row w-full text-left"
                  key={`${event.tool_name}-${event.id ?? index}`}
                  onClick={() => handleTraceClick(event)}
                  style={cascadeStyle(index)}
                  type="button"
                >
                  <span className="font-mono text-xs text-ink/45">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="font-medium">{event.tool_name}</span>
                  <span className="ml-auto rounded-full border border-signal/30 px-2 py-0.5 text-xs text-signal">
                    {statusLabel(event.status)}
                  </span>
                </button>
              ))
            )}
          </div>

          {selectedTrace ? (
            <div className="mt-3 operator-card operator-card-compact" data-tone="violet">
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-ink/60">
                  {t.traceEvidence}: {selectedTrace.tool_name}
                </span>
                <span className="text-xs text-ink/55">{statusLabel(selectedTrace.status)}</span>
              </div>
              <div className="mt-1 font-mono text-xs text-ink/75">
                {summarizeRecord(selectedTrace.output_json ?? selectedTrace.input_json)}
              </div>
            </div>
          ) : null}

          <div className="mt-5 grid grid-cols-3 gap-3 max-md:grid-cols-1">
            <div className="mini-block">
              <span>{t.providers}</span>
              <strong>{providerLabel(defaultProvider, t)}</strong>
            </div>
            <div className="mini-block">
              <span>{t.rag}</span>
              <strong>
                {overview.rag.document_count} 文档 / {overview.rag.chunk_count} 分片
              </strong>
            </div>
            <div className="mini-block">
              <span>{t.memory}</span>
              <strong>
                {overview.memory.active_count} 可用 / {overview.memory.total_count} 总数
              </strong>
            </div>
          </div>

          {runsList.length > 0 && onSelectRun ? (
            <div className="mt-5">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{t.recentRuns}</h3>
                <span className="text-xs text-ink/45">{runsList.length}</span>
              </div>
              <div className="trace-list">
                {runsList.slice(0, 6).map((runItem, index) => (
                  <button
                    className={`run-row w-full text-left ${
                      selectedRunId === runItem.id ? "bg-accent/10" : ""
                    }`}
                    key={runItem.id}
                    onClick={() => onSelectRun(runItem.id)}
                    style={cascadeStyle(index)}
                    type="button"
                  >
                    <span className="font-mono text-xs text-ink/55">{runItem.id}</span>
                    <span className="min-w-0 truncate text-xs">{runItem.prompt}</span>
                    <span className="rounded-full border border-signal/30 px-2 py-0.5 text-[11px] text-signal">
                      {statusLabel(runItem.status)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {overview.bitpro ? <BitProCard bitpro={overview.bitpro} t={t} /> : null}
        </>
      )}
    </div>
  );
}
