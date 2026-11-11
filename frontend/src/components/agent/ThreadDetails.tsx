import type { ThreadPresentation } from "../../agentThread";
import type { Copy } from "../../i18n/messages";
import { ReportSourceList } from "../report/StructuredReport";

/** Resolved references, the canonical message history, warnings and evidence of the Thread. */
export function ThreadDetails({ t, presentation }: { t: Copy; presentation: ThreadPresentation }) {
  return (
    <>
      {presentation.resolvedRefs.length > 0 ? (
        <div className="mt-4 mini-block">
          <span>{t.resolvedRefs}</span>
          <strong className="font-mono">{presentation.resolvedRefs.join(" / ")}</strong>
        </div>
      ) : null}
      {presentation.messages.length > 0 ? (
        <div className="mt-4">
          <h3 className="section-title">{t.canonicalHistory}</h3>
          <div className="mt-2 max-h-64 space-y-2 overflow-auto">
            {presentation.messages.map((message) => (
              <div
                className="operator-card operator-card-compact"
                data-tone={message.role === "user" ? "brass" : "signal"}
                key={message.id}
              >
                <span>
                  {message.role} · {message.kind} · {message.status}
                </span>
                <strong className="whitespace-pre-wrap text-sm">{message.text}</strong>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {presentation.warnings.length > 0 ? (
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
