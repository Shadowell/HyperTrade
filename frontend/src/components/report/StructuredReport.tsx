import type { ReportBlock, RouteMetric, StrategyEvidence } from "../../types";
import { renderMarkdown } from "../../lib/markdown";
import {
  isRecord,
  keyValueRows,
  stringifyValue,
  toStringList
} from "../../lib/values";

export function EvidenceMetric({
  label,
  tone,
  value
}: {
  label: string;
  tone: RouteMetric["tone"];
  value: string;
}) {
  return (
    <div className="operator-card operator-card-compact evidence-metric" data-tone={tone}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function SourceIdStrip({
  evidence,
  label,
  sourceMemoryIds
}: {
  evidence: StrategyEvidence | undefined;
  label: string;
  sourceMemoryIds: string[];
}) {
  const ids = [
    evidence?.memory_id ? `memory: ${evidence.memory_id}` : "",
    evidence?.experiment_id ? `experiment: ${evidence.experiment_id}` : "",
    evidence?.backtest_id ? `backtest: ${evidence.backtest_id}` : "",
    evidence?.bitpro_result_id ? `bitpro_result: ${evidence.bitpro_result_id}` : "",
    ...sourceMemoryIds
      .filter((id) => id && id !== evidence?.memory_id)
      .slice(0, 3)
      .map((id) => `memory: ${id}`)
  ].filter(Boolean);
  return (
    <div className="operator-card operator-card-compact evidence-source-card" data-tone="violet">
      <span className="evidence-source-label">{label}</span>
      <div className="evidence-id-strip">
        {ids.length === 0 ? (
          <span>n/a</span>
        ) : (
          ids.map((id) => (
            <span className="evidence-chip" key={id}>
              {id}
            </span>
          ))
        )}
      </div>
    </div>
  );
}

export function StructuredReport({
  blocks,
  markdown,
  t
}: {
  blocks: ReportBlock[];
  markdown: string;
  t: Record<string, string>;
}) {
  return (
    <div className="structured-report">
      <div className="flex items-center justify-between gap-3">
        <h4>{t.reportBlocks}</h4>
        <span className="font-mono text-xs text-ink/45">{blocks.length}</span>
      </div>
      <div className="mt-3 grid gap-3">
        {blocks.map((block, index) => (
          <div className="report-card" key={`${block.title ?? block.block_type}-${index}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <span>{block.block_type ?? "block"}</span>
                <strong>{block.title ?? "Report block"}</strong>
              </div>
              {block.severity ? (
                <span className="rounded border border-brass/25 px-2 py-1 text-xs text-brass">
                  {block.severity}
                </span>
              ) : null}
            </div>
            <ReportNotes notes={block.notes} />
            <ReportMetrics metrics={block.metrics} rows={block.rows} />
            <ReportSourceList label={t.sourceRefs} prefix="source" values={block.source_refs} />
            <ReportSourceList label={t.missingData} prefix="missing" values={block.missing} />
          </div>
        ))}
      </div>
      <h4 className="mt-4">{t.markdownFallback}</h4>
      <div className="markdown-report">{renderMarkdown(markdown)}</div>
    </div>
  );
}

export function ReportNotes({ notes }: { notes: unknown }) {
  const items = toStringList(notes);
  if (items.length === 0) {
    return null;
  }
  return (
    <ul className="report-note-list">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function ReportMetrics({ metrics, rows }: { metrics: unknown; rows: unknown }) {
  const metricRows = keyValueRows(metrics);
  const dataRows = Array.isArray(rows) ? rows.filter(isRecord).slice(0, 5) : [];
  if (metricRows.length === 0 && dataRows.length === 0) {
    return null;
  }
  return (
    <div className="report-metric-list">
      {metricRows.map((row) => (
        <div key={`${row.label}-${row.value}`}>
          <span>{row.label}</span>
          <strong>{row.value}</strong>
        </div>
      ))}
      {dataRows.map((row, index) => (
        <div key={`row-${index}`}>
          <span>row {index + 1}</span>
          <strong>
            {Object.entries(row)
              .slice(0, 4)
              .map(([key, value]) => `${key}=${stringifyValue(value)}`)
              .join(" / ")}
          </strong>
        </div>
      ))}
    </div>
  );
}

export function ReportSourceList({
  label,
  prefix,
  values
}: {
  label: string;
  prefix: string;
  values: unknown;
}) {
  const items = toStringList(values);
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="mt-3">
      <div className="mb-2 text-xs uppercase text-ink/45">{label}</div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span className="evidence-chip" key={item}>
            {prefix}: {item}
          </span>
        ))}
      </div>
    </div>
  );
}
