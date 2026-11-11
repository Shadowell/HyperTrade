import { TerminalSquare } from "lucide-react";
import type { Copy } from "../../i18n/messages";
import { renderMarkdown } from "../../lib/markdown";
import type { ReportBlock } from "../../types";
import { EmptyState } from "../ui/EmptyState";
import { StructuredReport } from "../report/StructuredReport";

/**
 * The report of the current run. With no run there is nothing to read, and the page says so;
 * it must never fill the space with an example report (an invented price in a trading console is
 * indistinguishable from a real one at a glance).
 */
export function ReportReader({
  t,
  busy,
  markdown,
  blocks,
  showRaw,
  onToggleRaw
}: {
  t: Copy;
  busy: boolean;
  markdown: string;
  blocks: ReportBlock[];
  showRaw: boolean;
  onToggleRaw: () => void;
}) {
  const empty = !busy && !markdown && blocks.length === 0;
  return (
    <>
      <div className="mt-4 flex items-center justify-between gap-3">
        <h3 className="section-title">{t.reportReader}</h3>
        {empty ? null : (
          <button className="icon-button" onClick={onToggleRaw} type="button">
            <TerminalSquare size={14} />
            {showRaw ? t.reportReader : t.rawMarkdown}
          </button>
        )}
      </div>
      {empty ? (
        <EmptyState hint={t.noRunYetHint} title={t.noRunYet} />
      ) : showRaw ? (
        <pre className="report-block">{busy ? `${t.overviewLoading}...` : markdown}</pre>
      ) : blocks.length > 0 ? (
        <StructuredReport blocks={blocks} markdown={markdown} t={t} />
      ) : (
        <div className="markdown-report">{busy ? t.overviewLoading : renderMarkdown(markdown)}</div>
      )}
    </>
  );
}
