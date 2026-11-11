import { Bot, Clock3 } from "lucide-react";
import type { Copy } from "../../i18n/messages";
import { cascadeStyle } from "../../lib/format";
import { EmptyState } from "../ui/EmptyState";

/** Node-by-node progress of the current turn. Polite live region: new steps are announced. */
export function AgentProgress({
  t,
  stage,
  items
}: {
  t: Copy;
  stage: string | null;
  items: string[];
}) {
  return (
    <div aria-label={t.agentProgress} aria-live="polite" className="mt-4 trace-list" role="status">
      <div className="px-1 py-2 text-xs font-semibold uppercase text-ink/45">{t.agentProgress}</div>
      <div className="trace-row">
        <Bot size={14} className="text-brass" />
        <span className="text-xs">{t.currentStage}</span>
        <span className="ml-auto font-mono text-xs text-ink/55">{stage ?? "—"}</span>
      </div>
      {items.length === 0 ? (
        <EmptyState title={t.noProgressYet} />
      ) : (
        items.map((item, index) => (
          <div className="trace-row" key={`${item}-${index}`} style={cascadeStyle(index)}>
            <Clock3 size={14} className="text-brass" />
            <span className="min-w-0 truncate font-mono text-xs">{item}</span>
          </div>
        ))
      )}
    </div>
  );
}
