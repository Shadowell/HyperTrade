import { AlertTriangle, CheckCircle2, Cpu, RefreshCw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { RouteMetricStrip } from "../components/ui/RouteMetricStrip";
import type { Copy } from "../i18n/messages";
import { describeError } from "../lib/errors";
import { formatAge, formatMetricNumber, statusLabel } from "../lib/format";
import type {
  AccessMode,
  EvolutionAlert,
  HarnessOverview,
  HealthzPayload,
  Language,
  MonitorAlert,
  RouteMetric,
  RuntimeErrorRecord
} from "../types";

export default function SystemDiagnosticsPage({
  t,
  language,
  overview,
  healthz,
  onRefreshHealthz,
  access,
  onAuthError
}: {
  t: Copy;
  language: Language;
  overview: HarnessOverview | null;
  healthz: HealthzPayload | null;
  onRefreshHealthz: () => Promise<void>;
  access: AccessMode;
  onAuthError: (error: unknown) => void;
}) {
  const [monitorAlerts, setMonitorAlerts] = useState<MonitorAlert[]>([]);
  const [arcAlerts, setArcAlerts] = useState<EvolutionAlert[]>([]);
  const [runtimeErrors, setRuntimeErrors] = useState<RuntimeErrorRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [pageError, setPageError] = useState("");

  const readonly = access === "readonly";

  const refreshDiagnostics = useCallback(async () => {
    setBusy(true);
    const [alertsRes, arcAlertsRes, runtimeErrRes] = await Promise.allSettled([
      apiGet<{ items?: MonitorAlert[] }>("/api/alerts"),
      apiGet<{ alerts?: EvolutionAlert[] }>("/api/v1/arc/evolution/alerts"),
      apiGet<{ items?: RuntimeErrorRecord[] }>("/api/v1/arc/runtime-errors")
    ]);

    if (alertsRes.status === "fulfilled") {
      setMonitorAlerts(Array.isArray(alertsRes.value.items) ? alertsRes.value.items : []);
    } else {
      setMonitorAlerts([]);
    }

    if (arcAlertsRes.status === "fulfilled") {
      setArcAlerts(Array.isArray(arcAlertsRes.value.alerts) ? arcAlertsRes.value.alerts : []);
    } else {
      onAuthError(arcAlertsRes.reason);
      setArcAlerts([]);
    }

    if (runtimeErrRes.status === "fulfilled") {
      setRuntimeErrors(Array.isArray(runtimeErrRes.value.items) ? runtimeErrRes.value.items : []);
    } else {
      onAuthError(runtimeErrRes.reason);
      setRuntimeErrors([]);
    }

    setBusy(false);
  }, [onAuthError]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshDiagnostics();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshDiagnostics]);

  const ackEvolutionAlert = async (alertId: string) => {
    setPageError("");
    try {
      await apiPost(`/api/v1/arc/evolution/alerts/${encodeURIComponent(alertId)}/ack`);
      await refreshDiagnostics();
    } catch (error) {
      onAuthError(error);
      setPageError(describeError(error, t));
    }
  };

  const instances = healthz?.workers?.instances ?? [];
  const workerStatus = healthz?.workers?.status ?? "unknown";
  const openArcAlerts = arcAlerts.filter((a) => a.status === "open" || a.status === "tracking");
  const evals = overview?.evals;

  const routeMetrics = useMemo<RouteMetric[]>(
    () => [
      {
        label: t.workerLoops,
        value: statusLabel(workerStatus),
        tone: workerStatus === "stale" ? "danger" : workerStatus === "alive" ? "signal" : "brass"
      },
      {
        label: t.currentAlerts,
        value: formatMetricNumber(monitorAlerts.length + openArcAlerts.length),
        tone: monitorAlerts.length + openArcAlerts.length > 0 ? "danger" : "signal"
      },
      {
        label: t.runtimeErrorsTitle,
        value: formatMetricNumber(runtimeErrors.length),
        tone: runtimeErrors.length > 0 ? "danger" : "signal"
      },
      {
        label: t.deterministicEvals,
        value: statusLabel(evals?.research_os?.status ?? evals?.status ?? "not_loaded"),
        tone: evals?.research_os?.status === "passed" ? "signal" : "brass"
      }
    ],
    [evals, monitorAlerts.length, openArcAlerts.length, runtimeErrors.length, t, workerStatus]
  );

  return (
    <div className="space-y-5">
      <RouteMetricStrip label={t.pageMetrics} metrics={routeMetrics} />

      {pageError ? (
        <div className="operator-card" data-tone="danger" role="alert">
          <span>{t.errorGeneric}</span>
          <strong>{pageError}</strong>
        </div>
      ) : null}

      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="section-title">{t.workerMatrixTitle}</h2>
            <p className="mt-1 text-xs text-ink/55">
              DB: {statusLabel(healthz?.database?.status)} ({healthz?.database?.latency_ms ?? 0}ms) ·
              BitPro: {String(healthz?.adapters?.bitpro?.status ?? "unknown")} ·
              QuantLab: {String(healthz?.adapters?.quantlab?.status ?? "unknown")}
            </p>
          </div>
          <button
            className="icon-button"
            disabled={busy}
            onClick={() => void Promise.all([onRefreshHealthz(), refreshDiagnostics()])}
            type="button"
          >
            <RefreshCw className={busy ? "animate-spin" : ""} size={14} />
            {t.refresh}
          </button>
        </div>

        {instances.length === 0 ? (
          <div className="empty-row mt-4">{t.workerUnavailable}</div>
        ) : (
          <div className="mt-4 space-y-4">
            {instances.map((inst) => (
              <div
                className="operator-card block"
                data-tone={
                  inst.stale || inst.failing_components.length > 0 ? "danger" : "signal"
                }
                key={inst.worker_id}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Cpu size={15} className="text-accent" />
                    <strong className="font-mono text-sm">{inst.worker_id}</strong>
                  </div>
                  <div className="flex flex-wrap gap-2 text-xs font-mono text-ink/60">
                    <span>{inst.stale ? "STALE" : "ALIVE"}</span>
                    <span>age={inst.heartbeat_age_seconds}s</span>
                    <span>uptime={formatAge(inst.uptime_seconds)}</span>
                    <span>stalls={inst.stalls_total}</span>
                    {inst.event_loop_lag_max_seconds != null ? (
                      <span>lag={inst.event_loop_lag_max_seconds.toFixed(3)}s</span>
                    ) : null}
                  </div>
                </div>

                {inst.last_stall ? (
                  <div className="mt-3 rounded-lg border border-danger/30 bg-danger/5 p-3 text-xs">
                    <div className="font-semibold text-danger">
                      Last Stall: {inst.last_stall.seconds}s (age {inst.last_stall.age_seconds ?? "?"}s)
                      {inst.last_stall.cause ? ` · ${String(inst.last_stall.cause)}` : ""}
                    </div>
                    {inst.last_stall.running?.length ? (
                      <pre className="mt-2 overflow-auto font-mono text-[11px] text-ink/75">
                        {inst.last_stall.running.join("\n")}
                      </pre>
                    ) : null}
                  </div>
                ) : null}

                <div className="mt-3 grid grid-cols-3 gap-2 max-lg:grid-cols-2 max-sm:grid-cols-1">
                  {Object.entries(inst.components ?? {}).map(([name, comp]) => (
                    <div
                      className="rounded-lg border border-ink/10 bg-paper px-3 py-2 text-xs"
                      key={name}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-mono font-semibold">{name}</span>
                        <span
                          className={
                            comp.consecutive_failures > 0 ? "text-danger font-bold" : "text-signal"
                          }
                        >
                          {comp.consecutive_failures > 0
                            ? `fail×${comp.consecutive_failures}`
                            : "ok"}
                        </span>
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-ink/55">
                        last_ok={formatAge(comp.last_ok_age_seconds)} · restarts={comp.restarts_total}
                        {comp.last_error_type ? ` · ${comp.last_error_type}` : ""}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-2 gap-5 max-xl:grid-cols-1">
        <section className="panel">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">{t.alertStatus}</h2>
              <p className="mt-1 text-sm text-ink/55">{t.alertStatusHint}</p>
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
                  data-tone={
                    ["critical", "high", "severe", "error"].includes(
                      (alert.severity ?? "").toLowerCase()
                    )
                      ? "danger"
                      : "brass"
                  }
                  key={alert.id ?? `${alert.code}-${index}`}
                >
                  <span className="font-mono text-xs text-ink/55">{alert.severity ?? "info"}</span>
                  <div className="min-w-0">
                    <div className="font-semibold">{alert.title ?? alert.code ?? "alert"}</div>
                    <div className="truncate text-xs text-ink/60">
                      {alert.message ?? alert.source_id ?? "n/a"}
                    </div>
                  </div>
                  <span className="rounded border border-ink/15 px-2 py-0.5 text-xs">
                    {alert.source_id ?? alert.id ?? "n/a"}
                  </span>
                </div>
              ))
            )}
          </div>

          <h3 className="mt-5 text-xs font-semibold uppercase text-ink/55">
            {t.arcAlertsTitle} ({arcAlerts.length})
          </h3>
          <div className="mt-2 space-y-2">
            {arcAlerts.length === 0 ? (
              <div className="empty-row">{t.noArcAlerts}</div>
            ) : (
              arcAlerts.map((alert) => (
                <div
                  className="operator-card status-row"
                  data-tone={alert.status === "acknowledged" ? "signal" : "danger"}
                  key={alert.id}
                >
                  <div className="min-w-0">
                    <div className="font-mono text-xs font-semibold">
                      {alert.code}
                      {alert.strategy_id != null ? ` · #${alert.strategy_id}` : ""}
                    </div>
                    <div className="text-xs text-ink/65">{alert.message}</div>
                  </div>
                  {alert.status === "open" || alert.status === "tracking" ? (
                    <button
                      className="icon-button shrink-0"
                      disabled={readonly || busy}
                      onClick={() => void ackEvolutionAlert(alert.id)}
                      type="button"
                    >
                      {t.ackAlert}
                    </button>
                  ) : (
                    <span className="text-xs text-signal">{statusLabel(alert.status)}</span>
                  )}
                </div>
              ))
            )}
          </div>
        </section>

        <section className="panel">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">{t.runtimeErrorsTitle}</h2>
              <p className="mt-1 text-sm text-ink/55">
                {language === "zh"
                  ? "Worker / AVO / Ablation 异常堆栈去重台账"
                  : "Deduplicated Worker / AVO / Ablation runtime exception journal"}
              </p>
            </div>
            <ShieldAlert size={18} className="text-danger" />
          </div>
          <div className="mt-4 space-y-2">
            {runtimeErrors.length === 0 ? (
              <div className="empty-row">{t.noRuntimeErrors}</div>
            ) : (
              runtimeErrors.map((err) => (
                <div className="operator-card block" data-tone="danger" key={err.error_id}>
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="font-mono font-semibold">
                      {err.component} · {err.exception_type}
                    </span>
                    <span className="font-mono text-ink/55">×{err.occurrences}</span>
                  </div>
                  <div className="mt-1 text-sm text-ink/80">{err.message}</div>
                  {err.mission_id ? (
                    <div className="mt-1 font-mono text-[11px] text-ink/55">
                      mission={err.mission_id}
                    </div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="section-title">{t.deterministicEvals}</h2>
            <p className="mt-1 text-sm text-ink/55">
              {language === "zh"
                ? "只读展示 cohort、口径版本与失败分类；评分逻辑由服务端统一执行。"
                : "Read-only cohorts, metric version, and failure classes scored by the server."}
            </p>
          </div>
          <CheckCircle2 className="text-signal" size={18} />
        </div>
        <div className="mt-4 grid grid-cols-4 gap-3 max-md:grid-cols-2">
          <div className="mini-block">
            <span>{language === "zh" ? "总用例" : "Cases"}</span>
            <strong className="font-mono">{formatMetricNumber(evals?.case_count ?? 0)}</strong>
          </div>
          <div className="mini-block">
            <span>{language === "zh" ? "确定性门禁" : "Deterministic gate"}</span>
            <strong>{statusLabel(evals?.research_os?.status ?? evals?.status)}</strong>
          </div>
          <div className="mini-block">
            <span>{language === "zh" ? "Provider 基线" : "Provider baseline"}</span>
            <strong className="font-mono">{evals?.quality?.provider_baseline ?? "not_loaded"}</strong>
          </div>
          <div className="mini-block">
            <span>{language === "zh" ? "质量合约" : "Quality contract"}</span>
            <strong className="font-mono">{evals?.quality?.metric_contract ?? "n/a"}</strong>
          </div>
        </div>
        <div className="operator-card operator-card-compact mt-4" data-tone="brass">
          <span>{t.runtimeBoundaryLabel}</span>
          <strong>
            {overview?.headless_mode
              ? language === "zh"
                ? `无头控制平面模式 · 实盘写入${overview?.bitpro?.live_write_enabled ? "已授权" : "受审批门禁保护"} · Worker ${statusLabel(workerStatus)}`
                : `Headless control plane · Live writes ${overview?.bitpro?.live_write_enabled ? "enabled" : "gated"} · Worker ${workerStatus}`
              : language === "zh"
                ? `标准运行模式 · 实盘写入${overview?.bitpro?.live_write_enabled ? "已授权" : "受审批门禁保护"} · Worker ${statusLabel(workerStatus)}`
                : `Standard mode · Live writes ${overview?.bitpro?.live_write_enabled ? "enabled" : "gated"} · Worker ${workerStatus}`}
          </strong>
        </div>
      </section>
    </div>
  );
}
