import { ArrowUpRight, Play, RefreshCw, Sparkles, Zap } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { RouteMetricStrip } from "../components/ui/RouteMetricStrip";
import type { Copy } from "../i18n/messages";
import { describeError } from "../lib/errors";
import { formatMetricNumber, statusLabel } from "../lib/format";
import { createClientIdempotencyKey } from "../lib/ids";
import type {
  AccessMode,
  EvolutionStatusPayload,
  MissionEvent,
  MissionProjection,
  RaceJudgeRecord,
  RouteMetric
} from "../types";

export default function MissionsEvolutionPage({
  t,
  access,
  bitproConsoleUrl,
  onAuthError
}: {
  t: Copy;
  access: AccessMode;
  bitproConsoleUrl: string;
  onAuthError: (error: unknown) => void;
}) {
  const [evolution, setEvolution] = useState<EvolutionStatusPayload | null>(null);
  const [races, setRaces] = useState<RaceJudgeRecord[]>([]);
  const [missions, setMissions] = useState<MissionProjection[]>([]);
  const [selectedMission, setSelectedMission] = useState<MissionProjection | null>(null);
  const [missionEvents, setMissionEvents] = useState<MissionEvent[]>([]);
  const [missionObjective, setMissionObjective] = useState("");
  const [missionBusy, setMissionBusy] = useState(false);
  const [evoBusy, setEvoBusy] = useState(false);
  const [pageError, setPageError] = useState("");

  const readonly = access === "readonly";

  const reportError = useCallback(
    (error: unknown) => {
      onAuthError(error);
      setPageError(describeError(error, t));
    },
    [onAuthError, t]
  );

  const loadMissionDetail = useCallback(async (mission: MissionProjection) => {
    setSelectedMission(mission);
    const [detailRes, eventsRes] = await Promise.allSettled([
      apiGet<MissionProjection>(`/api/agent/missions/${encodeURIComponent(mission.mission_id)}`),
      apiGet<{ events?: MissionEvent[] }>(
        `/api/agent/missions/${encodeURIComponent(mission.mission_id)}/events?after=0`
      )
    ]);
    if (detailRes.status === "fulfilled") {
      setSelectedMission(detailRes.value);
    }
    if (eventsRes.status === "fulfilled") {
      setMissionEvents(Array.isArray(eventsRes.value.events) ? eventsRes.value.events : []);
    } else {
      setMissionEvents([]);
    }
  }, []);

  const refreshAll = useCallback(
    async (targetMissionId = "") => {
      const [evoRes, raceRes, missionsRes] = await Promise.allSettled([
        apiGet<EvolutionStatusPayload>("/api/v1/arc/evolution?compact=true"),
        apiGet<RaceJudgeRecord[]>("/api/portfolio/race-judge/status"),
        apiGet<{ missions?: MissionProjection[] }>("/api/agent/missions")
      ]);

      if (evoRes.status === "fulfilled") {
        setEvolution(evoRes.value);
      } else {
        onAuthError(evoRes.reason);
      }

      if (raceRes.status === "fulfilled") {
        setRaces(Array.isArray(raceRes.value) ? raceRes.value : []);
      }

      if (missionsRes.status === "fulfilled") {
        const rows = Array.isArray(missionsRes.value.missions) ? missionsRes.value.missions : [];
        setMissions(rows);
        const chosen = rows.find((row) => row.mission_id === targetMissionId) ?? rows[0] ?? null;
        if (chosen) {
          await loadMissionDetail(chosen);
        } else {
          setSelectedMission(null);
          setMissionEvents([]);
        }
      } else {
        onAuthError(missionsRes.reason);
        setMissions([]);
      }
    },
    [loadMissionDetail, onAuthError]
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshAll();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [refreshAll]);

  const applyPreset = async () => {
    setEvoBusy(true);
    setPageError("");
    try {
      await apiPost("/api/v1/arc/evolution/preset", { preset: "production_3slot" });
      await refreshAll(selectedMission?.mission_id ?? "");
    } catch (error) {
      reportError(error);
    } finally {
      setEvoBusy(false);
    }
  };

  const triggerScan = async () => {
    setEvoBusy(true);
    setPageError("");
    try {
      await apiPost("/api/v1/arc/evolution/scan");
      await refreshAll(selectedMission?.mission_id ?? "");
    } catch (error) {
      reportError(error);
    } finally {
      setEvoBusy(false);
    }
  };

  const runRaceJudgeNow = async () => {
    setEvoBusy(true);
    setPageError("");
    try {
      const updated = await apiPost<RaceJudgeRecord[]>("/api/portfolio/race-judge/run-now");
      setRaces(Array.isArray(updated) ? updated : []);
    } catch (error) {
      reportError(error);
    } finally {
      setEvoBusy(false);
    }
  };

  const createMission = async () => {
    const objective = missionObjective.trim();
    if (!objective) return;
    setMissionBusy(true);
    setPageError("");
    try {
      const created = await apiPost<MissionProjection>(
        "/api/agent/missions",
        {
          objective,
          success_criteria: [
            {
              criterion_id: "validated",
              kind: "all_steps_validated",
              description: "所有步骤通过结构化证据验证"
            }
          ]
        },
        { headers: { "Idempotency-Key": createClientIdempotencyKey("web_mission") } }
      );
      setMissionObjective("");
      await refreshAll(created.mission_id);
    } catch (error) {
      reportError(error);
    } finally {
      setMissionBusy(false);
    }
  };

  const runMissionAction = async (action: "run" | "pause" | "resume" | "cancel") => {
    if (!selectedMission) return;
    setMissionBusy(true);
    setPageError("");
    try {
      await apiPost(
        `/api/agent/missions/${encodeURIComponent(selectedMission.mission_id)}/${
          action === "run" ? "run" : "control"
        }`,
        action === "run" ? undefined : { action, reason: "operator_mission_workspace" }
      );
      await refreshAll(selectedMission.mission_id);
    } catch (error) {
      reportError(error);
    } finally {
      setMissionBusy(false);
    }
  };

  const steerMission = async () => {
    if (!selectedMission || !missionObjective.trim()) return;
    setMissionBusy(true);
    setPageError("");
    try {
      await apiPost(
        `/api/agent/missions/${encodeURIComponent(selectedMission.mission_id)}/steer`,
        {
          instruction: missionObjective.trim(),
          reason: "operator_mission_workspace",
          actor: "operator"
        }
      );
      setMissionObjective("");
      await refreshAll(selectedMission.mission_id);
    } catch (error) {
      reportError(error);
    } finally {
      setMissionBusy(false);
    }
  };

  const sourcesList = useMemo(
    () => Object.entries(evolution?.budget?.sources ?? {}),
    [evolution?.budget?.sources]
  );

  const slotTotals = useMemo(() => {
    let used = 0;
    let limit = 0;
    for (const [, src] of sourcesList) {
      used += src.observing_slots ?? 0;
      limit += src.slot_limit ?? 0;
    }
    return { used, limit };
  }, [sourcesList]);

  const routeMetrics = useMemo<RouteMetric[]>(
    () => [
      {
        label: "ARC Evolution",
        value: evolution ? (evolution.config.enabled ? "ENABLED" : "DISABLED") : "—",
        tone: evolution?.config.enabled ? "signal" : "brass"
      },
      {
        label: "3-Slot Occupancy",
        value: sourcesList.length > 0 ? `${slotTotals.used}/${slotTotals.limit}` : "0/0",
        tone: "violet"
      },
      {
        label: "Active Twin Races",
        value: formatMetricNumber(races.length),
        tone: "brass"
      },
      {
        label: "Missions",
        value: formatMetricNumber(missions.length),
        tone: "signal"
      }
    ],
    [evolution, missions.length, races.length, slotTotals.limit, slotTotals.used, sourcesList.length]
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
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="eyebrow">ARC AUTONOMOUS EVOLUTION</div>
            <h2 className="mt-1 text-xl font-bold">{t.arcEvolutionTitle}</h2>
            <p className="mt-1 text-xs text-ink/55">
              {evolution
                ? `rev=${evolution.revision} · provider=${evolution.config.exploration_provider ?? "n/a"} · max_candidates=${evolution.config.max_candidates ?? 3} · daily=${evolution.budget.period_used ?? 0}/${evolution.budget.period_limit ?? evolution.config.max_research_per_day ?? 0}`
                : t.overviewConnecting}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="button-primary"
              disabled={readonly || evoBusy}
              onClick={() => void applyPreset()}
              type="button"
            >
              <Zap size={14} />
              {t.arcApplyPreset}
            </button>
            <button
              className="icon-button"
              disabled={readonly || evoBusy}
              onClick={() => void triggerScan()}
              type="button"
            >
              <Play size={14} />
              {t.arcTriggerScan}
            </button>
            <button
              className="icon-button"
              disabled={evoBusy}
              onClick={() => void refreshAll(selectedMission?.mission_id ?? "")}
              type="button"
            >
              <RefreshCw className={evoBusy ? "animate-spin" : ""} size={14} />
              {t.refresh}
            </button>
            <a
              className="hm-headless-link"
              href={`${bitproConsoleUrl}/ai-lab`}
              rel="noopener noreferrer"
              target="_blank"
            >
              /ai-lab
              <ArrowUpRight size={12} />
            </a>
            <a
              className="hm-headless-link"
              href={`${bitproConsoleUrl}/evolution`}
              rel="noopener noreferrer"
              target="_blank"
            >
              /evolution
              <ArrowUpRight size={12} />
            </a>
          </div>
        </div>

        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink/55">
            {t.arcSlotOccupancy}
          </h3>
          {sourcesList.length === 0 ? (
            <div className="empty-row mt-2">{t.noEvolutionSources}</div>
          ) : (
            <div className="mt-2 grid grid-cols-3 gap-3 max-xl:grid-cols-2 max-md:grid-cols-1">
              {sourcesList.map(([key, src]) => (
                <div
                  className="operator-card block"
                  data-tone={src.failure_streak ? "danger" : src.busy ? "brass" : "signal"}
                  key={key}
                >
                  <div className="flex items-center justify-between gap-2">
                    <strong className="font-mono text-sm">
                      #{src.source_strategy_id} · {src.target_id}
                    </strong>
                    <span className="rounded-full border border-ink/15 px-2 py-0.5 text-xs font-mono">
                      {src.observing_slots}/{src.slot_limit} slots
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-ink/60">
                    <span>open={src.slots_open}</span>
                    <span>cooldown={src.cooldown_hours ?? 0}h</span>
                    {src.in_research ? <span className="text-brass">in_research</span> : null}
                    {src.reason ? <span>{src.reason}</span> : null}
                  </div>
                  {src.active_slot_variants?.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {src.active_slot_variants.map((variant, idx) => (
                        <span className="evidence-chip" key={idx}>
                          {JSON.stringify(variant)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {src.failure_reason ? (
                    <div className="mt-2 text-xs text-danger">
                      streak={src.failure_streak}: {src.failure_reason}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="section-title">{t.raceJudgeTitle}</h2>
            <p className="mt-1 text-xs text-ink/55">
              BitPro Twin Race evaluation · observing / draining / eligible state
            </p>
          </div>
          <button
            className="icon-button"
            disabled={readonly || evoBusy}
            onClick={() => void runRaceJudgeNow()}
            type="button"
          >
            <Sparkles size={14} />
            {t.raceJudgeRunNow}
          </button>
        </div>
        {races.length === 0 ? (
          <div className="empty-row mt-3">{t.noRaces}</div>
        ) : (
          <div className="mt-3 grid grid-cols-2 gap-3 max-lg:grid-cols-1">
            {races.map((race) => (
              <div
                className="operator-card block"
                data-tone={race.eligible ? "signal" : race.state === "cancelled" ? "danger" : "brass"}
                key={`${race.parent_strategy_id}-${race.challenger_strategy_id}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <strong className="font-mono text-xs">
                    #{race.parent_strategy_id} → #{race.challenger_strategy_id}
                    {race.slot_no != null ? ` (Slot ${race.slot_no})` : ""}
                  </strong>
                  <span className="rounded-full border border-ink/15 px-2 py-0.5 text-xs">
                    {statusLabel(race.state)}
                  </span>
                </div>
                <div className="mt-1 text-xs text-ink/70">
                  {race.parent_name || "Parent"} vs {race.challenger_name || "Challenger"}
                </div>
                <div className="mt-2 flex flex-wrap gap-3 font-mono text-xs text-ink/55">
                  <span>
                    obs={race.observed_hours ?? 0}/{race.target_hours ?? 337}h
                  </span>
                  {race.excess_return_pct != null ? (
                    <span>excess={race.excess_return_pct.toFixed(2)}%</span>
                  ) : null}
                  {race.sign_test_p != null ? <span>p={race.sign_test_p.toFixed(4)}</span> : null}
                  <span>eligible={String(race.eligible)}</span>
                </div>
                {race.reason ? <p className="mt-1 text-xs text-ink/55">{race.reason}</p> : null}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="eyebrow">MISSION / TASK OS</div>
            <h2 className="mt-1 text-xl font-bold">{t.missions}</h2>
            <p className="mt-1 text-sm text-ink/55">
              {t.missionObjective}、Plan、Evidence 和控制事件在同一条可回放时间线上。
            </p>
          </div>
          <span className="rounded-full border border-ink/15 px-2.5 py-1 text-xs text-ink/65">
            {readonly ? t.readOnlyBadge : "governed"}
          </span>
        </div>
        <div className="mt-4 grid grid-cols-[1fr_auto] gap-2 max-md:grid-cols-1">
          <input
            className="field-light"
            onChange={(event) => setMissionObjective(event.target.value)}
            placeholder={t.missionObjective}
            value={missionObjective}
          />
          <button
            className="icon-button justify-center"
            disabled={readonly || missionBusy}
            onClick={() => void (selectedMission ? steerMission() : createMission())}
            type="button"
          >
            <Sparkles size={14} />
            {selectedMission ? t.missionSteer : t.missionCreate}
          </button>
        </div>
      </section>

      <div className="grid grid-cols-[260px_1fr] gap-5 max-lg:grid-cols-1">
        <div className="panel">
          <div className="section-title">MISSIONS</div>
          <div className="mt-3 space-y-2">
            {missions.length === 0 ? (
              <div className="empty-row">{t.missionNoData}</div>
            ) : (
              missions.map((mission) => (
                <button
                  className={`operator-card w-full text-left ${
                    selectedMission?.mission_id === mission.mission_id ? "border-accent/60" : ""
                  }`}
                  data-tone={mission.status === "failed" ? "danger" : "signal"}
                  key={mission.mission_id}
                  onClick={() => void loadMissionDetail(mission)}
                  type="button"
                >
                  <strong className="block truncate font-mono text-xs">{mission.mission_id}</strong>
                  <span className="mt-1 block truncate text-sm text-ink/75">{mission.objective}</span>
                  <span className="mt-2 inline-flex rounded border border-ink/15 px-2 py-0.5 text-[11px] text-ink/55">
                    {statusLabel(mission.status)}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="space-y-5">
          {selectedMission ? (
            <>
              <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
                <div className="operator-card" data-tone="signal">
                  <span>STATUS</span>
                  <strong>{statusLabel(selectedMission.status)}</strong>
                </div>
                <div className="operator-card" data-tone="brass">
                  <span>PLAN</span>
                  <strong>v{selectedMission.active_plan_version ?? 0}</strong>
                </div>
                <div className="operator-card" data-tone="violet">
                  <span>TOKENS</span>
                  <strong>{formatMetricNumber(selectedMission.usage?.tokens ?? 0)}</strong>
                </div>
                <div className="operator-card" data-tone="signal">
                  <span>TOOLS</span>
                  <strong>{formatMetricNumber(selectedMission.usage?.tool_calls ?? 0)}</strong>
                </div>
              </div>
              <div className="panel">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h3 className="section-title">{t.missionPlan}</h3>
                  <div className="flex flex-wrap gap-2">
                    {selectedMission.status === "draft" || selectedMission.status === "paused" ? (
                      <button
                        className="icon-button"
                        disabled={readonly || missionBusy}
                        onClick={() =>
                          void runMissionAction(selectedMission.status === "draft" ? "run" : "resume")
                        }
                        type="button"
                      >
                        {selectedMission.status === "draft" ? t.missionRun : t.missionResume}
                      </button>
                    ) : null}
                    {selectedMission.status === "running" ? (
                      <button
                        className="icon-button"
                        disabled={readonly || missionBusy}
                        onClick={() => void runMissionAction("pause")}
                        type="button"
                      >
                        {t.missionPause}
                      </button>
                    ) : null}
                    {!["completed", "failed", "canceled", "budget_exhausted"].includes(
                      selectedMission.status
                    ) ? (
                      <button
                        className="icon-button border-danger/30 text-danger"
                        disabled={readonly || missionBusy}
                        onClick={() => void runMissionAction("cancel")}
                        type="button"
                      >
                        {t.missionCancel}
                      </button>
                    ) : null}
                  </div>
                </div>
                <div className="mt-3 space-y-2">
                  {(selectedMission.plans?.at(-1)?.steps ?? []).map((step) => {
                    const attempt = selectedMission.attempts?.find(
                      (item) => item.step_id === step.step_id
                    );
                    return (
                      <div
                        className="operator-card operator-card-compact"
                        data-tone={attempt?.status === "succeeded" ? "signal" : "brass"}
                        key={step.step_id}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <strong className="font-mono text-sm">{step.step_id}</strong>
                          <span className="text-xs text-ink/55">
                            {statusLabel(attempt?.status ?? "pending")}
                          </span>
                        </div>
                        <div className="mt-1 text-sm text-ink/75">{step.title}</div>
                        <div className="mt-1 text-xs text-ink/50">{step.capability_id}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
                <div className="panel">
                  <h3 className="section-title">{t.missionEvents}</h3>
                  <div className="mt-3 max-h-64 space-y-2 overflow-auto">
                    {missionEvents.length === 0 ? (
                      <div className="empty-row">—</div>
                    ) : (
                      missionEvents.map((event) => (
                        <div className="trace-row" key={event.sequence}>
                          <span className="font-mono text-xs text-brass">#{event.sequence}</span>
                          <span className="text-sm">{event.event_type}</span>
                          <span className="ml-auto text-xs text-ink/50">
                            {event.actor ?? "runtime"}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
                <div className="panel">
                  <h3 className="section-title">{t.missionEvidence}</h3>
                  <div className="mt-3 space-y-2 text-sm">
                    <div className="mini-block">
                      <span>Artifact refs</span>
                      <strong>{formatMetricNumber(selectedMission.artifact_refs?.length ?? 0)}</strong>
                    </div>
                    <div className="mini-block">
                      <span>Unknowns</span>
                      <strong>{formatMetricNumber(selectedMission.unknowns?.length ?? 0)}</strong>
                    </div>
                    <div className="text-xs text-ink/55">
                      {(selectedMission.unknowns ?? []).join(" · ") || "No unknowns recorded"}
                    </div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="panel empty-row">{t.missionNoData}</div>
          )}
        </div>
      </div>
    </div>
  );
}
