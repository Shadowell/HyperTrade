import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  Bell,
  Brain,
  Clock3,
  Cpu,
  Languages,
  Menu,
  Moon,
  RefreshCw,
  ShieldCheck,
  Sun,
  TerminalSquare
} from "lucide-react";
import { type MouseEvent, type ReactNode, useState } from "react";
import { useNow } from "../../hooks/useNow";
import type { Copy } from "../../i18n/messages";
import { statusLabel } from "../../lib/format";
import { sectionPath } from "../../lib/routes";
import type { AccessMode, HarnessOverview, HealthzPayload, Language, NavSection, ThemeMode } from "../../types";
import { AccessBadge, type SyncState } from "../agent/HarnessHeader";
import { HyperBrandMark } from "../ui/HyperBrandMark";

const NAV_TABS: Array<{
  id: NavSection;
  icon: typeof TerminalSquare;
  colorClass: string;
}> = [
  { id: "harness", icon: TerminalSquare, colorClass: "tab-color-orange" },
  { id: "missions", icon: Activity, colorClass: "tab-color-cyan" },
  { id: "knowledge", icon: Brain, colorClass: "tab-color-violet" },
  { id: "system", icon: AlertTriangle, colorClass: "tab-color-amber" }
];

function LiveClock({ language }: { language: Language }) {
  const now = useNow(1000);
  const formatted =
    now === null
      ? "--:--:--"
      : new Date(now).toLocaleTimeString(language === "zh" ? "zh-CN" : "en-US", {
          hour12: false
        });
  return (
    <span className="clock">
      <Clock3 size={14} />
      {formatted}
    </span>
  );
}

