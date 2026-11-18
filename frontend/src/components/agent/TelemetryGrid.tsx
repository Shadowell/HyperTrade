import type { LucideIcon } from "lucide-react";
import { cascadeStyle } from "../../lib/format";

export type TelemetryMetric = {
  label: string;
  value: string;
  icon: LucideIcon;
  tone: string;
  detail?: string;
  ratio?: number | null;
};

/** While the overview has not arrived the values are unknown, not zero: show a placeholder. */
export function TelemetryGrid({
  label,
  metrics,
  loading
}: {
  label: string;
  metrics: TelemetryMetric[];
  loading: boolean;
}) {
  return (
    <section aria-label={label} aria-busy={loading} className="telemetry-grid mt-6">
      {metrics.map((metric, index) => {
        const clampedRatio =
          metric.ratio === null || metric.ratio === undefined
            ? null
            : Math.max(0, Math.min(1, metric.ratio));
        return (
          <article
            className="telemetry-cell hm-metric-card"
            data-tone={metric.tone}
            key={metric.label}
            style={cascadeStyle(index)}
          >
            <div className="metric-top">
              <span className="metric-icon">
                <metric.icon className={`metric-${metric.tone}`} size={18} />
              </span>
              <span className="metric-name">{metric.label}</span>
            </div>
            <div
              className={`metric-value ${
                loading ? "skeleton-pulse text-ink/30" : ""
              }`}
            >
              {loading ? "—" : metric.value}
            </div>
            {metric.detail ? (
              <div className="metric-detail" title={metric.detail}>
                {loading ? "…" : metric.detail}
              </div>
            ) : null}
            {clampedRatio !== null ? (
              <div className="metric-track">
                <i style={{ transform: `scaleX(${loading ? 0 : clampedRatio})` }} />
              </div>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
