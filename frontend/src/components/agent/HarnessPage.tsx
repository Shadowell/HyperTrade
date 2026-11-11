import type { ThreadPresentation } from "../../agentThread";
import type { Copy } from "../../i18n/messages";
import type {
  AccessMode,
  HarnessOverview,
  Language,
  ProviderStatus,
  ReportBlock,
  TraceEvent
} from "../../types";
import {
  AgentFlightRecorder,
  type RunObservability
} from "../observability/AgentFlightRecorder";
import { ErrorBoundary } from "../ui/ErrorBoundary";
import { AgentProgress } from "./AgentProgress";
import { HarnessHeader, type SyncState } from "./HarnessHeader";
import { ReportReader } from "./ReportReader";
import { RunControls, type ThreadMeta } from "./RunControls";
import { RuntimeMonitor } from "./RuntimeMonitor";
import { TelemetryGrid, type TelemetryMetric } from "./TelemetryGrid";
import { ThreadDetails } from "./ThreadDetails";

export type HarnessPageProps = {
  t: Copy;
  language: Language;
  sync: SyncState;
  overview: HarnessOverview | null;
  refreshing: boolean;
  onRefresh: () => void;
  access: AccessMode;
  metrics: TelemetryMetric[];
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
  };
  observability: { data: RunObservability | null; loading: boolean };
};

/**
 * The Agent workbench (`/harness`): run the Agent, follow its progress, read the report, and see
 * the runtime around it. Each region sits in its own error boundary so a crash in one of them
 * leaves the rest of the console usable.
 */
export function HarnessPage(props: HarnessPageProps) {
  const { t, language, sync, overview, run, monitor, observability } = props;
  const guard = (children: React.ReactNode) => (
    <ErrorBoundary retryLabel={t.reloadSection} title={t.sectionCrashed}>
      {children}
    </ErrorBoundary>
  );
  return (
    <>
      {guard(
        <HarnessHeader
          access={props.access}
          generatedAt={overview?.generated_at || null}
          language={language}
          refreshing={props.refreshing}
          sync={sync}
          t={t}
        />
      )}
      {guard(<TelemetryGrid label={t.overviewMetrics} loading={!overview} metrics={props.metrics} />)}
      <section className="mt-5 grid grid-cols-[0.95fr_1.05fr] gap-5 max-xl:grid-cols-1">
        {guard(
          <div className="panel">
            <RunControls
              access={props.access}
              busy={run.busy}
              error={run.error}
              hasThread={run.hasThread}
              onArchiveThread={run.onArchiveThread}
              onNewThread={run.onNewThread}
              onPromptChange={run.onPromptChange}
              onRun={run.onRun}
              prompt={run.prompt}
              t={t}
              thread={run.thread}
              turnActive={run.turnActive}
            />
            <AgentProgress items={run.progress} stage={run.stage} t={t} />
            <ThreadDetails presentation={run.presentation} t={t} />
            <ReportReader
              blocks={run.report.blocks}
              busy={run.busy}
              markdown={run.report.markdown}
              onToggleRaw={run.report.onToggleRaw}
              showRaw={run.report.showRaw}
              t={t}
            />
          </div>
        )}
        {guard(
          <RuntimeMonitor
            defaultProvider={monitor.defaultProvider}
            onRefresh={props.onRefresh}
            onSelectTraceEvidence={monitor.onSelectTraceEvidence}
            overview={overview}
            refreshing={props.refreshing}
            sync={sync}
            t={t}
            traceEvents={monitor.traceEvents}
          />
        )}
      </section>
      {guard(
        <AgentFlightRecorder
          data={observability.data}
          language={language}
          loading={run.busy || observability.loading}
        />
      )}
    </>
  );
}
