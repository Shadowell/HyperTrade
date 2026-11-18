import { Archive, Brain, FileText, MemoryStick } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiGet, apiPost } from "../api/client";
import { GovernanceReview } from "../components/knowledge/GovernanceReview";
import { MemoryObservatory } from "../components/knowledge/MemoryObservatory";
import { EvidenceMetric, SourceIdStrip } from "../components/report/StructuredReport";
import { RouteMetricStrip } from "../components/ui/RouteMetricStrip";
import type { Copy } from "../i18n/messages";
import { describeError } from "../lib/errors";
import {
  cascadeStyle,
  formatMetricNumber,
  formatPercentValue,
  metricTone
} from "../lib/format";
import { renderMarkdown } from "../lib/markdown";
import { strategyEvidenceSelection } from "../lib/report";
import { formatTimestamp } from "../lib/time";
import type {
  AccessMode,
  CognitiveMemoryCounts,
  CognitiveMemoryItem,
  EvidenceSelection,
  HarnessOverview,
  Language,
  MemoryAssertion,
  MemoryItem,
  MemoryPayload,
  RagHit,
  RouteMetric,
  SkillProposal,
  SkillRelease,
  StrategyLibraryPayload
} from "../types";

export default function KnowledgeMemoryPage({
  t,
  language,
  overview,
  access,
  onAuthError
}: {
  t: Copy;
  language: Language;
  overview: HarnessOverview | null;
  access: AccessMode;
  onAuthError: (error: unknown) => void;
}) {
  const [memoryItems, setMemoryItems] = useState<MemoryItem[]>([]);
  const [memoryInventoryItems, setMemoryInventoryItems] = useState<MemoryItem[]>([]);
  const [cognitiveCounts, setCognitiveCounts] = useState<CognitiveMemoryCounts | undefined>(
    overview?.memory.cognitive
  );
  const [cognitiveItems, setCognitiveItems] = useState<CognitiveMemoryItem[]>([]);
  const [selectedMemoryId, setSelectedMemoryId] = useState("");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryKind, setMemoryKind] = useState("");
  const [memoryTag, setMemoryTag] = useState("");
  const [memoryAssertions, setMemoryAssertions] = useState<MemoryAssertion[]>([]);
  const [skillProposals, setSkillProposals] = useState<SkillProposal[]>([]);
  const [skillReleases, setSkillReleases] = useState<SkillRelease[]>([]);
  const [governanceReason, setGovernanceReason] = useState("");
  const [ragQuery, setRagQuery] = useState("risk");
  const [ragHits, setRagHits] = useState<RagHit[]>([]);
  const [strategyLibrary, setStrategyLibrary] = useState<StrategyLibraryPayload>({
    source: "memory.strategy_knowledge",
    memory_count: 0,
    items: []
  });
  const [strategyQuery, setStrategyQuery] = useState("");
  const [evidenceSelection, setEvidenceSelection] = useState<EvidenceSelection | null>(null);
  const [pageError, setPageError] = useState("");

  const fetchMemory = useCallback(async (query = "", kind = "", tag = "") => {
    const params = new URLSearchParams();
    if (query.trim()) params.set("query", query.trim());
    if (kind.trim()) params.set("kind", kind.trim());
    if (tag.trim()) params.set("tag", tag.trim());
    const qs = params.toString();
    const payload = await apiGet<MemoryPayload>(qs ? `/api/memory?${qs}` : "/api/memory");
    const items = Array.isArray(payload.items) ? payload.items : [];
    setMemoryItems(items);
    if (!qs) {
      setMemoryInventoryItems(items);
    }
    if (payload.cognitive) {
      setCognitiveCounts(payload.cognitive);
    }
    if (Array.isArray(payload.cognitive_items)) {
      setCognitiveItems(payload.cognitive_items);
    }
    setSelectedMemoryId((current) => current || items[0]?.id || "");
  }, []);

  const fetchGovernance = useCallback(async () => {
    const [assertionsRes, proposalsRes, releasesRes] = await Promise.allSettled([
      apiGet<{ items?: MemoryAssertion[] }>("/api/memory/assertions"),
      apiGet<{ items?: SkillProposal[] }>("/api/skills/proposals"),
      apiGet<{ items?: SkillRelease[] }>("/api/skills/releases")
    ]);
    if (assertionsRes.status === "fulfilled") {
      setMemoryAssertions(assertionsRes.value.items ?? []);
    } else {
      onAuthError(assertionsRes.reason);
    }
    if (proposalsRes.status === "fulfilled") {
      setSkillProposals(proposalsRes.value.items ?? []);
    } else {
      onAuthError(proposalsRes.reason);
    }
    if (releasesRes.status === "fulfilled") {
      setSkillReleases(releasesRes.value.items ?? []);
    } else {
      onAuthError(releasesRes.reason);
    }
  }, [onAuthError]);

  const fetchStrategyLibrary = useCallback(async (query = "") => {
    const suffix = query.trim() ? `?query=${encodeURIComponent(query.trim())}` : "";
    const payload = await apiGet<StrategyLibraryPayload>(`/api/strategy/library${suffix}`);
    setStrategyLibrary({
      source: payload.source ?? "memory.strategy_knowledge",
      memory_count: payload.memory_count ?? 0,
      items: Array.isArray(payload.items) ? payload.items : []
    });
  }, []);

  const fetchRag = useCallback(async (query: string) => {
    const payload = await apiGet<{ hits?: RagHit[] }>(
      `/api/rag/search?query=${encodeURIComponent(query)}`
    );
    setRagHits(Array.isArray(payload.hits) ? payload.hits : []);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void Promise.allSettled([
        fetchMemory("", "", ""),
        fetchGovernance(),
        fetchStrategyLibrary(""),
        fetchRag("risk")
      ]);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [fetchGovernance, fetchMemory, fetchRag, fetchStrategyLibrary]);

  const handleGovernanceDecision = async (
    resource: "assertion" | "skill",
    resourceId: string,
    decision: "approve" | "reject" | "dispute"
  ) => {
    const reason = governanceReason.trim();
    if (!reason) return;
    setPageError("");
    const path =
      resource === "assertion"
        ? `/api/memory/assertions/${encodeURIComponent(resourceId)}/review`
        : `/api/skills/proposals/${encodeURIComponent(resourceId)}/approve`;
    try {
      await apiPost(path, {
        decision,
        reason,
        idempotency_key: `web_${resource}_${Date.now()}_${resourceId}`
      });
      setGovernanceReason("");
      await fetchGovernance();
    } catch (error) {
      onAuthError(error);
      setPageError(describeError(error, t));
    }
  };

  const selectedMemory =
    memoryItems.find((item) => item.id === selectedMemoryId) ?? memoryItems[0] ?? null;

  const semanticItems = useMemo(
    () => cognitiveItems.filter((item) => item.tier === "semantic"),
    [cognitiveItems]
  );
  const episodicItems = useMemo(
    () => cognitiveItems.filter((item) => item.tier === "episodic"),
    [cognitiveItems]
  );

  const effectiveCognitive = cognitiveCounts ?? overview?.memory.cognitive;

  const routeMetrics = useMemo<RouteMetric[]>(
    () => [
      {
        label: t.activeMemory,
        value: formatMetricNumber(overview?.memory.active_count ?? memoryInventoryItems.length),
        tone: "signal"
      },
      {
        label: t.semanticRules,
        value: formatMetricNumber(effectiveCognitive?.active_semantic_count ?? semanticItems.length),
        tone: "violet"
      },
      {
        label: t.episodicOutcomes,
        value: formatMetricNumber(effectiveCognitive?.episodic_count ?? episodicItems.length),
        tone: "brass"
      },
      {
        label: t.ragChunks,
        value: formatMetricNumber(overview?.rag.chunk_count ?? ragHits.length),
        tone: "signal"
      }
    ],
    [
      effectiveCognitive,
      episodicItems.length,
      memoryInventoryItems.length,
      overview?.memory.active_count,
      overview?.rag.chunk_count,
      ragHits.length,
      semanticItems.length,
      t
    ]
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

      <MemoryObservatory
        activeCount={overview?.memory.active_count ?? memoryInventoryItems.length}
        cognitive={effectiveCognitive}
        items={memoryInventoryItems}
        t={t}
      />

      <section className="panel">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="section-title">{t.cognitiveTiersTitle}</h2>
            <p className="mt-1 text-xs text-ink/55">
              {t.semanticRules}: {effectiveCognitive?.active_semantic_count ?? semanticItems.length} ·{" "}
              {t.episodicOutcomes}: {effectiveCognitive?.episodic_count ?? episodicItems.length} ·{" "}
              {t.hypothesisNodes}: {effectiveCognitive?.hypothesis_count ?? 0}
            </p>
          </div>
          <Brain className="text-accent" size={18} />
        </div>

        {cognitiveItems.length === 0 ? (
          <div className="empty-row mt-4">{t.noCognitiveItems}</div>
        ) : (
          <div className="mt-4 grid grid-cols-2 gap-4 max-xl:grid-cols-1">
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-ink/55">
                {t.semanticRules} ({semanticItems.length})
              </div>
              {semanticItems.length === 0 ? (
                <div className="empty-row">{t.noCognitiveItems}</div>
              ) : (
                semanticItems.map((rule) => (
                  <div className="operator-card operator-card-compact" data-tone="violet" key={rule.id}>
                    <div className="flex items-center justify-between gap-2 text-xs text-ink/55">
                      <span className="font-mono">{rule.kind}</span>
                      <span>
                        conf={rule.confidence} · v{rule.distillation_version} · ep=
                        {rule.derived_episode_count}
                      </span>
                    </div>
                    <strong className="mt-1 block text-sm">{rule.claim}</strong>
                    {rule.regimes.length > 0 || rule.symbols.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {[...rule.regimes, ...rule.symbols, rule.timeframe]
                          .filter(Boolean)
                          .map((tag) => (
                            <span className="evidence-chip" key={tag}>
                              {tag}
                            </span>
                          ))}
                      </div>
                    ) : null}
                  </div>
                ))
              )}
            </div>

            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-ink/55">
                {t.episodicOutcomes} ({episodicItems.length})
              </div>
              {episodicItems.length === 0 ? (
                <div className="empty-row">{t.noCognitiveItems}</div>
              ) : (
                episodicItems.map((episode) => (
                  <div className="operator-card operator-card-compact" data-tone="signal" key={episode.id}>
                    <div className="flex items-center justify-between gap-2 text-xs text-ink/55">
                      <span className="font-mono">
                        {episode.kind} · {episode.market_regime || "regime"}
                      </span>
                      <span className="font-mono">{episode.timeframe}</span>
                    </div>
                    <strong className="mt-1 block text-sm">{episode.summary}</strong>
                    <div className="mt-1 font-mono text-[11px] text-ink/50">
                      {episode.mission_id} · {episode.raw_evidence_ref}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="section-title">{t.memoryManager}</h2>
            <p className="mt-1 text-sm text-ink/55">
              {overview?.memory.active_count ?? memoryItems.length} 可用 /{" "}
              {overview?.memory.total_count ?? memoryItems.length} 总数
            </p>
          </div>
          <MemoryStick size={18} className="text-brass" />
        </div>
        <div className="mt-4 grid grid-cols-[1fr_140px_140px_auto] gap-2 max-md:grid-cols-1">
          <input
            className="field-light"
            onChange={(event) => setMemoryQuery(event.target.value)}
            placeholder={t.searchMemory}
            value={memoryQuery}
          />
          <input
            aria-label={t.kindFilter}
            className="field-light"
            onChange={(event) => setMemoryKind(event.target.value)}
            placeholder={t.kindFilter}
            value={memoryKind}
          />
          <input
            aria-label={t.tagFilter}
            className="field-light"
            onChange={(event) => setMemoryTag(event.target.value)}
            placeholder={t.tagFilter}
            value={memoryTag}
          />
          <button
            className="icon-button justify-center"
            onClick={() => void fetchMemory(memoryQuery, memoryKind, memoryTag)}
            type="button"
          >
            <Brain size={14} />
            {t.query}
          </button>
        </div>

        <div className="mt-4 space-y-2">
          {memoryItems.length === 0 ? (
            <div className="empty-row">{t.noMemoryItems}</div>
          ) : (
            memoryItems.slice(0, 10).map((item) => (
              <button
                className={`operator-card memory-row ${
                  selectedMemory?.id === item.id ? "memory-row-active" : ""
                }`}
                key={item.id}
                onClick={() => setSelectedMemoryId(item.id)}
                type="button"
              >
                <span className="min-w-0 shrink truncate font-mono text-xs text-ink/50">
                  {item.id}
                </span>
                <span className="min-w-0 flex-1 truncate text-left text-sm">{item.content}</span>
                <span className="shrink-0 rounded border border-ink/15 px-2 py-0.5 text-xs">
                  {item.kind}
                </span>
                {item.usage_count ? (
                  <span className="shrink-0 rounded border border-brass/30 px-2 py-0.5 text-xs text-brass">
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
            <div className="mt-3 grid gap-3">
              <div className="grid grid-cols-4 gap-3 max-md:grid-cols-2">
                <div className="mini-block">
                  <span>ID</span>
                  <strong className="font-mono">{selectedMemory.id}</strong>
                </div>
                <div className="mini-block">
                  <span>{t.source}</span>
                  <strong className="font-mono">{selectedMemory.source_tool || "n/a"}</strong>
                </div>
                <div className="mini-block">
                  <span>Run</span>
                  <strong className="font-mono">{selectedMemory.source_run_id || "n/a"}</strong>
                </div>
                <div className="mini-block">
                  <span>{t.lastUsedAt}</span>
                  <strong className="font-mono">
                    {formatTimestamp(selectedMemory.last_used_at, language) ?? "—"}
                  </strong>
                </div>
              </div>
              <div className="markdown-report">{renderMarkdown(selectedMemory.content)}</div>
              {selectedMemory.tags?.length ? (
                <div className="flex flex-wrap gap-2">
                  {selectedMemory.tags.map((tag) => (
                    <span className="evidence-chip" key={tag}>
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
      </section>

      <div className="grid grid-cols-[1.05fr_0.95fr] gap-5 max-xl:grid-cols-1">
        <section className="panel">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="section-title">{t.strategyEvidence}</h2>
              <p className="mt-1 text-sm text-ink/55">{t.strategyLibraryHint}</p>
            </div>
            <Archive size={18} className="text-brass" />
          </div>
          <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
            <input
              className="field-light"
              onChange={(event) => setStrategyQuery(event.target.value)}
              placeholder={t.strategyKey}
              value={strategyQuery}
            />
            <button
              className="icon-button"
              onClick={() => void fetchStrategyLibrary(strategyQuery)}
              type="button"
            >
              <Brain size={14} />
              {t.query}
            </button>
          </div>
          <div className="mt-4 grid gap-3">
            {strategyLibrary.items.length === 0 ? (
              <div className="empty-row">{t.noStrategyEvidence}</div>
            ) : (
              strategyLibrary.items.map((item, index) => (
                <button
                  className="operator-card strategy-card text-left"
                  data-tone={
                    item.failed_count > 0 && item.passed_count > 0
                      ? "brass"
                      : item.failed_count > 0
                        ? "danger"
                        : "signal"
                  }
                  key={item.strategy_key}
                  onClick={() => setEvidenceSelection(strategyEvidenceSelection(item, t))}
                  style={cascadeStyle(index)}
                  type="button"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <strong className="font-mono">{item.strategy_key}</strong>
                    <span className="rounded border border-brass/30 px-2 py-0.5 text-xs text-brass">
                      {item.passed_count}/{item.evidence_count}
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
                    <EvidenceMetric
                      label={t.trades}
                      tone="violet"
                      value={String(item.best?.trade_count ?? "n/a")}
                    />
                  </div>
                  <SourceIdStrip
                    evidence={item.best}
                    label={t.source}
                    sourceMemoryIds={item.source_memory_ids ?? []}
                  />
                </button>
              ))
            )}
          </div>
          {evidenceSelection ? (
            <div className="mt-4 space-y-2">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <FileText size={15} className="text-accent" />
                {evidenceSelection.title}
              </div>
              {evidenceSelection.rows.map((row) => (
                <div
                  className="operator-card operator-card-compact evidence-detail-row"
                  data-tone="violet"
                  key={`${row.label}-${row.value}`}
                >
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </div>
              ))}
            </div>
          ) : null}
        </section>

        <section className="panel">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="section-title">{t.rag}</h2>
              <p className="mt-1 text-sm text-ink/55">
                {overview?.rag.document_count ?? 0} 文档 / {overview?.rag.chunk_count ?? 0} 分片
              </p>
            </div>
            <Brain size={18} className="text-accent" />
          </div>
          <div className="mt-4 grid grid-cols-[1fr_auto] gap-2">
            <input
              className="field-light"
              onChange={(event) => setRagQuery(event.target.value)}
              placeholder={t.searchRag}
              value={ragQuery}
            />
            <button
              className="icon-button"
              onClick={() => void fetchRag(ragQuery)}
              type="button"
            >
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
                    <div className="truncate font-mono text-xs text-ink/50">
                      {hit.source_path}#{hit.chunk_index}
                    </div>
                    <p className="mt-1 max-h-12 overflow-hidden text-xs text-ink/60">
                      {hit.content_preview}
                    </p>
                  </div>
                  <span className="font-mono text-xs text-brass">{hit.score.toFixed(2)}</span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <GovernanceReview
        access={access}
        assertions={memoryAssertions}
        onDecision={handleGovernanceDecision}
        proposals={skillProposals}
        reason={governanceReason}
        releases={skillReleases}
        setReason={setGovernanceReason}
        t={t}
      />
    </div>
  );
}
