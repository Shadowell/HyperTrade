import type { LucideIcon } from "lucide-react";
import { cascadeStyle } from "../../lib/format";

export type TelemetryMetric = {
  label: string;
  value: string;
  icon: LucideIcon;
  tone: string;
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
      {metrics.map((metric, index) => (
        <div className="telemetry-cell" key={metric.label} style={cascadeStyle(index)}>
          <div className="flex items-start justify-between gap-4">
            <metric.icon className={`metric-${metric.tone}`} size={18} />
            <span
              className={`font-mono text-2xl font-semibold tracking-tight ${
                loading ? "skeleton-pulse text-ink/30" : "text-ink"
              }`}
            >
              {loading ? "—" : metric.value}
            </span>
          </div>
          <div className="mt-4 text-xs uppercase text-ink/45">{metric.label}</div>
        </div>
      ))}
    </section>
  );
}
