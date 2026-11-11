import type { RouteMetric } from "../../types/index";

export function RouteMetricStrip({ metrics, label }: { metrics: RouteMetric[]; label: string }) {
  return (
    <section aria-label={label} className="route-metric-strip">
      {metrics.map((metric) => (
        <div className="route-metric-card" data-tone={metric.tone} key={metric.label}>
          <span>{metric.label}</span>
          <strong>{metric.value}</strong>
        </div>
      ))}
    </section>
  );
}
