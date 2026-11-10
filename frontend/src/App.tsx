import {
  Activity,
  AlertTriangle,
  Archive,
  BarChart3,
  Bot,
  Brain,
  CheckCircle2,
  Clock3,
  FileText,
  Languages,
  Layers3,
  LineChart,
  MemoryStick,
  Radio,
  Sparkles,
  TerminalSquare
} from "lucide-react";
import {
  MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { RunObservability } from "./components/observability/AgentFlightRecorder";
import { QuantumPortfolioDashboard } from "./components/portfolio/QuantumPortfolioDashboard";
import {
  archiveAgentThread,
  clearThreadSession,
  createAgentThread,
  followAgentTurn,
  formatThreadEvent,
  getAgentThread,
  presentThread,
  readThreadSession,
  startAgentTurn,
  ThreadSnapshot,
  writeThreadSession
} from "./agentThread";

import { apiGet, isAuthError } from "./api/client";
import type { SyncState } from "./components/agent/HarnessHeader";
import { HarnessPage } from "./components/agent/HarnessPage";
import { EMPTY_OVERVIEW } from "./lib/emptyOverview";
import { describeError } from "./lib/errors";
import { copy } from "./i18n/messages";
import {
  cascadeStyle,
  formatAge,
  formatMetricNumber,
  formatPercentValue,
  metricTone,
  providerLabel,
  statusLabel
} from "./lib/format";
import { isRecord, stringOrUndefined, stringifyValue } from "./lib/values";
import { renderMarkdown } from "./lib/markdown";
import { createClientIdempotencyKey } from "./lib/ids";
import { activeSectionFromPath, sectionPath } from "./lib/routes";
import { reportBlocksFromRun, strategyEvidenceSelection, traceEvidenceSelection } from "./lib/report";
import { StatusDot } from "./components/ui/StatusDot";
import { RouteMetricStrip } from "./components/ui/RouteMetricStrip";
import { EvidenceMetric, SourceIdStrip } from "./components/report/StructuredReport";
import type {
  AccessMode,
  Language,
  NavSection,
  TraceEvent,
  AgentRun,
  MissionProjection,
  MissionEvent,
  StrategyCardProjection,
  ResearchFunnel,
  LiveOrderIntent,
  MemoryItem,
  MemoryAssertion,
  SkillProposal,
  SkillRelease,
  PortfolioAssessment,
  PortfolioObservationWindow,
  PaperCohort,
  PaperIncubationMandate,
  ShadowPortfolio,
  MarketRegimeSnapshotV2,
  RegimeShadowTargetV2,
  RagHit,
  StrategyLibraryItem,
  StrategyLibraryPayload,
  MonitorAlert,
  EvidenceSelection,
  RouteMetric,
  HarnessOverview
} from "./types";

function App() {
  const [access, setAccess] = useState<AccessMode>("unknown");
  const [overviewFailed, setOverviewFailed] = useState(false);
  const [language, setLanguage] = useState<Language>("zh");
  const [activeSection, setActiveSection] = useState<NavSection>(() => activeSectionFromPath());
  const [prompt, setPrompt] = useState(copy.zh.prompt);
  const [run, setRun] = useState<AgentRun | null>(null);
  const [threadSnapshot, setThreadSnapshot] = useState<ThreadSnapshot | null>(null);
  const [threadCursor, setThreadCursor] = useState(0);
  const [threadConnection, setThreadConnection] = useState("idle");
  const [partialAnswer, setPartialAnswer] = useState("");
  const [overview, setOverview] = useState<HarnessOverview | null>(null);
  const [missions, setMissions] = useState<MissionProjection[]>([]);
  const [selectedMission, setSelectedMission] = useState<MissionProjection | null>(null);
  const [missionEvents, setMissionEvents] = useState<MissionEvent[]>([]);
  const [missionObjective, setMissionObjective] = useState("");
  const [missionBusy, setMissionBusy] = useState(false);
  const activeTurnRequest = useRef<{
    threadId: string;
    prompt: string;
    clientMessageId: string;
  } | null>(null);
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
  const [portfolioObservationWindows, setPortfolioObservationWindows] = useState<
    PortfolioObservationWindow[]
  >([]);
  const [paperCohorts, setPaperCohorts] = useState<PaperCohort[]>([]);
  const [paperIncubationMandates, setPaperIncubationMandates] = useState<
    PaperIncubationMandate[]
  >([]);
  const [shadowPortfolios, setShadowPortfolios] = useState<ShadowPortfolio[]>([]);
  const [marketRegimesV2, setMarketRegimesV2] = useState<MarketRegimeSnapshotV2[]>([]);
  const [regimeShadowTargetsV2, setRegimeShadowTargetsV2] = useState<
    RegimeShadowTargetV2[]
  >([]);
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
  const [strategyCards, setStrategyCards] = useState<StrategyCardProjection[]>([]);
  const [researchFunnel, setResearchFunnel] = useState<ResearchFunnel>({
    denominator: 0,
    denominator_unit: "experiment_manifest",
    stages: {}
  });
  const [monitorAlerts, setMonitorAlerts] = useState<MonitorAlert[]>([]);
  const [evidenceSelection, setEvidenceSelection] = useState<EvidenceSelection | null>(null);
  const [runObservability, setRunObservability] = useState<RunObservability | null>(null);
  const [observabilityLoading, setObservabilityLoading] = useState(false);
  const t = copy[language];
  const activeOverview = overview ?? EMPTY_OVERVIEW;
  const threadPresentation = useMemo(() => presentThread(threadSnapshot), [threadSnapshot]);
  const reportMarkdown = partialAnswer || threadPresentation.answer || run?.report_markdown || "";
  const reportBlocks = useMemo(
    () => (threadSnapshot || !run ? [] : reportBlocksFromRun(run)),
    [run, threadSnapshot]
  );
  const sync: SyncState = overview ? "ready" : overviewFailed ? "unavailable" : "connecting";
  const defaultProvider =
    activeOverview.providers.find((provider) => provider.default) ?? activeOverview.providers[0];
  const traceEvents = threadSnapshot
    ? threadPresentation.tools.map((tool) => ({
        id: tool.id,
        tool_name: tool.name,
        status: tool.status
      }))
    : run
      ? run.trace_events
      : activeOverview.trace.recent_events.slice(0, 6);
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
    const incomplete = strategyCards.filter((card) => (card.missing_fields?.length ?? 0) > 0).length;
    return [
      { label: t.cardCandidates, value: formatMetricNumber(strategyCards.length), tone: "signal" },
      { label: t.incompleteCards, value: formatMetricNumber(incomplete), tone: "brass" },
      { label: t.manifestStage, value: formatMetricNumber(researchFunnel.stages.manifest ?? 0), tone: "violet" },
      { label: t.paperStage, value: formatMetricNumber(researchFunnel.stages.paper ?? 0), tone: "signal" }
    ];
  }, [researchFunnel, strategyCards, t]);

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
    const latestWindow = portfolioObservationWindows[0];
    return [
      {
        label: t.observationWindows,
        value: formatMetricNumber(portfolioObservationWindows.length),
        tone: "signal"
      },
      {
        label: t.windowCoverage,
        value: latestWindow?.quality.coverage_ratio ?? "0.00000000",
        tone: "violet"
      },
      {
        label: t.regimeShadowV2,
        value: formatMetricNumber(regimeShadowTargetsV2.length),
        tone: "brass"
      },
      {
        label: t.portfolioUnknowns,
        value: formatMetricNumber(latest?.unknowns.length ?? 0),
        tone: "danger"
      }
    ];
  }, [portfolioAssessments, portfolioObservationWindows, regimeShadowTargetsV2, t]);

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

  const refreshStrategyCards = useCallback(async () => {
    const [cardsResponse, funnelResponse] = await Promise.all([
      fetch("/api/research/strategy-cards", { credentials: "include" }),
      fetch("/api/research/strategy-cards/funnel", { credentials: "include" })
    ]);
    if (cardsResponse.ok) {
      const payload = (await cardsResponse.json()) as { items?: StrategyCardProjection[] };
      setStrategyCards(Array.isArray(payload.items) ? payload.items : []);
    } else {
      setStrategyCards([]);
    }
    if (funnelResponse.ok) {
      const payload = (await funnelResponse.json()) as Partial<ResearchFunnel>;
      setResearchFunnel({
        denominator: payload.denominator ?? 0,
        denominator_unit: payload.denominator_unit ?? "experiment_manifest",
        stages: payload.stages ?? {}
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

  const refreshPortfolioObservationWindows = useCallback(async () => {
    const response = await fetch("/api/portfolio/observation-windows", { credentials: "include" });
    if (!response.ok) {
      setPortfolioObservationWindows([]);
      return;
    }
    const payload = (await response.json()) as { items?: PortfolioObservationWindow[] };
    setPortfolioObservationWindows(Array.isArray(payload.items) ? payload.items : []);
  }, []);

  const refreshPaperCohorts = useCallback(async () => {
    const response = await fetch("/api/portfolio/paper-cohorts", { credentials: "include" });
    if (!response.ok) {
      setPaperCohorts([]);
      return;
    }
    const payload = (await response.json()) as { items?: PaperCohort[] };
    setPaperCohorts(Array.isArray(payload.items) ? payload.items : []);
  }, []);

  const refreshPaperIncubationMandates = useCallback(async () => {
    const response = await fetch("/api/research/paper-incubation/mandates", {
      credentials: "include"
    });
    if (!response.ok) {
      setPaperIncubationMandates([]);
      return;
    }
    const payload = (await response.json()) as { items?: PaperIncubationMandate[] };
    setPaperIncubationMandates(Array.isArray(payload.items) ? payload.items : []);
  }, []);

  const refreshShadowPortfolios = useCallback(async () => {
    const response = await fetch("/api/portfolio/shadow-portfolios", { credentials: "include" });
    if (!response.ok) {
      setShadowPortfolios([]);
      return;
    }
    const payload = (await response.json()) as { items?: ShadowPortfolio[] };
    setShadowPortfolios(Array.isArray(payload.items) ? payload.items : []);
  }, []);

  const refreshRegimeShadowV2 = useCallback(async () => {
    const [regimesResponse, targetsResponse] = await Promise.all([
      fetch("/api/portfolio/market-regimes-v2", { credentials: "include" }),
      fetch("/api/portfolio/regime-shadow-targets-v2", { credentials: "include" })
    ]);
    setMarketRegimesV2(
      regimesResponse.ok
        ? (((await regimesResponse.json()) as { items?: MarketRegimeSnapshotV2[] }).items ?? [])
        : []
    );
    setRegimeShadowTargetsV2(
      targetsResponse.ok
        ? (((await targetsResponse.json()) as { items?: RegimeShadowTargetV2[] }).items ?? [])
        : []
    );
  }, []);

  const refreshMissions = useCallback(async (missionId = "") => {
    const response = await fetch("/api/agent/missions", { credentials: "include" });
    if (!response.ok) {
      setMissions([]);
      return;
    }
    const payload = (await response.json()) as { missions?: MissionProjection[] };
    const rows = Array.isArray(payload.missions) ? payload.missions : [];
    setMissions(rows);
    const selected = rows.find((row) => row.mission_id === missionId) ?? rows[0] ?? null;
    if (!selected) {
      setSelectedMission(null);
      setMissionEvents([]);
      return;
    }
    const detailResponse = await fetch(`/api/agent/missions/${encodeURIComponent(selected.mission_id)}`, {
      credentials: "include"
    });
    const detail = detailResponse.ok ? ((await detailResponse.json()) as MissionProjection) : selected;
    setSelectedMission(detail);
    const eventsResponse = await fetch(`/api/agent/missions/${encodeURIComponent(selected.mission_id)}/events?after=0`, {
      credentials: "include"
    });
    if (eventsResponse.ok) {
      const eventPayload = (await eventsResponse.json()) as { events?: MissionEvent[] };
      setMissionEvents(Array.isArray(eventPayload.events) ? eventPayload.events : []);
    }
  }, []);

  const createMission = useCallback(async () => {
    const objective = missionObjective.trim();
    if (!objective) return;
    setMissionBusy(true);
    try {
      const response = await fetch("/api/agent/missions", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": createClientIdempotencyKey("web_mission")
        },
        body: JSON.stringify({
          objective,
          success_criteria: [{ criterion_id: "validated", kind: "all_steps_validated", description: "所有步骤通过结构化证据验证" }]
        })
      });
      if (response.ok) {
        const created = (await response.json()) as MissionProjection;
        setMissionObjective("");
        await refreshMissions(created.mission_id);
      }
    } finally {
      setMissionBusy(false);
    }
  }, [missionObjective, refreshMissions]);

  const runMissionAction = useCallback(async (action: "run" | "pause" | "resume" | "cancel") => {
    if (!selectedMission) return;
    setMissionBusy(true);
    try {
      await fetch(`/api/agent/missions/${encodeURIComponent(selectedMission.mission_id)}/${action === "run" ? "run" : "control"}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: action === "run" ? undefined : JSON.stringify({ action, reason: "operator_mission_workspace" })
      });
      await refreshMissions(selectedMission.mission_id);
    } finally {
      setMissionBusy(false);
    }
  }, [refreshMissions, selectedMission]);

  const steerMission = useCallback(async () => {
    if (!selectedMission || !missionObjective.trim()) return;
    setMissionBusy(true);
    try {
      await fetch(`/api/agent/missions/${encodeURIComponent(selectedMission.mission_id)}/steer`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: missionObjective.trim(), reason: "operator_mission_workspace", actor: "operator" })
      });
      setMissionObjective("");
      await refreshMissions(selectedMission.mission_id);
    } finally {
      setMissionBusy(false);
    }
  }, [missionObjective, refreshMissions, selectedMission]);

  const refreshOverview = useCallback(async () => {
    setRefreshing(true);
    try {
      setOverview(await apiGet<HarnessOverview>("/api/harness/overview"));
      setOverviewFailed(false);
    } catch {
      // The header and the monitor panel say so; the page never falls back to sample data.
      setOverviewFailed(true);
      return;
    } finally {
      setRefreshing(false);
    }
    // The other sections load in parallel and independently. This used to be a serial chain of
    // twelve awaits that stopped at the first request that threw.
    await Promise.allSettled([
      refreshMemoryItems(),
      refreshStrategyLibrary(),
      refreshStrategyCards(),
      refreshMonitorAlerts(),
      refreshGovernance(),
      refreshPortfolioAssessments(),
      refreshPortfolioObservationWindows(),
      refreshPaperCohorts(),
      refreshPaperIncubationMandates(),
      refreshShadowPortfolios(),
      refreshRegimeShadowV2(),
      refreshMissions()
    ]);
    setHarnessError("");
  }, [
    refreshGovernance,
    refreshMemoryItems,
    refreshMonitorAlerts,
    refreshPortfolioAssessments,
    refreshPortfolioObservationWindows,
    refreshPaperCohorts,
    refreshPaperIncubationMandates,
    refreshMissions,
    refreshRegimeShadowV2,
    refreshShadowPortfolios,
    refreshStrategyCards,
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

  const followCanonicalTurn = useCallback(
    async (threadId: string, turnId: string, after: number) => {
      setThreadConnection("streaming");
      const result = await followAgentTurn({
        threadId,
        turnId,
        after,
        onCursor: (cursor) => {
          setThreadCursor(cursor);
          writeThreadSession(window.localStorage, { threadId, cursor });
        },
        onReconnecting: (attempt) => {
          setThreadConnection(`reconnecting:${attempt}`);
        },
        onEvent: (event) => {
          setAgentProgress((items) => [...items.slice(-8), formatThreadEvent(event)]);
          if (event.event_type === "agent_message.delta" && isRecord(event.payload.content)) {
            const delta = stringOrUndefined(event.payload.content.text);
            if (delta) setPartialAnswer((value) => `${value}${delta}`);
          }
        }
      });
      setThreadSnapshot(result.snapshot);
      setThreadCursor(result.cursor);
      setPartialAnswer("");
      setThreadConnection("idle");
      writeThreadSession(window.localStorage, { threadId, cursor: result.cursor });
      activeTurnRequest.current = null;
    },
    []
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshOverview();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshOverview]);

  useEffect(() => {
    const pointer = readThreadSession(window.localStorage);
    if (!pointer) return;
    let cancelled = false;
    void (async () => {
      try {
        const snapshot = await getAgentThread(pointer.threadId);
        if (cancelled) return;
        if (snapshot.thread.status !== "active") {
          clearThreadSession(window.localStorage);
          return;
        }
        setThreadSnapshot(snapshot);
        setThreadCursor(Math.max(pointer.cursor, snapshot.thread.event_cursor));
        if (snapshot.thread.active_turn_id) {
          setBusy(true);
          await followCanonicalTurn(
            snapshot.thread.thread_id,
            snapshot.thread.active_turn_id,
            pointer.cursor
          );
        }
      } catch (error) {
        if (!cancelled) {
          clearThreadSession(window.localStorage);
          setHarnessError(error instanceof Error ? error.message : "Thread restore failed");
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [followCanonicalTurn]);

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

  function reportActionError(error: unknown) {
    if (isAuthError(error)) setAccess("readonly");
    setHarnessError(describeError(error, t));
  }

  async function handleRun() {
    const submittedPrompt = prompt.trim();
    if (!submittedPrompt) return;
    setBusy(true);
    setAgentProgress([]);
    setRunObservability(null);
    setPartialAnswer("");
    setHarnessError("");
    try {
      let snapshot = threadSnapshot;
      if (!snapshot || snapshot.thread.status !== "active") {
        snapshot = await createAgentThread();
        setThreadSnapshot(snapshot);
        setThreadCursor(snapshot.thread.event_cursor);
        writeThreadSession(window.localStorage, {
          threadId: snapshot.thread.thread_id,
          cursor: snapshot.thread.event_cursor
        });
      }
      const threadId = snapshot.thread.thread_id;
      const existing = activeTurnRequest.current;
      const request =
        existing && existing.threadId === threadId && existing.prompt === submittedPrompt
          ? existing
          : {
              threadId,
              prompt: submittedPrompt,
              clientMessageId: createClientIdempotencyKey("web_turn")
            };
      activeTurnRequest.current = request;
      const started = await startAgentTurn(threadId, submittedPrompt, request.clientMessageId);
      const accepted = await getAgentThread(threadId);
      setThreadSnapshot(accepted);
      setThreadCursor(started.event_cursor);
      writeThreadSession(window.localStorage, { threadId, cursor: started.event_cursor });
      await followCanonicalTurn(threadId, started.turn.turn_id, started.event_cursor);
      await refreshOverview();
    } catch (error) {
      reportActionError(error);
    } finally {
      setBusy(false);
    }
  }

  async function handleNewThread() {
    if (threadSnapshot?.thread.active_turn_id) {
      setHarnessError(t.errorConflict);
      return;
    }
    setBusy(true);
    try {
      if (threadSnapshot?.thread.status === "active") {
        await archiveAgentThread(threadSnapshot.thread.thread_id);
      }
      const created = await createAgentThread();
      setThreadSnapshot(created);
      setThreadCursor(created.thread.event_cursor);
      setAgentProgress([]);
      setPartialAnswer("");
      setHarnessError("");
      activeTurnRequest.current = null;
      writeThreadSession(window.localStorage, {
        threadId: created.thread.thread_id,
        cursor: created.thread.event_cursor
      });
    } catch (error) {
      reportActionError(error);
    } finally {
      setBusy(false);
    }
  }

  async function handleArchiveThread() {
    if (!threadSnapshot || threadSnapshot.thread.active_turn_id) return;
    setBusy(true);
    try {
      const archived = await archiveAgentThread(threadSnapshot.thread.thread_id);
      setThreadSnapshot(archived);
      clearThreadSession(window.localStorage);
      activeTurnRequest.current = null;
      setThreadConnection("archived");
    } catch (error) {
      reportActionError(error);
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

  async function handlePortfolioWindowCapture() {
    const response = await fetch("/api/portfolio/observation-windows", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `web_portfolio_window_${Date.now()}` })
    });
    if (response.ok) {
      await refreshPortfolioObservationWindows();
    }
  }

  async function handlePaperCohortBuild() {
    const response = await fetch("/api/portfolio/paper-cohorts", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `web_paper_cohort_${Date.now()}` })
    });
    if (response.ok) {
      await refreshPaperCohorts();
    }
  }

  async function handleShadowPortfolioBuild() {
    const response = await fetch("/api/portfolio/shadow-portfolios", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idempotency_key: `web_shadow_portfolio_${Date.now()}` })
    });
    if (response.ok) {
      await refreshShadowPortfolios();
    }
  }

  async function handleShadowPortfolioReview(
    proposalId: string,
    scenarioId: string,
    decision: "accept" | "reject" | "hold"
  ) {
    const reason = portfolioReason.trim();
    if (!reason) {
      return;
    }
    const response = await fetch(
      `/api/portfolio/shadow-portfolios/${encodeURIComponent(proposalId)}/reviews`,
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scenario_id: scenarioId,
          decision,
          reason,
          idempotency_key: `web_shadow_review_${Date.now()}`
        })
      }
    );
    if (response.ok) {
      await refreshShadowPortfolios();
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
        <aside className="border-r border-ink/15 bg-night px-5 py-6 text-ink shadow-[inset_-1px_0_0_rgba(90,214,196,0.05)] lg:sticky lg:top-0 lg:h-[100dvh] lg:self-start lg:overflow-y-auto">
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
              className={navItemClass("missions")}
              href={sectionPath("missions")}
              onClick={(event) => handleNavClick("missions", event)}
            >
              <Activity size={16} />
              {t.missions}
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
          <HarnessPage
            access={access}
            language={language}
            metrics={metrics}
            monitor={{
              defaultProvider,
              onSelectTraceEvidence: handleSelectTraceEvidence,
              traceEvents
            }}
            observability={{ data: runObservability, loading: observabilityLoading }}
            onRefresh={() => void refreshOverview()}
            overview={overview}
            refreshing={refreshing}
            run={{
              busy,
              error: harnessError,
              hasThread: Boolean(threadSnapshot),
              onArchiveThread: () => void handleArchiveThread(),
              onNewThread: () => void handleNewThread(),
              onPromptChange: setPrompt,
              onRun: () => void handleRun(),
              presentation: threadPresentation,
              progress: agentProgress,
              prompt,
              report: {
                blocks: reportBlocks,
                markdown: reportMarkdown,
                onToggleRaw: () => setShowRawMarkdown((value) => !value),
                showRaw: showRawMarkdown
              },
              stage: threadSnapshot ? threadPresentation.status : (run?.run_state_json?.current_node ?? null),
              thread: threadSnapshot
                ? {
                    cursor: threadCursor,
                    id: threadSnapshot.thread.thread_id,
                    reconnecting: threadConnection.startsWith("reconnecting")
                  }
                : null,
              turnActive: Boolean(threadSnapshot?.thread.active_turn_id)
            }}
            sync={sync}
            t={t}
          />
          </div>

          <section className="mt-5" hidden={activeSection !== "missions"}>
            <div className="panel">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-brass">MISSION / TASK OS</div>
                  <h2 className="mt-2 text-2xl font-semibold">{t.missions}</h2>
                  <p className="mt-1 text-sm text-ink/55">{t.missionObjective}、Plan、Evidence 和控制事件在同一条可回放时间线上。</p>
                </div>
                <span className="rounded border border-signal/25 bg-signal/10 px-2 py-1 text-xs text-signal">read-only / governed</span>
              </div>
              <div className="mt-4 grid grid-cols-[1fr_auto] gap-2 max-md:grid-cols-1">
                <input
                  className="field-light"
                  onChange={(event) => setMissionObjective(event.target.value)}
                  placeholder={t.missionObjective}
                  value={missionObjective}
                />
                <button className="icon-button justify-center" disabled={missionBusy} onClick={() => void (selectedMission ? steerMission() : createMission())} type="button">
                  <Sparkles size={14} />
                  {selectedMission ? t.missionSteer : t.missionCreate}
                </button>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-[260px_1fr] gap-5 max-lg:grid-cols-1">
              <div className="panel">
                <div className="section-title">MISSIONS</div>
                <div className="mt-3 space-y-2">
                  {missions.length === 0 ? <div className="empty-row">{t.missionNoData}</div> : missions.map((mission) => (
                    <button
                      className={`operator-card w-full text-left ${selectedMission?.mission_id === mission.mission_id ? "border-signal/45" : ""}`}
                      data-tone={mission.status === "failed" ? "danger" : "signal"}
                      key={mission.mission_id}
                      onClick={() => void refreshMissions(mission.mission_id)}
                      type="button"
                    >
                      <strong className="block truncate font-mono text-xs">{mission.mission_id}</strong>
                      <span className="mt-1 block truncate text-sm text-ink/70">{mission.objective}</span>
                      <span className="mt-2 inline-flex rounded border border-ink/15 px-2 py-0.5 text-[11px] text-ink/55">{statusLabel(mission.status)}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="space-y-5">
                {selectedMission ? (
                  <>
                    <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
                      <div className="operator-card" data-tone="signal"><span>STATUS</span><strong>{statusLabel(selectedMission.status)}</strong></div>
                      <div className="operator-card" data-tone="brass"><span>PLAN</span><strong>v{selectedMission.active_plan_version ?? 0}</strong></div>
                      <div className="operator-card" data-tone="violet"><span>TOKENS</span><strong>{formatMetricNumber(selectedMission.usage?.tokens ?? 0)}</strong></div>
                      <div className="operator-card" data-tone="signal"><span>TOOLS</span><strong>{formatMetricNumber(selectedMission.usage?.tool_calls ?? 0)}</strong></div>
                    </div>
                    <div className="panel">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <h3 className="section-title">{t.missionPlan}</h3>
                        <div className="flex flex-wrap gap-2">
                          {selectedMission.status === "draft" || selectedMission.status === "paused" ? <button className="icon-button" disabled={missionBusy} onClick={() => void runMissionAction(selectedMission.status === "draft" ? "run" : "resume")} type="button">{selectedMission.status === "draft" ? t.missionRun : t.missionResume}</button> : null}
                          {selectedMission.status === "running" ? <button className="icon-button" disabled={missionBusy} onClick={() => void runMissionAction("pause")} type="button">{t.missionPause}</button> : null}
                          {!['completed', 'failed', 'canceled', 'budget_exhausted'].includes(selectedMission.status) ? <button className="icon-button border-danger/30 text-danger" disabled={missionBusy} onClick={() => void runMissionAction("cancel")} type="button">{t.missionCancel}</button> : null}
                        </div>
                      </div>
                      <div className="mt-3 space-y-2">
                        {(selectedMission.plans?.at(-1)?.steps ?? []).map((step) => {
                          const attempt = selectedMission.attempts?.find((item) => item.step_id === step.step_id);
                          return <div className="operator-card operator-card-compact" data-tone={attempt?.status === "succeeded" ? "signal" : "brass"} key={step.step_id}><div className="flex items-center justify-between gap-3"><strong className="font-mono text-sm">{step.step_id}</strong><span className="text-xs text-ink/50">{statusLabel(attempt?.status ?? "pending")}</span></div><div className="mt-1 text-sm text-ink/70">{step.title}</div><div className="mt-1 text-xs text-ink/45">{step.capability_id}</div></div>;
                        })}
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
                      <div className="panel"><h3 className="section-title">{t.missionEvents}</h3><div className="mt-3 max-h-64 space-y-2 overflow-auto">{missionEvents.length === 0 ? <div className="empty-row">—</div> : missionEvents.map((event) => <div className="trace-row" key={event.sequence}><span className="font-mono text-xs text-brass">#{event.sequence}</span><span className="text-sm">{event.event_type}</span><span className="ml-auto text-xs text-ink/45">{event.actor ?? "runtime"}</span></div>)}</div></div>
                      <div className="panel"><h3 className="section-title">{t.missionEvidence}</h3><div className="mt-3 space-y-2 text-sm"><div className="mini-block"><span>Artifact refs</span><strong>{formatMetricNumber(selectedMission.artifact_refs?.length ?? 0)}</strong></div><div className="mini-block"><span>Unknowns</span><strong>{formatMetricNumber(selectedMission.unknowns?.length ?? 0)}</strong></div><div className="text-xs text-ink/45">{(selectedMission.unknowns ?? []).join(" · ") || "No unknowns recorded"}</div></div></div>
                    </div>
                  </>
                ) : <div className="panel empty-row">{t.missionNoData}</div>}
              </div>
            </div>
          </section>

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

          <section className="mt-5 space-y-5" hidden={activeSection !== "portfolio"}>
            <RouteMetricStrip label={t.pageMetrics} metrics={portfolioRouteMetrics} />
            <QuantumPortfolioDashboard />
            <PortfolioLifecyclePanel
              assessments={portfolioAssessments}
              cohorts={paperCohorts}
              incubationMandates={paperIncubationMandates}
              marketRegimesV2={marketRegimesV2}
              regimeShadowTargetsV2={regimeShadowTargetsV2}
              shadowPortfolios={shadowPortfolios}
              observationWindows={portfolioObservationWindows}
              onAssess={handlePortfolioAssessment}
              onCapture={handlePortfolioWindowCapture}
              onCohortBuild={handlePaperCohortBuild}
              onShadowBuild={handleShadowPortfolioBuild}
              onShadowReview={handleShadowPortfolioReview}
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
                <div>
                  <h2 className="section-title">{t.recentRuns}</h2>
                  <p className="mt-1 text-xs text-ink/45">{t.legacyHistory}</p>
                </div>
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
  cohorts,
  incubationMandates,
  marketRegimesV2,
  regimeShadowTargetsV2,
  shadowPortfolios,
  observationWindows,
  reason,
  setReason,
  onAssess,
  onCapture,
  onCohortBuild,
  onShadowBuild,
  onShadowReview,
  onReview,
  t
}: {
  assessments: PortfolioAssessment[];
  cohorts: PaperCohort[];
  incubationMandates: PaperIncubationMandate[];
  marketRegimesV2: MarketRegimeSnapshotV2[];
  regimeShadowTargetsV2: RegimeShadowTargetV2[];
  shadowPortfolios: ShadowPortfolio[];
  observationWindows: PortfolioObservationWindow[];
  reason: string;
  setReason: (value: string) => void;
  onAssess: () => Promise<void>;
  onCapture: () => Promise<void>;
  onCohortBuild: () => Promise<void>;
  onShadowBuild: () => Promise<void>;
  onShadowReview: (
    proposalId: string,
    scenarioId: string,
    decision: "accept" | "reject" | "hold"
  ) => Promise<void>;
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
        <div className="mt-4 grid grid-cols-[auto_1fr] gap-3 max-sm:grid-cols-1">
          <div className="flex flex-wrap gap-2">
            <button className="icon-button justify-center" onClick={() => void onCapture()} type="button">
              <Activity size={15} />
              {t.captureWindow}
            </button>
            <button className="icon-button justify-center" onClick={() => void onCohortBuild()} type="button">
              <Layers3 size={15} />
              {t.buildCohort}
            </button>
            <button className="icon-button justify-center" onClick={() => void onShadowBuild()} type="button">
              <Layers3 size={15} />
              {t.buildShadow}
            </button>
          </div>
          {observationWindows[0] ? (
            <div className="operator-card operator-card-compact" data-tone="signal">
              <span>
                {observationWindows[0].status} · {observationWindows[0].horizon_days}d/
                {observationWindows[0].bucket_minutes}m · raw_series=false
              </span>
              <strong className="font-mono">
                {t.windowCoverage}: {observationWindows[0].quality.coverage_ratio} · available=
                {observationWindows[0].quality.available_count}/
                {observationWindows[0].quality.denominator}
              </strong>
            </div>
          ) : (
            <div className="empty-row">{t.noObservationWindows}</div>
          )}
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
        <h2 className="section-title">{t.paperIncubation}</h2>
        <p className="mt-1 text-xs leading-5 text-ink/50">{t.paperIncubationHint}</p>
        <div className="mt-4 space-y-2">
          {incubationMandates.length === 0 ? (
            <div className="empty-row">{t.noPaperIncubation}</div>
          ) : (
            incubationMandates.slice(0, 6).map((mandate) => {
              const unknownActions = mandate.actions.filter(
                (action) => action.status === "effect_unknown"
              ).length;
              return (
                <div
                  className="operator-card block"
                  data-tone={mandate.kill_switch ? "danger" : "signal"}
                  key={mandate.id}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">{mandate.id}</span>
                    <span className="text-xs">
                      {statusLabel(mandate.status)} · kill={String(mandate.kill_switch)}
                    </span>
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-ink/55">
                    <span>{mandate.members.length}/{mandate.fixed_denominator} members</span>
                    <span>{mandate.actions.length} actions</span>
                    <span>{unknownActions} unknown</span>
                  </div>
                  <div className="mt-2 truncate font-mono text-[11px] text-ink/40">
                    policy={mandate.policy_hash} · paper_only=
                    {String(mandate.mutation_boundary.paper_only)} · live=false
                  </div>
                  {mandate.actions[0] ? (
                    <div className="mt-2 text-xs text-ink/55">
                      {mandate.actions[0].action} · {mandate.actions[0].status} ·{" "}
                      {mandate.actions[0].reason}
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
        <h2 className="section-title mt-5">{t.regimeShadowV2}</h2>
        <p className="mt-1 text-xs leading-5 text-ink/50">{t.regimeShadowHint}</p>
        <div className="mt-4 space-y-2">
          {marketRegimesV2.length === 0 ? (
            <div className="empty-row">{t.noRegimeSnapshots}</div>
          ) : (
            marketRegimesV2.slice(0, 3).map((snapshot) => (
              <div className="operator-card block" data-tone="signal" key={snapshot.id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">{snapshot.id}</span>
                  <span className="text-xs text-signal">{statusLabel(snapshot.status)}</span>
                </div>
                <div className="mt-2 text-xs text-ink/55">
                  confidence={snapshot.confidence} · as_of={snapshot.as_of} ·
                  unknown={snapshot.unknowns.length} · execution=false
                </div>
                <div className="mt-2 flex flex-wrap gap-2 font-mono text-[11px] text-ink/45">
                  {Object.entries(snapshot.probabilities).map(([name, probability]) => (
                    <span key={name}>{name}={probability}</span>
                  ))}
                </div>
              </div>
            ))
          )}
          {regimeShadowTargetsV2.length === 0 ? (
            <div className="empty-row">{t.noRegimeShadowTargets}</div>
          ) : (
            regimeShadowTargetsV2.slice(0, 6).map((target) => (
              <div className="operator-card block" data-tone="brass" key={target.id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">
                    {target.id} · v{target.version_number}
                  </span>
                  <span className="text-xs text-brass">{statusLabel(target.status)}</span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-ink/55">
                  <span>{target.eligible_count}/{target.intake_denominator} eligible</span>
                  <span>{target.selected_template || "infeasible"}</span>
                  <span>
                    turnover={target.estimated_turnover} · cost={target.estimated_cost_bps}bps
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 font-mono text-[11px] text-ink/45">
                  {target.target_weights.map((weight) => (
                    <span key={weight.card_id}>{weight.card_id}={weight.weight}</span>
                  ))}
                </div>
                {target.eligibility.map((item) => (
                  <div className="mt-2 text-xs text-ink/50" key={item.card_id}>
                    {item.card_id} · {item.status} · {item.reasons.join(", ") || "eligible"}
                  </div>
                ))}
                <div className="mt-2 text-[11px] text-ink/40">
                  hypothetical=true · capital={String(target.capital_authorized)} · execution=
                  {String(target.execution_authorized)}
                </div>
              </div>
            ))
          )}
        </div>
        <h2 className="section-title">{t.observationWindows}</h2>
        <div className="mt-4 space-y-2">
          {observationWindows.length === 0 ? (
            <div className="empty-row">{t.noObservationWindows}</div>
          ) : (
            observationWindows.slice(0, 6).map((window) => (
              <div className="operator-card block" data-tone="signal" key={window.id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">{window.id}</span>
                  <span className="text-xs text-signal">{statusLabel(window.status)}</span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-ink/55">
                  <span>{window.quality.available_count}/{window.quality.denominator} available</span>
                  <span>{window.quality.coverage_ratio} coverage</span>
                  <span>{window.pairwise.length} pairs</span>
                </div>
              </div>
            ))
          )}
        </div>
        <h2 className="section-title mt-5">{t.paperCohorts}</h2>
        <div className="mt-4 space-y-2">
          {cohorts.length === 0 ? (
            <div className="empty-row">{t.noPaperCohorts}</div>
          ) : (
            cohorts.slice(0, 6).map((cohort) => (
              <div className="operator-card block" data-tone="brass" key={cohort.id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">{cohort.id} · v{cohort.version_number}</span>
                  <span className="text-xs text-brass">{statusLabel(cohort.status)}</span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-ink/55">
                  <span>{cohort.intake_count} intake</span>
                  <span>{cohort.comparable_count} {t.cohortComparable}</span>
                  <span>{cohort.proposal_count} proposals · execution=false</span>
                </div>
              </div>
            ))
          )}
        </div>
        <h2 className="section-title mt-5">{t.shadowPortfolios}</h2>
        <div className="mt-4 space-y-2">
          {shadowPortfolios.length === 0 ? (
            <div className="empty-row">{t.noShadowPortfolios}</div>
          ) : (
            shadowPortfolios.slice(0, 6).map((proposal) => (
              <div className="operator-card block" data-tone="violet" key={proposal.id}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">
                    {proposal.id} · v{proposal.version_number}
                  </span>
                  <span className="text-xs text-violet">{statusLabel(proposal.status)}</span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-ink/55">
                  <span>{proposal.eligible_count}/{proposal.intake_count} eligible</span>
                  <span>{proposal.scenario_count} scenarios</span>
                  <span>hypothetical=true · capital=false · execution=false</span>
                </div>
                {proposal.scenarios.map((scenario) => (
                  <div className="mt-3 border-t border-ink/10 pt-3" key={scenario.scenario_id}>
                    <div className="font-mono text-xs text-ink/55">
                      {scenario.template} · {scenario.scenario_id}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {(["accept", "hold", "reject"] as const).map((decision) => (
                        <button
                          className="icon-button"
                          disabled={!reason.trim()}
                          key={decision}
                          onClick={() =>
                            void onShadowReview(proposal.id, scenario.scenario_id, decision)
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
            ))
          )}
        </div>
        <h2 className="section-title mt-5">{t.portfolioAssessments}</h2>
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

export default App;
