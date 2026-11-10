import type { AgentRun, EvidenceSelection, ReportBlock, StrategyLibraryItem, TraceEvent } from "../types";
import { formatPercentValue } from "./format";
import { isRecord, stringOrUndefined, summarizeRecord } from "./values";

export function reportBlocksFromRun(run: AgentRun): ReportBlock[] {
  const reportJson = run.report_json;
  if (!reportJson) {
    return [];
  }
  const blocks = reportJson.report_blocks ?? reportJson.blocks;
  if (!Array.isArray(blocks)) {
    return [];
  }
  return blocks.filter(isRecord).map((block) => ({
    block_type: stringOrUndefined(block.block_type),
    title: stringOrUndefined(block.title),
    severity: stringOrUndefined(block.severity),
    notes: block.notes,
    metrics: block.metrics,
    rows: block.rows,
    missing: block.missing,
    source_refs: block.source_refs
  }));
}

export function strategyEvidenceSelection(
  item: StrategyLibraryItem,
  t: Record<string, string>
): EvidenceSelection {
  const best = item.best ?? {};
  const rows = [
    { label: "memory", value: best.memory_id ?? "n/a" },
    { label: "experiment", value: best.experiment_id ?? "n/a" },
    { label: "backtest", value: best.backtest_id ?? "n/a" },
    { label: "bitpro_result", value: best.bitpro_result_id ?? "n/a" },
    { label: t.returnPct, value: formatPercentValue(best.total_return_pct) },
    { label: t.maxDrawdown, value: formatPercentValue(best.max_drawdown_pct) },
    { label: t.score, value: best.score ?? "n/a" },
    { label: t.sourceMemories, value: (item.source_memory_ids ?? []).join(", ") || t.noSourceIds }
  ];
  return {
    title: item.strategy_key,
    rows
  };
}

export function traceEvidenceSelection(event: TraceEvent, t: Record<string, string>): EvidenceSelection {
  return {
    title: `${t.traceEvidence}: ${event.tool_name}`,
    rows: [
      { label: "trace", value: event.id ?? "n/a" },
      { label: "tool", value: event.tool_name },
      { label: "status", value: event.status },
      { label: "created_at", value: event.created_at ?? "n/a" },
      { label: "input", value: summarizeRecord(event.input_json) },
      { label: "output", value: summarizeRecord(event.output_json) }
    ]
  };
}
