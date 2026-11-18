import type { ThreadPresentation } from "../../agentThread";
import type { Copy } from "../../i18n/messages";
import { ReportSourceList } from "../report/StructuredReport";

/** Resolved references, canonical turn history (deduplicated against ReportReader), and HITL state. */
export function ThreadDetails({
  t,
  presentation,
  deduplicateAnswer = ""
}: {
  t: Copy;
  presentation: ThreadPresentation;
  deduplicateAnswer?: string;
}) {
  const normalizedDisplayed = deduplicateAnswer.trim();
  let visibleMessages = presentation.messages;
  if (normalizedDisplayed && visibleMessages.length > 0) {
    const lastIndex = visibleMessages.length - 1;
    const last = visibleMessages[lastIndex];
    if (last.role === "agent" && last.text.trim() === normalizedDisplayed) {
      visibleMessages = visibleMessages.slice(0, lastIndex);
    }
  }

  const waitingForHuman =
    presentation.status === "waiting_input" || presentation.status === "waiting_approval";

  return (
    <>
      {presentation.resolvedRefs.length > 0 ? (
        <div className="mt-4 mini-block">
          <span>{t.resolvedRefs}</span>
          <strong className="font-mono">{presentation.resolvedRefs.join(" / ")}</strong>
        </div>
      ) : null}
      {visibleMessages.length > 0 ? (
        <div className="mt-4">
          <h3 className="section-title">{t.canonicalHistory}</h3>
          <div className="mt-2 max-h-64 space-y-2 overflow-auto">
            {visibleMessages.map((message) => (
              <div
                className="operator-card operator-card-compact"
                data-tone={message.role === "user" ? "brass" : "signal"}
                key={message.id}
              >
                <span className="font-mono text-[11px] text-ink/55">
                  {message.role} · {message.kind} · {message.status}
                </span>
                <strong className="mt-1 block whitespace-pre-wrap text-sm">{message.text}</strong>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {waitingForHuman ? (
        <div className="mt-4 operator-card operator-card-compact" data-tone="brass">
          <span>{t.hitlTitle}</span>
          <strong>
            {presentation.warnings.join(" · ") || presentation.status}
          </strong>
        </div>
      ) : presentation.warnings.length > 0 ? (
        <div className="mt-4 operator-card operator-card-compact" data-tone="danger">
          <span>warning / unknown</span>
          <strong>{presentation.warnings.join(" · ")}</strong>
        </div>
      ) : null}
      {presentation.evidence.length > 0 ? (
        <ReportSourceList label={t.sourceRefs} prefix="evidence" values={presentation.evidence} />
      ) : null}
    </>
  );
}