export function ConsoleShell({
  t,
  language,
  onToggleLanguage,
  theme,
  onToggleTheme,
  activeSection,
  onNavigate,
  sync,
  overview,
  healthz,
  refreshing,
  onRefresh,
  access,
  bitproConsoleUrl,
  children
}: {
  t: Copy;
  language: Language;
  onToggleLanguage: () => void;
  theme: ThemeMode;
  onToggleTheme: () => void;
  activeSection: NavSection;
  onNavigate: (section: NavSection, event?: MouseEvent<HTMLElement>) => void;
  sync: SyncState;
  overview: HarnessOverview | null;
  healthz: HealthzPayload | null;
  refreshing: boolean;
  onRefresh: () => void;
  access: AccessMode;
  bitproConsoleUrl: string;
  children: ReactNode;
}) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const workerStatus = healthz?.workers?.status ?? "unknown";
  const failingComponents = healthz?.workers?.failing_components ?? [];
  const workerInstances = healthz?.workers?.instances ?? [];
  const totalStalls = workerInstances.reduce((sum, item) => sum + (item.stalls_total ?? 0), 0);

  const probe = overview?.bitpro?.live_probe;
  const probeHealthy = Boolean(probe?.reachable && probe?.authenticated);

  const unreadSignalCount =
    failingComponents.length +
    (workerStatus === "stale" ? 1 : 0) +
    (probe && !probeHealthy ? 1 : 0);

  const globalStatusClass =
    sync === "unavailable" || workerStatus === "stale" || failingComponents.length > 0
      ? "danger"
      : sync === "ready"
        ? "healthy"
        : "";
  const globalStatusLabel =
    sync === "unavailable"
      ? t.overviewUnavailable
      : sync === "connecting"
        ? t.overviewConnecting
        : workerStatus === "alive"
          ? `${workerInstances.length} Worker ${statusLabel("alive")}`
          : failingComponents.length > 0
            ? `${failingComponents.length} ${t.stale}`
            : language === "zh"
              ? "控制面在线"
              : "ONLINE";

  const activeTabMeta = NAV_TABS.find((item) => item.id === activeSection) ?? NAV_TABS[0];
  const ActiveTabIcon = activeTabMeta.icon;
  const tabLabel = (id: NavSection): string => t[id];

  return (
    <div className="hm-shell">
      <header className="hm-topbar">
        <div className="hm-topbar-left">
          <a
            className="brand"
            href="/harness"
            onClick={(event) => onNavigate("harness", event)}
          >
            <HyperBrandMark />
            <span>
              HYPER<span className="brand-light">TRADE</span>
            </span>
            <span className="brand-tag">{t.controlPlaneTag}</span>
          </a>
        </div>

        <div className="hm-top-right">
          <div className="topbar-actions">
            <a
              className="hm-headless-link"
              href={`${bitproConsoleUrl}/ai-lab`}
              rel="noopener noreferrer"
              target="_blank"
            >
              AI Lab
              <ArrowUpRight size={12} />
            </a>
            <a
              className="hm-headless-link"
              href={`${bitproConsoleUrl}/evolution`}
              rel="noopener noreferrer"
              target="_blank"
            >
              Evolution
              <ArrowUpRight size={12} />
            </a>
            <button
              aria-label={t.toggleTheme}
              className="topbar-tool-btn"
              onClick={onToggleTheme}
              title={theme === "dark" ? t.themeLight : t.themeDark}
              type="button"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              aria-label={language === "zh" ? "Switch to English" : "切换中文界面"}
              className="topbar-lang-btn"
              onClick={onToggleLanguage}
              type="button"
            >
              <Languages size={14} />
              <span>{language === "zh" ? "EN" : "中文"}</span>
            </button>
            <button
              aria-label={t.monitorAlerts}
              className="topbar-tool-btn topbar-bell-btn"
              onClick={() => onNavigate("system")}
              title={t.monitorAlerts}
              type="button"
            >
              <Bell size={16} />
              {unreadSignalCount > 0 ? <span className="bell-badge" /> : null}
            </button>
          </div>

          <span className="topbar-console-pill">{t.consolePill}</span>
          <span className={`global-status ${globalStatusClass}`}>{globalStatusLabel}</span>
          <LiveClock language={language} />
          <button
            aria-label={t.refresh}
            className="refresh-button"
            disabled={refreshing}
            onClick={onRefresh}
            title={t.refresh}
            type="button"
          >
            <RefreshCw className={refreshing ? "animate-spin" : ""} size={15} />
          </button>
          <AccessBadge access={access} t={t} />
        </div>
      </header>

      <div className="hm-sub-topbar">
        <div className="sub-topbar-left">
          <button
            aria-expanded={!sidebarCollapsed}
            aria-label={t.toggleSidebar}
            className="sub-toggle-btn"
            onClick={() => setSidebarCollapsed((value) => !value)}
            type="button"
          >
            <Menu size={16} />
          </button>
          <div className="breadcrumb-trail">
            <span className="breadcrumb-root">{t.product}</span>
            <span className="breadcrumb-sep">/</span>
            <span className="breadcrumb-current">
              <ActiveTabIcon size={14} />
              <span>{tabLabel(activeSection)}</span>
            </span>
          </div>
        </div>

        <div className="hm-headless-strip" aria-label={t.headlessTitle}>
          <span>{t.headlessNotice}</span>
          <a
            className="hm-headless-link"
            href={`${bitproConsoleUrl}/ai-lab`}
            rel="noopener noreferrer"
            target="_blank"
          >
            {t.headlessAiLabLink}
            <ArrowUpRight size={12} />
          </a>
          <a
            className="hm-headless-link"
            href={`${bitproConsoleUrl}/evolution`}
            rel="noopener noreferrer"
            target="_blank"
          >
            {t.headlessEvolutionLink}
            <ArrowUpRight size={12} />
          </a>
        </div>

        <div className="pinned-tab-pill">
          <ActiveTabIcon size={13} />
          <span>{tabLabel(activeSection)}</span>
          <span className="pinned-tab-dot" />
        </div>
      </div>

      <div className={`hm-layout ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        <aside className="hm-sidebar lg:sticky lg:top-0 lg:h-[calc(100dvh-110px)] lg:self-start lg:overflow-y-auto">
          <div className="side-heading">
            <span className="eyebrow">{t.workspaceEyebrow}</span>
            <h2>{t.workspaceTitle}</h2>
          </div>
          <nav aria-label={t.workspaceTitle} className="hm-nav">
            {NAV_TABS.map((item) => {
              const Icon = item.icon;
              const isActive = activeSection === item.id;
              return (
                <a
                  className={`hm-tab ${item.colorClass} ${isActive ? "active nav-item-active" : ""}`}
                  href={sectionPath(item.id)}
                  key={item.id}
                  onClick={(event) => onNavigate(item.id, event)}
                >
                  <span className="hm-tab-icon-badge">
                    <Icon size={15} />
                  </span>
                  <span>{tabLabel(item.id)}</span>
                  <span className="hm-tab-arrow">
                    <ArrowRight size={13} />
                  </span>
                </a>
              );
            })}
          </nav>
          <div className="side-foot">
            <span className="pulse-dot" />
            <span>
              {overview?.generated_at
                ? `${t.lastSync}: ${new Date(overview.generated_at).toLocaleTimeString(
                    language === "zh" ? "zh-CN" : "en-US",
                    { hour12: false }
                  )}`
                : t.overviewConnecting}
            </span>
          </div>
        </aside>

        <main className="hm-workspace">{children}</main>

        <div aria-label={t.signalsRail} className="hm-signals-rail">
          <section className="hm-rail-section">
            <div className="hm-rail-heading">
              <div>
                <span className="eyebrow">SIGNALS</span>
                <h2>{t.signalsAlerts}</h2>
              </div>
              <span className={`hm-rail-badge ${unreadSignalCount > 0 ? "active" : ""}`}>
                {unreadSignalCount}
              </span>
            </div>
            <div className="space-y-2 text-xs">
              <div className="mini-block">
                <span>{t.signalsProbe}</span>
                <strong className={probeHealthy ? "text-signal" : "text-ink/70"}>
                  {probe
                    ? probeHealthy
                      ? `${t.mcpLiveOnline}${probe.latency_ms != null ? ` · ${Math.round(probe.latency_ms)} ms` : ""}`
                      : probe.reachable
                        ? t.mcpLiveAuthFailed
                        : t.mcpLiveUnreachable
                    : overview?.bitpro?.token_configured
                      ? t.mcpTokenReady
                      : t.missing}
                </strong>
              </div>
              <div className="mini-block">
                <span>{t.signalsWorkers}</span>
                <strong className="flex items-center gap-1.5">
                  <Cpu size={13} className="text-accent" />
                  <span>
                    {healthz
                      ? `${statusLabel(workerStatus)} · ${workerInstances.length} inst · ${totalStalls} stalls`
                      : statusLabel("unknown")}
                  </span>
                </strong>
              </div>
              {failingComponents.length > 0 ? (
                <div className="operator-card operator-card-compact" data-tone="danger">
                  <span>Failing Loops</span>
                  <strong className="font-mono text-xs">{failingComponents.join(", ")}</strong>
                </div>
              ) : null}
            </div>
          </section>

          <section className="hm-rail-section">
            <div className="hm-rail-heading">
              <div>
                <span className="eyebrow">MISSIONS & MEMORY</span>
                <h2>{t.missionsAndRuns}</h2>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="mini-block">
                <span>Missions</span>
                <strong className="font-mono">
                  {overview?.missions_summary?.active_count ?? 0} /{" "}
                  {overview?.missions_summary?.total_count ?? overview?.agent_runs.total_count ?? 0}
                </strong>
              </div>
              <div className="mini-block">
                <span>Cognitive</span>
                <strong className="font-mono">
                  {(overview?.memory.cognitive?.active_semantic_count ?? 0) +
                    (overview?.memory.cognitive?.episodic_count ?? 0)}
                </strong>
              </div>
            </div>
          </section>

          <div className="hm-rail-foot">
            <ShieldCheck size={14} className="shrink-0 text-signal" />
            <span>{t.signalsFoot}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
