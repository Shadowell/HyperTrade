import { Activity, Bot, BrainCircuit, Cpu, Radio } from "lucide-react";
import { useMemo } from "react";
import { HarnessPage } from "../components/agent/HarnessPage";
import type { TelemetryMetric } from "../components/agent/TelemetryGrid";
import type { ThreadMeta } from "../components/agent/RunControls";
import type { RunObservability } from "../components/observability/AgentFlightRecorder";
import type { ThreadPresentation, ThreadProjection } from "../agentThread";
import type { Copy } from "../i18n/messages";
import { formatMetricNumber, statusLabel } from "../lib/format";
import type {
  AccessMode,
  HarnessOverview,
  HealthzPayload,
  Language,
  ProviderStatus,
  ReportBlock,
  TraceEvent
} from "../types";
import type { SyncState } from "../components/agent/HarnessHeader";

export default function WorkbenchPage({
  t,
  language,
  sync,
  overview,
  healthz,
  refreshing,
  onRefresh,
  access,
  run,
  monitor,
  observability
}: {
  t: Copy;
  language: Language;
  sync: SyncState;
  overview: HarnessOverview | null;
  healthz: HealthzPayload | null;
  refreshing: boolean;
  onRefresh: () => void;
  access: AccessMode;
  run: {
    prompt: string;
    onPromptChange: (value: string) => void;
    busy: boolean;
    turnActive: boolean;
    hasThread: boolean;
    thread: ThreadMeta | null;
    error: string;
    onRun: () => void;
    onNewThread: () => void;
    onArchiveThread: () => void;
    onInterruptTurn: () => void;
    threads: ThreadProjection[];
    threadsOpen: boolean;
    threadsLoading: boolean;
    onToggleThreads: () => void;
    onSelectThread: (threadId: string) => void;
    stage: string | null;
    progress: string[];
    presentation: ThreadPresentation;
    report: {
      markdown: string;
      blocks: ReportBlock[];
      showRaw: boolean;
      onToggleRaw: () => void;
    };
  };
  monitor: {
    traceEvents: TraceEvent[];
    onSelectTraceEvidence: (event: TraceEvent) => void;
    defaultProvider: ProviderStatus | undefined;
    onSelectRun: (runId: string) => void;
    selectedRunId?: string;
  };
  observability: { data: RunObservability | null; loading: boolean };
}) {
  const metrics = useMemo<TelemetryMetric[]>(() => {
    const instances = healthz?.workers?.instances ?? [];
    const aliveCount = instances.filter((item) => !item.stale).length;
    const totalWorkers = instances.length;
    const failingCount = healthz?.workers?.failing_components?.length ?? 0;
    const workerStalls = instances.reduce((sum, item) => sum + (item.stalls_total ?? 0), 0);
    const workerValue =
      totalWorkers > 0
        ? `${aliveCount}/${totalWorkers}`
        : statusLabel(healthz?.workers?.status ?? "unknown");
    const workerDetail =
      failingCount > 0
        ? `${failingCount} failing · ${workerStalls} stalls`
        : totalWorkers > 0
          ? `${statusLabel(healthz?.workers?.status)} · ${workerStalls} stalls`
          : healthz
            ? statusLabel(healthz.status)
            : t.stale;

    const bitpro = overview?.bitpro;
    const probe = bitpro?.live_probe;
    const probeHealthy = Boolean(probe?.reachable && probe?.authenticated);
    const bitproValue = probe
      ? probeHealthy
        ? probe.latency_ms != null
          ? `${Math.round(probe.latency_ms)}ms`
          : t.mcpLiveOnline
        : probe.reachable
          ? t.mcpLiveAuthFailed
          : t.mcpLiveUnreachable
      : bitpro?.token_configured
        ? t.mcpTokenReady
        : t.missing;
    const bitproDetail = bitpro
      ? `${bitpro.tools.length} tools · ${bitpro.live_write_enabled ? t.mcpLiveWriteOn : t.mcpLiveWriteOff}`
      : t.missing;

    const missionsSummary = overview?.missions_summary;
    const missionsTotal = missionsSummary?.total_count ?? overview?.agent_runs.total_count ?? 0;
    const missionsActive = missionsSummary?.active_count ?? 0;
    const threadsCount = missionsSummary?.threads_count ?? 0;

    const cog = overview?.memory.cognitive;
    const opActive = overview?.memory.active_count ?? 0;
    const cogActive = (cog?.active_semantic_count ?? 0) + (cog?.episodic_count ?? 0);

    const evals = overview?.evals;
    const evalStatus = evals?.research_os?.status ?? evals?.status ?? "not_loaded";
    const totalTokens = overview?.observability?.total_tokens ?? 0;

    return [
      {
        label: t.workerLoops,
        value: workerValue,
        icon: Cpu,
        tone: failingCount > 0 || healthz?.workers?.status === "stale" ? "danger" : "signal",
        detail: workerDetail,
        ratio: totalWorkers > 0 ? aliveCount / totalWorkers : healthz ? 0.65 : 0
      },
      {
        label: t.bitproMcpShort,
        value: bitproValue,
        icon: Radio,
        tone: probe && !probeHealthy ? "danger" : "signal",
        detail: bitproDetail,
        ratio: probeHealthy ? 1 : bitpro?.token_configured ? 0.55 : 0.15
      },
      {
        label: t.missionsAndRuns,
        value: formatMetricNumber(missionsTotal),
        icon: Bot,
        tone: "brass",
        detail: `${missionsActive} active · ${threadsCount} threads`,
        ratio: missionsTotal > 0 ? Math.min(1, (missionsActive + 1) / Math.max(1, missionsTotal)) : 0.25
      },
      {
        label: t.unifiedMemory,
        value: formatMetricNumber(opActive + cogActive),
        icon: BrainCircuit,
        tone: "signal",
        detail: `${opActive} op · ${cog?.active_semantic_count ?? 0} sem · ${cog?.episodic_count ?? 0} ep`,
        ratio: opActive + cogActive > 0 ? Math.min(1, (opActive + cogActive) / 50) : 0.2
      },
      {
        label: t.evalsAndTokens,
        value: totalTokens > 0 ? formatMetricNumber(totalTokens) : `${evals?.case_count ?? 0}`,
        icon: Activity,
        tone: evalStatus === "passed" ? "signal" : "brass",
        detail: `${statusLabel(evalStatus)} · ${evals?.case_count ?? 0} cases · ${formatMetricNumber(totalTokens)} tok`,
        ratio: evalStatus === "passed" ? 1 : 0.45
      }
    ];
  }, [healthz, overview, t]);

  return (
    <HarnessPage
      access={access}
      language={language}
      metrics={metrics}
      monitor={{
        defaultProvider: monitor.defaultProvider,
        onSelectRun: monitor.onSelectRun,
        onSelectTraceEvidence: monitor.onSelectTraceEvidence,
        recentRuns: overview?.agent_runs.recent,
        selectedRunId: monitor.selectedRunId,
        traceEvents: monitor.traceEvents
      }}
      observability={observability}
      onRefresh={onRefresh}
      overview={overview}
      refreshing={refreshing}
      run={run}
      showAccessBadge={false}
      sync={sync}
      t={t}
    />
  );
}
