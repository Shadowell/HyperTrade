import { Activity, BarChart3 } from "lucide-react";
import { useMemo } from "react";
import type { Copy } from "../../i18n/messages";
import { formatMetricNumber } from "../../lib/format";
import type { CognitiveMemoryCounts, MemoryItem } from "../../types";

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

export function MemoryObservatory({
  items,
  activeCount,
  cognitive,
  t
}: {
  items: MemoryItem[];
  activeCount: number;
  cognitive?: CognitiveMemoryCounts;
  t: Copy;
}) {
  const insights = useMemo(() => memoryInsights(items), [items]);
  const activityPeak = Math.max(1, ...insights.activity.map((entry) => entry.count));
  const activeLabel =
    activeCount > 0 ? `${items.length} / ${activeCount}` : formatMetricNumber(items.length);

  return (
    <section className="memory-observatory" aria-labelledby="memory-observatory-title">
      <div className="memory-observatory-head">
        <div>
          <div className="memory-observatory-kicker">Memory telemetry</div>
          <h2 id="memory-observatory-title">{t.memoryObservatory}</h2>
          <p>{t.memoryObservatoryHint}</p>
          {cognitive ? (
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <span className="evidence-chip">
                {t.semanticRules}: {cognitive.active_semantic_count}/{cognitive.semantic_count}
              </span>
              <span className="evidence-chip">
                {t.episodicOutcomes}: {cognitive.episodic_count}
              </span>
              <span className="evidence-chip">
                {t.hypothesisNodes}: {cognitive.hypothesis_count}
              </span>
            </div>
          ) : null}
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
    if (confidenceValue !== null) confidence.push(confidenceValue);
    if (importanceValue !== null) importance.push(importanceValue);
    usage += item.usage_count ?? 0;
    if (item.source_tool) sources.add(item.source_tool);
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
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.min(1, parsed));
}

function averageMemoryRatio(values: number[]): number | null {
  if (values.length === 0) return null;
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
  return ["#c026d3", "#06b6d4", "#10b981", "#f59e0b", "#8b5cf6"][index % 5];
}
