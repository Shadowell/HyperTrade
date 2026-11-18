import { lazy, type MouseEvent, Suspense, useCallback, useEffect, useState } from "react";
import { apiGet, isAuthError } from "./api/client";
import type { SyncState } from "./components/agent/HarnessHeader";
import { ConsoleShell } from "./components/layout/ConsoleShell";
import { ErrorBoundary } from "./components/ui/ErrorBoundary";
import { useAgentWorkbench } from "./hooks/useAgentWorkbench";
import { copy } from "./i18n/messages";
import { EMPTY_OVERVIEW } from "./lib/emptyOverview";
import { describeError } from "./lib/errors";
import { activeSectionFromPath, sectionPath } from "./lib/routes";
import WorkbenchPage from "./pages/WorkbenchPage";
import type {
  AccessMode,
  HarnessOverview,
  HealthzPayload,
  Language,
  NavSection,
  ThemeMode
} from "./types";

const MissionsEvolutionPage = lazy(() => import("./pages/MissionsEvolutionPage"));
const KnowledgeMemoryPage = lazy(() => import("./pages/KnowledgeMemoryPage"));
const SystemDiagnosticsPage = lazy(() => import("./pages/SystemDiagnosticsPage"));

const THEME_STORAGE_KEY = "hypertrade.theme.v1";

const BITPRO_CONSOLE_URL = (
  import.meta.env.VITE_BITPRO_CONSOLE_URL || "https://bitpro.notenap.com"
).replace(/\/+$/, "");

function readStoredTheme(): ThemeMode {
  try {
    const saved = window.localStorage.getItem(THEME_STORAGE_KEY);
    return saved === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export default function App() {
  const [access, setAccess] = useState<AccessMode>("unknown");
  const [overviewFailed, setOverviewFailed] = useState(false);
  const [language, setLanguage] = useState<Language>("zh");
  const [theme, setTheme] = useState<ThemeMode>(readStoredTheme);
  const [activeSection, setActiveSection] = useState<NavSection>(() => activeSectionFromPath());
  const [overview, setOverview] = useState<HarnessOverview | null>(null);
  const [healthz, setHealthz] = useState<HealthzPayload | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [harnessError, setHarnessError] = useState("");

  const t = copy[language];
  const activeOverview = overview ?? EMPTY_OVERVIEW;
  const sync: SyncState = overview ? "ready" : overviewFailed ? "unavailable" : "connecting";
  const defaultProvider =
    activeOverview.providers.find((provider) => provider.default) ?? activeOverview.providers[0];

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // Ignore storage failures in restricted browser environments.
    }
  }, [theme]);

  const handleAuthError = useCallback((error: unknown) => {
    if (isAuthError(error)) setAccess("readonly");
  }, []);

  const reportActionError = useCallback(
    (error: unknown) => {
      handleAuthError(error);
      setHarnessError(describeError(error, t));
    },
    [handleAuthError, t]
  );

  const refreshHealthz = useCallback(async () => {
    try {
      setHealthz(await apiGet<HealthzPayload>("/api/healthz"));
    } catch {
      // Tolerate missing or degraded /api/healthz gracefully without breaking overview.
      setHealthz(null);
    }
  }, []);

  const refreshOverview = useCallback(async () => {
    setRefreshing(true);
    try {
      const [overviewRes] = await Promise.allSettled([
        apiGet<HarnessOverview>("/api/harness/overview"),
        refreshHealthz()
      ]);
      if (overviewRes.status === "fulfilled") {
        setOverview(overviewRes.value);
        setOverviewFailed(false);
        setHarnessError("");
      } else {
        setOverviewFailed(true);
      }
    } finally {
      setRefreshing(false);
    }
  }, [refreshHealthz]);

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

  const workbench = useAgentWorkbench({
    t,
    onError: reportActionError,
    onTurnCompleted: refreshOverview
  });

  const handleNavigate = useCallback((section: NavSection, event?: MouseEvent<HTMLElement>) => {
    if (event) event.preventDefault();
    window.history.pushState({}, "", sectionPath(section));
    setActiveSection(section);
  }, []);

  const traceEvents = workbench.threadSnapshot
    ? workbench.threadPresentation.tools.map((tool) => ({
        id: tool.id,
        tool_name: tool.name,
        status: tool.status
      }))
    : workbench.run
      ? workbench.run.trace_events
      : activeOverview.trace.recent_events.slice(0, 6);

  return (
    <ConsoleShell
      access={access}
      activeSection={activeSection}
      bitproConsoleUrl={BITPRO_CONSOLE_URL}
      healthz={healthz}
      language={language}
      onNavigate={handleNavigate}
      onRefresh={() => void refreshOverview()}
      onToggleLanguage={() => setLanguage((current) => (current === "zh" ? "en" : "zh"))}
      onToggleTheme={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
      overview={overview}
      refreshing={refreshing}
      sync={sync}
      t={t}
      theme={theme}
    >
      <ErrorBoundary resetKey={activeSection} retryLabel={t.reloadSection} title={t.sectionCrashed}>
        <Suspense fallback={<div className="panel empty-row">{t.overviewLoading}…</div>}>
          {activeSection === "harness" ? (
            <WorkbenchPage
              access={access}
              healthz={healthz}
              language={language}
              monitor={{
                defaultProvider,
                onSelectRun: (runId) => void workbench.handleSelectRun(runId),
                onSelectTraceEvidence: () => undefined,
                selectedRunId: workbench.run?.id,
                traceEvents
              }}
              observability={{
                data: workbench.runObservability,
                loading: workbench.observabilityLoading
              }}
              onRefresh={() => void refreshOverview()}
              overview={overview}
              refreshing={refreshing}
              run={{
                busy: workbench.busy,
                error: harnessError,
                hasThread: Boolean(workbench.threadSnapshot),
                onArchiveThread: () => void workbench.handleArchiveThread(),
                onInterruptTurn: () => void workbench.handleInterruptTurn(),
                onNewThread: () => void workbench.handleNewThread(),
                onPromptChange: workbench.setPrompt,
                onRun: () => void workbench.handleRun(),
                onSelectThread: (id) => void workbench.handleSelectThread(id),
                onToggleThreads: () => void workbench.handleToggleThreads(),
                presentation: workbench.threadPresentation,
                progress: workbench.agentProgress,
                prompt: workbench.prompt,
                report: {
                  blocks: workbench.reportBlocks,
                  markdown: workbench.reportMarkdown,
                  onToggleRaw: () => workbench.setShowRawMarkdown((value) => !value),
                  showRaw: workbench.showRawMarkdown
                },
                stage: workbench.threadSnapshot
                  ? workbench.threadPresentation.status
                  : (workbench.run?.run_state_json?.current_node ?? null),
                thread: workbench.threadSnapshot
                  ? {
                      cursor: workbench.threadCursor,
                      id: workbench.threadSnapshot.thread.thread_id,
                      reconnecting: workbench.threadConnection.startsWith("reconnecting")
                    }
                  : null,
                threads: workbench.threads,
                threadsLoading: workbench.threadsLoading,
                threadsOpen: workbench.threadsOpen,
                turnActive: Boolean(workbench.threadSnapshot?.thread.active_turn_id)
              }}
              sync={sync}
              t={t}
            />
          ) : null}

          {activeSection === "missions" ? (
            <MissionsEvolutionPage
              access={access}
              bitproConsoleUrl={BITPRO_CONSOLE_URL}
              onAuthError={handleAuthError}
              t={t}
            />
          ) : null}

          {activeSection === "knowledge" ? (
            <KnowledgeMemoryPage
              access={access}
              language={language}
              onAuthError={handleAuthError}
              overview={overview}
              t={t}
            />
          ) : null}

          {activeSection === "system" ? (
            <SystemDiagnosticsPage
              access={access}
              healthz={healthz}
              language={language}
              onAuthError={handleAuthError}
              onRefreshHealthz={refreshHealthz}
              overview={overview}
              t={t}
            />
          ) : null}
        </Suspense>
      </ErrorBoundary>
    </ConsoleShell>
  );
}
